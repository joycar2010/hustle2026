"""risk-ledger v1(骨架):跨域风控面,独立第三方进程(C 机,与执行面分机)。

v1 监察范围(30s 一轮):
  R1 服务心跳巡检:EXPECTED 服务的 dcm:hb:* 缺失/停更 → 告警
  R2 coin 引擎活性:dcm:engine:coin:state 中 RUNNING scope 的 last_heartbeat 停走 → 告警
  R3 coin 僵尸仓:非终态仓位(PENDING_BORROW/BORROWED_IDLE/PENDING_REPAY)超龄 → 告警
     (PENDING_BORROW 钉死币旧伤的独立第三方哨兵)
  R4 feed 吞吐:updates_30s==0 → 告警
  净敞口 v1=意图口径汇总(coin 意图账逐币 net_base,只报不判),写 dcm:risk:status 供 gateway 展示。

实盘对账(五所只读 API=最终真相源)接口留位:API key 未配置前如实报 unconfigured,不猜。

铁律(coin 事故史):风控面**只告警不动手**——绝不自愈、绝不改仓、绝不写任何业务键;
独立于一切执行进程存活;告警走共享节流(dcm:throttle:),致命级绕过节流。
"""
import asyncio
import json
import logging
import os
import time

import asyncpg
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat
from dcm_common.notify import Notifier, feishu_from_env

from policy import compute_and_publish, corebox_check  # noqa: E402  # G0 风险策略权威+CORE_POOL 封闭盒子

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("risk-ledger")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_RISK_INTERVAL_SEC", "30"))
STALE_POS_SEC = int(os.environ.get("DCM_RISK_STALE_POS_SEC", "1800"))
THROTTLE_SEC = int(os.environ.get("DCM_RISK_THROTTLE_SEC", "1800"))
# 双合约风控三护栏阈值
DIST_LIQ_WARN = float(os.environ.get("DCM_RISK_DIST_LIQ_WARN", "10"))   # 距强平<此% 预警
DIST_LIQ_CRIT = float(os.environ.get("DCM_RISK_DIST_LIQ_CRIT", "4"))    # 距强平<此% 致命
ADL_WARN = float(os.environ.get("DCM_RISK_ADL_WARN", "4"))              # ADL档≥此 预警(0-5,越高越可能被减)
LEG_MISMATCH_TOL = float(os.environ.get("DCM_RISK_LEG_MISMATCH_TOL", "0.1"))  # 两腿量差>10% 判单腿
NET_EXPOSURE_FLOOR_USDT = float(os.environ.get("DCM_RISK_NET_EXPOSURE_FLOOR", "25"))  # 逐币全域净敞口地板
MARGIN_LEV_WARN = float(os.environ.get("DCM_RISK_MARGIN_LEV_WARN", "5"))  # 逐所有效杠杆预警线
# R11 RECON v2 逆向对账(testgo 单腿噪音根治课的 dcm 版):实盘 perp 仓无 DB 行解释=孤儿仓。
# 地板过滤(粉尘/结算残留不告警)+连续 2 轮命中才 fire(快照滞后/开仓瞬间的假阳性去抖)。
ORPHAN_FLOOR_USDT = float(os.environ.get("DCM_RISK_ORPHAN_FLOOR_USDT", "5"))
# 平仓过渡窗:账户快照 60s 轮询,行刚 CLOSED 时快照仍照着旧腿→R11 假阳性孤儿风暴
# (GWEI/VANRY 2026-07-12 实例:closed_at 后 45s 触发 fatal)。R7 开仓侧新鲜度闸的平仓镜像。
CLOSE_GRACE_SEC = int(os.environ.get("DCM_RISK_CLOSE_GRACE_SEC", "180"))
_orphan_hits: dict = {}   # (venue,sym) -> 连续命中轮数(进程内即可,重启重数)

