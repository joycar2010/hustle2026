"""account-snapshot(B 机):五所真实账户只读快照发布器。

API key 白名单只绑 B 机 → 所有交易所私有调用只从 B 发起,key 只存 B 一处;
风控面 risk-ledger(C 机)读 Redis 快照做对账,永不持 key——与 coin-bridge 同一隔离哲学。

键契约:dcm:account:{venue} = {ts, ok, equity_usdt, positions, err}(EX 180)
        dcm:hb:account-snapshot 逐所 ok/equity 计数
只读:本服务无任何下单能力。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

from dcm_common.exchanges import fetch_account

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("account-snapshot")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_ACCT_INTERVAL_SEC", "60"))

VENUE_CFG = {
    "binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
    "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
    "okx": {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
            "passphrase": os.environ.get("OKX_PASSPHRASE", "")},
    "gate": {"key": os.environ.get("GATE_KEY", ""), "secret": os.environ.get("GATE_SECRET", "")},
    "bitget": {"key": os.environ.get("BITGET_KEY", ""), "secret": os.environ.get("BITGET_SECRET", ""),
               "passphrase": os.environ.get("BITGET_PASSPHRASE", "")},
}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    active = {v: c for v, c in VENUE_CFG.items() if c.get("key") and c.get("secret")}
    log.info("account-snapshot up interval=%ss venues=%s", INTERVAL, list(active))
    async with httpx.AsyncClient(timeout=15) as cli:
        while True:
            try:
                snaps = await asyncio.gather(*(fetch_account(cli, v, c) for v, c in active.items()))
                hb = {"service": "account-snapshot", "ts": int(time.time()), "pid": os.getpid()}
                for s in snaps:
                    await r.set(f"dcm:account:{s.venue}", json.dumps({
                        "ts": int(time.time()), "ok": s.ok, "equity_usdt": round(s.equity_usdt, 2),
                        "positions": {k: round(v, 10) for k, v in s.positions.items()},
                        "pos_detail": s.pos_detail,
                        "err": s.err}, ensure_ascii=False), ex=180)
                    hb[s.venue] = f"{round(s.equity_usdt, 2)}U/{len(s.positions)}pos" if s.ok else f"ERR:{s.err[:60]}"
                await r.set("dcm:hb:account-snapshot", json.dumps(hb, ensure_ascii=False), ex=max(INTERVAL * 3, 300))
                log.info("ACCT_OK %s", {s.venue: (s.ok, round(s.equity_usdt, 2), len(s.positions)) for s in snaps})
            except Exception:
                log.exception("snapshot round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
