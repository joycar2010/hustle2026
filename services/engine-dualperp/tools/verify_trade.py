"""交易写入路径安全验证:远离盘口的限价单 → 查单确认 NEW → 立即撤单。

绝不成交(BUY 挂在市价 50% 下方 / SELL 挂在 50% 上方),验证 place+fetch+cancel 三方法签名。
用法(B 机):set -a; . ~/dexcexmix/.env; set +a; python verify_trade.py <venue> <symbol>
只在显式给参数时运行——不进任何常驻循环,不被 systemd 拉起。
"""
import asyncio
import os
import sys
from decimal import Decimal

import httpx
import redis.asyncio as aioredis

from dcm_common.exchange_trade import TRADE_CLIENTS

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
CFG = {
    "binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
    "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
}


async def mid_price(symbol, venue):
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    import json
    raw = await r.hget(f"dcm:feed:{venue}:perp", symbol)
    await r.aclose()
    d = json.loads(raw)
    return (Decimal(str(d["bid"])) + Decimal(str(d["ask"]))) / 2


async def main():
    venue, symbol = sys.argv[1], sys.argv[2]
    cli_cls = TRADE_CLIENTS[venue]
    tc = cli_cls(CFG[venue])
    async with httpx.AsyncClient(timeout=15) as cli:
        await tc.load_filter(cli, symbol)
        mid = await mid_price(symbol, venue)
        # BUY 挂到市价一半 → 绝不成交;名义约 6 USDT(过 minNotional)
        price = mid / 2
        qty = (Decimal("6") / price)
        print(f"[{venue}:{symbol}] mid={mid} 挂单价={price}(市价50%,不成交) 目标名义~6U")

        ok, res = await tc.place_limit(cli, symbol, "Buy" if venue == "bybit" else "BUY", qty, price)
        print(f"  place -> ok={ok} {res if not ok else res['order_id']}")
        if not ok:
            print("  FAIL place"); return
        oid = res["order_id"]

        ok2, st = await tc.fetch_order(cli, symbol, oid)
        print(f"  fetch -> ok={ok2} status={st.get('status') if ok2 else st}")

        ok3, cn = await tc.cancel(cli, symbol, oid)
        print(f"  cancel-> ok={ok3} {cn if not ok3 else 'CANCELLED'}")

        ok4, st2 = await tc.fetch_order(cli, symbol, oid)
        print(f"  confirm-> status={st2.get('status') if ok4 else st2}")
        print(f"RESULT {venue}: place={ok} fetch={ok2} cancel={ok3} "
              f"{'ALL_OK' if (ok and ok2 and ok3) else 'FAILED'}")


if __name__ == "__main__":
    asyncio.run(main())
