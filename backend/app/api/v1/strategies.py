"""Strategy configuration API endpoints"""
import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional, Union
from uuid import UUID
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.strategy import StrategyConfig
from app.models.account import Account

async def _resolve_pair_accounts(db, user_id, pair_code, request_binance_id=None, request_bybit_id=None):
    """Resolve A/B accounts: user_pair_accounts binding > request params > account_role fallback"""
    from sqlalchemy import text as _text
    from app.models.account import Account as _Account
    from sqlalchemy import select as _select
    from uuid import UUID as _UUID

    binance_account = None
    bybit_account = None

    # 1. Try user_pair_accounts binding
    _binding = await db.execute(_text(
        "SELECT account_a_id, account_b_id FROM user_pair_accounts WHERE user_id=:uid AND pair_code=:pc"
    ), {"uid": user_id, "pc": pair_code})
    _row = _binding.fetchone()

    if _row and _row[0]:
        _r = await db.execute(_select(_Account).where(_Account.account_id == _row[0], _Account.user_id == _UUID(user_id)))
        binance_account = _r.scalar_one_or_none()
    if _row and _row[1]:
        _r = await db.execute(_select(_Account).where(_Account.account_id == _row[1], _Account.user_id == _UUID(user_id)))
        bybit_account = _r.scalar_one_or_none()

    # 2. Fallback: use request-provided IDs
    if not binance_account and request_binance_id:
        _r = await db.execute(_select(_Account).where(_Account.account_id == request_binance_id, _Account.user_id == _UUID(user_id)))
        binance_account = _r.scalar_one_or_none()
    if not bybit_account and request_bybit_id:
        _r = await db.execute(_select(_Account).where(_Account.account_id == request_bybit_id, _Account.user_id == _UUID(user_id)))
        bybit_account = _r.scalar_one_or_none()

    # 3. Fallback: account_role
    if not binance_account:
        _r = await db.execute(_select(_Account).where(_Account.user_id == _UUID(user_id), _Account.account_role == 'primary', _Account.is_active == True))
        binance_account = _r.scalar_one_or_none()
    if not bybit_account:
        _r = await db.execute(_select(_Account).where(_Account.user_id == _UUID(user_id), _Account.account_role == 'hedge', _Account.is_active == True))
        bybit_account = _r.scalar_one_or_none()

    return binance_account, bybit_account

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

logger = logging.getLogger(__name__)
router = APIRouter()
order_executor_v2 = OrderExecutorV2()


# Request models for strategy execution
class ExecuteStrategyRequest(BaseModel):
    binance_account_id: UUID
    bybit_account_id: UUID
    quantity: float
    ladder_index: int = 0
    target_spread: float = None
    pair_code: str = "XAU"


