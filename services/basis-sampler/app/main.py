"""basis-sampler:连续基差采样(数据面)。

持续记录 活跃路由 ∪ 在场持仓 的基差(gap=(空腿bid-多腿ask)/多腿ask)到 dualperp_basis_samples,
供基差止损历史分位用——覆盖比 shadow_log 更全:route 置 off 后 shadow_log 停记,但持仓仍需
基差历史来判分位;本采样器按持仓+活跃路由持续采,不受 route 状态影响。

独立数据面服务(A 机):只读 feed + 写时序样本,崩了不影响交易;周期清理超窗样本。
"""
import asyncio
import json
import logging
import os
import time
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("basis-sampler")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_BASIS_SAMPLE_SEC", "45"))
RETAIN_HOURS = int(os.environ.get("DCM_BASIS_RETAIN_HOURS", "48"))


async def _gap(r, vl, vs, sym):
    """基差=(空腿bid-多腿ask)/多腿ask,bps。任一腿缺失返 None。"""
    ll = await r.hget(f"dcm:feed:{vl}:perp", sym)
    sl = await r.hget(f"dcm:feed:{vs}:perp", sym)
    if not (ll and sl):
        return None
    try:
        long_ask = Decimal(str(json.loads(ll)["ask"]))
        short_bid = Decimal(str(json.loads(sl)["bid"]))
    except Exception:
        return None
    if long_ask <= 0:
        return None
    return (short_bid - long_ask) / long_ask * Decimal("10000")


async def _pairs(r) -> set[tuple[str, str, str]]:
    """采样对象:活跃双合约路由 ∪ 在场持仓(dualperp)。"""
    out: set[tuple[str, str, str]] = set()
    try:
        for js in (await r.hgetall("dcm:route:assignments")).values():
            rt = json.loads(js)
            if rt.get("engine") == "dualperp" and rt.get("state") == "active":
                out.add((rt["symbol"], rt["venue_long"], rt["venue_short"]))
    except Exception as e:
        log.warning(f"route read failed: {e!r}")
    try:
        dp = json.loads(await r.get("dcm:engine:dualperp:positions") or "{}")
        for p in dp.get("positions", []) or []:
            out.add((p["symbol"], p["venue_long"], p["venue_short"]))
    except Exception as e:
        log.warning(f"positions read failed: {e!r}")
    return out


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    log.info("basis-sampler up interval=%ss retain=%sh", INTERVAL, RETAIN_HOURS)
    last_clean = 0.0
    while True:
        try:
            pairs = await _pairs(r)
            n = 0
            for sym, vl, vs in pairs:
                gap = await _gap(r, vl, vs, sym)
                if gap is not None:
                    await pool.execute(
                        "INSERT INTO dualperp_basis_samples(symbol,venue_long,venue_short,basis_bps) "
                        "VALUES($1,$2,$3,$4)", sym, vl, vs, gap)
                    n += 1
            if time.time() - last_clean > 3600:
                await pool.execute(
                    f"DELETE FROM dualperp_basis_samples WHERE ts < now() - interval '{RETAIN_HOURS} hours'")
                last_clean = time.time()
            await r.set("dcm:hb:basis-sampler", json.dumps(
                {"service": "basis-sampler", "ts": int(time.time()), "pid": os.getpid(),
                 "pairs": len(pairs), "sampled": n}), ex=max(INTERVAL * 3, 200))
            log.info("BASIS_OK pairs=%d sampled=%d", len(pairs), n)
        except Exception:
            log.exception("basis round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
