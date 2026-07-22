"""exec-kernel opener 决策服务(V4.0 §5.1)—— B 机,**shadow 先行,绝不下单绝不武装**。
dualperp 引擎退役后,carry-advisor 的 active 路由无人消费开仓。opener 补这个洞:
  每轮读 dcm:route:assignments(active)→ 对每条路由过 O1 带符号净现金流 + E 闸 →
  产出 would_open 候选(dcm:exec:opener)。**候选不自动进 manager,operator 审后手动并入
  dcm:exec:manager:config 的 pairs 段(shadow),确认采纳+recon 绿再翻 armed**——保持
  shadow/armed 人为边界(V4.0 铁律:武装绝不自动)。

经济闸(与 engine-dualperp 同口径,离散化持有窗防假正 E):
  net_daily = O1 带符号(空腿 +funding − 多腿 +funding);funding stale>阈值→跳过不臆断
  funding_income_bps = net_daily × HOLD_HOURS/24 × 100    (只按预期持有窗收,不连续 × 天数)
  e_bps = funding_income_bps − fees(4 taker) − 往返价差估计
  开候选 = net_daily ≥ MIN_NET_DAILY_PCT 且 e_bps ≥ MIN_E_BPS 且未在管
发布 dcm:exec:opener + 心跳 dcm:hb:exec-opener。
"""
import asyncio
import json
import os
import re
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/packages/dcm-common")
from policy_client import can_open, read_policy, set_pool as policy_set_pool  # noqa: E402  # G0 风险策略消费

# RestrictionRiskCharge shadow(ADR-009 首期口径:Tier情景+锁资天数+救援成本上限;
# **只记录不闸**——概率化定价等真实事件样本攒够再进强制经济闸)
_TIER_SCENARIO_BPS = {"A": 0.0, "B": 15.0, "C": 40.0}
_TIER_LOCK_DAYS = {"A": 2, "B": 7, "C": 21}
_CAPCOST_BPS_PER_DAY = float(os.environ.get("DCM_RC_CAPCOST_BPS_D", "1"))
_RESCUE_BPS = float(os.environ.get("DCM_RC_RESCUE_BPS", "10"))


def _risk_charge_bps(tier):
    t = tier or "C"
    return _TIER_SCENARIO_BPS.get(t, 40.0) + _TIER_LOCK_DAYS.get(t, 21) * _CAPCOST_BPS_PER_DAY + _RESCUE_BPS
try:
    from dcm_common.arb_contract import o1_signed_cashflow_daily_pct
except Exception:  # noqa: BLE001  # 包缺失时内联同口径(禁 abs)
    def o1_signed_cashflow_daily_pct(legs):
        net = 0.0
        for lg in legs or []:
            if lg.get("side") == "perp_long":
                net += -float(lg.get("daily_pct") or 0)
            elif lg.get("side") == "perp_short":
                net += float(lg.get("daily_pct") or 0)
        return net

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_OPENER_INTERVAL_SEC", "60"))
FUNDING_STALE_SEC = int(os.environ.get("DCM_OPENER_FUNDING_STALE_SEC", "1800"))
HOLD_HOURS = float(os.environ.get("DCM_OPENER_HOLD_HOURS", "8"))
FEE_BPS_PER_FILL = float(os.environ.get("DCM_OPENER_FEE_BPS", "5"))
EST_ROUNDTRIP_COST_BPS = float(os.environ.get("DCM_OPENER_EST_COST_BPS", "8"))  # 往返价差估计(缺深度时)
MIN_NET_DAILY_PCT = float(os.environ.get("DCM_OPENER_MIN_NET_DAILY_PCT", "0.1"))
MIN_E_BPS = float(os.environ.get("DCM_OPENER_MIN_E_BPS", "0"))
MAX_CANDIDATES = int(os.environ.get("DCM_OPENER_MAX_CANDIDATES", "20"))
# ── 三期:carry衰减折价+持续性闸+新候选飞书(2026-07-21,三天冲刺tracking error课) ──
# ACE实证:开仓报3.3%/d,9h实收carry为负——尖峰费率入场即衰减。两道防线:
#  折价: funding_income按 DECAY 打折后过E闸(报价高估的经验修正)
#  持续性: 同一(symbol,腿对) net_daily 连续 PERSIST_ROUNDS 轮达标才出候选(尖峰过滤)
CARRY_DECAY = float(os.environ.get("DCM_OPENER_CARRY_DECAY", "0.5"))
PERSIST_ROUNDS = int(os.environ.get("DCM_OPENER_PERSIST_ROUNDS", "3"))
NOTIFY_NEW = os.environ.get("DCM_OPENER_NOTIFY_NEW", "true").lower() == "true"
try:
    from dcm_common.notify import Notifier
    _notifier = Notifier(REDIS_URL, "exec-opener")
