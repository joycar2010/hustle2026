"""C2 跨所业务 canary(V4.0):exec_core + MultiVenue 驱动跨所双永续腿(engine-dualperp 的活)。
默认 --dry:逐所证明门控拒单(PermissionError,零下单)+ query 幂等(NOTFOUND)。
--arm 真金小额往返:venueA 多腿 + venueB 空腿 → 开(open_pair)→ 实盘核对 → 平(close_pair)→ flat。
try/finally 兜底:任何异常都按实盘余量 reduce-only 平回。
--arm --hold 只开不平:开仓后打印 manager pairs 配置片段退出(生命周期交给 exec-manager 接管演练)。
--arm --close 只平不开:按两所实盘余量 reduce-only 平回(manager 失效时的手动兜底)。
用法: python canary_c2.py DOGEUSDT 6 binance bybit [--arm [--hold|--close]]
      (多腿所=第3参,空腿所=第4参;缺省 binance bybit)
"""
import asyncio
import math
import sys
import time

import httpx

sys.path.insert(0, "/home/ec2-user/dexcexmix")
import exec_core as E  # noqa: E402
from real_venue import BINANCE_FAPI, MultiVenue, venue_armed, venue_sym  # noqa: E402


async def _mark_price(symbol):
    async with httpx.AsyncClient(timeout=15) as cli:
        return float((await cli.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}")).json()["markPrice"])


async def _qty_step(venue, symbol):
    """各所公开合约规格 → base 数量步长(gate/okx=乘数张,binance/bybit/bitget=LOT/qtyStep)。"""
    async with httpx.AsyncClient(timeout=15) as cli:
        if venue == "binance":
            d = (await cli.get(f"{BINANCE_FAPI}/fapi/v1/exchangeInfo")).json()
            for s in d.get("symbols", []):
                if s["symbol"] == symbol:
                    for f in s.get("filters", []):
                        if f["filterType"] == "LOT_SIZE":
                            return float(f["stepSize"])
        if venue == "bybit":
            d = (await cli.get(f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={symbol}")).json()
            lst = (d.get("result", {}) or {}).get("list") or []
            if lst:
                return float(lst[0].get("lotSizeFilter", {}).get("qtyStep") or 1)
        if venue == "gate":
            d = (await cli.get("https://api.gateio.ws/api/v4/futures/usdt/contracts/" + symbol)).json()
            return float(d.get("quanto_multiplier") or 1) or 1
        if venue == "okx":
            d = (await cli.get(f"https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId={symbol}")).json()
            c = (d.get("data") or [{}])[0]
            return (float(c.get("ctVal") or 1) or 1) * (float(c.get("lotSz") or 1) or 1)
        if venue == "bitget":
            d = (await cli.get(f"https://api.bitget.com/api/v2/mix/market/contracts?productType=USDT-FUTURES&symbol={symbol}")).json()
            c = (d.get("data") or [{}])[0]
            return float(c.get("sizeMultiplier") or c.get("minTradeNum") or 1) or 1
        if venue == "hyperliquid":
            d = (await cli.post("https://api.hyperliquid.xyz/info", json={"type": "meta"})).json()
            for u in d.get("universe", []):
                if u.get("name") == symbol:
                    return 10 ** -int(u.get("szDecimals") or 0)
    return 1.0


def _fl(q, step):
    return math.floor(q / step + 1e-9) * step


async def main():
    symbol = sys.argv[1]
    notional = float(sys.argv[2])
    v_long = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "binance"
    v_short = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else "bybit"
    arm = "--arm" in sys.argv
    hold = "--hold" in sys.argv
    close_only = "--close" in sys.argv
    sym_l, sym_s = venue_sym(v_long, symbol), venue_sym(v_short, symbol)

    px = await _mark_price(symbol)
    step_l, step_s = await _qty_step(v_long, sym_l), await _qty_step(v_short, sym_s)
    step = max(step_l, step_s)
    Q = _fl(notional / px, step)
    print(f"canary_c2 {symbol}: {v_long}(多,{sym_l}) x {v_short}(空,{sym_s}) "
          f"Q={Q}(~{Q * px:.2f}U/腿) step={step}({v_long}={step_l}/{v_short}={step_s}) arm={arm}")
    if Q <= 0:
        print("Q=0,加大 notional")
        return

    legs = [{"venue": v_long, "symbol": sym_l, "side": "BUY", "market": "perp", "qty": Q},
            {"venue": v_short, "symbol": sym_s, "side": "SELL", "market": "perp", "qty": Q}]

    if not arm:
        # 门控证明:两所 place 必须被 PermissionError 拒绝(零下单);query 幂等 NOTFOUND
        for lg in legs:
            v = venue_armed(lg["venue"], False, [])
            try:
                await v.place(f"c2dry:{symbol}:{lg['venue']}", lg)
                print(f"  ❌ {lg['venue']} place 未被门控拒绝!!!")
            except PermissionError as e:
                print(f"  ✅ {lg['venue']} 门控拒单: {e}")
            q = await v.query(f"c2dry:{symbol}:nonexist:{int(time.time())}", lg)
            print(f"  ✅ {lg['venue']} query 不存在单 → {q['status']}(幂等{'OK' if q['status'] == 'NOTFOUND' else '⚠️非NOTFOUND,查'})")
        print("dry 完成,零下单。")
        return

    # --arm 真金:构造武装适配器(仅本 symbol 白名单);G1 注入 policy_r=place 过风险策略最后一跳
    import os

    import asyncpg
    import redis.asyncio as _A
    from policy_client import can_open
    from store import PgSagaStore
    pr = _A.from_url(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"), decode_responses=True)
    for vv in (v_long, v_short):   # 开仓前策略预检(place 仍会强制,此处提前告知)
        ok, why = await can_open(pr, vv)
        if not ok and not close_only:
            print(f"  ⚠️ {vv} 风险策略不允许新增: {why}(如需强开,先经 /risk/overrides 置 NORMAL)")
    adapters = {v_long: venue_armed(v_long, True, [sym_l], policy_r=pr),
                v_short: venue_armed(v_short, True, [sym_s], policy_r=pr)}
    mv = MultiVenue(adapters)
    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    store = PgSagaStore(pool, mode="armed")
    ex = E.SagaExecutor(mv, store)
    sid = f"c2-{symbol}-{int(time.time())}"

    async def _pos(v, s):
        p = await adapters[v].get_position(s)
        return p.get("amt") if p.get("ok") else f"ERR:{p.get('err')}"

    if close_only:
        # 手动兜底:按两所实盘余量 reduce-only 平回(不走 open)
        for v, s, stp in ((v_long, sym_l, step_l), (v_short, sym_s, step_s)):
            amt = await _pos(v, s)
            if isinstance(amt, (int, float)) and abs(amt) > 1e-12:
                qq = _fl(abs(amt), stp)
                res = await adapters[v].place(f"c2man:{symbol}:{v}:{int(time.time())}",
                                              {"venue": v, "symbol": s, "market": "perp", "qty": qq,
                                               "side": "BUY" if amt < 0 else "SELL", "reduce_only": True})
                print(f"  手动平 {v}: {res.get('status')} {res.get('err') or ''}")
        await asyncio.sleep(2)
        print(f"  终查: {v_long}={await _pos(v_long, sym_l)} {v_short}={await _pos(v_short, sym_s)}")
        await pool.close()
        return

    if hold:
        # 只开不平:开仓后打印 manager 接管配置,不进兜底(留仓是目的)
        final = await ex.open_pair(sid, legs)
        await asyncio.sleep(2)
        al, as_ = await _pos(v_long, sym_l), await _pos(v_short, sym_s)
        print(f"open_pair 终态: {final}\n  开仓后实盘: {v_long}={al} {v_short}={as_}")
        if final != "OPEN":
            print("  ⚠️未达 OPEN,无仓可交接(exec_core 已回滚)。")
        else:
            cfg = {"mode": "shadow", "target": "hold", "signal_source": "config", "symbol": symbol,
                   "legs": [{"venue": v_long, "side": "BUY"}, {"venue": v_short, "side": "SELL"}]}
            print("  → 交接 manager pairs 配置片段(并入 dcm:exec:manager:config 的 pairs 段):")
            print(f'    "{symbol}": ' + __import__("json").dumps(cfg, ensure_ascii=False))
        await pool.close()
        return

    try:
        final = await ex.open_pair(sid, legs)
        print(f"open_pair 终态: {final}")
        await asyncio.sleep(2)
        al, as_ = await _pos(v_long, sym_l), await _pos(v_short, sym_s)
        print(f"  开仓后实盘: {v_long}={al} {v_short}={as_}")
        if final == "OPEN":
            fin = await ex.close_pair(sid, legs)
            print(f"close_pair 终态: {fin}")
    finally:
        # 兜底:按实盘余量 reduce-only 平回(任何路径都要 flat)
        await asyncio.sleep(2)
        for v, s, stp in ((v_long, sym_l, step_l), (v_short, sym_s, step_s)):
            amt = await _pos(v, s)
            if isinstance(amt, (int, float)) and abs(amt) > 1e-12:
                qq = _fl(abs(amt), stp)
                if qq > 0:
                    res = await adapters[v].place(f"c2fix:{symbol}:{v}:{int(time.time())}",
                                                  {"venue": v, "symbol": s, "market": "perp", "qty": qq,
                                                   "side": "BUY" if amt < 0 else "SELL", "reduce_only": True})
                    print(f"  兜底平 {v}: {res.get('status')} {res.get('err') or ''}")
        await asyncio.sleep(2)
        fl_, fs_ = await _pos(v_long, sym_l), await _pos(v_short, sym_s)
        flat = all(isinstance(x, (int, float)) and abs(x) < 1e-9 for x in (fl_, fs_))
        print(f"  终查: {v_long}={fl_} {v_short}={fs_}", "✅ C2跨所两腿平回flat" if flat else "⚠️有残留,人工核查!")
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