# 期望在场的服务及其心跳最大年龄(秒)。缺失键==停更同罪。
EXPECTED_HB = {
    "feed-cex": 120,
    "coin-bridge": 240,
    "universe-sync": 7500,
    "event-calendar": 900,
    "fund-scheduler": 7500,
    "borrow-monitor": 400,
    "transfer-monitor": 900,
    "gateway": 120,
    "decision": 120,
    "funding-sync": 900,
    "carry-advisor": 1900,
    "account-snapshot": 240,
    "depth-sampler": 400,
    "basis-sampler": 200,
    "engine-lending": 900,   # S4 shadow 决策账,300s/轮
    # engine-basis/engine-dualperp 已退役(2026-07-14,统一执行内核接管)——新权威:
    "exec-manager": 120,     # 20s/轮,持仓 owner-of-record
    "exec-recon": 400,       # 120s/轮,6所对账
    "exec-opener": 300,      # 60s/轮,shadow 开仓候选决策(不下单)
    "exec-repair": 300,      # 60s/轮,G2 RiskRepair 修复意图(shadow,不下单)
}
RECON_VENUES = ("binance", "bybit", "okx", "gate", "bitget", "hyperliquid")
STALE_STATUSES = ("PENDING_BORROW", "BORROWED_IDLE", "PENDING_REPAY")

notifier = Notifier(
    REDIS_URL, "risk-ledger", feishu=feishu_from_env(),
    throttle_interval_sec=THROTTLE_SEC, throttle_max_count=1,
)


_alert_pool = None  # main() 注入,用于告警落库(alerts_log)


async def fire(key: str, title: str, content: str, level: str = "warn"):
    """告警=日志+飞书(若配置)+跑马灯发布+落库(alerts_log 供告警历史页);经共享节流;绝不抛异常。"""
    try:
        res = await asyncio.to_thread(notifier.fire, key, title, content,
                                      level=level, marquee=True, color="#ef4444")
        log.warning("ALERT[%s] %s | %s -> %s", key, title, content, res)
        if _alert_pool is not None and not (isinstance(res, dict) and res.get("throttled")):
            try:
                await _alert_pool.execute(
                    "INSERT INTO alerts_log(service,akey,level,title,content) VALUES('risk-ledger',$1,$2,$3,$4)",
                    key, level, title, content[:500])
            except Exception:
                pass
    except Exception as e:
        log.error("alert fire failed %s: %r", key, e)


async def get_json(r: aioredis.Redis, key: str):
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        log.warning("redis get %s failed: %r", key, e)
        return None


def intent_net(positions: list) -> dict:
    """coin 意图账逐币净 delta(base 口径,粗):现货腿=买回-卖出,合约腿=多头数量。
    只汇总呈现,不在 v1 下判断——实盘核对上线后才谈差异告警。"""
    net: dict[str, float] = {}
    for p in positions:
        try:
            sym = p.get("symbol") or "?"
            spot = float(p.get("spot_buy_qty") or 0) - float(p.get("spot_sell_qty") or 0)
            fut = float(p.get("futures_long_qty") or 0)
            net[sym] = round(net.get(sym, 0.0) + spot + fut, 8)
        except (TypeError, ValueError):
            continue
    return net


