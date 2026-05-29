"""AiCoin K-line and coin search proxy endpoints.

Credentials are loaded from DB (table: aicoin_config, single row id=1).
Cached in memory for 60s to avoid repeated DB hits.
"""
import logging
import time as _time
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.services.aicoin_client import AiCoinClient
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

_PERIOD_TO_SECONDS = {"1": "60", "5": "300", "15": "900", "30": "1800",
                      "60": "3600", "240": "14400", "1440": "86400"}

# In-memory cache: (client, key, secret, ts)
_client_cache: dict = {"client": None, "key": "", "secret": "", "ts": 0}
_CACHE_TTL = 60


async def _load_credentials() -> tuple[str, str, bool]:
    """Load AiCoin credentials from aicoin_config table (id=1)."""
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                text("SELECT api_key, api_secret, enabled FROM aicoin_config WHERE id=1")
            )).first()
            if row:
                return (row[0] or "", row[1] or "", bool(row[2]) if row[2] is not None else True)
    except Exception as e:
        logger.warning(f"AiCoin: failed to read config from DB: {e}")
    return ("", "", False)


async def _get_client() -> Optional[AiCoinClient]:
    """Get (cached) AiCoin client. Returns None if credentials missing/disabled."""
    now = _time.time()
    # Refresh cache after TTL or on first call
    if _client_cache["client"] is None or now - _client_cache["ts"] > _CACHE_TTL:
        key, secret, enabled = await _load_credentials()
        if not enabled or not key or not secret:
            _client_cache.update({"client": None, "key": "", "secret": "", "ts": now})
            return None
        if key != _client_cache["key"] or secret != _client_cache["secret"]:
            _client_cache.update({
                "client": AiCoinClient(key, secret),
                "key": key, "secret": secret,
            })
        _client_cache["ts"] = now
    return _client_cache["client"]


@router.get("/kline")
async def get_kline(
    symbol: str = Query(..., description="AiCoin dbKeys, e.g. btcswapusdt:binance"),
    period: str = Query("60", description="Period in minutes: 1,5,15,30,60,240,1440"),
    size: int = Query(300, ge=1, le=500),
):
    ac = await _get_client()
    if ac is None:
        raise HTTPException(
            status_code=503,
            detail="AiCoin 未配置或已禁用, 请在系统管理 → AiCoin 配置中填入 AccessKeyId 和 Secret",
        )
    api_period = _PERIOD_TO_SECONDS.get(period, period)
    try:
        data = await ac.get_kline(symbol, api_period, size)
        return {"data": data}
    except Exception as e:
        logger.warning(f"AiCoin kline error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


@router.get("/coin-search")
async def search_coin(
    q: str = Query(..., description="Search keyword"),
):
    ac = await _get_client()
    if ac is None:
        raise HTTPException(
            status_code=503,
            detail="AiCoin 未配置或已禁用, 请在系统管理 → AiCoin 配置中填入 AccessKeyId 和 Secret",
        )
    try:
        data = await ac.search_coin(q)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"AiCoin search error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")
