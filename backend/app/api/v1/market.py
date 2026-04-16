"""Market data API endpoints"""
from fastapi import APIRouter, HTTPException, Query
from typing import List
from app.services.market_service import market_data_service
from app.services.realtime_market_service import market_data_service as realtime_service
from app.schemas.market import MarketQuote, SpreadData

router = APIRouter()


@router.get("/connection/status")
async def get_connection_status():
    """Get MT5 connection status and health information"""
    try:
        mt5_client = realtime_service.mt5_client
        status = mt5_client.get_connection_status()

        return {
            "mt5": status,
            "service_running": realtime_service.running,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connection/reset")
async def reset_connection():
    """Reset MT5 connection failure counter"""
    try:
        mt5_client = realtime_service.mt5_client
        mt5_client.reset_connection_failures()

        return {
            "message": "Connection failure counter reset successfully",
            "status": mt5_client.get_connection_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connection/reconnect")
async def force_reconnect():
    """Force MT5 reconnection"""
    try:
        mt5_client = realtime_service.mt5_client

        # Disconnect if connected
        if mt5_client.connected:
            mt5_client.disconnect()

        # Reset failure counter
        mt5_client.reset_connection_failures()

        # Attempt to reconnect
        success = mt5_client.connect()

        return {
            "success": success,
            "message": "Reconnection successful" if success else "Reconnection failed",
            "status": mt5_client.get_connection_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    start_time: str = Query(default=None, description="Start time in ISO format"),
    end_time: str = Query(default=None, description="End time in ISO format"),
):
    """Get historical spread data"""
    try:
        return await market_data_service.get_spread_history(
            limit=limit,
            binance_symbol=binance_symbol,
            bybit_symbol=bybit_symbol,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/latest")
async def get_latest_market_data(
    symbol: str = Query(default="XAUUSDT", description="Trading symbol"),
):
    """Get latest market data from database"""
    try:
        data = await realtime_service.get_latest_market_data(symbol)
        if not data:
            raise HTTPException(status_code=404, detail="No market data available")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/{symbol}")
async def get_market_data(symbol: str = "XAUUSDT"):
    """Get combined market data for a symbol"""
    try:
        # Use the realtime service to get data from database
        data = await realtime_service.get_latest_market_data(symbol)
        if not data:
            raise HTTPException(status_code=404, detail="No market data available")
        return data
    except HTTPException:
        raise
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


@router.get("/orderbook")
async def get_order_book():
    """Get real-time order book data from Binance and Bybit MT5"""
    try:
        return await market_data_service.get_order_book()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/funding-rate")
async def get_binance_funding_rate():
    """
    Get real-time Binance XAUUSDT funding rate and convert to per-lot cost.

    Returns:
        funding_rate: Current funding rate (e.g. 0.0001 = 0.01%)
        next_funding_time: Next settlement timestamp (ms)
        mark_price: Current mark price (USD)
        long_cost_per_lot: Amount LONG pays per lot (100 XAU) at next settlement (USDT)
                           Positive = long pays short; Negative = short pays long
        short_cost_per_lot: Amount SHORT pays per lot (100 XAU) at next settlement (USDT)
                            Opposite sign of long_cost_per_lot
    """
    try:
        from app.services.binance_client import BinanceFuturesClient
        # Use anonymous client — premiumIndex is a public endpoint, no auth needed
        client = BinanceFuturesClient("", "")
        try:
            data = await client.get_premium_index("XAUUSDT")
        finally:
            await client.close()

        funding_rate = float(data.get("lastFundingRate", 0))
        mark_price = float(data.get("markPrice", 0))
        next_funding_time = int(data.get("nextFundingTime", 0))

        # 1 XAU; cost = funding_rate × mark_price × 1
        # Positive funding_rate: longs pay shorts
        # Negative funding_rate: shorts pay longs
        cost_per_lot = round(funding_rate * mark_price, 4)

        return {
            "symbol": "XAUUSDT",
            "funding_rate": funding_rate,
            "funding_rate_pct": round(funding_rate * 100, 6),  # percentage display
            "mark_price": mark_price,
            "next_funding_time": next_funding_time,
            "long_cost_per_lot": cost_per_lot,    # >0 long pays, <0 long receives
            "short_cost_per_lot": -cost_per_lot,  # opposite direction
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bybit-swap-rate")
async def get_bybit_swap_rate():
    """
    Get real-time Bybit XAUUSD+ swap (overnight) rates from MT5 symbol info.

    Returns:
        long_swap_per_lot:  Daily swap cost for LONG 1 lot (negative = long pays)
        short_swap_per_lot: Daily swap cost for SHORT 1 lot (positive = short receives)
    """
    try:
        import MetaTrader5 as mt5
        from app.services.realtime_market_service import market_data_service as realtime_service

        mt5_client = realtime_service.mt5_client
        if not mt5_client.ensure_connection():
            raise HTTPException(status_code=503, detail="MT5 not connected")

        symbol = "XAUUSD+"
        info = mt5.symbol_info(symbol)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found in MT5")

        # swap_long/swap_short: USD per lot per day (swap_mode=1), divided by 100
        # Negative swap_long = long pays; Positive swap_short = short receives
        return {
            "symbol": symbol,
            "long_swap_per_lot": round(info.swap_long / 100, 4),
            "short_swap_per_lot": round(info.swap_short / 100, 4),
            "swap_mode": info.swap_mode,
            "rollover_day": info.swap_rollover3days,
            "contract_size": info.trade_contract_size,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exchange-rate")
async def get_exchange_rate():
    """Get USDC/USDT exchange rate (cached, proxied through backend to avoid frontend IP exposure)"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT")
            data = resp.json()
            return {"price": data.get("price", "1.0000"), "symbol": "USDCUSDT"}
    except Exception:
        return {"price": "1.0000", "symbol": "USDCUSDT"}
