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
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/packages/dcm-common")
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
            for row in await pool.fetch(
                    "SELECT DISTINCT symbol FROM exec_saga WHERE state NOT IN ('CLOSED','QUARANTINED')"):
                managed.add(row["symbol"])
        except Exception:  # noqa: BLE001
            pass
    return {m for m in managed if m}


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
        fl, sl = await _funding(r, vl, sym, now)
        fs, ss = await _funding(r, vs, sym, now)
        if fl is None or fs is None:
            skipped.append({"symbol": sym, "reason": f"funding {vl}={sl}/{vs}={ss}"})
            continue
        net_daily = o1_signed_cashflow_daily_pct(
            [{"side": "perp_long", "daily_pct": fl}, {"side": "perp_short", "daily_pct": fs}])
        funding_income_bps = net_daily * HOLD_HOURS / 24.0 * 100.0
        fees_bps = FEE_BPS_PER_FILL * 4.0
        e_bps = funding_income_bps - fees_bps - EST_ROUNDTRIP_COST_BPS
        rec = {"symbol": sym, "venue_long": vl, "venue_short": vs,
               "target_notional_usdt": round(target, 2),
               "net_daily_pct": round(net_daily, 5),
               "e_bps": round(e_bps, 3),
               "parts": {"funding_income": round(funding_income_bps, 2),
                         "fees": round(fees_bps, 2), "est_cost": EST_ROUNDTRIP_COST_BPS},
               "route_reason": rt.get("reason")}
        gate_ok = (target > 0 and net_daily >= MIN_NET_DAILY_PCT and e_bps >= MIN_E_BPS)
        if gate_ok:
            # manager pairs 交接片段(operator 直接复制并入 config;默认 shadow+hold,采纳后再翻 armed+close 由信号驱动)
            rec["manager_pair"] = {
                "mode": "shadow", "target": "hold", "signal_source": "route", "symbol": sym,
                "legs": [{"venue": vl, "side": "BUY"}, {"venue": vs, "side": "SELL"}]}
            candidates.append(rec)
        else:
            rec["reason"] = ("net<%.2f" % MIN_NET_DAILY_PCT if net_daily < MIN_NET_DAILY_PCT
                             else "e_bps<%.1f" % MIN_E_BPS if e_bps < MIN_E_BPS else "target=0")
            skipped.append(rec)
    candidates.sort(key=lambda c: c["e_bps"], reverse=True)
    return {"ts": int(now), "mode": "shadow", "candidates": candidates[:MAX_CANDIDATES],
            "candidate_count": len(candidates), "skipped": skipped[:MAX_CANDIDATES],
            "gate": {"min_net_daily_pct": MIN_NET_DAILY_PCT, "min_e_bps": MIN_E_BPS,
                     "hold_hours": HOLD_HOURS}}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2) if PG_DSN else None
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
        except Exception as e:  # noqa: BLE001
            print("opener err", repr(e)[:160])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
