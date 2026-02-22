"""Test API endpoints for account data"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.mt5_client import MT5Client
from app.services.binance_client import BinanceFuturesClient
from app.core.config import settings
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter()


class MT5BalanceResponse(BaseModel):
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    profit: float


@router.get("/mt5-balance", response_model=MT5BalanceResponse)
async def get_mt5_balance():
    """Get MT5 account balance"""
    try:
        # Initialize MT5 client
        mt5_client = MT5Client(
            login=int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0,
            password=settings.BYBIT_MT5_PASSWORD,
            server=settings.BYBIT_MT5_SERVER
        )

        # Connect to MT5
        if not mt5_client.connect():
            raise HTTPException(status_code=500, detail="Failed to connect to MT5")

        # Get account info
        account_info = mt5_client.get_account_info()

        # Disconnect
        mt5_client.disconnect()

        if not account_info:
            raise HTTPException(status_code=500, detail="Failed to get MT5 account info")

        return MT5BalanceResponse(
            balance=account_info.get("balance", 0.0),
            equity=account_info.get("equity", 0.0),
            margin=account_info.get("margin", 0.0),
            margin_free=account_info.get("margin_free", 0.0),
            margin_level=account_info.get("margin_level", 0.0),
            profit=account_info.get("profit", 0.0)
        )

    except Exception as e:
        logger.error(f"Error getting MT5 balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/binance/spot")
async def get_binance_spot_account(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
) -> Dict[str, Any]:
    """Get Binance Spot account data"""
    client = BinanceFuturesClient(api_key, api_secret)
    try:
        data = await client.get_spot_account()
        return data
    except Exception as e:
        logger.error(f"Error getting Binance Spot account: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.get("/binance/margin")
async def get_binance_margin_account(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
) -> Dict[str, Any]:
    """Get Binance Cross Margin account data"""
    client = BinanceFuturesClient(api_key, api_secret)
    try:
        data = await client.get_margin_account()
        return data
    except Exception as e:
        logger.error(f"Error getting Binance Margin account: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.get("/binance/futures")
async def get_binance_futures_account(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
) -> Dict[str, Any]:
    """Get Binance USDT-M Futures account data"""
    client = BinanceFuturesClient(api_key, api_secret)
    try:
        data = await client.get_account()
        return data
    except Exception as e:
        logger.error(f"Error getting Binance Futures account: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.get("/binance/options")
async def get_binance_options_account(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
) -> Dict[str, Any]:
    """Get Binance Options account data (EAPI)"""
    # Note: Options API is not implemented yet
    # This endpoint returns a placeholder response
    return {
        "msg": "Options account data is not available in this implementation",
        "totalAsset": "0",
        "availableBalance": "0"
    }


@router.get("/binance/position-risk")
async def get_binance_position_risk(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
):
    """Get Binance Futures position risk data"""
    client = BinanceFuturesClient(api_key, api_secret)
    try:
        data = await client.get_position_risk()
        return data
    except Exception as e:
        logger.error(f"Error getting Binance position risk: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.get("/binance/daily-pnl")
async def get_binance_daily_pnl(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
):
    """Get Binance Futures daily P&L"""
    client = BinanceFuturesClient(api_key, api_secret)
    try:
        from datetime import datetime
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(today.timestamp() * 1000)

        data = await client.get_income(
            income_type="REALIZED_PNL",
            start_time=start_time,
            limit=1000
        )
        return data
    except Exception as e:
        logger.error(f"Error getting Binance daily P&L: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.get("/binance/funding-fees")
async def get_binance_funding_fees(
    api_key: str = Query(..., description="Binance API Key"),
    api_secret: str = Query(..., description="Binance API Secret")
):
    """Get Binance Futures funding fees"""
    client = BinanceFuturesClient(api_key, api_secret)
    try:
        from datetime import datetime
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(today.timestamp() * 1000)

        data = await client.get_income(
            income_type="FUNDING_FEE",
            start_time=start_time,
            limit=1000
        )
        return data
    except Exception as e:
        logger.error(f"Error getting Binance funding fees: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()