except Exception:  # noqa: BLE001
    _notifier = None



async def _funding(r, venue, sym, now):
    """(daily_pct, 状态)。缺失/超龄→(None, 原因)。"""
    raw = await r.hget(f"dcm:feed:funding:{venue}", sym)
    if not raw:
        return None, "missing"
    try:
        f = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None, "bad"
    if now - float(f.get("ts") or 0) > FUNDING_STALE_SEC:
        return None, f"stale({int(now - float(f['ts']))}s)"
    return float(f.get("daily_pct") or 0), "ok"


async def _managed_symbols(r, pool):
    """已在管的 symbol 集合:manager 配置 pairs + exec_saga OPEN + 引擎 basis/coin。
    opener 只对'无人管'的路由出候选,避免与在管仓冲突重开。"""
    managed = set()
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        for pid, pc in (cfg.get("pairs") or {}).items():
            managed.add(pc.get("symbol") or pid)
        for s in (cfg.get("symbols") or {}):
            managed.add(s)
    except Exception:  # noqa: BLE001
        pass
    try:
        mg = json.loads(await r.get("dcm:exec:manager") or "{}")
        for p in (mg.get("pairs") or []):
            managed.add(p.get("symbol"))
        for s in (mg.get("symbols") or []):
            managed.add(s.get("symbol"))
    except Exception:  # noqa: BLE001
        pass
    if pool is not None:
        try:
            # ⚠️exec_saga 无 symbol 列——symbol 内嵌在 saga_id(mgr-APTUSDT-<gen> / c2-ESPORTSUSDT-<gen> /
            #   C1 形态 mgr-BTCUSDT 无 gen 尾)。旧查询 SELECT symbol 每轮抛 UndefinedColumnError 被
            #   except:pass 静默吞掉→此去重护栏自诞生起从未生效(2026-07-22 P2 发现)。改为解析 saga_id。
            for row in await pool.fetch(
                    "SELECT saga_id FROM exec_saga WHERE state NOT IN ('CLOSED','QUARANTINED')"):
                s = _symbol_from_saga_id(row["saga_id"])
                if s:
                    managed.add(s)
        except Exception:  # noqa: BLE001
            pass
    return {m for m in managed if m}


_SAGA_SYM_RE = re.compile(r"[A-Z0-9]{2,}(?:USDT|USDC|USD|BUSD)")


def _symbol_from_saga_id(saga_id):
    """从 saga_id 提取交易对 symbol。saga_id 形如 mgr-<sym>-<gen> / c2-<sym>-<gen> / mgr-<sym>(C1)。
    取第一个形如 <BASE>USDT 的 token(gen 是纯数字时间戳,不会误匹配)。"""
    if not saga_id:
        return None
    m = _SAGA_SYM_RE.search(str(saga_id).upper())
    return m.group(0) if m else None


# ── 二期:一档容量因子(shadow先行,enforce须DCM_OPENER_DEPTH_ENFORCE=true) ──
DEPTH_K = float(os.environ.get("DCM_OPENER_DEPTH_K", "3"))          # 一档额须≥目标名义×K
DEPTH_ENFORCE = os.environ.get("DCM_OPENER_DEPTH_ENFORCE", "").lower() == "true"


