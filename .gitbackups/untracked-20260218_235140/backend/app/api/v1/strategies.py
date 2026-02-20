"""Strategy configuration API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.strategy import StrategyConfig
from app.models.account import Account
from app.schemas.strategy import (
    StrategyConfigCreate,
    StrategyConfigUpdate,
    StrategyConfigResponse,
)
from app.services.arbitrage_strategy import arbitrage_strategy

router = APIRouter()


@router.get("/configs", response_model=List[StrategyConfigResponse])
async def list_strategy_configs(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List all strategy configurations for current user"""
    result = await db.execute(
        select(StrategyConfig).where(StrategyConfig.user_id == UUID(user_id))
    )
    configs = result.scalars().all()

    return configs


@router.post("/configs", response_model=StrategyConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy_config(
    config_data: StrategyConfigCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new strategy configuration"""
    new_config = StrategyConfig(
        user_id=UUID(user_id),
        strategy_type=config_data.strategy_type,
        target_spread=config_data.target_spread,
        order_qty=config_data.order_qty,
        retry_times=config_data.retry_times,
        mt5_stuck_threshold=config_data.mt5_stuck_threshold,
        is_enabled=config_data.is_enabled,
    )

    db.add(new_config)
    await db.commit()
    await db.refresh(new_config)

    return new_config


@router.get("/configs/{config_id}", response_model=StrategyConfigResponse)
async def get_strategy_config(
    config_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get strategy configuration details"""
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == config_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found",
        )

    return config


@router.put("/configs/{config_id}", response_model=StrategyConfigResponse)
async def update_strategy_config(
    config_id: UUID,
    config_update: StrategyConfigUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update strategy configuration"""
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == config_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found",
        )

    # Update fields
    if config_update.target_spread is not None:
        config.target_spread = config_update.target_spread

    if config_update.order_qty is not None:
        config.order_qty = config_update.order_qty

    if config_update.retry_times is not None:
        config.retry_times = config_update.retry_times

    if config_update.mt5_stuck_threshold is not None:
        config.mt5_stuck_threshold = config_update.mt5_stuck_threshold

    if config_update.is_enabled is not None:
        config.is_enabled = config_update.is_enabled

    await db.commit()
    await db.refresh(config)

    return config


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy_config(
    config_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete strategy configuration"""
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == config_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found",
        )

    await db.delete(config)
    await db.commit()

    return None


# Execution schemas
class ExecuteStrategyRequest(BaseModel):
    binance_account_id: UUID
    bybit_account_id: UUID
    quantity: float
    target_spread: float


class ClosePositionRequest(BaseModel):
    task_id: UUID
    binance_account_id: UUID
    bybit_account_id: UUID
    quantity: float


@router.post("/execute/forward")
async def execute_forward_arbitrage(
    request: ExecuteStrategyRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute forward arbitrage strategy (long Binance, short Bybit)"""
    # Get accounts
    binance_result = await db.execute(
        select(Account).where(
            Account.account_id == request.binance_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    binance_account = binance_result.scalar_one_or_none()

    bybit_result = await db.execute(
        select(Account).where(
            Account.account_id == request.bybit_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    bybit_account = bybit_result.scalar_one_or_none()

    if not binance_account or not bybit_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        result = await arbitrage_strategy.execute_forward_arbitrage(
            user_id=UUID(user_id),
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            target_spread=request.target_spread,
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/execute/reverse")
async def execute_reverse_arbitrage(
    request: ExecuteStrategyRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute reverse arbitrage strategy (short Binance, long Bybit)"""
    # Get accounts
    binance_result = await db.execute(
        select(Account).where(
            Account.account_id == request.binance_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    binance_account = binance_result.scalar_one_or_none()

    bybit_result = await db.execute(
        select(Account).where(
            Account.account_id == request.bybit_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    bybit_account = bybit_result.scalar_one_or_none()

    if not binance_account or not bybit_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        result = await arbitrage_strategy.execute_reverse_arbitrage(
            user_id=UUID(user_id),
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            target_spread=request.target_spread,
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/close/forward")
async def close_forward_position(
    request: ClosePositionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Close forward arbitrage position"""
    # Get accounts
    binance_result = await db.execute(
        select(Account).where(
            Account.account_id == request.binance_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    binance_account = binance_result.scalar_one_or_none()

    bybit_result = await db.execute(
        select(Account).where(
            Account.account_id == request.bybit_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    bybit_account = bybit_result.scalar_one_or_none()

    if not binance_account or not bybit_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        result = await arbitrage_strategy.close_forward_arbitrage(
            task_id=request.task_id,
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/close/reverse")
async def close_reverse_position(
    request: ClosePositionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Close reverse arbitrage position"""
    # Get accounts
    binance_result = await db.execute(
        select(Account).where(
            Account.account_id == request.binance_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    binance_account = binance_result.scalar_one_or_none()

    bybit_result = await db.execute(
        select(Account).where(
            Account.account_id == request.bybit_account_id,
            Account.user_id == UUID(user_id),
        )
    )
    bybit_account = bybit_result.scalar_one_or_none()

    if not binance_account or not bybit_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        result = await arbitrage_strategy.close_reverse_arbitrage(
            task_id=request.task_id,
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
