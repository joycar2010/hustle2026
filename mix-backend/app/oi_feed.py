"""多所持仓量(OI)采集——公开端点无需 key,60s 进程内缓存。
口径:返回 {oi_base(基础币数量), oi_usdt(名义USDT)};取不到=None 诚实降级,绝不 0 冒充。
符号:入参为 dcm 符号(BTCUSDT),逐所转各自 instrument id。1000X 类乘数币直接透传(与 feed 同名)。
"""
import json
import time

import httpx

_cache: dict = {}   # (venue, symbol) -> (ts, dict)
_TTL = 60


def _base_of(sym: str) -> str:
    return sym[:-4] if sym.upper().endswith("USDT") else sym


async def _fetch(cli: httpx.AsyncClient, venue: str, sym: str, mid) -> dict:
    base = _base_of(sym)
    oi_base = oi_usdt = None
    if venue == "binance":
        r = await cli.get("https://fapi.binance.com/fapi/v1/openInterest", params={"symbol": sym})
        if r.status_code == 200:
            oi_base = float(r.json().get("openInterest") or 0) or None
        # binance perp 24h成交量:同域REST(fstream @ticker在l1lite不达,binance是唯一REST例外)
        try:
            t = await cli.get("https://fapi.binance.com/fapi/v1/ticker/24hr", params={"symbol": sym})
            if t.status_code == 200:
                qv = t.json().get("quoteVolume")
                if qv:
                    from . import datasources as _ds
                    _r = _ds.rds()
                    if _r:
                        import json as _j
                        await _r.setex(f"dcm:l1lite:vol:binance:perp:{base}", 300,
                                       _j.dumps({"vol_usdt": float(qv), "ts": int(__import__('time').time())}))
        except Exception:  # noqa: BLE001
            pass
    elif venue == "bybit":
        r = await cli.get("https://api.bybit.com/v5/market/tickers",
                          params={"category": "linear", "symbol": sym})
        lst = (r.json().get("result") or {}).get("list") or []
        if lst:
            oi_base = float(lst[0].get("openInterest") or 0) or None
            v = lst[0].get("openInterestValue")
            oi_usdt = float(v) if v else None
    elif venue == "okx":
        r = await cli.get("https://www.okx.com/api/v5/public/open-interest",
                          params={"instType": "SWAP", "instId": f"{base}-USDT-SWAP"})
        d = (r.json().get("data") or [])
        if d:
            oi_base = float(d[0].get("oiCcy") or 0) or None
            v = d[0].get("oiUsd")
            oi_usdt = float(v) if v else None
    elif venue == "gate":
        r = await cli.get("https://api.gateio.ws/api/v4/futures/usdt/tickers",
                          params={"contract": f"{base}_USDT"})
        d = r.json()
        row = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else None)
        if row and row.get("total_size") is not None:
            # total_size=张;×quanto_multiplier=base(乘数从合约端点取,失败回落1)
            mult = 1.0
            try:
                c = await cli.get(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{base}_USDT")
                mult = float(c.json().get("quanto_multiplier") or 1) or 1.0
            except Exception:  # noqa: BLE001
                pass
            oi_base = float(row["total_size"]) * mult or None
    elif venue == "bitget":
        r = await cli.get("https://api.bitget.com/api/v2/mix/market/open-interest",
                          params={"symbol": sym, "productType": "usdt-futures"})
        lst = ((r.json().get("data") or {}).get("openInterestList") or [])
        if lst:
            oi_base = float(lst[0].get("size") or 0) or None
    elif venue == "hyperliquid":
        r = await cli.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"})
        d = r.json()
        uni = (d[0].get("universe") or []) if isinstance(d, list) and d else []
        for i, a in enumerate(uni):
            if a.get("name") == base:
                ctx = d[1][i] if len(d) > 1 and i < len(d[1]) else {}
                oi_base = float(ctx.get("openInterest") or 0) or None
                break
    if oi_usdt is None and oi_base is not None and mid:
        oi_usdt = oi_base * float(mid)
    return {"oi_base": oi_base, "oi_usdt": round(oi_usdt, 0) if oi_usdt else None}


async def get_oi(venue: str, sym: str, mid=None) -> dict:
    """WS 优先(dcm:l1lite:oi:{venue}:{CANON},l1lite 推送);仅 binance(WS无OI频道)REST兜底。
    用户纪律 2026-07-19:行情采集全 WS,REST 仅保留无 WS 等价物的 binance OI 单点(60s缓存)。"""
    canon = _base_of(sym)
    try:
        from . import datasources as _ds
        r = _ds.rds()
        if r:
            raw = await r.get(f"dcm:l1lite:oi:{venue}:{canon}")
            if raw:
                d = json.loads(raw)
                ob = d.get("oi_base")
                if ob is not None:
                    ou = round(ob * float(mid), 0) if mid else None
                    return {"oi_base": ob, "oi_usdt": ou}
    except Exception:  # noqa: BLE001
        pass
    if venue != "binance":
        return {"oi_base": None, "oi_usdt": None}   # 其余所只认WS,不回落REST
    key = (venue, sym)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    out = {"oi_base": None, "oi_usdt": None}
    try:
        async with httpx.AsyncClient(timeout=8) as cli:
            out = await _fetch(cli, venue, sym, mid)
    except Exception:  # noqa: BLE001
        pass
    _cache[key] = (now, out)
    return out
