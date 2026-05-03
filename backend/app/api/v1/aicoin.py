"""AiCoin K-line and coin search proxy endpoints"""
import logging
from fastapi import APIRouter, HTTPException, Query

from app.services.aicoin_client import AiCoinClient

logger = logging.getLogger(__name__)

router = APIRouter()

AICOIN_API_KEY = "Kc9TBaTv5qA8ZFFGWFiLWuXL7DG2iIaB"
AICOIN_API_SECRET = "YNXiSLTUgAhFEWaOXFQYpbCwCwsrIPLC"

_PERIOD_TO_SECONDS = {"1": "60", "5": "300", "15": "900", "30": "1800",
                      "60": "3600", "240": "14400", "1440": "86400"}

_client: AiCoinClient | None = None


def _get_client() -> AiCoinClient:
    global _client
    if _client is None:
        _client = AiCoinClient(AICOIN_API_KEY, AICOIN_API_SECRET)
    return _client


@router.get("/kline")
async def get_kline(
    symbol: str = Query(..., description="AiCoin dbKeys, e.g. btcswapusdt:binance"),
    period: str = Query("60", description="Period in minutes: 1,5,15,30,60,240,1440"),
    size: int = Query(300, ge=1, le=500),
):
    ac = _get_client()
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
    ac = _get_client()
    try:
        data = await ac.search_coin(q)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"AiCoin search error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")
