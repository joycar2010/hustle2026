"""fund-scheduler v1:资金调度面(蓝图第五平面)——只提案不动手。

水位线定义(蓝图原文):每所维持"最大单日不利行情下双腿补仓需求"的保证金储备。
量化口径:
  target_equity[venue] = max(
      PORTFOLIO_CAP / 3,                          # 永不瓶颈线(预算闸=权益×3)
      leg_notional / 3 + leg_notional × ADVERSE   # 支撑现有腿 + 单日不利补仓弹药
  )
  富余所 = equity > target × SURPLUS_RATIO;缺口所 = equity < target。
  提案 = 从最富余所依次划拨补齐缺口(贪心配平),经飞书发出,人工执行。

v1 铁律:**绝不调用任何转账/提现 API**——提现权限是全系统最高危面,自动划转(v2)
须独立 key+地址白名单+单笔/日累计限额+二次确认,未建成前只做"算+说"。
状态键 dcm:fund:proposal(EX 2×interval)供控制台展示;有提案才发飞书(节流)。
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("fund-scheduler")

SERVICE = "fund-scheduler"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_FUND_INTERVAL_SEC", "3600"))
VENUES = ("binance", "bybit", "okx", "gate", "bitget", "hyperliquid")
ADVERSE_PCT = float(os.environ.get("DCM_FUND_ADVERSE_PCT", "20")) / 100.0  # 单日不利行情假设
PORTFOLIO_CAP = float(os.environ.get("DCM_FUND_PORTFOLIO_CAP", "120"))     # 与引擎组合上限对齐
SURPLUS_RATIO = float(os.environ.get("DCM_FUND_SURPLUS_RATIO", "1.5"))     # 超目标此倍数才算富余
MIN_MOVE_USDT = float(os.environ.get("DCM_FUND_MIN_MOVE_USDT", "10"))      # 小于此不值一次划转


async def venue_leg_notional(pool) -> dict:
    """逐所在场腿名义(dualperp 非终态两腿 + basis 非终态 binance perp 腿)。"""
    out = {v: 0.0 for v in VENUES}
    try:
        rows = await pool.fetch(
            "SELECT venue_long,venue_short,notional_usdt FROM dualperp_positions "
            "WHERE state NOT IN ('CLOSED','FAILED','ROLLBACK')")
        for rec in rows:
            n = float(rec["notional_usdt"] or 0)
            for v in (rec["venue_long"], rec["venue_short"]):
                if v in out:
                    out[v] += n
        brows = await pool.fetch(
            "SELECT notional_usdt FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED')")
        for rec in brows:
            out["binance"] += float(rec["notional_usdt"] or 0)
    except Exception as e:
        log.warning("leg notional read failed: %r", e)
    return out


async def scheduler_round(r: aioredis.Redis, pool, notify: Notifier) -> dict:
    now = int(time.time())
    legs = await venue_leg_notional(pool)
    plan = {"ts": now, "venues": [], "proposals": []}
    deficits, surpluses = [], []
    for v in VENUES:
        acct = json.loads(await r.get(f"dcm:account:{v}") or "{}")
        if not acct.get("ok"):
            plan["venues"].append({"venue": v, "status": "snapshot_unavailable"})
            continue
        eq = float(acct.get("equity_usdt") or 0)
        notl = legs.get(v, 0.0)
        if eq == 0 and notl == 0:
            plan["venues"].append({"venue": v, "status": "inactive(零权益零腿,不催款)"})
            continue  # 未启用所(如 HL 待入金)豁免最低水位线
        target = max(PORTFOLIO_CAP / 3.0, notl / 3.0 + notl * ADVERSE_PCT)
        row = {"venue": v, "equity": round(eq, 2), "leg_notional": round(notl, 2),
               "target": round(target, 2)}
        plan["venues"].append(row)
        if eq < target:
            deficits.append([v, target - eq])
        elif eq > target * SURPLUS_RATIO:
            surpluses.append([v, eq - target * SURPLUS_RATIO])

    # 贪心配平:最富余 → 最大缺口
    deficits.sort(key=lambda x: -x[1])
    surpluses.sort(key=lambda x: -x[1])
    for d in deficits:
        need = d[1]
        for s in surpluses:
            if need < MIN_MOVE_USDT:
                break
            if s[1] < MIN_MOVE_USDT:
                continue
            amt = min(need, s[1])
            plan["proposals"].append(
                {"from": s[0], "to": d[0], "usdt": round(amt, 2)})
            s[1] -= amt
            need -= amt
        d[1] = need

    await r.set("dcm:fund:proposal", json.dumps(plan, ensure_ascii=False), ex=INTERVAL * 2)
    if plan["proposals"]:
        lines = [f"{p['from']} → {p['to']}: {p['usdt']}U" for p in plan["proposals"]]
        await asyncio.to_thread(
            notify.fire, "rebalance", "资金调度提案(人工执行)",
            "水位线缺口配平:\n" + "\n".join(lines) +
            f"\n口径:目标=max(组合上限/3, 腿名义/3+{int(ADVERSE_PCT*100)}%弹药);"
            f"提现属最高危权限,v1 只提案不动手", level="warn")
    return {"proposals": len(plan["proposals"]),
            "deficit_venues": [d[0] for d in deficits if d[1] >= MIN_MOVE_USDT]}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    notify = Notifier(REDIS_URL, SERVICE, feishu=feishu_from_env())
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=60, ttl_sec=1200)
    asyncio.create_task(hb.run_forever())
    log.info(f"fund-scheduler up interval={INTERVAL}s cap={PORTFOLIO_CAP} adverse={ADVERSE_PCT}")
    while True:
        try:
            stats = await scheduler_round(r, pool, notify)
            hb.extra = stats
            log.info(f"FUND_OK {stats}")
        except Exception:
            log.exception("scheduler round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
