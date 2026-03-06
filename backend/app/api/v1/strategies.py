"""Strategy configuration API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Union
from uuid import UUID
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.strategy import StrategyConfig
from app.models.account import Account
from app.schemas.strategy import (
    StrategyConfigCreate,
    StrategyConfigUpdate,
    StrategyConfigResponse,
)
from app.services.position_manager import position_manager
from app.services.order_executor_v2 import OrderExecutorV2
from app.services.market_service import market_data_service
from app.services.risk_alert_service import RiskAlertService
from app.websocket.manager import manager

router = APIRouter()
order_executor_v2 = OrderExecutorV2()


# Request models for strategy execution
class ExecuteStrategyRequest(BaseModel):
    binance_account_id: UUID
    bybit_account_id: UUID
    quantity: float
    ladder_index: int = 0
    target_spread: float = None


class ClosePositionRequest(BaseModel):
    binance_account_id: UUID
    bybit_account_id: UUID
    quantity: float
    ladder_index: int = 0


async def send_single_leg_alert(user_id: str, strategy_type: str, action: str, details: dict, db: AsyncSession):
    """Send single-leg trade alert via WebSocket and Feishu"""
    alert_message = {
        "type": "single_leg_alert",
        "data": {
            "strategy_type": strategy_type,
            "action": action,
            "binance_filled": details.get("binance_filled", 0),
            "bybit_filled": details.get("bybit_filled", 0),
            "unfilled_qty": details.get("unfilled_qty", 0),
            "timestamp": details.get("timestamp"),
            "level": "critical",
            "title": "单腿交易警告",
            "message": f"{strategy_type} {action}: Binance成交 {details.get('binance_filled', 0)}, Bybit成交 {details.get('bybit_filled', 0)}, 未成交 {details.get('unfilled_qty', 0)}"
        }
    }
    # Send WebSocket notification
    await manager.send_to_user(alert_message, user_id)

    # Send Feishu notification
    try:
        risk_alert_service = RiskAlertService(db)
        # Determine direction based on strategy type and action
        direction = "多头" if "forward" in strategy_type.lower() else "空头"
        exchange = "Binance"  # Single-leg usually happens on Binance side

        await risk_alert_service.check_single_leg(
            user_id=user_id,
            exchange=exchange,
            quantity=details.get("unfilled_qty", 0),
            duration=0,  # Immediate alert
            direction=direction
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to send Feishu single-leg alert: {e}")


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
        opening_sync_count=config_data.opening_sync_count,
        closing_sync_count=config_data.closing_sync_count,
        is_enabled=config_data.is_enabled,
    )

    db.add(new_config)
    await db.commit()
    await db.refresh(new_config)

    return new_config


@router.post("/configs/upsert", response_model=StrategyConfigResponse)
async def upsert_strategy_config(
    config_data: StrategyConfigCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create or update strategy config by type (upsert)"""
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.user_id == UUID(user_id),
            StrategyConfig.strategy_type == config_data.strategy_type,
        ).order_by(StrategyConfig.create_time.desc())
    )
    config = result.scalars().first()

    # If duplicates exist, delete them and keep only the first one
    if config:
        dup_result = await db.execute(
            select(StrategyConfig).where(
                StrategyConfig.user_id == UUID(user_id),
                StrategyConfig.strategy_type == config_data.strategy_type,
                StrategyConfig.config_id != config.config_id,
            )
        )
        duplicates = dup_result.scalars().all()
        for dup in duplicates:
            await db.delete(dup)

    ladders_data = [l.model_dump() for l in config_data.ladders]

    if config:
        config.target_spread = config_data.target_spread
        config.order_qty = config_data.order_qty
        config.retry_times = config_data.retry_times
        config.mt5_stuck_threshold = config_data.mt5_stuck_threshold
        config.opening_sync_count = config_data.opening_sync_count
        config.closing_sync_count = config_data.closing_sync_count
        # Handle backward compatibility
        if config_data.m_coin is not None:
            config.m_coin = config_data.m_coin
            config.opening_m_coin = config_data.m_coin
            config.closing_m_coin = config_data.m_coin
        else:
            config.opening_m_coin = config_data.opening_m_coin
            config.closing_m_coin = config_data.closing_m_coin
            config.m_coin = config_data.opening_m_coin  # Keep m_coin for backward compatibility
        config.ladders = ladders_data
        config.is_enabled = config_data.is_enabled
    else:
        # Handle backward compatibility for new records
        if config_data.m_coin is not None:
            opening_m_coin = config_data.m_coin
            closing_m_coin = config_data.m_coin
            m_coin = config_data.m_coin
        else:
            opening_m_coin = config_data.opening_m_coin
            closing_m_coin = config_data.closing_m_coin
            m_coin = config_data.opening_m_coin

        config = StrategyConfig(
            user_id=UUID(user_id),
            strategy_type=config_data.strategy_type,
            target_spread=config_data.target_spread,
            order_qty=config_data.order_qty,
            retry_times=config_data.retry_times,
            mt5_stuck_threshold=config_data.mt5_stuck_threshold,
            opening_sync_count=config_data.opening_sync_count,
            closing_sync_count=config_data.closing_sync_count,
            m_coin=m_coin,
            opening_m_coin=opening_m_coin,
            closing_m_coin=closing_m_coin,
            ladders=ladders_data,
            is_enabled=config_data.is_enabled,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return config


@router.get("/configs/by-type/{strategy_type}", response_model=StrategyConfigResponse)
async def get_strategy_config_by_type(
    strategy_type: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get strategy config by type (forward/reverse)"""
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.user_id == UUID(user_id),
            StrategyConfig.strategy_type == strategy_type,
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found",
        )

    return config


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
    if config_update.opening_sync_count is not None:
        config.opening_sync_count = config_update.opening_sync_count
    if config_update.closing_sync_count is not None:
        config.closing_sync_count = config_update.closing_sync_count
    if config_update.m_coin is not None:
        config.m_coin = config_update.m_coin
    if config_update.ladders is not None:
        config.ladders = [l.model_dump() for l in config_update.ladders]
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
# (Removed duplicate - using the definition at line 35)


class ValidateConfigRequest(BaseModel):
    strategy_type: str
    action: str  # 'opening' or 'closing'
    ladders: List[dict]
    opening_m_coin: float
    closing_m_coin: float
    opening_sync_qty: int
    closing_sync_qty: int


class ValidateConfigResponse(BaseModel):
    valid: bool
    errors: List[str]


@router.post("/configs/validate", response_model=ValidateConfigResponse)
async def validate_strategy_config(
    request: ValidateConfigRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Validate strategy configuration before execution"""
    errors = []

    # Check if there are enabled ladders
    enabled_ladders = [l for l in request.ladders if l.get('enabled', False)]
    if len(enabled_ladders) == 0:
        errors.append('至少需要启用一个阶梯')
        return ValidateConfigResponse(valid=False, errors=errors)

    # Check each enabled ladder
    for idx, ladder in enumerate(enabled_ladders):
        ladder_num = request.ladders.index(ladder) + 1

        if request.action == 'opening':
            # Check opening spread value
            open_price = ladder.get('openPrice')
            if open_price is None:
                errors.append(f'阶梯{ladder_num}: 开仓点差值未配置')

            # Check opening trigger count
            if not request.opening_sync_qty or request.opening_sync_qty < 1:
                errors.append('开仓触发次数必须至少为1')

            # Check opening m_coin
            if not request.opening_m_coin or request.opening_m_coin <= 0:
                errors.append('开仓单次下单手数必须大于0')

            # Check m_coin doesn't exceed total quantity
            qty_limit = ladder.get('qtyLimit', 0)
            if request.opening_m_coin > qty_limit:
                errors.append(f'阶梯{ladder_num}: 开仓单次下单手数({request.opening_m_coin})不能超过总手数({qty_limit})')

        elif request.action == 'closing':
            # Check closing spread value
            threshold = ladder.get('threshold')
            if threshold is None:
                errors.append(f'阶梯{ladder_num}: 平仓点差值未配置')

            # Check closing trigger count
            if not request.closing_sync_qty or request.closing_sync_qty < 1:
                errors.append('平仓触发次数必须至少为1')

            # Check closing m_coin
            if not request.closing_m_coin or request.closing_m_coin <= 0:
                errors.append('平仓单次下单手数必须大于0')

            # Check m_coin doesn't exceed total quantity
            qty_limit = ladder.get('qtyLimit', 0)
            if request.closing_m_coin > qty_limit:
                errors.append(f'阶梯{ladder_num}: 平仓单次下单手数({request.closing_m_coin})不能超过总手数({qty_limit})')

        # Check total quantity
        qty_limit = ladder.get('qtyLimit', 0)
        if not qty_limit or qty_limit <= 0:
            errors.append(f'阶梯{ladder_num}: 总手数必须大于0')

    return ValidateConfigResponse(
        valid=len(errors) == 0,
        errors=errors
    )


@router.post("/execute/reverse")
async def execute_reverse_arbitrage(
    request: ExecuteStrategyRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute reverse arbitrage strategy (Binance short, Bybit long)"""
    try:
        # 1. Get accounts
        binance_result = await db.execute(
            select(Account).where(Account.account_id == request.binance_account_id)
        )
        binance_account = binance_result.scalar_one_or_none()

        bybit_result = await db.execute(
            select(Account).where(Account.account_id == request.bybit_account_id)
        )
        bybit_account = bybit_result.scalar_one_or_none()

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found")

        # 2. Check position limits
        strategy_id = f"{user_id}_reverse"
        can_open = position_manager.check_can_open(
            strategy_id=strategy_id,
            ladder_index=request.ladder_index,
            strategy_type="reverse",
            quantity=request.quantity,
            max_position=request.quantity
        )

        if not can_open:
            raise HTTPException(status_code=400, detail="Position limit exceeded for this ladder")

        # 3. Get current market prices (use ask for sell, bid for buy)
        # For reverse opening: Binance SELL (use ask price for MAKER), Bybit BUY (market)
        from app.services.market_service import market_data_service
        market_data = await market_data_service.get_current_spread()

        binance_price = market_data.binance_quote.ask_price  # MAKER: use ask price for sell order
        bybit_price = market_data.bybit_quote.ask_price  # Market will use current ask

        # 4. Execute order using OrderExecutorV2
        result = await order_executor_v2.execute_reverse_opening(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_opening(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="reverse",
                quantity=result.get("binance_filled_qty", 0)
            )

            # Check for single-leg trade and send alert
            if result.get("is_single_leg"):
                import datetime
                details = result.get("single_leg_details", {})
                details["timestamp"] = datetime.datetime.utcnow().isoformat()
                await send_single_leg_alert(
                    user_id=user_id,
                    strategy_type="反向套利",
                    action="开仓",
                    details=details,
                    db=db
                )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.post("/execute/forward")
async def execute_forward_arbitrage(
    request: ExecuteStrategyRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute forward arbitrage strategy (Binance long, Bybit short)"""
    try:
        # 1. Get accounts
        binance_result = await db.execute(
            select(Account).where(Account.account_id == request.binance_account_id)
        )
        binance_account = binance_result.scalar_one_or_none()

        bybit_result = await db.execute(
            select(Account).where(Account.account_id == request.bybit_account_id)
        )
        bybit_account = bybit_result.scalar_one_or_none()

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found")

        # 2. Check position limits
        strategy_id = f"{user_id}_forward"
        can_open = position_manager.check_can_open(
            strategy_id=strategy_id,
            ladder_index=request.ladder_index,
            strategy_type="forward",
            quantity=request.quantity,
            max_position=request.quantity
        )

        if not can_open:
            raise HTTPException(status_code=400, detail="Position limit exceeded for this ladder")

        # 3. Get current market prices
        # For forward opening: Binance BUY (use bid price for MAKER), Bybit SELL (market)
        from app.services.market_service import market_data_service
        market_data = await market_data_service.get_current_spread()

        binance_price = market_data.binance_quote.bid_price  # MAKER: use bid price for buy order
        bybit_price = market_data.bybit_quote.bid_price  # Market will use current bid

        # 4. Execute order using OrderExecutorV2
        result = await order_executor_v2.execute_forward_opening(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_opening(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="forward",
                quantity=result.get("binance_filled_qty", 0)
            )

            # Check for single-leg trade and send alert
            if result.get("is_single_leg"):
                import datetime
                details = result.get("single_leg_details", {})
                details["timestamp"] = datetime.datetime.utcnow().isoformat()
                await send_single_leg_alert(
                    user_id=user_id,
                    strategy_type="正向套利",
                    action="开仓",
                    details=details,
                    db=db
                )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.post("/close/reverse")
async def close_reverse_position(
    request: ClosePositionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Close reverse arbitrage position (Binance buy to close short, Bybit sell to close long)"""
    try:
        # 1. Get accounts
        binance_result = await db.execute(
            select(Account).where(Account.account_id == request.binance_account_id)
        )
        binance_account = binance_result.scalar_one_or_none()

        bybit_result = await db.execute(
            select(Account).where(Account.account_id == request.bybit_account_id)
        )
        bybit_account = bybit_result.scalar_one_or_none()

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found")

        # 2. Check if can close
        strategy_id = f"{user_id}_reverse"
        can_close = position_manager.check_can_close(
            strategy_id=strategy_id,
            ladder_index=request.ladder_index,
            strategy_type="reverse",
            quantity=request.quantity
        )

        if not can_close:
            raise HTTPException(status_code=400, detail="Insufficient position to close")

        # 3. Get current market prices
        # For reverse closing: Binance BUY (use bid price for MAKER), Bybit SELL (market)
        from app.services.market_service import market_data_service
        market_data = await market_data_service.get_current_spread()

        binance_price = market_data.binance_quote.bid_price  # MAKER: use bid price for buy order
        bybit_price = market_data.bybit_quote.bid_price  # Market will use current bid

        # 4. Execute order using OrderExecutorV2
        result = await order_executor_v2.execute_reverse_closing(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_closing(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="reverse",
                quantity=result.get("binance_filled_qty", 0)
            )

            # Check for single-leg trade and send alert
            if result.get("is_single_leg"):
                import datetime
                details = result.get("single_leg_details", {})
                details["timestamp"] = datetime.datetime.utcnow().isoformat()
                await send_single_leg_alert(
                    user_id=user_id,
                    strategy_type="反向套利",
                    action="平仓",
                    details=details,
                    db=db
                )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.post("/close/forward")
async def close_forward_position(
    request: ClosePositionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Close forward arbitrage position (Binance sell to close long, Bybit buy to close short)"""
    try:
        # 1. Get accounts
        binance_result = await db.execute(
            select(Account).where(Account.account_id == request.binance_account_id)
        )
        binance_account = binance_result.scalar_one_or_none()

        bybit_result = await db.execute(
            select(Account).where(Account.account_id == request.bybit_account_id)
        )
        bybit_account = bybit_result.scalar_one_or_none()

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found")

        # 2. Check if can close
        strategy_id = f"{user_id}_forward"
        can_close = position_manager.check_can_close(
            strategy_id=strategy_id,
            ladder_index=request.ladder_index,
            strategy_type="forward",
            quantity=request.quantity
        )

        if not can_close:
            raise HTTPException(status_code=400, detail="Insufficient position to close")

        # 3. Get current market prices
        # For forward closing: Binance SELL (use ask price for MAKER), Bybit BUY (market)
        from app.services.market_service import market_data_service
        market_data = await market_data_service.get_current_spread()

        binance_price = market_data.binance_quote.ask_price  # MAKER: use ask price for sell order
        bybit_price = market_data.bybit_quote.ask_price  # Market will use current ask

        # 4. Execute order using OrderExecutorV2
        result = await order_executor_v2.execute_forward_closing(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_closing(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="forward",
                quantity=result.get("binance_filled_qty", 0)
            )

            # Check for single-leg trade and send alert
            if result.get("is_single_leg"):
                import datetime
                details = result.get("single_leg_details", {})
                details["timestamp"] = datetime.datetime.utcnow().isoformat()
                await send_single_leg_alert(
                    user_id=user_id,
                    strategy_type="正向套利",
                    action="平仓",
                    details=details,
                    db=db
                )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


# Position management endpoints
@router.get("/positions/{strategy_id}")
async def get_strategy_positions(
    strategy_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get all positions for a strategy"""
    # Verify strategy belongs to user
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == strategy_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )

    # Convert UUID to string for position_manager
    strategy_id_str = str(strategy_id)
    positions = position_manager.get_all_positions(strategy_id_str)
    summary = position_manager.get_strategy_summary(strategy_id_str)

    return {
        "strategy_id": str(strategy_id),
        "strategy_type": config.strategy_type,
        "positions": positions,
        "summary": summary,
    }


@router.get("/positions/{strategy_id}/ladder/{ladder_index}")
async def get_ladder_position(
    strategy_id: UUID,
    ladder_index: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get position for specific ladder"""
    # Verify strategy belongs to user
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == strategy_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )

    strategy_id_str = str(strategy_id)
    position = position_manager.get_position(
        strategy_id_str, ladder_index, config.strategy_type
    )

    return position


@router.post("/positions/{strategy_id}/reset")
async def reset_strategy_positions(
    strategy_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Reset all positions for a strategy"""
    # Verify strategy belongs to user
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == strategy_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )

    strategy_id_str = str(strategy_id)
    position_manager.reset_strategy(strategy_id_str)

    return {"success": True, "message": "Positions reset successfully"}


@router.post("/positions/{strategy_id}/ladder/{ladder_index}/reset")
async def reset_ladder_position(
    strategy_id: UUID,
    ladder_index: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Reset position for specific ladder"""
    # Verify strategy belongs to user
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == strategy_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )

    strategy_id_str = str(strategy_id)
    position_manager.reset_ladder(strategy_id_str, ladder_index)

    return {"success": True, "message": "Ladder position reset successfully"}


@router.post("/positions/{strategy_id}/sync")
async def sync_positions_from_exchange(
    strategy_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Sync positions from actual exchange (Binance)"""
    # Verify strategy belongs to user
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.config_id == strategy_id,
            StrategyConfig.user_id == UUID(user_id),
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )

    # Convert UUID to string for position_manager
    strategy_id_str = str(strategy_id)

    # Sync from exchange
    sync_result = await position_manager.sync_from_exchange(
        strategy_id=strategy_id_str,
        strategy_type=config.strategy_type,
        db=db
    )

    if not sync_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sync_result.get("error", "Sync failed"),
        )

    return sync_result

