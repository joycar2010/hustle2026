"""C1 业务接管验证(V4.0):exec_core 驱动完整两腿现货+永续 delta 中性对(engine-basis 的活)。
证明统一执行器能执行 C1 业务(2 腿 HEDGING/现货腿/永续腿协调),真金小额,--arm 才下单,
try/finally 保证平回 flat。这是替代 engine-basis 前的功能证明(实盘 XVG 切换是后续 config flip)。
用法: python canary_c1.py DOGEUSDT 6 --arm
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


async def _mark_steps(symbol):
    async with httpx.AsyncClient(timeout=15) as cli:
        px = float((await cli.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}")).json()["markPrice"])
        fi = (await cli.get(f"{BINANCE_FAPI}/fapi/v1/exchangeInfo")).json()
        pstep = 1.0
        for s in fi.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        pstep = float(f["stepSize"])
        si = (await cli.get("https://api.binance.com/api/v3/exchangeInfo?symbol=" + symbol)).json()
        sstep = 1.0
        for s in si.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        sstep = float(f["stepSize"])
        return px, pstep, sstep


def _fl(q, step):
    return math.floor(q / step) * step


async def main():
    symbol = sys.argv[1]; notional = float(sys.argv[2]); arm = "--arm" in sys.argv
    base_asset = symbol[:-4]
    px, pstep, sstep = await _mark_steps(symbol)
    step = max(pstep, sstep)   # 两腿同量,取较粗步长保证都合法
    Q = _fl(notional / px, step)
    print(f"canary_c1 {symbol}: Q={Q} (~{Q*px:.2f}U/腿) pstep={pstep} sstep={sstep} arm={arm}")
    if arm:
        os.environ["DCM_EXEC_ARMED"] = "true"; os.environ["DCM_EXEC_ARM_SYMBOLS"] = symbol

    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    venue = BinanceRealVenue()
    store = PgSagaStore(pool, mode="armed" if arm else "shadow")
    ex = E.SagaExecutor(venue, store)
    sid = f"c1-{symbol}-{int(time.time())}"
    # C1:leg0=永续空(风险腿先进),leg1=现货多(对冲)
    legs = [{"symbol": symbol, "side": "SELL", "market": "perp", "qty": Q},
            {"symbol": symbol, "side": "BUY", "market": "spot", "qty": Q}]

    try:
        final = await ex.open_pair(sid, legs)
        print(f"open_pair 终态: {final}")
        if arm:
            await asyncio.sleep(1.5)
            p = await venue.get_position(symbol)
            bal = await venue.get_spot_balance(base_asset)
            print(f"  开仓后: 永续amt={p.get('amt')} 现货{base_asset}={bal} (delta≈{(p.get('amt') or 0)+bal:.4f})")
    finally:
        if arm:
            # 平永续(reduceOnly BUY)+ 平现货(SELL 实际余额)
            p = await venue.get_position(symbol)
            if abs(p.get("amt") or 0) > 1e-12:
                await venue.place(f"{sid}:0:close", {"symbol": symbol, "side": "BUY", "market": "perp",
                                                     "qty": _fl(abs(p["amt"]), pstep), "reduce_only": True})
            bal = await venue.get_spot_balance(base_asset)
            if bal > sstep:
                await venue.place(f"{sid}:1:close", {"symbol": symbol, "side": "SELL", "market": "spot",
                                                     "qty": _fl(bal, sstep)})
            await asyncio.sleep(1.5)
            pf = await venue.get_position(symbol)
            balf = await venue.get_spot_balance(base_asset)
            flat = pf.get("flat") and balf < sstep
            print(f"  平仓后: 永续amt={pf.get('amt')} 现货{base_asset}={balf}",
                  "✅ C1两腿平回flat" if flat else f"⚠️残留(现货{balf}可能是手续费尘,查)")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
