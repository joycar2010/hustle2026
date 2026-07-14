"""武装执行器单币 canary(V4.0 §17 61-90天,门控碰真金)—— B 机运行。
首发最简形态:单条永续腿 market 开 + 立即 market 平回 flat(hedge/回滚逻辑已由混沌测试
充分验证,首发只需证明 RealVenue 真实下单/查单/平仓对真交易所通)。
安全:
- --dry(默认):不武装,place() 被门控拒绝,证明流程走到下单边界正确阻断,零下单;
- --arm:真下单,但 try/finally **保证任何情况都平回 flat**;开仓后 get_position 实证,平仓后实证 flat;
- 极小 notional;engine-basis 锁 XVG、dualperp shadow → 对其他币零双交易。
用法: python canary.py DOGEUSDT 6 [--arm]
"""
import asyncio
import os
import sys
import time

import httpx

sys.path.insert(0, "/home/ec2-user/dexcexmix")
from real_venue import BinanceRealVenue, BINANCE_FAPI  # noqa: E402


async def _mark_and_step(symbol):
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


def _round_step(qty, step):
    import math
    return math.floor(qty / step) * step


async def main():
    if len(sys.argv) < 3:
        print("用法: canary.py <SYMBOL> <NOTIONAL_USDT> [--arm]"); return
    symbol = sys.argv[1]
    notional = float(sys.argv[2])
    arm = "--arm" in sys.argv

    px, step = await _mark_and_step(symbol)
    qty = _round_step(notional / px, step)
    if qty <= 0:
        print(f"qty 取整后为 0(notional 太小 / step={step})"); return
    print(f"canary {symbol}: mark={px} step={step} qty={qty} (~{qty*px:.2f}U) arm={arm}")

    if arm:
        os.environ["DCM_EXEC_ARMED"] = "true"
        os.environ["DCM_EXEC_ARM_SYMBOLS"] = symbol
    v = BinanceRealVenue()
    cid_open = f"canary:{symbol}:{int(time.time())}:open"

    # ---- dry:证明门控 ----
    if not arm:
        try:
            await v.place(cid_open, {"symbol": symbol, "side": "SELL", "market": "perp", "qty": qty})
            print("!! dry 模式竟下单成功(门控失效!)")
        except PermissionError as e:
            print("✅ dry:place 被门控拒绝 —", str(e)[:70])
        # 读路径照常验证
        p = await v.get_position(symbol)
        print("get_position:", {k: p.get(k) for k in ("amt", "flat")})
        return

    # ---- armed:开 → 实证 → 立即平 ----
    opened = False
    try:
        r = await v.place(cid_open, {"symbol": symbol, "side": "SELL", "market": "perp", "qty": qty})
        print("开仓(SELL):", r.get("status"), "filled=", r.get("filled"), "oid=", r.get("venue_order_id"))
        await asyncio.sleep(1.5)
        p = await v.get_position(symbol)
        print("开仓后实盘:", {k: p.get(k) for k in ("amt", "entry", "flat")})
        opened = abs(p.get("amt") or 0) > 1e-12
    except Exception as e:  # noqa: BLE001
        print("开仓异常:", repr(e)[:150])
    finally:
        # 无论如何平回 flat(reduce-only 反向)
        p = await v.get_position(symbol)
        amt = p.get("amt") or 0
        if abs(amt) > 1e-12:
            close_qty = _round_step(abs(amt), step)
            side = "BUY" if amt < 0 else "SELL"
            cid_close = f"canary:{symbol}:{int(time.time())}:close"
            rc = await v.place(cid_close, {"symbol": symbol, "side": side, "market": "perp",
                                           "qty": close_qty, "reduce_only": True})
            print(f"平仓({side} reduceOnly):", rc.get("status"), "filled=", rc.get("filled"))
            await asyncio.sleep(1.5)
            pf = await v.get_position(symbol)
            print("平仓后实盘:", {k: pf.get(k) for k in ("amt", "flat")},
                  "✅ 已平回 flat" if pf.get("flat") else "⚠️ 仍有残仓,人工检查!")
        elif opened:
            print("⚠️ 开过仓但现读为平,复核")
        else:
            print("未开仓,无需平")


if __name__ == "__main__":
    asyncio.run(main())
