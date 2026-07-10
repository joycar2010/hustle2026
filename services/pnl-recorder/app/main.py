"""pnl-recorder(B 机,key 只在 B):PnL 三表持久化——五所账单逐笔入账 + 权益快照。

- 每 DCM_PNL_INTERVAL_SEC(300s) 按游标增量拉五所账单(资金费/手续费/已实现盈亏),
  (venue, ext_id) 唯一去重幂等入 income_records;游标=该所本轮最大 ts-60s(重叠窗防漏);
- 每小时写 equity_snapshots(从 dcm:account:* 读,已是实盘真相);
- 逐所失败隔离,失败只告日志绝不写假数据(coin 学费:失败静默返空=假巨亏);
- 汇总写 dcm:pnl:summary 供面板(累计资金费/手续费/PNL+今日)。
"""
import asyncio
import json
import logging
import os
import time

import asyncpg
import httpx
import redis.asyncio as aioredis

from dcm_common.exchange_bills import fetch_income

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pnl-recorder")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_PNL_INTERVAL_SEC", "300"))
BOOTSTRAP_HOURS = int(os.environ.get("DCM_PNL_BOOTSTRAP_HOURS", "24"))

VENUE_CFG = {
    "binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
    "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
    "okx": {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
            "passphrase": os.environ.get("OKX_PASSPHRASE", "")},
    "gate": {"key": os.environ.get("GATE_KEY", ""), "secret": os.environ.get("GATE_SECRET", "")},
    "bitget": {"key": os.environ.get("BITGET_KEY", ""), "secret": os.environ.get("BITGET_SECRET", ""),
               "passphrase": os.environ.get("BITGET_PASSPHRASE", "")},
}


async def pull_venue(cli, pool, venue, cfg) -> tuple[int, str]:
    cur = await pool.fetchval("SELECT last_ts_ms FROM income_cursors WHERE venue=$1", venue)
    since = int(cur) if cur else int((time.time() - BOOTSTRAP_HOURS * 3600) * 1000)
    try:
        recs = await fetch_income(cli, venue, cfg, since)
    except Exception as e:
        return 0, f"{e!r}"[:120]
    ins = 0
    max_ts = since
    for r in recs:
        if not r.ext_id:
            continue
        max_ts = max(max_ts, r.ts_ms)
        status = await pool.execute(
            "INSERT INTO income_records(venue,ext_id,symbol,itype,amount,ts,raw) "
            "VALUES($1,$2,$3,$4,$5,to_timestamp($6/1000.0),$7) ON CONFLICT (venue,ext_id) DO NOTHING",
            r.venue, r.ext_id, r.symbol, r.itype, r.amount, r.ts_ms,
            json.dumps(r.raw, ensure_ascii=False, default=str))
        if status.endswith("1"):
            ins += 1
    # 游标回退60s重叠窗,由唯一约束吸收重复
    await pool.execute(
        "INSERT INTO income_cursors(venue,last_ts_ms,updated_at) VALUES($1,$2,now()) "
        "ON CONFLICT (venue) DO UPDATE SET last_ts_ms=GREATEST(income_cursors.last_ts_ms,$2),updated_at=now()",
        venue, max(since, max_ts - 60_000))
    return ins, ""


async def equity_snapshot(r, pool):
    for v in VENUE_CFG:
        raw = await r.get(f"dcm:account:{v}")
        if not raw:
            continue
        d = json.loads(raw)
        if d.get("ok"):
            await pool.execute("INSERT INTO equity_snapshots(venue,equity_usdt) VALUES($1,$2)",
                               v, float(d.get("equity_usdt") or 0))


async def summary(pool) -> dict:
    rows = await pool.fetch(
        "SELECT itype, round(sum(amount),4) AS total, "
        "round(sum(amount) FILTER (WHERE ts>date_trunc('day',now())),4) AS today "
        "FROM income_records GROUP BY itype")
    out = {"ts": int(time.time()), "total": {}, "today": {}}
    for r in rows:
        out["total"][r["itype"]] = float(r["total"] or 0)
        out["today"][r["itype"]] = float(r["today"] or 0)
    trade_keys = ("FUNDING", "FEE", "PNL")  # 净额只含交易性收支;TRANSFER/OTHER(划转入金)剔除
    out["net_total"] = round(sum(v for k, v in out["total"].items() if k in trade_keys), 4)
    out["net_today"] = round(sum(v for k, v in out["today"].items() if k in trade_keys), 4)
    return out


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
    active = {v: c for v, c in VENUE_CFG.items() if c.get("key")}
    log.info("pnl-recorder up interval=%ss venues=%s", INTERVAL, list(active))
    last_snap = 0.0
    while True:
        try:
            stats = {}
            async with httpx.AsyncClient(timeout=20) as cli:
                for v, c in active.items():
                    ins, err = await pull_venue(cli, pool, v, c)
                    stats[v] = ins if not err else f"ERR:{err[:60]}"
            if time.time() - last_snap > 3600:
                await equity_snapshot(r, pool)
                last_snap = time.time()
            s = await summary(pool)
            await r.set("dcm:pnl:summary", json.dumps(s, ensure_ascii=False), ex=INTERVAL * 3)
            await r.set("dcm:hb:pnl-recorder", json.dumps(
                {"service": "pnl-recorder", "ts": int(time.time()), "pid": os.getpid(),
                 "pulled": stats, "net_total": s["net_total"]}, ensure_ascii=False),
                ex=max(INTERVAL * 3, 900))
            log.info("PNL_OK pulled=%s net_total=%s net_today=%s", stats, s["net_total"], s["net_today"])
        except Exception:
            log.exception("pnl round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
