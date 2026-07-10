"""engine-basis(shadow):币安期现底仓 carry 评估器(收益地板层)。

结构:币安现货多 + 永续空,收正资金费(+可质押现货腿转理财=双份收益,shadow 期先只算资金费)。
单所双腿(同账户),无跨所保证金对称问题,容量最大零转账风险——蓝图第 1 层。

shadow 自驱:扫币安 funding 哈希取正资金费币,读现货+永续 L1 算净期望 E:
  E = 资金费收益(日化%×HORIZON×100) − 往返价差(买现货ask+卖永续bid, 平仓反向) − 双边手续费
funding 正 且 E≥门槛 → would_open;记 basis_shadow_log + 发 dcm:engine:basis:positions。
armed 执行留后续(复用 binance client:现货买/永续卖 + PM 质押),本版只 shadow 攒战绩。
"""
import asyncio
import json
import logging
import os
import socket
import time
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("engine-basis")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
EVAL_SEC = int(os.environ.get("DCM_BASIS_EVAL_SEC", "10"))
HORIZON_DAYS = Decimal(os.environ.get("DCM_BASIS_HORIZON_DAYS", "5"))     # 底仓持有更久
FEE_BPS_PER_FILL = Decimal(os.environ.get("DCM_BASIS_FEE_BPS", "4"))       # 现货+合约 maker 化更低
MIN_E_BPS = Decimal(os.environ.get("DCM_BASIS_MIN_E_BPS", "5"))
MIN_FUNDING_DAILY = Decimal(os.environ.get("DCM_BASIS_MIN_FUNDING", "0.01"))
STALE_MS = int(os.environ.get("DCM_BASIS_STALE_MS", "10000"))
TOP_N = int(os.environ.get("DCM_BASIS_TOP_N", "30"))
LOG_EVERY_SEC = 60


async def l1(r, market, sym):
    raw = await r.hget(f"dcm:feed:binance:{market}", sym)
    return json.loads(raw) if raw else None


def evaluate(spot, perp, fund_daily: Decimal):
    """现货多+永续空:funding 正=永续空收。返回 (decision, detail)。"""
    now_ms = int(time.time() * 1000)
    for x in (spot, perp):
        if x is None or now_ms - int(x.get("recv_ts") or 0) > STALE_MS:
            return "skip_stale", {}
    spot_ask = Decimal(str(spot["ask"])); spot_bid = Decimal(str(spot["bid"]))
    perp_bid = Decimal(str(perp["bid"])); perp_ask = Decimal(str(perp["ask"]))
    if spot_ask <= 0:
        return "skip_stale", {}
    # 入场:买现货@ask 卖永续@bid;出场:卖现货@bid 买永续@ask
    entry_gap = (perp_bid - spot_ask) / spot_ask * Decimal("10000")
    exit_gap = (spot_bid - perp_ask) / spot_ask * Decimal("10000")
    funding_bps = fund_daily * HORIZON_DAYS * Decimal("100")
    fees_bps = FEE_BPS_PER_FILL * Decimal("4")
    e_bps = funding_bps + entry_gap + exit_gap - fees_bps
    detail = {"e_bps": str(round(e_bps, 2)), "funding_daily": str(round(fund_daily, 5)),
              "entry_gap": str(round(entry_gap, 2)), "exit_gap": str(round(exit_gap, 2)),
              "funding_bps": str(round(funding_bps, 1))}
    if fund_daily >= MIN_FUNDING_DAILY and e_bps >= MIN_E_BPS:
        return "would_open", detail
    return "idle", detail


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    hb = Heartbeat(REDIS_URL, "engine-basis", interval_sec=30, ttl_sec=120)
    asyncio.create_task(hb.run_forever())
    log.info("engine-basis(shadow) up pid=%s host=%s min_E=%sbps horizon=%sd",
             os.getpid(), socket.gethostname(), MIN_E_BPS, HORIZON_DAYS)
    last_log: dict[str, tuple[str, float]] = {}
    while True:
        try:
            fmap = await r.hgetall("dcm:feed:funding:binance")
            cand = []
            for sym, js in fmap.items():
                try:
                    fd = Decimal(str(json.loads(js)["daily_pct"]))
                except Exception:
                    continue
                if fd >= MIN_FUNDING_DAILY:
                    cand.append((sym, fd))
            cand.sort(key=lambda x: -x[1])
            shadow = {}
            for sym, fd in cand[:TOP_N]:
                sp = await l1(r, "spot", sym); pp = await l1(r, "perp", sym)
                decision, detail = evaluate(sp, pp, fd)
                if not detail:
                    continue
                shadow[sym] = {"decision": decision, **detail}
                prev = last_log.get(sym)
                if prev is None or prev[0] != decision or time.time() - prev[1] >= LOG_EVERY_SEC:
                    await pool.execute(
                        "INSERT INTO basis_shadow_log(symbol,funding_daily,e_bps,decision,detail) "
                        "VALUES($1,$2,$3,$4,$5)",
                        sym, fd, Decimal(detail["e_bps"]), decision, json.dumps(detail))
                    last_log[sym] = (decision, time.time())
            await r.set("dcm:engine:basis:positions", json.dumps(
                {"ts": int(time.time()), "mode": "shadow", "positions": [],
                 "candidates": len(cand), "shadow": shadow}, ensure_ascii=False), ex=180)
            hb.extra = {"mode": "shadow", "candidates": len(cand), "would_open":
                        sum(1 for v in shadow.values() if v["decision"] == "would_open")}
        except Exception:
            log.exception("basis eval crashed (continuing)")
        await asyncio.sleep(EVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
