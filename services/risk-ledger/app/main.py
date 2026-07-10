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
from dcm_common.notify import FeishuTarget, Notifier

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

# 期望在场的服务及其心跳最大年龄(秒)。缺失键==停更同罪。
EXPECTED_HB = {
    "feed-cex": 120,
    "coin-bridge": 240,
    "universe-sync": 7500,
    "gateway": 120,
    "decision": 120,
    "engine-dualperp": 120,
    "funding-sync": 900,
    "carry-advisor": 1900,
    "account-snapshot": 240,
    "depth-sampler": 400,
}
RECON_VENUES = ("binance", "bybit", "okx", "gate", "bitget")
STALE_STATUSES = ("PENDING_BORROW", "BORROWED_IDLE", "PENDING_REPAY")

notifier = Notifier(
    REDIS_URL, "risk-ledger",
    feishu=FeishuTarget(webhook_url=os.environ.get("DCM_FEISHU_WEBHOOK", "")),
    throttle_interval_sec=THROTTLE_SEC, throttle_max_count=1,
)


async def fire(key: str, title: str, content: str, level: str = "warn"):
    """告警=日志+飞书(若配置)+跑马灯发布,经共享节流;绝不抛异常打断巡检轮。"""
    try:
        res = await asyncio.to_thread(notifier.fire, key, title, content,
                                      level=level, marquee=True, color="#ef4444")
        log.warning("ALERT[%s] %s | %s -> %s", key, title, content, res)
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
                    if dist is not None and dist < DIST_LIQ_CRIT:
                        await fire(f"liq-crit:{sym}:{leg}", f"双合约腿逼近强平 {sym}",
                                   f"{leg}腿距强平仅 {dist}%(<{DIST_LIQ_CRIT}%)—补保证金或减双腿", level="fatal")
                        alerts += 1
                    elif dist is not None and dist < DIST_LIQ_WARN:
                        await fire(f"liq-warn:{sym}:{leg}", f"双合约腿保证金侵蚀 {sym}",
                                   f"{leg}腿距强平 {dist}%(<{DIST_LIQ_WARN}%)", level="warn")
                        alerts += 1
                    if adl is not None and adl >= ADL_WARN:
                        await fire(f"adl:{sym}:{leg}", f"双合约腿 ADL 高位 {sym}",
                                   f"{leg}腿 ADL={adl}(≥{ADL_WARN})—盈利腿或被自动减仓", level="warn")
                        alerts += 1
                pg["dist_liq"] = {"long": dl.get("dist_liq_pct"), "short": ds.get("dist_liq_pct")}
                pg["adl"] = {"long": dl.get("adl"), "short": ds.get("adl")}
                pg["upnl"] = {"long": dl.get("upnl"), "short": ds.get("upnl")}
            guards["pairs"].append(pg)
    status["guards"] = guards

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
    hb = Heartbeat(REDIS_URL, "risk-ledger", interval_sec=INTERVAL, ttl_sec=INTERVAL * 3 + 30)
    log.info("risk-ledger up interval=%ss stale_pos=%ss guards=%s expected=%s",
             INTERVAL, STALE_POS_SEC, pool is not None, list(EXPECTED_HB))
    while True:
        try:
            status = await check_round(r, pool)
            hb.extra = {"alerts": status.get("alerts_this_round", 0)}
            await r.set("dcm:risk:status", json.dumps(status, ensure_ascii=False, default=str), ex=180)
            await hb.beat_once()
            log.info("LEDGER_OK services=%s alerts=%d",
                     status.get("services"), status.get("alerts_this_round", 0))
        except Exception:
            log.exception("check round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