async def _depth_l1(r, venue, sym):
    """读 l1lite 一档(WS采集,base qty已含张数换算);开多吃卖1/开空吃买1。
    顺带续订 want 键(TTL900,opener 60s/轮=候选币常驻订阅)。"""
    canon = sym[:-4] if sym.upper().endswith("USDT") else sym
    try:
        await r.setex(f"dcm:l1lite:want:{canon}", 900, "1")
        raw = await r.get(f"dcm:l1lite:{venue}:perp:{canon}")
        if not raw:
            return None
        d = json.loads(raw)
        return d
    except Exception:  # noqa: BLE001
        return None


async def evaluate(r, pool, now):
    ra = await r.hgetall("dcm:route:assignments")
    managed = await _managed_symbols(r, pool)
    candidates, skipped = [], []
    for sym, raw in (ra or {}).items():
        try:
            rt = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if rt.get("state") != "active":
            continue
        if str(rt.get("engine")) != "dualperp":   # opener v1 只接 C2 跨所双永续(dualperp 的活)
            continue
        if sym in managed:
            skipped.append({"symbol": sym, "reason": "already_managed"})
            continue
        vl, vs = rt.get("venue_long"), rt.get("venue_short")
        target = float(rt.get("target_notional_usdt") or 0)
        # G0 风险策略闸:任一腿 venue 不允许新增(敞口超限/NO_NEW/超龄 fail-closed)→ 不出候选
        okl, rl = await can_open(r, vl)
        oks, rs = await can_open(r, vs)
        if not (okl and oks):
            skipped.append({"symbol": sym, "reason": f"policy {vl}={rl}/{vs}={rs}"})
            continue
        fl, sl = await _funding(r, vl, sym, now)
        fs, ss = await _funding(r, vs, sym, now)
        if fl is None or fs is None:
            skipped.append({"symbol": sym, "reason": f"funding {vl}={sl}/{vs}={ss}"})
            continue
        net_daily = o1_signed_cashflow_daily_pct(
            [{"side": "perp_long", "daily_pct": fl}, {"side": "perp_short", "daily_pct": fs}])
        funding_income_bps = net_daily * HOLD_HOURS / 24.0 * 100.0
        fees_bps = FEE_BPS_PER_FILL * 4.0
        # 三期折价:按经验衰减系数打折(raw保留展示)
        funding_income_raw_bps = funding_income_bps
        funding_income_bps = funding_income_bps * CARRY_DECAY
        e_bps = funding_income_bps - fees_bps - EST_ROUNDTRIP_COST_BPS
        pol, _ = await read_policy(r)
        pv = (pol or {}).get("venues") or {}
        charge = max(_risk_charge_bps((pv.get(vl) or {}).get("tier")),
                     _risk_charge_bps((pv.get(vs) or {}).get("tier")))
        rec = {"symbol": sym, "venue_long": vl, "venue_short": vs,
               "target_notional_usdt": round(target, 2),
               "net_daily_pct": round(net_daily, 5),
               "e_bps": round(e_bps, 3),
               "risk_charge_bps": round(charge, 2),
               "risk_adjusted_e_bps": round(e_bps - charge, 3),
               "parts": {"funding_income": round(funding_income_bps, 2),
                         "funding_income_raw": round(funding_income_raw_bps, 2),
                         "carry_decay": CARRY_DECAY,
                         "fees": round(fees_bps, 2), "est_cost": EST_ROUNDTRIP_COST_BPS},
               "route_reason": rt.get("reason")}
        # 一档容量因子(shadow):多腿开仓吃 venue_long 卖1,空腿吃 venue_short 买1
        dl = await _depth_l1(r, vl, sym)
        ds_ = await _depth_l1(r, vs, sym)
        top_l = (dl.get("aq") or 0) * (dl.get("ask") or 0) if dl else None
        top_s = (ds_.get("bq") or 0) * (ds_.get("bid") or 0) if ds_ else None
        depth_top = min(top_l, top_s) if (top_l is not None and top_s is not None) else None
        cap_ratio = round(depth_top / target, 2) if (depth_top is not None and target > 0) else None
        rec["depth_l1_usdt"] = round(depth_top, 0) if depth_top is not None else None
        rec["capacity_ratio"] = cap_ratio
        rec["depth_verdict"] = ("NO_DATA" if cap_ratio is None
                                else "OK" if cap_ratio >= DEPTH_K else "THIN")
        gate_ok = (target > 0 and net_daily >= MIN_NET_DAILY_PCT and e_bps >= MIN_E_BPS)
        if DEPTH_ENFORCE and rec["depth_verdict"] == "THIN":
            gate_ok = False
            rec["reason"] = f"depth_thin(一档{rec['depth_l1_usdt']}U<{DEPTH_K}x目标{target}U)"
        if gate_ok and PERSIST_ROUNDS > 1:
            pk = f"dcm:opener:persist:{sym}:{vl}:{vs}"
            try:
                strikes = await r.incr(pk)
                await r.expire(pk, INTERVAL * PERSIST_ROUNDS * 4)  # 断档自然过期清零
            except Exception:  # noqa: BLE001
                strikes = PERSIST_ROUNDS  # Redis异常不误杀
            rec["persist_rounds"] = int(strikes)
            if strikes < PERSIST_ROUNDS:
                gate_ok = False
                rec["reason"] = f"persist {strikes}/{PERSIST_ROUNDS}(连续达标轮数不足,防尖峰)"
        if gate_ok:
            # manager pairs 交接片段(operator 直接复制并入 config;默认 shadow+hold,采纳后再翻 armed+close 由信号驱动)
            rec["manager_pair"] = {
                "mode": "shadow", "target": "hold", "signal_source": "route", "symbol": sym,
                "legs": [{"venue": vl, "side": "BUY"}, {"venue": vs, "side": "SELL"}]}
            candidates.append(rec)
        else:
            if "reason" not in rec:
                rec["reason"] = ("net<%.2f" % MIN_NET_DAILY_PCT if net_daily < MIN_NET_DAILY_PCT
                                 else "e_bps<%.1f" % MIN_E_BPS if e_bps < MIN_E_BPS else "target=0")
            if not rec["reason"].startswith("persist"):
                try:
                    await r.delete(f"dcm:opener:persist:{sym}:{vl}:{vs}")
                except Exception:  # noqa: BLE001
                    pass
            skipped.append(rec)
    candidates.sort(key=lambda c: c["e_bps"], reverse=True)
    return {"ts": int(now), "mode": "shadow", "candidates": candidates[:MAX_CANDIDATES],
            "candidate_count": len(candidates), "skipped": skipped[:MAX_CANDIDATES],
            "gate": {"min_net_daily_pct": MIN_NET_DAILY_PCT, "min_e_bps": MIN_E_BPS,
                     "hold_hours": HOLD_HOURS,
                     "depth_k": DEPTH_K, "depth_enforce": DEPTH_ENFORCE}}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2) if PG_DSN else None
    policy_set_pool(pool)
    once = "--once" in sys.argv
    while True:
        try:
            s = await evaluate(r, pool, time.time())
            await r.set("dcm:exec:opener", json.dumps(s, ensure_ascii=False), ex=max(INTERVAL * 3, 300))
            await r.set("dcm:hb:exec-opener", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-opener", "candidates": s["candidate_count"]}), ex=300)
            print(f"opener: candidates={s['candidate_count']} "
                  + ", ".join(f"{c['symbol']}(E={c['e_bps']}bps net={c['net_daily_pct']}%)"
                              for c in s["candidates"][:5]))
            if NOTIFY_NEW and _notifier is not None:
                for c in s["candidates"]:
                    if (c.get("risk_adjusted_e_bps") or -1) <= 0:
                        continue
                    try:
                        _notifier.fire(
                            f"cand:{c['symbol']}",
                            f"C2.H候选 {c['symbol']}",
                            (f"{c['venue_long']}多/{c['venue_short']}空 净{c['net_daily_pct']}%/d "
                             f"折价后E={c['e_bps']}bps 风险调整{c['risk_adjusted_e_bps']}bps "
                             f"深度{c.get('depth_l1_usdt')}U 连续{c.get('persist_rounds','-')}轮 "
                             f"(shadow,人工审批后并入manager)"),
                            level="warn", marquee=True, color="#F0B90B")
                    except Exception as e:  # noqa: BLE001
                        print("notify err", repr(e)[:80])
        except Exception as e:  # noqa: BLE001
            print("opener err", repr(e)[:160])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
