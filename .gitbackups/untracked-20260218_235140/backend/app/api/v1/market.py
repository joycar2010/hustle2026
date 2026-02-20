"""Market data API endpoints"""
from fastapi import APIRouter, HTTPException, Query
from typing import List
from app.services.market_service import market_data_service
from app.schemas.market import MarketQuote, SpreadData

router = APIRouter()


@router.get("/quotes/binance", response_model=MarketQuote)
async def get_binance_quote(
    symbol: str = Query(default="XAUUSDT", description="Trading symbol"),
):
    """Get current Binance market quote"""
    try:
        return await market_data_service.get_binance_quote(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quotes/bybit", response_model=MarketQuote)
async def get_bybit_quote(
    symbol: str = Query(default="XAUUSDT", description="Trading symbol"),
    category: str = Query(default="linear", description="Product category"),
):
    """Get current Bybit market quote"""
    try:
        return await market_data_service.get_bybit_quote(symbol, category)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spread", response_model=SpreadData)
async def get_current_spread(
    binance_symbol: str = Query(default="XAUUSDT", description="Binance symbol"),
    bybit_symbol: str = Query(default="XAUUSDT", description="Bybit symbol"),
    bybit_category: str = Query(default="linear", description="Bybit category"),
    use_cache: bool = Query(default=True, description="Use cached data"),
):
    """Get current spread data between Binance and Bybit"""
    try:
        return await market_data_service.get_current_spread(
            binance_symbol=binance_symbol,
            bybit_symbol=bybit_symbol,
            bybit_category=bybit_category,
            use_cache=use_cache,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spread/history")
async def get_spread_history(
    limit: int = Query(default=100, ge=1, le=1000, description="Number of records"),
    binance_symbol: str = Query(default="XAUUSDT", description="Binance symbol"),
    bybit_symbol: str = Query(default="XAUUSDT", description="Bybit symbol"),
):
    """Get historical spread data"""
    try:
        return await market_data_service.get_spread_history(
            limit=limit,
            binance_symbol=binance_symbol,
            bybit_symbol=bybit_symbol,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/time/sync")
async def sync_server_time():
    """Synchronize server time with Binance"""
    try:
        return await market_data_service.sync_server_time()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/time/offset")
async def get_time_offset():
    """Get current time offset"""
    try:
        offset = await market_data_service.get_time_offset()
        return {"offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
