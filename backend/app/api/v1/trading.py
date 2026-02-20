"""Trading history API endpoints"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.order import OrderRecord

router = APIRouter()


@router.get("/history")
async def get_trading_history(
    date: Optional[str] = Query(default=None, description="Query date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
):
    """Get trading history for a specific date"""
    try:
        # TODO: Implement actual database query for trading history
        # For now, return empty data structure
        return {
            "stats": {
                "totalVolume": 0,
                "totalAmount": 0,
                "buySellAmount": 0,
                "taskAmount": 0,
                "totalFees": 0,
                "overnightFees": 0,
                "marketFundingRate": 0,
                "mt5OvernightFee": 0,
                "marketFee": 0,
                "mt5Fee": 0,
                "peRatio": 0,
                "mt5TodayReturn": 0,
                "totalReturnProfit": 0
            },
            "accountTrades": [],
            "mt5Trades": []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/all")
async def get_all_trading_history(
    current_user: User = Depends(get_current_user),
):
    """Get all trading history"""
    try:
        # TODO: Implement actual database query for all trading history
        # For now, return empty data structure
        return {
            "stats": {
                "totalVolume": 0,
                "totalAmount": 0,
                "buySellAmount": 0,
                "taskAmount": 0,
                "totalFees": 0,
                "overnightFees": 0,
                "marketFundingRate": 0,
                "mt5OvernightFee": 0,
                "marketFee": 0,
                "mt5Fee": 0,
                "peRatio": 0,
                "mt5TodayReturn": 0,
                "totalReturnProfit": 0
            },
            "accountTrades": [],
            "mt5Trades": []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/all")
async def delete_all_trading_history(
    current_user: User = Depends(get_current_user),
):
    """Delete all trading history"""
    try:
        # TODO: Implement actual database deletion for trading history
        # For now, return success message
        return {"message": "All trading history deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders")
async def get_recent_orders(
    limit: int = Query(default=50, le=200, description="Maximum number of orders to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent orders for the current user"""
    try:
        # Get user's accounts
        from app.models.account import Account
        result = await db.execute(
            select(Account).filter(Account.user_id == current_user.user_id)
        )
        user_accounts = result.scalars().all()
        account_ids = [acc.account_id for acc in user_accounts]

        if not account_ids:
            return []

        # Fetch recent orders for user's accounts
        result = await db.execute(
            select(OrderRecord)
            .filter(OrderRecord.account_id.in_(account_ids))
            .order_by(OrderRecord.create_time.desc())
            .limit(limit)
        )
        orders = result.scalars().all()

        # Transform to response format
        result_list = []
        for order in orders:
            # Get account info for platform name
            account = next((acc for acc in user_accounts if acc.account_id == order.account_id), None)
            platform_name = "Unknown"
            if account:
                if account.platform_id == 1:
                    platform_name = "Binance"
                elif account.platform_id == 2:
                    platform_name = "Bybit" if not account.is_mt5_account else "Bybit MT5"

            result_list.append({
                "id": str(order.order_id),
                "timestamp": order.create_time.isoformat() if order.create_time else None,
                "exchange": platform_name,
                "side": order.order_side,
                "quantity": order.qty,
                "price": order.price,
                "status": order.status,
                "symbol": order.symbol,
            })

        return result_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