async def check_round(r: aioredis.Redis, self_pool) -> dict:
    self_pool_ok = self_pool is not None
    now = int(time.time())
    status: dict = {"ts": now, "services": {}, "coin": {}, "reconcile": {"configured": False}}
    alerts = 0

    # R1 服务心跳巡检
    for svc, max_age in EXPECTED_HB.items():
        hb = await get_json(r, f"dcm:hb:{svc}")
        if hb is None:
            status["services"][svc] = "missing"
            await fire(f"hb-missing:{svc}", f"{svc} 心跳缺失", f"dcm:hb:{svc} 键不存在(服务死亡或总线不可达)")
            alerts += 1
            continue
        age = now - int(hb.get("ts") or 0)
        if age > max_age:
            status["services"][svc] = f"stale({age}s)"
            await fire(f"hb-stale:{svc}", f"{svc} 心跳停更", f"最后心跳 {age}s 前(阈值 {max_age}s)")
            alerts += 1
        else:
            status["services"][svc] = "ok"
        # R4 feed 吞吐归零
        if svc == "feed-cex" and status["services"][svc] == "ok" and int(hb.get("updates") or 0) == 0:
            await fire("feed-zero", "feed-cex 吞吐归零", "30s 窗口 updates=0(全所静默,疑总线/上游断)")
            alerts += 1

    # R2 coin 引擎活性(桥透传的 engine_state;桥自身死活已在 R1)
    state = await get_json(r, "dcm:engine:coin:state")
    if state:
        scopes = state.get("engine_state") or []
        stale_scopes = []
        for s in scopes:
            # scope=global 且带 user_id 的行是「用户期望态旗标」(pid/心跳长期不更新,
            # 引擎重启据其决定拉不拉该用户)——不是活性行,勿判停更(2026-07-11 两次学费)
            if s.get("scope") == "global" and s.get("user_id") is not None:
                continue
            if s.get("status") == "RUNNING":
                hb_ts = int(s.get("heartbeat_ts") or 0)
                if hb_ts and now - hb_ts > 120:
                    # 带 user_id/pid 消歧义:engine_state 可能存在同名 scope 多行
                    # (真引擎行心跳鲜活 + 卡 RUNNING 的僵尸行并存,testgo C层僵尸假运行的 coin 版)
                    stale_scopes.append(
                        f"{s.get('scope')}/u{s.get('user_id')}/pid{s.get('pid')}({(now - hb_ts) // 60}min)")
        status["coin"]["engine_scopes"] = len(scopes)
        status["coin"]["stale_scopes"] = stale_scopes
        if stale_scopes:
            await fire("coin-engine-stale", "coin 引擎心跳停走",
                       f"RUNNING scope 停走: {', '.join(stale_scopes)}", level="fatal")
            alerts += 1

    # R3 coin 僵尸仓 + 净敞口(意图口径)
    snap = await get_json(r, "dcm:engine:coin:positions")
    if snap:
        positions = snap.get("positions") or []
        status["coin"]["open_positions"] = len(positions)
        stale_pos = []
        for p in positions:
            st = p.get("status")
            upd = int(p.get("updated_ts") or 0)
            if st in STALE_STATUSES and upd and now - upd > STALE_POS_SEC:
                stale_pos.append({"symbol": p.get("symbol"), "status": st,
                                  "age_min": (now - upd) // 60,
                                  "borrow_qty": p.get("borrow_qty")})
        status["coin"]["stale_positions"] = stale_pos
        status["coin"]["intent_net"] = intent_net(positions)
        for sp in stale_pos:
            await fire(f"stalepos:{sp['symbol']}", f"coin 非终态仓位滞留 {sp['symbol']}",
                       f"status={sp['status']} 已滞留 {sp['age_min']}min borrow_qty={sp['borrow_qty']}"
                       f" — 僵尸仓/钉死币前兆,需人工核")
            alerts += 1

    # R5 实盘对账(account-snapshot 只读快照为真相源):逐所权益+持仓汇总,鉴权失败 fatal
    recon: dict = {"configured": False, "venues": {}}
    total_equity = 0.0
    any_configured = False
    for v in RECON_VENUES:
        acct = await get_json(r, f"dcm:account:{v}")
        if acct is None:
            continue
        any_configured = True
        if acct.get("ok"):
            eq = float(acct.get("equity_usdt") or 0)
            total_equity += eq
            recon["venues"][v] = {"equity_usdt": eq, "positions": len(acct.get("positions") or {})}
        else:
            err = str(acct.get("err") or "")
            recon["venues"][v] = {"error": err[:120]}
            # 鉴权/IP 类错误 fatal(裸奔风险:引擎以为能交易实则被拒);区分限频等瞬时错误
            low = err.lower()
            if any(k in low for k in ("ip", "-2015", "unauthorized", "invalid api", "sign")):
                await fire(f"acct-auth:{v}", f"{v} 账户鉴权失败", f"实盘对账被拒: {err[:100]}", level="fatal")
                alerts += 1
    recon["configured"] = any_configured
    recon["total_equity_usdt"] = round(total_equity, 2)
    status["reconcile"] = recon

    # R6/R7 双合约风控三护栏:对每个 dualperp OPEN 配对,交叉两腿实盘明细
    guards: dict = {"pairs": [], "configured": bool(self_pool_ok)}
    if self_pool_ok:
        try:
            pairs = await self_pool.fetch(
                "SELECT symbol,venue_long,venue_short,qty_base,"
                "EXTRACT(EPOCH FROM opened_at)::bigint AS opened_epoch "
                "FROM dualperp_positions WHERE state='OPEN'")  # noqa
        except Exception as e:
            pairs = []
            log.warning("dualperp pairs read failed: %r", e)
        acct_by_venue = {v: (await get_json(r, f"dcm:account:{v}") or {}) for v in RECON_VENUES}
        detail_by_venue = {v: a.get("pos_detail", {}) for v, a in acct_by_venue.items()}
        ts_by_venue = {v: int(a.get("ts") or 0) for v, a in acct_by_venue.items()}
        for p in pairs:
            sym, vl, vs = p["symbol"], p["venue_long"], p["venue_short"]
            dl = detail_by_venue.get(vl, {}).get(sym)
            ds = detail_by_venue.get(vs, {}).get(sym)
            pg = {"symbol": sym, "venue_long": vl, "venue_short": vs}
            intended = float(p["qty_base"] or 0)
            opened = int(p["opened_epoch"] or 0)
            # 新鲜度闸:账户快照须晚于 opened_at+宽限(60s 轮询期+余量),否则快照尚未反映新仓,
            # "缺腿"是滞后假象而非真单腿——判"待验证"跳过,杜绝开仓后 ~1min 的单腿误报风暴
            acct_ready = (min(ts_by_venue.get(vl, 0), ts_by_venue.get(vs, 0)) >= opened + 90)
            if not acct_ready:
                pg["verifying"] = "账户快照未追上新仓"
                guards["pairs"].append(pg)
                continue
            # R7 单腿/ADL 减仓检测:实盘任一腿缺失或量偏离 intended → 单腿裸奔
            if dl is None or ds is None:
                pg["single_leg"] = f"long={'有' if dl else '缺'} short={'有' if ds else '缺'}"
                await fire(f"singleleg:{sym}", f"双合约单腿裸露 {sym}",
                           f"实盘仅一腿在场({pg['single_leg']})—ADL/强平/漏腿,立即人工核", level="fatal")
                alerts += 1
            else:
                ql, qs = abs(float(dl.get("qty") or 0)), abs(float(ds.get("qty") or 0))
                if intended > 0 and (abs(ql - intended) / intended > LEG_MISMATCH_TOL
                                     or abs(qs - intended) / intended > LEG_MISMATCH_TOL):
                    pg["leg_mismatch"] = {"long": ql, "short": qs, "intended": intended}
                    await fire(f"legmismatch:{sym}", f"双合约两腿量失衡 {sym}",
                               f"long={ql} short={qs} intended={intended}—疑 ADL/部分强平", level="fatal")
                    alerts += 1
                # R6 保证金对称/距强平:亏损腿逼近强平
                for leg, d in (("long", dl), ("short", ds)):
                    dist = d.get("dist_liq_pct")
                    adl = d.get("adl")
                    legcn = "多头腿" if leg == "long" else "空头腿"
                    if dist is not None and dist < DIST_LIQ_CRIT:
                        await fire(f"liq-crit:{sym}:{leg}", f"{sym} 快要爆仓了",
                                   f"{sym} 的{legcn}离强平只剩 {dist}% 的安全垫，很危险。赶紧补点保证金，或者把两条腿一起减一减。",
                                   level="fatal")
                        alerts += 1
                    elif dist is not None and dist < DIST_LIQ_WARN:
                        await fire(f"liq-warn:{sym}:{leg}", f"{sym} 保证金有点吃紧",
                                   f"{sym} 的{legcn}离强平还有 {dist}%，垫子在变薄，留意一下。", level="warn")
                        alerts += 1
                    if adl is not None and adl >= ADL_WARN:
                        await fire(f"adl:{sym}:{leg}", f"{sym} 可能被交易所强减",
                                   f"{sym} 的{legcn}排到了自动减仓队列前面（ADL {adl}）。这通常是赚钱那条腿，交易所可能替你减掉一部分，盯着点别单腿裸奔。",
                                   level="warn")
                        alerts += 1
                pg["dist_liq"] = {"long": dl.get("dist_liq_pct"), "short": ds.get("dist_liq_pct")}
                pg["adl"] = {"long": dl.get("adl"), "short": ds.get("adl")}
                pg["upnl"] = {"long": dl.get("upnl"), "short": ds.get("upnl")}
            guards["pairs"].append(pg)
    status["guards"] = guards

    # R8 全域净敞口账本:逐币归并五所实盘 signed 持仓(已 base),delta 中性组合应≈0;
    # 某币净敞口名义超地板 = 有腿裸奔/配对失衡(全书级,跨所跨引擎)
    acct_all = {v: (await get_json(r, f"dcm:account:{v}") or {}) for v in RECON_VENUES}
    net_by_coin: dict[str, float] = {}
    mark_by_coin: dict[str, float] = {}
    for v in RECON_VENUES:
        acct = acct_all.get(v) or {}
        for s, q in (acct.get("positions") or {}).items():
            net_by_coin[s] = net_by_coin.get(s, 0.0) + float(q)
            d = (acct.get("pos_detail") or {}).get(s) or {}
            if d.get("mark"):
                mark_by_coin[s] = float(d["mark"])
    net_exposure = []
    for s, nq in net_by_coin.items():
        mark = mark_by_coin.get(s, 0.0)
        notional = abs(nq) * mark
        if notional > NET_EXPOSURE_FLOOR_USDT:
            net_exposure.append({"symbol": s, "net_base": round(nq, 8), "notional": round(notional, 2)})
            await fire(f"netexp:{s}", f"全域净敞口超限 {s}",
                       f"五所归并净 {round(nq,6)} base ≈ {round(notional,1)}U(>{NET_EXPOSURE_FLOOR_USDT})"
                       f"—裸腿/配对失衡,查实盘", level="fatal")
            alerts += 1
    status["net_exposure"] = {"floor": NET_EXPOSURE_FLOOR_USDT, "breaches": net_exposure,
                              "coins_with_pos": len([s for s, q in net_by_coin.items() if abs(q) > 0])}

    # R11 RECON v2 逆向对账:实盘 perp 仓 ∖ DB 期望腿 = 孤儿仓。
    # 补 R7(只遍历 DB 行)与 R8(delta 中性孤儿对净≈0 不触地板)都看不见的洞——
    # 实例:引擎重启 adopt 持仓但 DB 无行(PARTI 2026-07-11)、平仓残腿(B3 同日)。
    expected_legs: set = set()
    if self_pool_ok:
        try:
            drows = await self_pool.fetch(
                "SELECT symbol,venue_long,venue_short FROM dualperp_positions "
                "WHERE state NOT IN ('CLOSED','FAILED','ROLLBACK') "
                "   OR closed_at > now() - make_interval(secs => $1)",  # 平仓过渡窗内仍算期望腿
                float(CLOSE_GRACE_SEC))
            for p in drows:
                expected_legs.add((p["venue_long"], p["symbol"]))
                expected_legs.add((p["venue_short"], p["symbol"]))
            brows = await self_pool.fetch(
                "SELECT symbol FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED') "
                "   OR closed_at > now() - make_interval(secs => $1)", float(CLOSE_GRACE_SEC))
            for b in brows:   # basis=币安现货多+永续空,perp 腿在 binance
                expected_legs.add(("binance", b["symbol"]))
        except Exception as e:
            log.warning("recon_v2 expected legs read failed: %r", e)
        # exec-manager 接管仓(引擎退役后无 DB 行,owner-of-record=dcm:exec:manager 发布态):
        # pair 顶层 symbol=dcm 格式,与账户快照 positions 键同一口径;manager 死→键消失→如实转孤儿告警。
        try:
            mgr = await get_json(r, "dcm:exec:manager") or {}
            for s in (mgr.get("symbols") or []):
                if abs(float(s.get("perp_amt") or 0)) > 1e-12:
                    expected_legs.add(("binance", str(s.get("symbol") or "")))
            for p in (mgr.get("pairs") or []):
                psym = str(p.get("symbol") or "")
                for lg in (p.get("legs") or []):
                    if abs(float(lg.get("amt") or 0)) > 1e-12:
                        expected_legs.add((lg.get("venue"), psym))
        except Exception as e:
            log.warning("recon_v2 manager claims read failed: %r", e)
        orphans = []
        seen_keys = set()
        for v in RECON_VENUES:
            acct = acct_all.get(v) or {}
            if not acct.get("ok"):
                continue
            for s, q in (acct.get("positions") or {}).items():
                mark = float(((acct.get("pos_detail") or {}).get(s) or {}).get("mark") or 0)
                notional = abs(float(q)) * mark
                if notional <= ORPHAN_FLOOR_USDT:   # 地板:粉尘/结算残留不告警(绝对缺口误判课)
                    continue
                if (v, s) in expected_legs:
                    continue
                key = (v, s)
                seen_keys.add(key)
                _orphan_hits[key] = _orphan_hits.get(key, 0) + 1
                if _orphan_hits[key] >= 2:          # 去抖:连续 2 轮命中才 fire
                    orphans.append({"venue": v, "symbol": s, "qty": q,
                                    "notional": round(notional, 2)})
                    await fire(f"orphan:{v}:{s}", f"孤儿实盘仓 {v} {s}",
                               f"实盘 {q} base ≈{round(notional,1)}U 无 DB 配对行解释"
                               f"—平仓残腿/adopt未落库/手动仓,须人工核", level="fatal")
                    alerts += 1
        for key in list(_orphan_hits):              # 消失即清零(连续语义)
            if key not in seen_keys:
                _orphan_hits.pop(key, None)
        status["recon_v2"] = {"expected_legs": len(expected_legs), "orphans": orphans,
                              "floor_usdt": ORPHAN_FLOOR_USDT}

    # R9 保证金水位线:逐所 在场名义/权益 = 有效杠杆,超阈预警(补仓依赖余量,见底=补不动)
    waterline = []
    for v in RECON_VENUES:
        acct = acct_all.get(v) or {}
        if not acct.get("ok"):
            continue
        eq = float(acct.get("equity_usdt") or 0)
        notl = sum(abs(float(q)) * float(((acct.get("pos_detail") or {}).get(s) or {}).get("mark") or 0)
                   for s, q in (acct.get("positions") or {}).items())
        lev = (notl / eq) if eq > 0 else 0.0
        wl = {"venue": v, "equity": round(eq, 2), "pos_notional": round(notl, 2), "leverage": round(lev, 2)}
        waterline.append(wl)
        if eq > 0 and lev > MARGIN_LEV_WARN:
            await fire(f"waterline:{v}", f"{v} 保证金水位偏低",
                       f"在场名义 {round(notl,1)}U / 权益 {round(eq,1)}U = {round(lev,1)}x(>{MARGIN_LEV_WARN}x)"
                       f"—补仓余量不足,需注资或减仓", level="warn")
            alerts += 1
    status["waterline"] = waterline

    # R10 basis 底仓可见性:引擎已发布 dcm:engine:basis:positions(意图账),此处只呈现不新增告警——
    # basis 引擎 liveness 已由 R1 心跳(engine-basis)覆盖;单腿裸露由 R8 全域净敞口跨所归并兜底
    # (basis 现货多+永续空,delta 中性→R8 net≈0;缺腿则 R8 净敞口超地板 fatal,无需在此重复判断)。
    basis = await get_json(r, "dcm:engine:basis:positions")
    if basis:
        bpos = basis.get("positions") or []
        status["basis"] = {"mode": basis.get("mode"), "open": len(bpos),
                           "candidates": basis.get("candidates"),
                           "positions": [{"symbol": p.get("symbol"), "state": p.get("state"),
                                          "notional_usdt": p.get("notional_usdt"),
                                          "funding_daily": p.get("funding_daily")} for p in bpos]}

    status["alerts_this_round"] = alerts
    return status


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = None
    if PG_DSN:
        try:
            pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
        except Exception as e:
            log.warning("pg pool init failed (guards disabled): %r", e)
    global _alert_pool
    _alert_pool = pool
    hb = Heartbeat(REDIS_URL, "risk-ledger", interval_sec=INTERVAL, ttl_sec=INTERVAL * 3 + 30)
    log.info("risk-ledger up interval=%ss stale_pos=%ss guards=%s expected=%s",
             INTERVAL, STALE_POS_SEC, pool is not None, list(EXPECTED_HB))
    while True:
        try:
            status = await check_round(r, pool)
            hb.extra = {"alerts": status.get("alerts_this_round", 0)}
            await r.set("dcm:risk:status", json.dumps(status, ensure_ascii=False, default=str), ex=180)
            # G0 风险策略权威:算逐 venue 有效模式+能力位→发布 dcm:risk:policy(唯一发布者)
            try:
                pol = await compute_and_publish(pool, r)
                status["policy"] = {"version": pol["policy_version"], "capped": pol["capped_venues"],
                                    "nav": pol.get("nav")}
                # G2:trapped capital 折价>0 或 venue 落入 REDUCE 以上 → 告警(fire 共享节流防刷屏)
                nav = pol.get("nav") or {}
                if float(nav.get("trapped_usdt") or 0) > 0:
                    by = ", ".join(f"{k}={x}U" for k, x in (nav.get("trapped_by_venue") or {}).items())
                    await fire("nav-haircut", "NAV haircut:受限venue权益折价",
                               f"净NAV {nav.get('net_nav_usdt')}U = 总权益 {nav.get('gross_equity_usdt')}U"
                               f" − 折价 {nav.get('trapped_usdt')}U({by})", level="warn")
                for vn, vd in (pol.get("venues") or {}).items():
                    if vd.get("mode") in ("REDUCE_ONLY", "EXIT_ONLY", "FROZEN"):
                        await fire(f"policy-mode:{vn}", f"{vn} 风险模式={vd['mode']}",
                                   str(vd.get("reason", ""))[:300], level="fatal")
            except Exception:
                log.exception("policy compute/publish failed (continuing)")
            # CORE_POOL 封闭盒子不变量:组权益突降/成员限制 → 告警(fire 走共享节流+落库)
            try:
                cbmon = await corebox_check(r, fire=fire)
                status["corebox"] = {"sealed": cbmon.get("sealed"), "equity": cbmon.get("total_equity_usdt"),
                                     "members": cbmon.get("member_count")}
            except Exception:
                log.exception("corebox check failed (continuing)")
            await hb.beat_once()
            log.info("LEDGER_OK services=%s alerts=%d policy_v=%s capped=%s",
                     status.get("services"), status.get("alerts_this_round", 0),
                     status.get("policy", {}).get("version"), status.get("policy", {}).get("capped"))
        except Exception:
            log.exception("check round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
