"""Risk control API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime
import os
import shutil
from pathlib import Path
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.account import Account
from app.models.risk_alert import RiskAlert
from app.models.risk_settings import RiskSettings
from app.services.risk_monitor import risk_monitor

router = APIRouter()


# Pydantic models
class AlertSettings(BaseModel):
    binanceNetAsset: float = 10000
    bybitMT5NetAsset: float = 10000
    totalNetAsset: float = 20000
    binanceLiquidationPrice: float = 2000
    bybitMT5LiquidationPrice: float = 2000
    mt5LagCount: int = 5
    reverseOpenPrice: float = 0.5
    reverseOpenSyncCount: int = 3
    reverseClosePrice: float = 0.2
    reverseCloseSyncCount: int = 3
    forwardOpenPrice: float = 0.5
    forwardOpenSyncCount: int = 3
    forwardClosePrice: float = 0.2
    forwardCloseSyncCount: int = 3
    singleLegAlertSound: Optional[str] = None
    singleLegAlertRepeatCount: int = 3
    spreadAlertSound: Optional[str] = None
    spreadAlertRepeatCount: int = 3
    netAssetAlertSound: Optional[str] = None
    netAssetAlertRepeatCount: int = 3
    mt5AlertSound: Optional[str] = None
    mt5AlertRepeatCount: int = 3
    liquidationAlertSound: Optional[str] = None
    liquidationAlertRepeatCount: int = 3


@router.get("/status")
async def get_risk_status(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get risk status"""
    try:
        is_emergency_stop = await risk_monitor.is_emergency_stop_active()
        return {
            "emergency_stop_active": is_emergency_stop,
            "account_risk": 45,
            "mt5_status": "正常",
            "active_alerts": 0
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/alert-settings")
async def get_alert_settings(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AlertSettings:
    """Get alert settings for current user from database"""
    try:
        # Query database for user's risk settings
        result = await db.execute(
            select(RiskSettings).where(RiskSettings.user_id == UUID(user_id))
        )
        settings = result.scalar_one_or_none()

        if settings:
            # Convert database model to response model
            return AlertSettings(
                binanceNetAsset=settings.binance_net_asset,
                bybitMT5NetAsset=settings.bybit_mt5_net_asset,
                totalNetAsset=settings.total_net_asset,
                binanceLiquidationPrice=settings.binance_liquidation_price,
                bybitMT5LiquidationPrice=settings.bybit_mt5_liquidation_price,
                mt5LagCount=settings.mt5_lag_count,
                reverseOpenPrice=settings.reverse_open_price,
                reverseOpenSyncCount=settings.reverse_open_sync_count,
                reverseClosePrice=settings.reverse_close_price,
                reverseCloseSyncCount=settings.reverse_close_sync_count,
                forwardOpenPrice=settings.forward_open_price,
                forwardOpenSyncCount=settings.forward_open_sync_count,
                forwardClosePrice=settings.forward_close_price,
                forwardCloseSyncCount=settings.forward_close_sync_count,
                singleLegAlertSound=settings.single_leg_alert_sound,
                singleLegAlertRepeatCount=settings.single_leg_alert_repeat_count,
                spreadAlertSound=settings.spread_alert_sound,
                spreadAlertRepeatCount=settings.spread_alert_repeat_count,
                netAssetAlertSound=settings.net_asset_alert_sound,
                netAssetAlertRepeatCount=settings.net_asset_alert_repeat_count,
                mt5AlertSound=settings.mt5_alert_sound,
                mt5AlertRepeatCount=settings.mt5_alert_repeat_count,
                liquidationAlertSound=settings.liquidation_alert_sound,
                liquidationAlertRepeatCount=settings.liquidation_alert_repeat_count,
            )

        # Return default settings if none exist
        return AlertSettings()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/alert-settings")
async def save_alert_settings(
    settings: AlertSettings,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Save alert settings for current user to database"""
    try:
        # Check if settings already exist
        result = await db.execute(
            select(RiskSettings).where(RiskSettings.user_id == UUID(user_id))
        )
        existing_settings = result.scalar_one_or_none()

        if existing_settings:
            # Update existing settings
            existing_settings.binance_net_asset = settings.binanceNetAsset
            existing_settings.bybit_mt5_net_asset = settings.bybitMT5NetAsset
            existing_settings.total_net_asset = settings.totalNetAsset
            existing_settings.binance_liquidation_price = settings.binanceLiquidationPrice
            existing_settings.bybit_mt5_liquidation_price = settings.bybitMT5LiquidationPrice
            existing_settings.mt5_lag_count = settings.mt5LagCount
            existing_settings.reverse_open_price = settings.reverseOpenPrice
            existing_settings.reverse_open_sync_count = settings.reverseOpenSyncCount
            existing_settings.reverse_close_price = settings.reverseClosePrice
            existing_settings.reverse_close_sync_count = settings.reverseCloseSyncCount
            existing_settings.forward_open_price = settings.forwardOpenPrice
            existing_settings.forward_open_sync_count = settings.forwardOpenSyncCount
            existing_settings.forward_close_price = settings.forwardClosePrice
            existing_settings.forward_close_sync_count = settings.forwardCloseSyncCount
            existing_settings.single_leg_alert_sound = settings.singleLegAlertSound
            existing_settings.single_leg_alert_repeat_count = settings.singleLegAlertRepeatCount
            existing_settings.spread_alert_sound = settings.spreadAlertSound
            existing_settings.spread_alert_repeat_count = settings.spreadAlertRepeatCount
            existing_settings.net_asset_alert_sound = settings.netAssetAlertSound
            existing_settings.net_asset_alert_repeat_count = settings.netAssetAlertRepeatCount
            existing_settings.mt5_alert_sound = settings.mt5AlertSound
            existing_settings.mt5_alert_repeat_count = settings.mt5AlertRepeatCount
            existing_settings.liquidation_alert_sound = settings.liquidationAlertSound
            existing_settings.liquidation_alert_repeat_count = settings.liquidationAlertRepeatCount
            existing_settings.update_time = datetime.utcnow()
        else:
            # Create new settings
            new_settings = RiskSettings(
                user_id=UUID(user_id),
                binance_net_asset=settings.binanceNetAsset,
                bybit_mt5_net_asset=settings.bybitMT5NetAsset,
                total_net_asset=settings.totalNetAsset,
                binance_liquidation_price=settings.binanceLiquidationPrice,
                bybit_mt5_liquidation_price=settings.bybitMT5LiquidationPrice,
                mt5_lag_count=settings.mt5LagCount,
                reverse_open_price=settings.reverseOpenPrice,
                reverse_open_sync_count=settings.reverseOpenSyncCount,
                reverse_close_price=settings.reverseClosePrice,
                reverse_close_sync_count=settings.reverseCloseSyncCount,
                forward_open_price=settings.forwardOpenPrice,
                forward_open_sync_count=settings.forwardOpenSyncCount,
                forward_close_price=settings.forwardClosePrice,
                forward_close_sync_count=settings.forwardCloseSyncCount,
                single_leg_alert_sound=settings.singleLegAlertSound,
                single_leg_alert_repeat_count=settings.singleLegAlertRepeatCount,
                spread_alert_sound=settings.spreadAlertSound,
                spread_alert_repeat_count=settings.spreadAlertRepeatCount,
                net_asset_alert_sound=settings.netAssetAlertSound,
                net_asset_alert_repeat_count=settings.netAssetAlertRepeatCount,
                mt5_alert_sound=settings.mt5AlertSound,
                mt5_alert_repeat_count=settings.mt5AlertRepeatCount,
                liquidation_alert_sound=settings.liquidationAlertSound,
                liquidation_alert_repeat_count=settings.liquidationAlertRepeatCount,
            )
            db.add(new_settings)

        await db.commit()
        return {"message": "Alert settings saved successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


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


@router.post("/alert-sound/upload")
async def upload_alert_sound(
    alert_type: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Upload alert sound file (MP3)

    Args:
        alert_type: Type of alert (spread, net_asset, mt5, liquidation)
        file: MP3 file to upload
    """
    try:
        # Validate alert type
        valid_types = ["single_leg", "spread", "net_asset", "mt5", "liquidation"]
        if alert_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid alert type. Must be one of: {', '.join(valid_types)}"
            )

        # Validate file type
        if not file.filename.endswith('.mp3'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only MP3 files are allowed"
            )

        # Create uploads directory if it doesn't exist
        upload_dir = Path("uploads/alert_sounds")
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        file_extension = Path(file.filename).suffix
        filename = f"{user_id}_{alert_type}{file_extension}"
        file_path = upload_dir / filename

        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Return relative path for storage in database
        relative_path = f"/uploads/alert_sounds/{filename}"
        return {
            "message": "File uploaded successfully",
            "file_path": relative_path
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
