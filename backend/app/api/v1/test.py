"""Test API endpoints for account data"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.mt5_client import MT5Client
from app.core.config import settings
import logging

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
