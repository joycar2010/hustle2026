"""Risk control API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.account import Account
from app.models.risk_alert import RiskAlert
from app.services.risk_monitor import risk_monitor

router = APIRouter()


@router.get("/mt5/stuck")
async def check_mt5_stuck(
    symbol: str = "XAUUSDT",
    threshold: int = 5,
):
    """Check if MT5 data is stuck"""
    try:
        result = await risk_monitor.check_mt5_stuck(symbol, threshold)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/account/{account_id}/risk")
async def check_account_risk(
    account_id: UUID,
    max_risk_ratio: float = 80.0,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Check account risk ratio"""
    # Get account
    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        risk_result = await risk_monitor.check_account_risk(account, max_risk_ratio)
        return risk_result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/alerts")
async def get_active_alerts(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get active risk alerts for current user"""
    try:
        alerts = await risk_monitor.get_active_alerts(db, UUID(user_id))
        return [
            {
                "alert_id": str(alert.alert_id),
                "level": alert.alert_level,
                "message": alert.alert_message,
                "create_time": alert.create_time.isoformat(),
                "expire_time": alert.expire_time.isoformat() if alert.expire_time else None,
            }
            for alert in alerts
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.delete("/alerts/expired")
async def clear_expired_alerts(
    db: AsyncSession = Depends(get_db),
):
    """Clear expired risk alerts"""
    try:
        await risk_monitor.clear_expired_alerts(db)
        return {"message": "Expired alerts cleared"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/emergency-stop/activate")
async def activate_emergency_stop(
    user_id: str = Depends(get_current_user_id),
):
    """Activate emergency stop - prevents all trading"""
    try:
        await risk_monitor.activate_emergency_stop()
        return {
            "message": "Emergency stop activated",
            "active": True,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/emergency-stop/deactivate")
async def deactivate_emergency_stop(
    user_id: str = Depends(get_current_user_id),
):
    """Deactivate emergency stop - allows trading"""
    try:
        await risk_monitor.deactivate_emergency_stop()
        return {
            "message": "Emergency stop deactivated",
            "active": False,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/emergency-stop/status")
async def get_emergency_stop_status():
    """Get emergency stop status"""
    try:
        is_active = await risk_monitor.is_emergency_stop_active()
        return {
            "active": is_active,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
