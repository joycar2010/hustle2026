"""exec_core 真实驱动单币往返(V4.0 §6 门控)—— B 机。
不再 canary 直调 place,而是让 exec_core.open_pair/close_pair **完整状态机**驱动真实下单,
PgSagaStore 持久化(崩溃可恢复)。单腿小额,验证 RESERVED→OPENING→confirm(place→ACK→query)→OPEN→
CLOSING→rollback→CLOSED 全链在真交易所走通。--arm 才真下单;try/finally 保证平回 flat。
用法: python canary_exec.py DOGEUSDT 6 [--arm]
"""
import asyncio
import math
import os
import sys
import time

import asyncpg
import httpx

sys.path.insert(0, "/home/ec2-user/dexcexmix")
from real_venue import BinanceRealVenue, BINANCE_FAPI  # noqa: E402
from store import PgSagaStore  # noqa: E402
import exec_core as E  # noqa: E402


async def _mark_step(symbol):
    async with httpx.AsyncClient(timeout=15) as cli:
        px = float((await cli.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}")).json()["markPrice"])
        info = (await cli.get(f"{BINANCE_FAPI}/fapi/v1/exchangeInfo")).json()
        step = 1.0
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step = float(f["stepSize"])
        return px, step


async def main():
    symbol = sys.argv[1]; notional = float(sys.argv[2]); arm = "--arm" in sys.argv
    px, step = await _mark_step(symbol)
    qty = math.floor((notional / px) / step) * step
    print(f"canary_exec {symbol}: qty={qty} (~{qty*px:.2f}U) arm={arm}")
    if arm:
        os.environ["DCM_EXEC_ARMED"] = "true"; os.environ["DCM_EXEC_ARM_SYMBOLS"] = symbol

    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    venue = BinanceRealVenue()
    store = PgSagaStore(pool, mode="armed" if arm else "shadow")
    ex = E.SagaExecutor(venue, store)
    sid = f"cxec-{symbol}-{int(time.time())}"
    legs = [{"symbol": symbol, "side": "SELL", "market": "perp", "qty": qty}]

    try:
        final = await ex.open_pair(sid, legs)
        print(f"open_pair 终态: {final}")
        row = await pool.fetchrow("SELECT state, legs FROM exec_saga WHERE saga_id=$1", sid)
        print(f"  PG持久化: state={row['state']} legs={row['legs']}")
        if arm:
            await asyncio.sleep(1.5)
            p = await venue.get_position(symbol)
            print(f"  开仓后实盘: amt={p.get('amt')} flat={p.get('flat')}")
    finally:
        if arm:
            fc = await ex.close_pair(sid, legs)
            print(f"close_pair 终态: {fc}")
            await asyncio.sleep(1.5)
            pf = await venue.get_position(symbol)
            print(f"  平仓后实盘: amt={pf.get('amt')} flat={pf.get('flat')}",
                  "✅平回flat" if pf.get("flat") else "⚠️残仓人工查!")
            row = await pool.fetchrow("SELECT state, legs FROM exec_saga WHERE saga_id=$1", sid)
            print(f"  PG终态: state={row['state']}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
