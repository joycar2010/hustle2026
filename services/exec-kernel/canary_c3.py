"""C3 借币利差 canary(V4.0 §6.1 BORROW_SPOT_SHORT_DERIVATIVE_LONG)——
exec_core + MultiVenue 驱动:借币现货空腿(binance-margin,MARGIN_BUY/AUTO_REPAY 原子)+ 永续多腿对冲(binance-perp)。
经济结构(§7.3 带符号,禁 abs):收益/天 = (-funding_daily) - borrow_daily(多头永续只在负费率收钱)。

默认 --dry:两腿证明门控拒单(PermissionError,零下单)+ query 幂等(NOTFOUND)。
--arm  真金小额往返:借币卖出开空 + 永续买多 → 开(open_pair)→ 实盘核对 → 平(close_pair 买回还债+平永续)→ flat。
       ⚠️碰真金保证金债务=最高风险,须 operator 显式放行盯盘。
       close 侧永续腿 reduce-only、margin 腿 AUTO_REPAY 按活债务买回(§11 债务现查)。
用法: python canary_c3.py XVGUSDT 11 [--arm]
"""
import asyncio
import math
import os
import sys
import time

import httpx

sys.path.insert(0, "/home/ec2-user/dexcexmix")
import exec_core as E  # noqa: E402
from real_venue import BINANCE_FAPI, BinanceMarginRealVenue, MultiVenue, venue_armed  # noqa: E402


async def _perp_mark_step(symbol):
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
    return math.floor(q / step + 1e-9) * step


async def main():
    symbol = sys.argv[1]
    notional = float(sys.argv[2])
    arm = "--arm" in sys.argv
    base = symbol[:-4]
    px, pstep, sstep = await _perp_mark_step(symbol)
    step = max(pstep, sstep)
    Q = _fl(notional / px, step)
    print(f"canary_c3 {symbol}: 借币空(binance-margin) x 永续多(binance) "
          f"Q={Q}(~{Q * px:.2f}U/腿) step={step}(perp={pstep}/spot={sstep}) arm={arm}")
    if Q <= 0:
        print("Q=0,加大 notional")
        return

    # C3:leg0=借币现货空(风险腿先进),leg1=永续多(对冲)
    legs = [{"venue": "binance-margin", "symbol": symbol, "side": "SELL", "market": "spot", "qty": Q},
            {"venue": "binance", "symbol": symbol, "side": "BUY", "market": "perp", "qty": Q}]

    if not arm:
        for lg in legs:
            v = venue_armed(lg["venue"], False, [])
            try:
                await v.place(f"c3dry:{symbol}:{lg['venue']}", lg)
                print(f"  ❌ {lg['venue']} place 未被门控拒绝!!!")
            except PermissionError as e:
                print(f"  ✅ {lg['venue']} 门控拒单: {e}")
            q = await v.query(f"c3dry:{symbol}:nonexist:{int(time.time())}", lg)
            print(f"  ✅ {lg['venue']} query 不存在单 → {q['status']}"
                  f"({'OK' if q['status'] == 'NOTFOUND' else '⚠️非NOTFOUND,查'})")
        print("dry 完成,零下单。")
        return

    # --arm 真金
    import asyncpg
    from store import PgSagaStore
    adapters = {"binance-margin": venue_armed("binance-margin", True, [symbol]),
                "binance": venue_armed("binance", True, [symbol])}
    mv = MultiVenue(adapters)
    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    store = PgSagaStore(pool, mode="armed")
    ex = E.SagaExecutor(mv, store)
    sid = f"c3-{symbol}-{int(time.time())}"
    marg = adapters["binance-margin"]
    perp = adapters["binance"]

    try:
        final = await ex.open_pair(sid, legs)
        print(f"open_pair 终态: {final}")
        await asyncio.sleep(2)
        debt = await marg.debt(base)
        pp = await perp.get_position(symbol)
        print(f"  开仓后: 借币债务({base})={debt} 永续amt={pp.get('amt')} (delta≈{pp.get('amt', 0) - debt:.4f})")
        if final == "OPEN":
            # 平:永续 reduce-only + margin 按活债务 AUTO_REPAY 买回
            fin = await ex.close_pair(sid, legs)
            print(f"close_pair 终态: {fin}")
    finally:
        # 兜底:永续按实盘 reduce-only 平;margin 按活债务买回还清(§11 债务现查)
        await asyncio.sleep(2)
        pp = await perp.get_position(symbol)
        if abs(pp.get("amt") or 0) > 1e-12:
            await perp.place(f"c3fix:{symbol}:perp:{int(time.time())}",
                             {"symbol": symbol, "side": "BUY" if pp["amt"] < 0 else "SELL",
                              "market": "perp", "qty": _fl(abs(pp["amt"]), pstep), "reduce_only": True})
        debt = await marg.debt(base)
        if debt > 0:
            qy = _fl(debt * 1.002, sstep)   # ×1.002 覆盖利息,AUTO_REPAY 多买只还到零
            if qy > 0:
                await marg.place(f"c3fix:{symbol}:margin:{int(time.time())}",
                                 {"symbol": symbol, "side": "BUY", "market": "spot",
                                  "qty": qy, "reduce_only": True})
        await asyncio.sleep(2)
        debt_f = await marg.debt(base)
        pp_f = await perp.get_position(symbol)
        flat = debt_f < 1e-6 and abs(pp_f.get("amt") or 0) < 1e-9
        print(f"  平仓后: 债务({base})={debt_f} 永续amt={pp_f.get('amt')}",
              "✅ C3两腿平回flat" if flat else f"⚠️残留(债务{debt_f}),人工核查!")
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