class ClosePositionRequest(BaseModel):
    binance_account_id: UUID
    bybit_account_id: UUID
    quantity: float
    ladder_index: int = 0
    pair_code: str = "XAU"


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
            direction=direction,
            binance_filled=details.get("binance_filled", 0),
            bybit_filled=details.get("bybit_filled", 0)
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
    pair_code = getattr(config_data, 'pair_code', 'XAU') or 'XAU'
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.user_id == UUID(user_id),
            StrategyConfig.strategy_type == config_data.strategy_type,
            StrategyConfig.pair_code == pair_code,
        ).order_by(StrategyConfig.create_time.desc())
    )
    config = result.scalars().first()

    # If duplicates exist, delete them and keep only the first one
    if config:
        dup_result = await db.execute(
            select(StrategyConfig).where(
                StrategyConfig.user_id == UUID(user_id),
                StrategyConfig.strategy_type == config_data.strategy_type,
                StrategyConfig.pair_code == pair_code,
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
        config.opening_trigger_check_interval = config_data.opening_trigger_check_interval
        config.closing_trigger_check_interval = config_data.closing_trigger_check_interval
        config.ladders = ladders_data
        flag_modified(config, 'ladders')
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
            pair_code=pair_code,
            target_spread=config_data.target_spread,
            order_qty=config_data.order_qty,
            retry_times=config_data.retry_times,
            mt5_stuck_threshold=config_data.mt5_stuck_threshold,
            opening_sync_count=config_data.opening_sync_count,
            closing_sync_count=config_data.closing_sync_count,
            m_coin=m_coin,
            opening_m_coin=opening_m_coin,
            closing_m_coin=closing_m_coin,
            opening_trigger_check_interval=config_data.opening_trigger_check_interval,
            closing_trigger_check_interval=config_data.closing_trigger_check_interval,
            ladders=ladders_data,
            is_enabled=config_data.is_enabled,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)

    # Update timing_config for both opening and closing
    from app.services.timing_config_service import TimingConfigService
    from app.models.timing_config import TimingConfig

    for action in ['opening', 'closing']:
        strategy_type_name = f"{config_data.strategy_type}_{action}"
        interval = config_data.opening_trigger_check_interval if action == 'opening' else config_data.closing_trigger_check_interval

        result = await db.execute(
            select(TimingConfig).where(
                TimingConfig.config_level == 'strategy_type',
                TimingConfig.strategy_type == strategy_type_name
            )
        )
        timing_config = result.scalar_one_or_none()

        if timing_config:
            timing_config.trigger_check_interval = interval
        else:
            timing_config = TimingConfig(
                config_level='strategy_type',
                strategy_type=strategy_type_name,
                trigger_check_interval=interval
            )
            db.add(timing_config)

        await db.commit()
        await TimingConfigService._clear_cache_and_notify('strategy_type', strategy_type_name, None)

    return config


@router.get("/configs/by-type/{strategy_type}", response_model=StrategyConfigResponse)
async def get_strategy_config_by_type(
    strategy_type: str,
    pair_code: str = "XAU",
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get strategy config by type (forward/reverse) and pair_code"""
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.user_id == UUID(user_id),
            StrategyConfig.strategy_type == strategy_type,
            StrategyConfig.pair_code == pair_code,
        ).order_by(StrategyConfig.create_time.desc())
    )
    config = result.scalars().first()

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
        flag_modified(config, 'ladders')
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
        # 1. Get accounts (with user ownership check)
        binance_account, bybit_account = await _resolve_pair_accounts(
            db, user_id, request.pair_code or "XAU",
            request.binance_account_id, request.bybit_account_id
        )

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")

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
        # For reverse opening: Binance SELL (use ask+0.01 for MAKER), Bybit BUY (market)
        from app.services.market_service import market_data_service
        from app.services.hedging_pair_service import hedging_pair_service
        _pair = hedging_pair_service.get_pair(request.pair_code or "XAU")
        _sym_a = _pair.symbol_a.symbol if _pair else "XAUUSDT"
        _sym_b = _pair.symbol_b.symbol if _pair else "XAUUSD+"
        market_data = await market_data_service.get_current_spread(
            binance_symbol=_sym_a, bybit_symbol=_sym_b
        )

        binance_price = market_data.binance_quote.ask_price + 0.01  # MAKER: use ask+0.01 for sell order to ensure MAKER
        bybit_price = market_data.bybit_quote.ask_price  # Market will use current ask

        # 4. Execute order using OrderExecutorV2
        # Fetch hedge multiplier from user strategy config
        _hm_result = await db.execute(
            text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
            {"uid": user_id, "pc": request.pair_code or "XAU"}
        )
        _hm_row = _hm_result.fetchone()
        _hedge_multiplier = float(_hm_row[0]) if _hm_row and _hm_row[0] else 1.0

        result = await order_executor_v2.execute_reverse_opening(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db,
            pair_code=request.pair_code or "XAU",
            hedge_multiplier=_hedge_multiplier,
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_opening(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="reverse",
                quantity=result.get("binance_filled_qty", 0)
            )

        # 6. Check for single-leg trade and send alert (regardless of success status)
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
        # 1. Get accounts (with user ownership check)
        binance_account, bybit_account = await _resolve_pair_accounts(
            db, user_id, request.pair_code or "XAU",
            request.binance_account_id, request.bybit_account_id
        )

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")

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
        # For forward opening: Binance BUY (use bid-0.01 for MAKER), Bybit SELL (market)
        from app.services.market_service import market_data_service
        from app.services.hedging_pair_service import hedging_pair_service
        _pair = hedging_pair_service.get_pair(request.pair_code or "XAU")
        _sym_a = _pair.symbol_a.symbol if _pair else "XAUUSDT"
        _sym_b = _pair.symbol_b.symbol if _pair else "XAUUSD+"
        market_data = await market_data_service.get_current_spread(
            binance_symbol=_sym_a, bybit_symbol=_sym_b
        )

        binance_price = market_data.binance_quote.bid_price - 0.01  # MAKER: use bid-0.01 for buy order to ensure MAKER
        bybit_price = market_data.bybit_quote.bid_price  # Market will use current bid

        # 4. Execute order using OrderExecutorV2
        # Fetch hedge multiplier from user strategy config
        _hm_result = await db.execute(
            text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
            {"uid": user_id, "pc": request.pair_code or "XAU"}
        )
        _hm_row = _hm_result.fetchone()
        _hedge_multiplier = float(_hm_row[0]) if _hm_row and _hm_row[0] else 1.0

        result = await order_executor_v2.execute_forward_opening(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db,
            pair_code=request.pair_code or "XAU",
            hedge_multiplier=_hedge_multiplier,
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_opening(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="forward",
                quantity=result.get("binance_filled_qty", 0)
            )

        # 6. Check for single-leg trade and send alert (regardless of success status)
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
        # 1. Get accounts (with user ownership check)
        binance_account, bybit_account = await _resolve_pair_accounts(
            db, user_id, request.pair_code or "XAU",
            request.binance_account_id, request.bybit_account_id
        )

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")

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
        # For reverse closing: Binance BUY (use bid-0.01 for MAKER), Bybit SELL (market)
        from app.services.market_service import market_data_service
        from app.services.hedging_pair_service import hedging_pair_service
        _pair = hedging_pair_service.get_pair(request.pair_code or "XAU")
        _sym_a = _pair.symbol_a.symbol if _pair else "XAUUSDT"
        _sym_b = _pair.symbol_b.symbol if _pair else "XAUUSD+"
        market_data = await market_data_service.get_current_spread(
            binance_symbol=_sym_a, bybit_symbol=_sym_b
        )

        binance_price = market_data.binance_quote.bid_price - 0.01  # MAKER: use bid-0.01 for buy order to ensure MAKER
        bybit_price = market_data.bybit_quote.bid_price  # Market will use current bid

        # 4. Execute order using OrderExecutorV2
        # Fetch hedge multiplier from user strategy config
        _hm_result = await db.execute(
            text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
            {"uid": user_id, "pc": request.pair_code or "XAU"}
        )
        _hm_row = _hm_result.fetchone()
        _hedge_multiplier = float(_hm_row[0]) if _hm_row and _hm_row[0] else 1.0

        result = await order_executor_v2.execute_reverse_closing(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db,
            pair_code=request.pair_code or "XAU",
            hedge_multiplier=_hedge_multiplier,
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_closing(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="reverse",
                quantity=result.get("binance_filled_qty", 0)
            )

        # 6. Check for single-leg trade and send alert (regardless of success status)
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
        # 1. Get accounts (with user ownership check)
        binance_account, bybit_account = await _resolve_pair_accounts(
            db, user_id, request.pair_code or "XAU",
            request.binance_account_id, request.bybit_account_id
        )

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")

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
        # For forward closing: Binance SELL (use ask+0.01 for MAKER), Bybit BUY (market)
        from app.services.market_service import market_data_service
        from app.services.hedging_pair_service import hedging_pair_service
        _pair = hedging_pair_service.get_pair(request.pair_code or "XAU")
        _sym_a = _pair.symbol_a.symbol if _pair else "XAUUSDT"
        _sym_b = _pair.symbol_b.symbol if _pair else "XAUUSD+"
        market_data = await market_data_service.get_current_spread(
            binance_symbol=_sym_a, bybit_symbol=_sym_b
        )

        binance_price = market_data.binance_quote.ask_price + 0.01  # MAKER: use ask+0.01 for sell order to ensure MAKER
        bybit_price = market_data.bybit_quote.ask_price  # Market will use current ask

        # 4. Execute order using OrderExecutorV2
        # Fetch hedge multiplier from user strategy config
        _hm_result = await db.execute(
            text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
            {"uid": user_id, "pc": request.pair_code or "XAU"}
        )
        _hm_row = _hm_result.fetchone()
        _hedge_multiplier = float(_hm_row[0]) if _hm_row and _hm_row[0] else 1.0

        result = await order_executor_v2.execute_forward_closing(
            binance_account=binance_account,
            bybit_account=bybit_account,
            quantity=request.quantity,
            binance_price=binance_price,
            bybit_price=bybit_price,
            db=db,
            pair_code=request.pair_code or "XAU",
            hedge_multiplier=_hedge_multiplier,
        )

        # 5. Record position if successful
        if result.get("success"):
            position_manager.record_closing(
                strategy_id=strategy_id,
                ladder_index=request.ladder_index,
                strategy_type="forward",
                quantity=result.get("binance_filled_qty", 0)
            )

        # 6. Check for single-leg trade and send alert (regardless of success status)
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



# ============================================================================
# Continuous Execution Endpoints
# ============================================================================

class LadderConfigSchema(BaseModel):
    """Ladder configuration schema for opening strategies"""
    enabled: bool
    opening_spread: float
    closing_spread: float
    total_qty: float
    opening_trigger_count: int
    closing_trigger_count: int


class ClosingLadderConfigSchema(BaseModel):
    """Ladder configuration schema for closing strategies"""
    enabled: bool
    closing_spread: float
    total_qty: float
    closing_trigger_count: int


class ContinuousExecuteRequest(BaseModel):
    """Request schema for continuous opening execution"""
    binance_account_id: UUID
    bybit_account_id: UUID
    pair_code: str = "XAU"
    opening_m_coin: float
    closing_m_coin: float
    trigger_check_interval: float = Field(default=0.05, ge=0.01, le=1.0)  # 10ms to 1000ms
    ladders: List[LadderConfigSchema]


class ContinuousClosingRequest(BaseModel):
    """Request schema for continuous closing execution"""
    binance_account_id: UUID
    bybit_account_id: UUID
    pair_code: str = "XAU"
    closing_m_coin: float
    trigger_check_interval: float = Field(default=0.05, ge=0.01, le=1.0)  # 10ms to 1000ms
    ladders: List[ClosingLadderConfigSchema]


@router.post("/execute/{strategy_type}/continuous")
async def execute_continuous_opening(
    strategy_type: str,
    request: ContinuousExecuteRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute arbitrage strategy opening with continuous execution

    Args:
        strategy_type: 'forward' or 'reverse'
    """
    # Write to a debug file to confirm API is called
    import datetime
    with open("api_debug.log", "a") as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"[{datetime.datetime.now()}] API CALLED: /execute/{strategy_type}/continuous\n")
        f.write(f"User ID: {user_id}\n")
        f.write(f"Request: {request.dict()}\n")
        f.write(f"{'='*80}\n")

    import logging
    logger = logging.getLogger(__name__)

    logger.error("=" * 80)
    logger.error(f"API ENDPOINT CALLED: /execute/{strategy_type}/continuous")
    logger.error(f"User ID: {user_id}")
    logger.error(f"Request data: {request.dict()}")
    logger.error("=" * 80)

    from app.services.continuous_executor import ContinuousStrategyExecutor, LadderConfig
    from app.services.execution_task_manager import execution_task_manager

    # Validate strategy type
    if strategy_type not in ['forward', 'reverse']:
        raise HTTPException(status_code=400, detail="Invalid strategy type. Must be 'forward' or 'reverse'")

    try:
        # 1. Get accounts (with user ownership check)
        binance_account, bybit_account = await _resolve_pair_accounts(
            db, user_id, request.pair_code or "XAU",
            request.binance_account_id, request.bybit_account_id
        )

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")

        # 2. Convert ladder schemas to LadderConfig objects
        ladders = [
            LadderConfig(
                enabled=ladder.enabled,
                opening_spread=ladder.opening_spread,
                closing_spread=ladder.closing_spread,
                total_qty=ladder.total_qty,
                opening_trigger_count=ladder.opening_trigger_count,
                closing_trigger_count=ladder.closing_trigger_count
            )
            for ladder in request.ladders
        ]

        # 2.5. Get timing configuration for this strategy type
        from app.services.timing_config_service import TimingConfigService
        strategy_type_name = f"{strategy_type}_opening"
        timing_config = await TimingConfigService.get_effective_config(
            db=db,
            strategy_type=strategy_type_name
        )
        api_spam_prevention_delay = timing_config.get('api_spam_prevention_delay', 3.0)
        trigger_check_interval = request.trigger_check_interval  # Use user-configured value from panel
        delayed_single_leg_check_delay = timing_config.get('delayed_single_leg_check_delay', 10.0)
        delayed_single_leg_second_check_delay = timing_config.get('delayed_single_leg_second_check_delay', 1.0)
        binance_timeout = timing_config.get('binance_timeout', 2.0)
        bybit_timeout = timing_config.get('bybit_timeout', 0.1)
        order_check_interval = timing_config.get('order_check_interval', 0.2)
        spread_check_interval = timing_config.get('spread_check_interval', 2.0)
        mt5_deal_sync_wait = timing_config.get('mt5_deal_sync_wait', 3.0)
        api_retry_times = timing_config.get('api_retry_times', 1)
        api_retry_delay = timing_config.get('api_retry_delay', 0.5)
        max_binance_limit_retries = timing_config.get('max_binance_limit_retries', 25)
        open_wait_after_cancel_no_trade = timing_config.get('open_wait_after_cancel_no_trade', 1.0)
        open_wait_after_cancel_part = timing_config.get('open_wait_after_cancel_part', 2.0)

        # 动态更新OrderExecutorV2的timing参数
        order_executor_v2.binance_timeout = binance_timeout
        order_executor_v2.bybit_timeout = bybit_timeout
        order_executor_v2.max_retries = api_retry_times
        order_executor_v2.order_check_interval = order_check_interval
        order_executor_v2.spread_check_interval = spread_check_interval
        order_executor_v2.mt5_deal_sync_wait = mt5_deal_sync_wait
        order_executor_v2.api_retry_delay = api_retry_delay
        order_executor_v2.max_binance_limit_retries = max_binance_limit_retries
        order_executor_v2.open_wait_after_cancel_no_trade = open_wait_after_cancel_no_trade
        order_executor_v2.open_wait_after_cancel_part = open_wait_after_cancel_part

        logger.info(f"Using timing config for {strategy_type_name}: binance_timeout={binance_timeout}, bybit_timeout={bybit_timeout}, trigger_check_interval={trigger_check_interval}, api_spam_prevention_delay={api_spam_prevention_delay}, mt5_deal_sync_wait={mt5_deal_sync_wait}, api_retry_times={api_retry_times}")

        # 3. Create continuous executor
        pair_code = request.pair_code or "XAU"
        strategy_id = f"{user_id}_{pair_code}_{strategy_type}_opening_continuous"
        # Reset position tracker for this strategy before each new execution
        from app.services.position_manager import position_manager
        position_manager.reset_strategy(strategy_id)
        # ── Safety guard: seed position_manager with actual Binance position ──
        # Prevents double-opening after Python crash/restart (position_manager is in-memory only)
        try:
            from app.services.hedging_pair_service import hedging_pair_service as _hps_guard
            from app.services.binance_client import BinanceFuturesClient as _BFC_guard
            from app.core.proxy_utils import build_proxy_url as _bpu
            _guard_pair = _hps_guard.get_pair(pair_code)
            _guard_sym_a = _guard_pair.symbol_a.symbol if _guard_pair else "XAUUSDT"
            _guard_client = _BFC_guard(binance_account.api_key, binance_account.api_secret,
                                       proxy_url=_bpu(binance_account.proxy_config))
            _guard_positions = await _guard_client.get_position_risk(symbol=_guard_sym_a)
            await _guard_client.close()
            _target_side = "SHORT" if strategy_type == "reverse" else "LONG"
            _existing_qty = sum(
                abs(float(p.get("positionAmt", 0)))
                for p in _guard_positions
                if p.get("positionSide", "") == _target_side and float(p.get("positionAmt", 0)) != 0
            )
            if _existing_qty > 0:
                _first_ladder_idx = next((i for i, l in enumerate(ladders) if l.enabled), 0)
                _ladder_total = ladders[_first_ladder_idx].total_qty if ladders else _existing_qty
                _seed_qty = min(_existing_qty, _ladder_total)
                position_manager.record_opening(strategy_id, _first_ladder_idx,
                                                f"{strategy_type}_opening", _seed_qty)
                logger.warning(
                    f"[POSITION_GUARD] Pre-seeded {_seed_qty}/{_ladder_total} XAU "
                    f"({_target_side}) from existing Binance position (pair={pair_code})"
                )
        except Exception as _guard_err:
            logger.warning(f"[POSITION_GUARD] Position check skipped: {_guard_err}")

        # Fetch hedge_multiplier for this user and pair
        _hm_res = await db.execute(
            text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
            {"uid": user_id, "pc": pair_code}
        )
        _hm_row = _hm_res.fetchone()
        _hedge_multiplier = float(_hm_row[0]) if _hm_row and _hm_row[0] else 1.0

        executor = ContinuousStrategyExecutor(
            strategy_id=strategy_id,
            pair_code=pair_code,
            order_executor=order_executor_v2,
            hedge_multiplier=_hedge_multiplier,
            trigger_check_interval=trigger_check_interval,
            api_spam_prevention_delay=api_spam_prevention_delay,
            delayed_single_leg_check_delay=delayed_single_leg_check_delay,
            delayed_single_leg_second_check_delay=delayed_single_leg_second_check_delay
        )

        # 4. Start continuous execution in background based on strategy type
        if strategy_type == 'reverse':
            coro = executor.execute_reverse_opening_continuous(
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                opening_m_coin=request.opening_m_coin,
                user_id=user_id
            )
        else:  # forward
            coro = executor.execute_forward_opening_continuous(
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                opening_m_coin=request.opening_m_coin,
                user_id=user_id
            )

        task_id = execution_task_manager.start_task(executor, coro)

        # Write debug info
        with open("api_debug.log", "a") as f:
            f.write(f"[{datetime.datetime.now()}] Task created: {task_id}\n")
            f.write(f"Executor is_running: {executor.is_running}\n")
            f.write(f"Coroutine: {coro}\n\n")

        return {
            "success": True,
            "task_id": task_id,
            "message": "Continuous execution started",
            "strategy_id": strategy_id
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start continuous execution: {str(e)}"
        )


@router.post("/close/{strategy_type}/continuous")
async def execute_continuous_closing(
    strategy_type: str,
    request: ContinuousClosingRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute arbitrage strategy closing with continuous execution

    Args:
        strategy_type: 'forward' or 'reverse'
    """
    from app.services.continuous_executor import ContinuousStrategyExecutor, LadderConfig
    from app.services.execution_task_manager import execution_task_manager

    # Validate strategy type
    if strategy_type not in ['forward', 'reverse']:
        raise HTTPException(status_code=400, detail="Invalid strategy type. Must be 'forward' or 'reverse'")

    try:
        # 1. Get accounts (with user ownership check)
        binance_account, bybit_account = await _resolve_pair_accounts(
            db, user_id, request.pair_code or "XAU",
            request.binance_account_id, request.bybit_account_id
        )

        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")

        # 2. Convert ladder schemas to LadderConfig objects
        # For closing, we don't need opening_spread and opening_trigger_count
        ladders = [
            LadderConfig(
                enabled=ladder.enabled,
                opening_spread=0.0,  # Not used for closing
                closing_spread=ladder.closing_spread,
                total_qty=ladder.total_qty,
                opening_trigger_count=1,  # Not used for closing
                closing_trigger_count=ladder.closing_trigger_count
            )
            for ladder in request.ladders
        ]

        # 2.5. Get timing configuration for this strategy type
        from app.services.timing_config_service import TimingConfigService
        strategy_type_name = f"{strategy_type}_closing"
        timing_config = await TimingConfigService.get_effective_config(
            db=db,
            strategy_type=strategy_type_name
        )
        api_spam_prevention_delay = timing_config.get('api_spam_prevention_delay', 3.0)
        trigger_check_interval = request.trigger_check_interval  # Use user-configured value from panel
        delayed_single_leg_check_delay = timing_config.get('delayed_single_leg_check_delay', 10.0)
        delayed_single_leg_second_check_delay = timing_config.get('delayed_single_leg_second_check_delay', 1.0)
        binance_timeout = timing_config.get('binance_timeout', 2.0)
        bybit_timeout = timing_config.get('bybit_timeout', 0.1)
        order_check_interval = timing_config.get('order_check_interval', 0.2)
        spread_check_interval = timing_config.get('spread_check_interval', 2.0)
        mt5_deal_sync_wait = timing_config.get('mt5_deal_sync_wait', 3.0)
        api_retry_times = timing_config.get('api_retry_times', 1)
        api_retry_delay = timing_config.get('api_retry_delay', 0.5)
        max_binance_limit_retries = timing_config.get('max_binance_limit_retries', 25)
        close_wait_after_cancel_no_trade = timing_config.get('close_wait_after_cancel_no_trade', 1.0)
        close_wait_after_cancel_part = timing_config.get('close_wait_after_cancel_part', 2.0)

        # 动态更新OrderExecutorV2的timing参数
        order_executor_v2.binance_timeout = binance_timeout
        order_executor_v2.bybit_timeout = bybit_timeout
        order_executor_v2.max_retries = api_retry_times
        order_executor_v2.order_check_interval = order_check_interval
        order_executor_v2.spread_check_interval = spread_check_interval
        order_executor_v2.mt5_deal_sync_wait = mt5_deal_sync_wait
        order_executor_v2.api_retry_delay = api_retry_delay
        order_executor_v2.max_binance_limit_retries = max_binance_limit_retries
        order_executor_v2.close_wait_after_cancel_no_trade = close_wait_after_cancel_no_trade
        order_executor_v2.close_wait_after_cancel_part = close_wait_after_cancel_part

        logger.info(f"Using timing config for {strategy_type_name}: binance_timeout={binance_timeout}, bybit_timeout={bybit_timeout}, trigger_check_interval={trigger_check_interval}, api_spam_prevention_delay={api_spam_prevention_delay}, mt5_deal_sync_wait={mt5_deal_sync_wait}, api_retry_times={api_retry_times}")

        # 3. Create continuous executor
        pair_code = request.pair_code or "XAU"
        strategy_id = f"{user_id}_{pair_code}_{strategy_type}_closing_continuous"
        # Reset position tracker for this strategy before each new execution
        from app.services.position_manager import position_manager
        position_manager.reset_strategy(strategy_id)
        # ── Safety guard: seed position_manager with actual Binance position ──
        # Prevents double-opening after Python crash/restart (position_manager is in-memory only)
        try:
            from app.services.hedging_pair_service import hedging_pair_service as _hps_guard
            from app.services.binance_client import BinanceFuturesClient as _BFC_guard
            from app.core.proxy_utils import build_proxy_url as _bpu
            _guard_pair = _hps_guard.get_pair(pair_code)
            _guard_sym_a = _guard_pair.symbol_a.symbol if _guard_pair else "XAUUSDT"
            _guard_client = _BFC_guard(binance_account.api_key, binance_account.api_secret,
                                       proxy_url=_bpu(binance_account.proxy_config))
            _guard_positions = await _guard_client.get_position_risk(symbol=_guard_sym_a)
            await _guard_client.close()
            _target_side = "SHORT" if strategy_type == "reverse" else "LONG"
            _existing_qty = sum(
                abs(float(p.get("positionAmt", 0)))
                for p in _guard_positions
                if p.get("positionSide", "") == _target_side and float(p.get("positionAmt", 0)) != 0
            )
            if _existing_qty > 0:
                _first_ladder_idx = next((i for i, l in enumerate(ladders) if l.enabled), 0)
                _ladder_total = ladders[_first_ladder_idx].total_qty if ladders else _existing_qty
                _seed_qty = min(_existing_qty, _ladder_total)
                position_manager.record_opening(strategy_id, _first_ladder_idx,
                                                f"{strategy_type}_opening", _seed_qty)
                logger.warning(
                    f"[POSITION_GUARD] Pre-seeded {_seed_qty}/{_ladder_total} XAU "
                    f"({_target_side}) from existing Binance position (pair={pair_code})"
                )
        except Exception as _guard_err:
            logger.warning(f"[POSITION_GUARD] Position check skipped: {_guard_err}")

        # Fetch hedge_multiplier for this user and pair
        _hm_res = await db.execute(
            text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
            {"uid": user_id, "pc": pair_code}
        )
        _hm_row = _hm_res.fetchone()
        _hedge_multiplier = float(_hm_row[0]) if _hm_row and _hm_row[0] else 1.0

        executor = ContinuousStrategyExecutor(
            strategy_id=strategy_id,
            pair_code=pair_code,
            order_executor=order_executor_v2,
            hedge_multiplier=_hedge_multiplier,
            trigger_check_interval=trigger_check_interval,
            api_spam_prevention_delay=api_spam_prevention_delay,
            delayed_single_leg_check_delay=delayed_single_leg_check_delay,
            delayed_single_leg_second_check_delay=delayed_single_leg_second_check_delay
        )

        # 4. Start continuous execution in background based on strategy type
        if strategy_type == 'reverse':
            coro = executor.execute_reverse_closing_continuous(
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                closing_m_coin=request.closing_m_coin,
                user_id=user_id
            )
        else:  # forward
            coro = executor.execute_forward_closing_continuous(
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                closing_m_coin=request.closing_m_coin,
                user_id=user_id
            )

        task_id = execution_task_manager.start_task(executor, coro)

        # Write debug info
        with open("api_debug.log", "a") as f:
            f.write(f"[{datetime.datetime.now()}] Task created: {task_id}\n")
            f.write(f"Executor is_running: {executor.is_running}\n")
            f.write(f"Coroutine: {coro}\n\n")

        return {
            "success": True,
            "task_id": task_id,
            "message": "Continuous execution started",
            "strategy_id": strategy_id
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start continuous execution: {str(e)}"
        )


@router.get("/execution/{task_id}/status")
async def get_execution_status(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get status of continuous execution task"""
    from app.services.execution_task_manager import execution_task_manager

    task_status = execution_task_manager.get_status(task_id)

    if not task_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    return {
        "success": True,
        "task": task_status
    }


@router.post("/execution/{task_id}/stop")
async def stop_execution(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Stop continuous execution task"""
    from app.services.execution_task_manager import execution_task_manager

    stopped = await execution_task_manager.stop_task(task_id)

    if not stopped:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    return {
        "success": True,
        "message": "Execution stopped",
        "task_id": task_id
    }


@router.get("/execution/tasks")
async def get_all_execution_tasks(
    user_id: str = Depends(get_current_user_id),
):
    """Get all execution tasks"""
    from app.services.execution_task_manager import execution_task_manager

    tasks = execution_task_manager.get_all_tasks()

    return {
        "success": True,
        "tasks": tasks
    }
