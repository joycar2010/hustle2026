"""I1 合约矩阵多所采集器(V4.0 §7.1)——公开 instruments 端点,无需 key。
各所字段差异大,逐所归一到统一 (venue, instrument_id, canonical_underlying, market_type,
linear_or_inverse, contract_multiplier, quote, settle, collateral, contract_type, expiry,
min_qty, tick_size, status)。乘数口径:OKX=ctVal / Bitget=sizeMultiplier / Gate=quanto_multiplier /
binance COIN-M=contractSize;不归一直接张数配平会错(§7.1 铁律)。
"""
import httpx

_PERP_SENTINEL_MS = 4133404800000


def _expiry(ms):
    try:
        v = int(ms)
    except (TypeError, ValueError):
        return None
    if v <= 0 or v >= _PERP_SENTINEL_MS:
        return None
    import datetime as dt
    return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc)


async def _get(cli, url, **kw):
    r = await cli.get(url, timeout=20, **kw)
    r.raise_for_status()
    return r.json()


async def collect_bybit(cli) -> list:
    rows = []
    for cat, lin in (("linear", "linear"), ("inverse", "inverse")):
        d = await _get(cli, f"https://api.bybit.com/v5/market/instruments-info?category={cat}")
        for s in (d.get("result", {}).get("list") or []):
            if s.get("status") != "Trading":
                continue
            ct = s.get("contractType", "")
            mt = "future" if "Futures" in ct else "perp"
            dt_ = s.get("deliveryTime", "0")
            tick = (s.get("priceFilter") or {}).get("tickSize")
            minq = (s.get("lotSizeFilter") or {}).get("minOrderQty")
            rows.append(("bybit", s["symbol"], s.get("baseCoin", ""), mt, lin, 1,
                         s.get("quoteCoin", ""), s.get("settleCoin", ""), s.get("settleCoin", ""),
                         ct, _expiry(dt_), float(minq) if minq else None,
                         float(tick) if tick else None, "TRADING"))
    return rows


async def collect_okx(cli) -> list:
    rows = []
    for it, mt in (("SWAP", "perp"), ("FUTURES", "future")):
        d = await _get(cli, f"https://www.okx.com/api/v5/public/instruments?instType={it}")
        for s in (d.get("data") or []):
            if s.get("state") != "live":
                continue
            base = s.get("ctValCcy") if s.get("ctType") == "inverse" else s.get("settleCcy")
            # canonical:优先 instFamily 的 base(BTC-USD-SWAP → BTC)
            canon = (s.get("instFamily") or s.get("instId", "")).split("-")[0]
            rows.append(("okx", s["instId"], canon, mt, s.get("ctType", "linear"),
                         float(s.get("ctVal") or 1), s.get("ctValCcy", ""), s.get("settleCcy", ""),
                         s.get("settleCcy", ""), (s.get("alias") or "").upper() or ("PERPETUAL" if it == "SWAP" else ""),
                         _expiry(s.get("expTime")), float(s.get("minSz")) if s.get("minSz") else None,
                         float(s.get("tickSz")) if s.get("tickSz") else None, "TRADING"))
    return rows


async def collect_gate(cli) -> list:
    rows = []
    # USDT 本位永续(linear);Gate 交割在 /delivery,此处先永续
    d = await _get(cli, "https://api.gateio.ws/api/v4/futures/usdt/contracts")
    for s in d:
        if s.get("in_delisting"):
            continue
        name = s.get("name", "")  # 0G_USDT
        base = name.split("_")[0]
        mult = s.get("quanto_multiplier") or "1"
        rows.append(("gate", name, base, "perp", "linear", float(mult) if mult and float(mult) > 0 else 1,
                     "USDT", "USDT", "USDT", "PERPETUAL", None,
                     float(s.get("order_size_min")) if s.get("order_size_min") else None,
                     float(s.get("order_price_round")) if s.get("order_price_round") else None, "TRADING"))
    return rows


async def collect_bitget(cli) -> list:
    rows = []
    for pt, lin, settle in (("USDT-FUTURES", "linear", "USDT"), ("COIN-FUTURES", "inverse", "")):
        d = await _get(cli, f"https://api.bitget.com/api/v2/mix/market/contracts?productType={pt}")
        for s in (d.get("data") or []):
            mt = "future" if s.get("symbolType") == "delivery" else "perp"
            dt_ = s.get("deliveryTime") or ""
            rows.append(("bitget", s["symbol"], s.get("baseCoin", ""), mt, lin,
                         float(s.get("sizeMultiplier") or 1), s.get("quoteCoin", ""),
                         settle or s.get("baseCoin", ""), settle or s.get("baseCoin", ""),
                         (s.get("symbolType") or "").upper(), _expiry(dt_) if dt_ else None,
                         float(s.get("minTradeNum")) if s.get("minTradeNum") else None, None, "TRADING"))
    return rows


async def collect_hyperliquid(cli) -> list:
    rows = []
    d = await cli.post("https://api.hyperliquid.xyz/info", json={"type": "meta"}, timeout=20)
    d.raise_for_status()
    for a in (d.json().get("universe") or []):
        if a.get("isDelisted"):
            continue
        name = a.get("name", "")
        rows.append(("hyperliquid", name, name, "perp", "linear", 1, "USDC", "USDC", "USDC",
                     "PERPETUAL", None, None, None, "TRADING"))
    return rows


_COLLECTORS = {"bybit": collect_bybit, "okx": collect_okx, "gate": collect_gate,
               "bitget": collect_bitget, "hyperliquid": collect_hyperliquid}


async def collect(venue: str) -> list:
    fn = _COLLECTORS.get(venue)
    if not fn:
        return []
    async with httpx.AsyncClient(timeout=25) as cli:
        return await fn(cli)
