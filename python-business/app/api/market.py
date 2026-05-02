import json
import logging
import time

import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.middleware.permissions import get_current_user_id
from app.services.aicoin_client import AiCoinClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

_aicoin: AiCoinClient | None = None


def _get_aicoin() -> AiCoinClient:
    global _aicoin
    if _aicoin is None:
        if not settings.aicoin_api_key:
            raise HTTPException(status_code=500, detail="AiCoin API key not configured")
        _aicoin = AiCoinClient(settings.aicoin_api_key, settings.aicoin_api_secret)
    return _aicoin


def _redis():
    return redis_lib.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)


def _safe_float(val, default=0.0) -> float:
    if not val or val == "-":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ─── K-Line ───

@router.get("/kline")
async def get_kline(symbol: str, period: str = "60", size: int = 200, request: Request = None):
    get_current_user_id(request)
    ac = _get_aicoin()
    try:
        data = await ac.get_kline(symbol, period, size)
        return {"data": data}
    except Exception as e:
        logger.warning(f"AiCoin kline error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


# ─── Coin Search ───

@router.get("/coin-search")
async def search_coin(q: str, request: Request = None):
    get_current_user_id(request)
    ac = _get_aicoin()
    try:
        data = await ac.search_coin(q)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"AiCoin search error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


# ─── Rankings (shares cache with admin endpoint) ───

def _compute_5min_changes(r, price_map: dict[str, float]) -> dict[str, float]:
    import math
    now_bucket = int(time.time()) // 300
    prev_bucket = now_bucket - 1
    prev_key = f"aicoin:prices:{prev_bucket}"
    curr_key = f"aicoin:prices:{now_bucket}"

    r.hset(curr_key, mapping={k: str(v) for k, v in price_map.items()})
    r.expire(curr_key, 600)

    prev_prices = r.hgetall(prev_key)
    changes = {}
    for coin_key, cur_price in price_map.items():
        prev_str = prev_prices.get(coin_key)
        if prev_str and cur_price > 0:
            prev_price = float(prev_str)
            if prev_price > 0:
                pct = ((cur_price - prev_price) / prev_price) * 100
                if not math.isnan(pct) and not math.isinf(pct):
                    changes[coin_key] = round(pct, 4)
    return changes


def _update_history_scores(r, gainers_24h: list[dict]) -> list[dict]:
    key = "aicoin:history_scores"
    for i, item in enumerate(gainers_24h[:20]):
        score = 5 if i == 0 else (3 if i < 5 else 1)
        r.zincrby(key, score, item["symbol"])
    raw = r.zrevrange(key, 0, 19, withscores=True)
    return [{"symbol": sym, "score": int(sc)} for sym, sc in raw]


@router.get("/rankings")
async def get_rankings(request: Request):
    get_current_user_id(request)
    try:
        r = _redis()
        cached = r.get("aicoin:rankings")
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    ac = _get_aicoin()
    try:
        coin_list = await ac.get_coin_list()
        coin_map = {}
        for c in coin_list:
            coin_map[c.get("coin_key", "")] = c.get("show", c.get("coin_key", "").upper())

        keys = [c.get("coin_key", "") for c in coin_list if c.get("coin_key")]
        if not keys:
            return {"gainers": [], "losers": [], "gainers_5min": [], "historical": []}

        ticker_data = await ac.get_coin_ticker(",".join(keys))

        items = []
        price_map = {}
        for info in ticker_data:
            if not isinstance(info, dict):
                continue
            coin_key = info.get("coin_key", "")
            change_24h = _safe_float(info.get("degree_24h_usd") or info.get("degree_24h_cny"))
            change_7d = _safe_float(info.get("degree_7day_usd") or info.get("degree_7day_cny"))
            price = _safe_float(info.get("price_usd") or info.get("price_cny"))
            vol = _safe_float(info.get("vol_24h") or info.get("trade_24h_usd"))
            if not coin_key or price == 0:
                continue

            symbol = coin_map.get(coin_key, coin_key.upper())
            price_map[coin_key] = price
            items.append({
                "symbol": symbol,
                "coin_key": coin_key,
                "price": price,
                "change_24h": change_24h,
                "change_7d": change_7d,
                "vol_24h": vol,
            })

        gainers = sorted(items, key=lambda x: x["change_24h"], reverse=True)[:20]
        losers = sorted(items, key=lambda x: x["change_24h"])[:20]

        gainers_5min = []
        historical = []
        try:
            r = _redis()
            changes_5m = _compute_5min_changes(r, price_map)
            if changes_5m:
                items_5m = []
                for it in items:
                    ch = changes_5m.get(it["coin_key"])
                    if ch is not None:
                        items_5m.append({**it, "change_5min": ch})
                gainers_5min = sorted(items_5m, key=lambda x: x["change_5min"], reverse=True)[:20]
            historical = _update_history_scores(r, gainers)
        except Exception as exc:
            logger.warning(f"Redis history/5min error: {exc}")

        result = {
            "gainers": gainers,
            "losers": losers,
            "gainers_5min": gainers_5min,
            "historical": historical,
        }
        try:
            r = _redis()
            r.setex("aicoin:rankings", 30, json.dumps(result))
        except Exception:
            pass
        return result
    except Exception as e:
        logger.warning(f"AiCoin rankings error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")
