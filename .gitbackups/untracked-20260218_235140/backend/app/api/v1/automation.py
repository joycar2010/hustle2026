"""
Strategy Automation API Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.strategy import Strategy
from app.services.strategy_manager import strategy_manager
from app.services.position_monitor import position_monitor
from app.schemas.strategy import StrategyAutomationResponse

router = APIRouter()


@router.post("/strategies/{strategy_id}/start", response_model=StrategyAutomationResponse)
async def start_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start automated strategy execution"""
    # Verify strategy belongs to user
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if strategy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Start strategy
    success = await strategy_manager.start_strategy(strategy_id, db)

    if not success:
        raise HTTPException(status_code=400, detail="Strategy already running")

    return StrategyAutomationResponse(
        success=True,
        message=f"Strategy {strategy_id} started",
        strategy_id=strategy_id
    )


@router.post("/strategies/{strategy_id}/stop", response_model=StrategyAutomationResponse)
async def stop_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stop automated strategy execution"""
    # Verify strategy belongs to user
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if strategy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Stop strategy
    success = await strategy_manager.stop_strategy(strategy_id, db)

    if not success:
        raise HTTPException(status_code=400, detail="Strategy not running")

    return StrategyAutomationResponse(
        success=True,
        message=f"Strategy {strategy_id} stopped",
        strategy_id=strategy_id
    )


@router.get("/strategies/running")
async def get_running_strategies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all running strategies for current user"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.user_id == current_user.id,
            Strategy.status == "running"
        )
    )
    strategies = result.scalars().all()

    return {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "symbol": s.symbol,
                "direction": s.direction,
                "min_spread": float(s.min_spread),
                "status": s.status
            }
            for s in strategies
        ]
    }


@router.post("/position-monitor/start")
async def start_position_monitor(
    current_user: User = Depends(get_current_user)
):
    """Start position monitoring (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    await position_monitor.start_monitoring()

    return {"success": True, "message": "Position monitoring started"}


@router.post("/position-monitor/stop")
async def stop_position_monitor(
    current_user: User = Depends(get_current_user)
):
    """Stop position monitoring (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    await position_monitor.stop_monitoring()

    return {"success": True, "message": "Position monitoring stopped"}


@router.get("/position-monitor/status")
async def get_position_monitor_status(
    current_user: User = Depends(get_current_user)
):
    """Get position monitor status"""
    return {
        "monitoring": position_monitor.monitoring,
        "active": position_monitor.monitor_task is not None and not position_monitor.monitor_task.done()
    }
