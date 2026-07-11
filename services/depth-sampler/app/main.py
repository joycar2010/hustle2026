"""depth-sampler(A 机):活跃双合约路由两腿的盘口深度采样,算 ±band 内可成交名义金额。

armed 硬前置——xv 命门:高费差长尾币 ±25bps 深度仅 0.1~0.5 万 U,按榜面费差配仓=滑穿。
本服务给每个 (venue, perp, symbol) 算 bid/ask 两侧 ±BAND 内累计名义 USDT,顾问按此钳单币上限。

只采活跃路由涉及的 (venue,symbol)(≤几十个),公开 REST 无需 key。
Gate 深度单位=张,需 ×quanto_multiplier 换 base(xv 已趟平的口径,contracts 端点取乘数缓存)。
键:dcm:depth:{venue}:perp:{symbol} = {bid_usdt, ask_usdt, mid, ts}(EX 300)。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("depth-sampler")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_DEPTH_INTERVAL_SEC", "90"))
BAND_BPS = float(os.environ.get("DCM_DEPTH_BAND_BPS", "25"))
LIMIT = 50
gate_qm: dict[str, float] = {}   # 统一符号 -> Gate 每张币数


def _native(venue: str, sym: str) -> str:
    """统一符号(BTCUSDT)→ venue 原生盘口查询符号。"""
    base = sym[:-4]
    if venue == "okx":
        return f"{base}-USDT-SWAP"
    if venue == "gate":
        return f"{base}_USDT"
    if venue == "hyperliquid":
        return base  # HL coin 无 USDT 后缀
    return sym  # binance/bybit/bitget


def _band_notional(bids, asks, band_bps, contract_mult=1.0):
    """bids/asks: [(price, qty)]。返回 (bid_side_usdt, ask_side_usdt, mid)。qty×mult=base。"""
    if not bids or not asks:
        return 0.0, 0.0, 0.0
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return 0.0, 0.0, 0.0
    lo, hi = mid * (1 - band_bps / 10000), mid * (1 + band_bps / 10000)
    bid_usdt = sum(p * q * contract_mult for p, q in bids if p >= lo)
    ask_usdt = sum(p * q * contract_mult for p, q in asks if p <= hi)
    return bid_usdt, ask_usdt, mid


async def _levels(cli, venue, sym):
    """返回 (bids, asks) 各为 [(price, qty)],失败 None。"""
    nat = _native(venue, sym)
    try:
        if venue == "binance":
            d = (await cli.get(f"https://fapi.binance.com/fapi/v1/depth?symbol={nat}&limit={LIMIT}")).json()
            return ([(float(p), float(q)) for p, q in d["bids"]],
                    [(float(p), float(q)) for p, q in d["asks"]])
        if venue == "bybit":
            d = (await cli.get(f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={nat}&limit={LIMIT}")).json()["result"]
            return ([(float(p), float(q)) for p, q in d["b"]],
                    [(float(p), float(q)) for p, q in d["a"]])
        if venue == "okx":
            d = (await cli.get(f"https://www.okx.com/api/v5/market/books?instId={nat}&sz={LIMIT}")).json()["data"][0]
            # okx 张数×ctVal,但 books 的 sz 已是合约张;近似用张=币(主流永续 ctVal≈基准),v1 容差可接受
            return ([(float(x[0]), float(x[1])) for x in d["bids"]],
                    [(float(x[0]), float(x[1])) for x in d["asks"]])
        if venue == "gate":
            d = (await cli.get(f"https://api.gateio.ws/api/v4/futures/usdt/order_book?contract={nat}&limit={LIMIT}")).json()
            return ([(float(x["p"]), float(x["s"])) for x in d["bids"]],
                    [(float(x["p"]), float(x["s"])) for x in d["asks"]])
        if venue == "hyperliquid":
            d = (await cli.post("https://api.hyperliquid.xyz/info",
                                json={"type": "l2Book", "coin": nat})).json()
            lv = d.get("levels") or [[], []]
            return ([(float(x["px"]), float(x["sz"])) for x in lv[0]],
                    [(float(x["px"]), float(x["sz"])) for x in lv[1]])
        if venue == "bitget":
            d = (await cli.get(f"https://api.bitget.com/api/v2/mix/market/orderbook?symbol={nat}&productType=USDT-FUTURES&limit={LIMIT}")).json()["data"]
            return ([(float(p), float(q)) for p, q in d["bids"]],
                    [(float(p), float(q)) for p, q in d["asks"]])
    except Exception as e:
        log.warning(f"depth {venue}:{sym} failed: {e!r}")
    return None


async def refresh_gate_qm(cli):
    try:
        d = (await cli.get("https://api.gateio.ws/api/v4/futures/usdt/contracts")).json()
        for c in d:
            name = c.get("name", "")
            if name.endswith("_USDT"):
                qm = float(c.get("quanto_multiplier") or 1) or 1.0
                gate_qm[name.replace("_USDT", "USDT")] = qm
        log.info(f"gate quanto multipliers: {len(gate_qm)}")
    except Exception as e:
        log.warning(f"gate contracts qm failed: {e!r}")


async def active_leg_set(r) -> set[tuple[str, str]]:
    """从路由哈希取活跃双合约两腿的 (venue, symbol) 去重集。"""
    legs: set[tuple[str, str]] = set()
    try:
        raw = await r.hgetall("dcm:route:assignments")
    except Exception as e:
        log.warning(f"route read failed: {e!r}")
        return legs
    for js in raw.values():
        try:
            rt = json.loads(js)
        except json.JSONDecodeError:
            continue
        if rt.get("engine") != "dualperp" or rt.get("state") != "active":
            continue
        legs.add((rt["venue_long"], rt["symbol"]))
        legs.add((rt["venue_short"], rt["symbol"]))
    # 破鸡蛋环:顾问把候选腿写 watchlist,采样器先采,顾问下一轮才有深度可钳
    try:
        wl = await r.get("dcm:depth:watchlist")
        if wl:
            for venue, sym in json.loads(wl):
                legs.add((venue, sym))
    except Exception as e:
        log.warning(f"watchlist read failed: {e!r}")
    return legs


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    log.info(f"depth-sampler up interval={INTERVAL}s band=±{BAND_BPS}bps")
    async with httpx.AsyncClient(timeout=12) as cli:
        await refresh_gate_qm(cli)
        gate_qm_at = time.monotonic()
        while True:
            try:
                if time.monotonic() - gate_qm_at > 3600:
                    await refresh_gate_qm(cli)
                    gate_qm_at = time.monotonic()
                legs = await active_leg_set(r)
                sampled = 0
                for venue, sym in legs:
                    lv = await _levels(cli, venue, sym)
                    if lv is None:
                        continue
                    mult = gate_qm.get(sym, 1.0) if venue == "gate" else 1.0
                    bid_usdt, ask_usdt, mid = _band_notional(lv[0], lv[1], BAND_BPS, mult)
                    await r.set(f"dcm:depth:{venue}:perp:{sym}", json.dumps(
                        {"bid_usdt": round(bid_usdt, 2), "ask_usdt": round(ask_usdt, 2),
                         "mid": mid, "band_bps": BAND_BPS, "ts": int(time.time())}), ex=300)
                    sampled += 1
                await r.set("dcm:hb:depth-sampler", json.dumps(
                    {"service": "depth-sampler", "ts": int(time.time()), "pid": os.getpid(),
                     "legs": len(legs), "sampled": sampled, "band_bps": BAND_BPS}),
                    ex=max(INTERVAL * 3, 400))
                log.info(f"DEPTH_OK legs={len(legs)} sampled={sampled}")
            except Exception:
                log.exception("depth round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
