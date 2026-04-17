"""Trading history API endpoints"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime, date, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from app.core.security import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.order import OrderRecord
from app.models.account import Account
# Order executor service removed - manual trading disabled
# from app.services.order_executor import order_executor
from app.services.market_service import market_data_service
from app.core.proxy_utils import build_proxy_url
import asyncio
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
import logging
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_pair_symbols():
    """Get symbol names from hedging pair config, with fallback"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair("XAU")
        if pair:
            return pair.symbol_a.symbol, pair.symbol_b.symbol
    except Exception:
        pass
    return "XAUUSDT", "XAUUSD+"


def _build_stats(orders, accounts_map, enable_logging=True):
    """Build stats dict from a list of OrderRecord

    Args:
        orders: List of OrderRecord objects
        accounts_map: Dict mapping account_id to Account objects
        enable_logging: Whether to log detailed PnL calculation process

    Returns:
        Tuple of (stats_dict, account_trades, mt5_trades)
    """
    # Separate totals for Binance and MT5
    binance_volume = 0
    binance_amount = 0.0
    binance_buy_sell_amount = 0.0  # manual + strategy
    binance_task_amount = 0.0      # sync
    binance_fees = 0.0
    binance_realized_pnl = 0.0     # Realized profit/loss

    mt5_volume = 0
    mt5_amount = 0.0
    mt5_fees = 0.0
    mt5_realized_pnl = 0.0

    account_trades = []
    mt5_trades = []

    # Track positions for PnL calculation (支持做多和做空)
    # position structure: {qty: float, cost: float}
    # qty > 0: long position (做多), qty < 0: short position (做空)
    binance_positions = {}  # symbol -> {qty, cost}
    mt5_positions = {}

    # Valid order types for trading (exclude transfers and other non-trade types)
    valid_order_types = ['limit', 'market', 'stop', 'stop_limit', 'take_profit', 'take_profit_limit']

    # Exclude transfer-related order types and sides
    excluded_types = ['transfer', 'deposit', 'withdrawal', 'internal_transfer', 'funding', 'rebate']
    excluded_sides = ['transfer', 'deposit', 'withdrawal', 'funding']

    if enable_logging:
        logger.info(f"开始计算统计数据，共 {len(orders)} 笔订单")

    for order in orders:
        # Skip non-trade orders (transfers, deposits, withdrawals, etc.)
        if order.order_type and order.order_type.lower() not in valid_order_types:
            continue

        # Skip if order_type is explicitly a transfer type
        if order.order_type and order.order_type.lower() in excluded_types:
            continue

        # Skip if order_side indicates a transfer
        if order.order_side and order.order_side.lower() in excluded_sides:
            continue

        # Skip orders with zero quantity (likely system records)
        qty = order.filled_qty if order.filled_qty else order.qty
        if not qty or qty <= 0:
            continue

        acc = accounts_map.get(order.account_id)
        if not acc:
            continue

        # Explicitly check platform: 1=Binance, 2=Bybit
        is_binance = (acc.platform_id == 1)
        is_mt5 = (acc.platform_id == 2 and acc.is_mt5_account)

        # Skip if not Binance or MT5 (safety check)
        if not is_binance and not is_mt5:
            continue

        # Platform-specific symbol filtering
        _sym_a, _sym_b = _get_pair_symbols()
        if is_binance:
            if not order.symbol or order.symbol.upper() != _sym_a:
                continue
        elif is_mt5:
            if not order.symbol or order.symbol != _sym_b:
                continue

        amount = qty * (order.price or 0)

        # Skip orders with zero price (likely transfers or invalid records)
        if not order.price or order.price <= 0:
            continue

        # Use actual fee from database if available, otherwise estimate
        # Check if fee exists and is a valid positive number
        if order.fee is not None and order.fee > 0:
            fee = float(order.fee)
        else:
            # Estimate fees based on platform and order type
            if is_binance:
                # Binance XAUUSDT Perpetual Futures fees (VIP 0)
                # Maker: 0.02% (0.0002), Taker: 0.04% (0.0004)
                # Assume Maker for limit orders, Taker for market orders
                if order.order_type and order.order_type.lower() == 'limit':
                    # Limit orders are typically Maker (0.02%)
                    fee = amount * 0.0002
                else:
                    # Market orders are Taker (0.04%)
                    fee = amount * 0.0004
            else:
                # Bybit MT5 ~0.01% estimate
                fee = amount * 0.0001

        # Determine if this is a buy or sell order
        is_buy = order.order_side.lower() == 'buy'
        is_sell = order.order_side.lower() == 'sell'

        # Accumulate separately for each platform
        if is_mt5:
            mt5_volume += qty
            mt5_amount += amount
            mt5_fees += fee

            # Calculate MT5 realized PnL using FIFO method (支持做多和做空)
            symbol_key = order.symbol
            if symbol_key not in mt5_positions:
                mt5_positions[symbol_key] = {'qty': 0, 'cost': 0}

            position = mt5_positions[symbol_key]
            old_qty = position['qty']
            old_cost = position['cost']

            if is_buy:
                if position['qty'] >= 0:
                    # 做多：买入增加仓位
                    position['cost'] += amount
                    position['qty'] += qty
                    if enable_logging:
                        logger.info(f"[MT5] 做多买入 {order.symbol}: qty={qty}, price={order.price}, "
                                  f"仓位 {old_qty:.4f} -> {position['qty']:.4f}")
                else:
                    # 做空平仓：买入平掉空头仓位
                    close_qty = min(qty, abs(position['qty']))
                    avg_cost_price = abs(position['cost'] / position['qty']) if position['qty'] != 0 else 0
                    # 做空盈亏 = (开仓价 - 平仓价) × 数量 - 手续费
                    realized_pnl = (avg_cost_price - order.price) * close_qty - fee
                    mt5_realized_pnl += realized_pnl

                    if enable_logging:
                        logger.info(f"[MT5] 做空平仓 {order.symbol}: 平仓qty={close_qty}, 开仓均价={avg_cost_price:.2f}, "
                                  f"平仓价={order.price}, 盈亏={realized_pnl:.2f} USDT, "
                                  f"仓位 {old_qty:.4f} -> {position['qty'] + close_qty:.4f}")

                    # Update position
                    position['cost'] += avg_cost_price * close_qty
                    position['qty'] += close_qty

                    # 如果买入数量大于空头仓位，剩余部分转为做多
                    if qty > close_qty:
                        remaining_qty = qty - close_qty
                        position['cost'] += remaining_qty * order.price
                        position['qty'] += remaining_qty
                        if enable_logging:
                            logger.info(f"[MT5] 空头平仓后转做多 {order.symbol}: 剩余qty={remaining_qty}, "
                                      f"仓位 -> {position['qty']:.4f}")

            else:  # sell
                if position['qty'] <= 0:
                    # 做空：卖出增加空头仓位
                    position['cost'] -= amount
                    position['qty'] -= qty
                    if enable_logging:
                        logger.info(f"[MT5] 做空卖出 {order.symbol}: qty={qty}, price={order.price}, "
                                  f"仓位 {old_qty:.4f} -> {position['qty']:.4f}")
                else:
                    # 做多平仓：卖出平掉多头仓位
                    close_qty = min(qty, position['qty'])
                    avg_cost_price = position['cost'] / position['qty'] if position['qty'] > 0 else 0
                    # 做多盈亏 = (平仓价 - 开仓价) × 数量 - 手续费
                    realized_pnl = (order.price - avg_cost_price) * close_qty - fee
                    mt5_realized_pnl += realized_pnl

                    if enable_logging:
                        logger.info(f"[MT5] 做多平仓 {order.symbol}: 平仓qty={close_qty}, 开仓均价={avg_cost_price:.2f}, "
                                  f"平仓价={order.price}, 盈亏={realized_pnl:.2f} USDT, "
                                  f"仓位 {old_qty:.4f} -> {position['qty'] - close_qty:.4f}")

                    # Update position
                    position['cost'] -= avg_cost_price * close_qty
                    position['qty'] -= close_qty

                    # 如果卖出数量大于多头仓位，剩余部分转为做空
                    if qty > close_qty:
                        remaining_qty = qty - close_qty
                        position['cost'] -= remaining_qty * order.price
                        position['qty'] -= remaining_qty
                        if enable_logging:
                            logger.info(f"[MT5] 多头平仓后转做空 {order.symbol}: 剩余qty={remaining_qty}, "
                                      f"仓位 -> {position['qty']:.4f}")

        elif is_binance:
            binance_volume += qty
            binance_amount += amount
            binance_fees += fee

            # Separate buy/sell from task amounts based on source
            if order.source in ['manual', 'strategy']:
                binance_buy_sell_amount += amount
            elif order.source == 'sync':
                binance_task_amount += amount

            # Calculate Binance realized PnL using FIFO method (支持做多和做空)
            symbol_key = order.symbol
            if symbol_key not in binance_positions:
                binance_positions[symbol_key] = {'qty': 0, 'cost': 0}

            position = binance_positions[symbol_key]
            old_qty = position['qty']
            old_cost = position['cost']

            if is_buy:
                if position['qty'] >= 0:
                    # 做多：买入增加仓位
                    position['cost'] += amount
                    position['qty'] += qty
                    if enable_logging:
                        logger.info(f"[Binance] 做多买入 {order.symbol}: qty={qty}, price={order.price}, "
                                  f"仓位 {old_qty:.4f} -> {position['qty']:.4f}")
                else:
                    # 做空平仓：买入平掉空头仓位
                    close_qty = min(qty, abs(position['qty']))
                    avg_cost_price = abs(position['cost'] / position['qty']) if position['qty'] != 0 else 0
                    # 做空盈亏 = (开仓价 - 平仓价) × 数量 - 手续费
                    realized_pnl = (avg_cost_price - order.price) * close_qty - fee
                    binance_realized_pnl += realized_pnl

                    if enable_logging:
                        logger.info(f"[Binance] 做空平仓 {order.symbol}: 平仓qty={close_qty}, 开仓均价={avg_cost_price:.2f}, "
                                  f"平仓价={order.price}, 盈亏={realized_pnl:.2f} USDT, "
                                  f"仓位 {old_qty:.4f} -> {position['qty'] + close_qty:.4f}")

                    # Update position
                    position['cost'] += avg_cost_price * close_qty
                    position['qty'] += close_qty

                    # 如果买入数量大于空头仓位，剩余部分转为做多
                    if qty > close_qty:
                        remaining_qty = qty - close_qty
                        position['cost'] += remaining_qty * order.price
                        position['qty'] += remaining_qty
                        if enable_logging:
                            logger.info(f"[Binance] 空头平仓后转做多 {order.symbol}: 剩余qty={remaining_qty}, "
                                      f"仓位 -> {position['qty']:.4f}")

            else:  # sell
                if position['qty'] <= 0:
                    # 做空：卖出增加空头仓位
                    position['cost'] -= amount
                    position['qty'] -= qty
                    if enable_logging:
                        logger.info(f"[Binance] 做空卖出 {order.symbol}: qty={qty}, price={order.price}, "
                                  f"仓位 {old_qty:.4f} -> {position['qty']:.4f}")
                else:
                    # 做多平仓：卖出平掉多头仓位
                    close_qty = min(qty, position['qty'])
                    avg_cost_price = position['cost'] / position['qty'] if position['qty'] > 0 else 0
                    # 做多盈亏 = (平仓价 - 开仓价) × 数量 - 手续费
                    realized_pnl = (order.price - avg_cost_price) * close_qty - fee
                    binance_realized_pnl += realized_pnl

                    if enable_logging:
                        logger.info(f"[Binance] 做多平仓 {order.symbol}: 平仓qty={close_qty}, 开仓均价={avg_cost_price:.2f}, "
                                  f"平仓价={order.price}, 盈亏={realized_pnl:.2f} USDT, "
                                  f"仓位 {old_qty:.4f} -> {position['qty'] - close_qty:.4f}")

                    # Update position
                    position['cost'] -= avg_cost_price * close_qty
                    position['qty'] -= close_qty

                    # 如果卖出数量大于多头仓位，剩余部分转为做空
                    if qty > close_qty:
                        remaining_qty = qty - close_qty
                        position['cost'] -= remaining_qty * order.price
                        position['qty'] -= remaining_qty
                        if enable_logging:
                            logger.info(f"[Binance] 多头平仓后转做空 {order.symbol}: 剩余qty={remaining_qty}, "
                                      f"仓位 -> {position['qty']:.4f}")

        trade = {
            "id": str(order.order_id),
            "timestamp": order.create_time.isoformat() if order.create_time else None,
            "symbol": order.symbol,
            "side": order.order_side,
            "quantity": qty,
            "price": order.price or 0,
            "fee": fee,
            "status": order.status,
            "account_name": acc.account_name,
            "platform": "对冲账户" if is_mt5 else "主账号",
        }
        if is_mt5:
            mt5_trades.append(trade)
        elif is_binance:
            account_trades.append(trade)

    binance_return = binance_amount * 0.001  # simplified estimate
    mt5_return = mt5_amount * 0.001

    if enable_logging:
        logger.info(f"统计计算完成:")
        logger.info(f"  [Binance] 总交易量={binance_volume:.4f}, 总金额={binance_amount:.2f} USDT, "
                   f"手续费={binance_fees:.2f} USDT, 已实现盈亏={binance_realized_pnl:.2f} USDT")
        logger.info(f"  [MT5] 总交易量={mt5_volume:.4f}, 总金额={mt5_amount:.2f} USDT, "
                   f"手续费={mt5_fees:.2f} USDT, 已实现盈亏={mt5_realized_pnl:.2f} USDT")

        # Log remaining positions
        for symbol, pos in binance_positions.items():
            if abs(pos['qty']) > 0.0001:
                position_type = "做多" if pos['qty'] > 0 else "做空"
                logger.info(f"  [Binance] {symbol} 剩余{position_type}仓位: {abs(pos['qty']):.4f}, "
                           f"成本: {abs(pos['cost']):.2f} USDT")

        for symbol, pos in mt5_positions.items():
            if abs(pos['qty']) > 0.0001:
                position_type = "做多" if pos['qty'] > 0 else "做空"
                logger.info(f"  [MT5] {symbol} 剩余{position_type}仓位: {abs(pos['qty']):.4f}, "
                           f"成本: {abs(pos['cost']):.2f} USDT")

    stats = {
        # Binance statistics
        "totalVolume": round(binance_volume, 4),
        "totalAmount": round(binance_amount, 2),
        "buySellAmount": round(binance_buy_sell_amount, 2),
        "taskAmount": round(binance_task_amount, 2),
        "totalFees": round(binance_fees, 2),
        "realizedPnL": round(binance_realized_pnl, 2),  # 已实现盈亏
        "overnightFees": 0.0,
        # MT5 statistics
        "marketFundingRate": 0.0,
        "mt5OvernightFee": 0.0,
        "marketFee": round(binance_fees, 2),
        "mt5Fee": round(mt5_fees, 2),
        "mt5RealizedPnL": round(mt5_realized_pnl, 2),  # MT5已实现盈亏
        "peRatio": round((binance_return / binance_amount * 100) if binance_amount else 0, 2),
        "mt5TodayReturn": round(mt5_return, 2),
        "totalReturnProfit": round(binance_return + mt5_return, 2),
    }
    return stats, account_trades, mt5_trades


async def _get_user_accounts(db, user_id):
    result = await db.execute(
        select(Account).filter(Account.user_id == user_id)
    )
    accounts = result.scalars().all()
    return accounts, {acc.account_id: acc for acc in accounts}


@router.get("/history")
async def get_trading_history(
    date: Optional[str] = Query(default=None, description="Query date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get trading history for a specific date"""
    try:
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"stats": _build_stats([], {}, enable_logging=False)[0], "accountTrades": [], "mt5Trades": []}

        account_ids = [acc.account_id for acc in accounts]
        query = select(OrderRecord).filter(
            OrderRecord.account_id.in_(account_ids),
        )

        if date:
            try:
                # Parse date string as UTC date (naive datetime for DB comparison)
                query_datetime_start = datetime.strptime(date, "%Y-%m-%d")
                query_datetime_end = query_datetime_start + timedelta(days=1)
                # Filter by UTC datetime range to avoid database timezone issues
                query = query.filter(
                    OrderRecord.create_time >= query_datetime_start,
                    OrderRecord.create_time < query_datetime_end
                )
            except ValueError:
                pass

        query = query.order_by(OrderRecord.create_time.asc())  # 升序：FIFO计算需要按时间顺序
        result = await db.execute(query)
        orders = result.scalars().all()

        # Enable logging for single date queries (usually smaller dataset)
        stats, account_trades, mt5_trades = _build_stats(orders, accounts_map, enable_logging=True)
        return {"stats": stats, "accountTrades": account_trades, "mt5Trades": mt5_trades}
    except Exception as e:
        logger.error(f"Error in get_trading_history: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/all")
async def get_all_trading_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all trading history with performance optimization for large datasets"""
    try:
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"stats": _build_stats([], {}, enable_logging=False)[0], "accountTrades": [], "mt5Trades": []}

        account_ids = [acc.account_id for acc in accounts]

        # First, count total orders to determine if we need batch processing
        count_query = select(func.count(OrderRecord.order_id)).filter(
            OrderRecord.account_id.in_(account_ids),
        )
        count_result = await db.execute(count_query)
        total_orders = count_result.scalar()

        logger.info(f"查询全部交易历史，共 {total_orders} 笔订单")

        # Performance optimization: Use batch processing for large datasets
        BATCH_SIZE = 5000  # Process 5000 orders at a time

        if total_orders > BATCH_SIZE:
            logger.info(f"数据量较大 ({total_orders} 笔)，启用分批处理模式 (批次大小: {BATCH_SIZE})")

            # Process in batches using offset/limit
            all_orders = []
            for offset in range(0, total_orders, BATCH_SIZE):
                batch_query = select(OrderRecord).filter(
                    OrderRecord.account_id.in_(account_ids),
                ).order_by(OrderRecord.create_time.asc()).offset(offset).limit(BATCH_SIZE)

                batch_result = await db.execute(batch_query)
                batch_orders = batch_result.scalars().all()
                all_orders.extend(batch_orders)

                logger.info(f"已加载 {len(all_orders)}/{total_orders} 笔订单")

            # Disable detailed logging for large datasets to improve performance
            stats, account_trades, mt5_trades = _build_stats(all_orders, accounts_map, enable_logging=False)
            logger.info(f"大数据集处理完成: Binance盈亏={stats['realizedPnL']:.2f} USDT, "
                       f"MT5盈亏={stats['mt5RealizedPnL']:.2f} USDT")
        else:
            # For smaller datasets, load all at once with detailed logging
            result = await db.execute(
                select(OrderRecord)
                .filter(
                    OrderRecord.account_id.in_(account_ids),
                )
                .order_by(OrderRecord.create_time.asc())
            )
            orders = result.scalars().all()

            # Enable detailed logging for smaller datasets
            stats, account_trades, mt5_trades = _build_stats(orders, accounts_map, enable_logging=True)

        return {"stats": stats, "accountTrades": account_trades, "mt5Trades": mt5_trades}
    except Exception as e:
        logger.error(f"Error in get_all_trading_history: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/all")
async def delete_all_trading_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete all trading history"""
    try:
        accounts, _ = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"message": "No data to delete"}

        account_ids = [acc.account_id for acc in accounts]
        result = await db.execute(
            select(OrderRecord).filter(OrderRecord.account_id.in_(account_ids))
        )
        orders = result.scalars().all()
        for order in orders:
            await db.delete(order)
        await db.commit()
        return {"message": "All trading history deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders")
async def get_recent_orders(
    limit: int = Query(default=50, le=200, description="Maximum number of orders to return"),
    source: Optional[str] = Query(default=None, description="Filter by source: manual, strategy, sync"),
    status: Optional[str] = Query(default=None, description="Filter by status: new, pending, filled, canceled (comma-separated)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent orders for the current user"""
    try:
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return []

        account_ids = list(accounts_map.keys())
        query = select(OrderRecord).filter(OrderRecord.account_id.in_(account_ids))

        # Filter by source if specified
        if source:
            query = query.filter(OrderRecord.source == source)

        # Filter by status if specified
        if status:
            status_list = [s.strip() for s in status.split(',')]
            query = query.filter(OrderRecord.status.in_(status_list))

        query = query.order_by(OrderRecord.create_time.desc()).limit(limit)
        result = await db.execute(query)
        orders = result.scalars().all()

        result_list = []
        for order in orders:
            acc = accounts_map.get(order.account_id)
            platform_name = "Unknown"
            if acc:
                if acc.platform_id == 1:
                    platform_name = "主账号"
                elif acc.platform_id == 2:
                    platform_name = "对冲账户"

            result_list.append({
                "id": str(order.order_id),
                "timestamp": order.create_time.isoformat() if order.create_time else None,
                "exchange": platform_name,
                "side": order.order_side,
                "quantity": order.qty,
                "price": order.price,
                "status": order.status,
                "symbol": order.symbol,
                "source": order.source,
            })

        return result_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/realtime")
async def get_realtime_pending_orders(
    status: Optional[str] = Query(default="new,pending", description="订单状态过滤: new,pending | filled | canceled,cancelled | all"),
    source: Optional[str] = Query(default=None, description="来源过滤: strategy | manual"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
    days: int = Query(default=7, ge=1, le=90, description="历史查询天数（仅状态非挂单中时有效）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    实时从 Binance API 获取订单历史，无需数据库。

    status=new,pending  → 当前挂单中（get_open_orders，最快）
    status=filled       → 已成交历史（get_all_orders + FILLED 过滤）
    status=canceled     → 已取消历史（get_all_orders + CANCELED 过滤）
    status=all/空       → 全部（get_all_orders，最近 days 天）
    """
    import time as _time
    try:
        from app.utils.time_utils import utc_ms_to_beijing
        from app.services.binance_client import BinanceFuturesClient

        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return []

        binance_accs = [a.account_name for a in accounts if a.platform_id == 1]
        logger.info(f"[orders/realtime] user={current_user.username}, binance_accounts={binance_accs}")

        result_orders = []
        status_list = [s.strip().upper() for s in (status or "").split(",") if s.strip()]
        want_open = any(s in ("NEW", "PENDING") for s in status_list)

        for account in accounts:
            if account.platform_id != 1:
                continue
            client = BinanceFuturesClient(
                account.api_key, account.api_secret,
                proxy_url=build_proxy_url(account.proxy_config)
            )
            try:
                _sym_a, _ = _get_pair_symbols()
                if want_open:
                    raw_orders = await client.get_open_orders(symbol=_sym_a)
                else:
                    end_ms = int(_time.time() * 1000)
                    start_ms = end_ms - days * 86400 * 1000
                    raw_orders = await client.get_all_orders(
                        symbol=_sym_a, start_time=start_ms, limit=min(limit * 3, 500)
                    )
                    # 按 status 过滤
                    if status_list and "ALL" not in status_list:
                        target = set(status_list)
                        if "CANCELED" in target or "CANCELLED" in target:
                            target.update({"CANCELED", "CANCELLED"})
                        raw_orders = [o for o in raw_orders if o.get("status", "").upper() in target]

                for order in raw_orders:
                    order_time = order.get("time", 0) or order.get("updateTime", 0)
                    beijing_time = utc_ms_to_beijing(order_time)
                    order_status = order.get("status", "").lower()
                    if order_status == "new":
                        ui_status = "new"
                    elif order_status == "partially_filled":
                        ui_status = "pending"
                    elif order_status == "filled":
                        ui_status = "filled"
                    elif order_status in ("canceled", "cancelled", "expired", "rejected"):
                        ui_status = "canceled"
                    else:
                        ui_status = order_status

                    result_orders.append({
                        "id":         str(order.get("orderId", "")),
                        "timestamp":  beijing_time,
                        "exchange":   account.account_name,
                        "side":       order.get("side", "").lower(),
                        "quantity":   float(order.get("origQty") or order.get("qty", 0)),
                        "price":      float(order.get("price") or 0),
                        "status":     ui_status,
                        "symbol":     order.get("symbol", _sym_a),
                        "source":     "strategy",
                        "filled_qty": float(order.get("executedQty") or 0),
                        "order_type": order.get("type", ""),
                    })
            except Exception as e:
                logger.error(f"Binance realtime orders error [{account.account_name}]: {e}")
            finally:
                await client.close()

        result_orders.sort(key=lambda x: x["timestamp"], reverse=True)
        return result_orders[:limit]

    except Exception as e:
        logger.error(f"Realtime pending orders error: {str(e)}", exc_info=True)
        return []


class ManualOrderRequest(BaseModel):
    exchange: str  # "binance" or "bybit"
    side: str      # "buy" or "sell"
    quantity: float
    account_id: Optional[str] = None



async def _resolve_manual_target_account(db, user_id, exchange, pair_code="XAU"):
    """Resolve the correct account for manual/emergency trading using pair-account binding.
    
    For Binance (A-side): use pair binding account_a_id, fallback to first platform=1
    For Bybit (B-side): use pair binding account_b_id, fallback to first platform=2
    """
    from sqlalchemy import text
    
    # Try pair-account binding first
    result = await db.execute(text("""
        SELECT account_a_id::text, account_b_id::text
        FROM user_pair_accounts
        WHERE user_id = :uid AND pair_code = :pc
    """), {"uid": str(user_id), "pc": pair_code})
    binding = result.fetchone()
    
    if binding:
        target_id = binding[0] if exchange == "binance" else binding[1]
        if target_id:
            from app.models.account import Account as AccModel
            acc_result = await db.execute(
                select(AccModel).where(AccModel.account_id == target_id)
            )
            acc = acc_result.scalar_one_or_none()
            if acc:
                return acc
    
    # Fallback: first matching platform account for this user
    accounts, _ = await _get_user_accounts(db, user_id)
    target_platform = 1 if exchange == "binance" else 2
    for account in accounts:
        if account.platform_id == target_platform:
            return account
    return None

@router.post("/manual/order")
async def place_manual_order(
    req: ManualOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Place a manual order on a single exchange with auto-price logic

    买入开多: 使用bid价
    卖出开空: 使用ask价
    """
    try:
        # Get user accounts
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            raise HTTPException(status_code=404, detail="No trading accounts found")

        # Find the correct account via pair-account binding
        target_account = await _resolve_manual_target_account(db, current_user.user_id, req.exchange)
        if not target_account:
            raise HTTPException(status_code=404, detail=f"No {req.exchange} account found")

        # Get current market prices
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Determine price based on side and exchange
        if req.exchange == "binance":
            # Binance: 买入开多用bid价挂单，卖出开空用ask价挂单
            if req.side == "buy":
                price = spread_data.binance_quote.bid_price
            else:  # sell
                price = spread_data.binance_quote.ask_price
            _sym_a, _sym_b = _get_pair_symbols()
            symbol = _sym_a
        else:  # bybit
            # Bybit: Market单不需要价格，直接以市价成交
            symbol = _sym_b

        # Import order executor
        from app.services.order_executor import order_executor

        # Place order
        if req.exchange == "binance":
            result = await order_executor.place_binance_order(
                account=target_account,
                symbol=symbol,
                side="BUY" if req.side == "buy" else "SELL",
                order_type="LIMIT",
                quantity=req.quantity,
                price=price,
                position_side="LONG" if req.side == "buy" else "SHORT",
                post_only=True,
            )
        else:  # bybit — 紧急交易用Market单立即成交，quantity已由前端换算为Lot
            bybit_qty = round(float(req.quantity), 2)
            result = await order_executor.place_bybit_order(
                account=target_account,
                symbol=symbol,
                side="Buy" if req.side == "buy" else "Sell",
                order_type="Market",
                quantity=str(bybit_qty),
                price=None,
                close_position=False,
            )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Order failed"))

        # Trigger immediate position snapshot so frontend updates without waiting 30s
        try:
            from app.websocket.manager import manager as ws_manager
            from app.tasks.broadcast_tasks import account_balance_streamer
            account_balance_streamer.trigger_immediate_refresh()
        except Exception:
            pass

        return {
            "success": True,
            "exchange": req.exchange,
            "side": req.side,
            "quantity": req.quantity,
            "order_id": result.get("order_id"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual order error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual/close-all")
async def close_all_positions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close all open positions at market price on both exchanges

    多单: 使用ask价平仓
    空单: 使用bid价平仓
    """
    try:
        # Get user accounts
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            raise HTTPException(status_code=404, detail="No trading accounts found")

        # Get current market prices
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Import order executor
        from app.services.order_executor import order_executor

        results = []

        # Close Binance positions
        binance_account = None
        for account in accounts:
            if account.platform_id == 1:
                binance_account = account
                break

        if binance_account:
            try:
                # Get Binance positions
                from app.services.binance_client import BinanceFuturesClient
                client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret,
                                               proxy_url=build_proxy_url(binance_account.proxy_config))
                try:
                    _sym_a, _ = _get_pair_symbols()
                    positions = await client.get_position_risk(_sym_a)

                    for pos in positions:
                        position_amt = float(pos.get("positionAmt", 0))
                        if position_amt == 0:
                            continue

                        # 多单用ask价平仓，空单用bid价平仓
                        if position_amt > 0:  # LONG position
                            price = spread_data.binance_quote.ask_price
                            side = "SELL"
                            position_side = "LONG"
                        else:  # SHORT position
                            price = spread_data.binance_quote.bid_price
                            side = "BUY"
                            position_side = "SHORT"
                            position_amt = abs(position_amt)

                        result = await order_executor.place_binance_order(
                            account=binance_account,
                            symbol=_sym_a,
                            side=side,
                            order_type="LIMIT",
                            quantity=position_amt,
                            price=price,
                            position_side=position_side,
                            post_only=True,
                        )

                        results.append({
                            "exchange": "binance",
                            "position_side": position_side,
                            "quantity": position_amt,
                            "price": price,
                            "success": result.get("success"),
                            "order_id": result.get("order_id"),
                        })
                finally:
                    await client.close()
            except Exception as e:
                logger.error(f"Binance close positions error: {str(e)}", exc_info=True)
                results.append({"exchange": "binance", "error": str(e)})

        # Close Bybit positions
        bybit_account = None
        for account in accounts:
            if account.platform_id == 2:
                bybit_account = account
                break

        if bybit_account:
            try:
                # Get Bybit MT5 positions
                import MetaTrader5 as mt5
                loop = asyncio.get_event_loop()
                _, _sym_b = _get_pair_symbols()
                positions = await loop.run_in_executor(None, mt5.positions_get, _sym_b)

                if positions:
                    for pos in positions:
                        volume = round(pos.volume, 2)
                        if volume == 0:
                            continue

                        # Bybit: Market Taker单平仓，close_position=True关联持仓ticket
                        if pos.type == mt5.POSITION_TYPE_BUY:  # LONG position → Sell to close
                            side = "Sell"
                        else:  # SHORT position → Buy to close
                            side = "Buy"

                        result = await order_executor.place_bybit_order(
                            account=bybit_account,
                            symbol=_sym_b,
                            side=side,
                            order_type="Market",
                            quantity=str(volume),
                            price=None,
                            close_position=True,
                        )

                        results.append({
                            "exchange": "bybit",
                            "position_type": "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT",
                            "quantity": volume,
                            "success": result.get("success"),
                            "order_id": result.get("order_id"),
                        })
            except Exception as e:
                logger.error(f"Bybit close positions error: {str(e)}", exc_info=True)
                results.append({"exchange": "bybit", "error": str(e)})

        return {
            "success": True,
            "results": results,
            "message": f"Closed {len(results)} positions"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Close all positions error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-trades")
async def sync_trades_from_exchanges(
    days: int = Query(default=7, le=30, description="Number of days to sync"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync trade history from exchange APIs to database"""
    try:
        accounts, _ = await _get_user_accounts(db, current_user.user_id)
        synced_count = 0
        errors = []

        # Calculate time range (last N days)
        end_time = int(datetime.utcnow().timestamp() * 1000)
        start_time = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

        for account in accounts:
            if not account.is_active:
                continue

            try:
                if account.platform_id == 1:
                    # Sync Binance trades
                    from app.services.binance_client import BinanceFuturesClient
                    client = BinanceFuturesClient(account.api_key, account.api_secret,
                                                   proxy_url=build_proxy_url(account.proxy_config))
                    try:
                        _sym_a, _ = _get_pair_symbols()
                        trades = await client.get_user_trades(
                            symbol=_sym_a,
                            start_time=start_time,
                            end_time=end_time,
                            limit=500
                        )

                        for trade in trades:
                            symbol = trade.get("symbol", "")
                            if symbol.upper() != _sym_a:
                                continue

                            # Skip if side indicates a transfer
                            side = trade.get("side", "").lower()
                            if side in ["transfer", "deposit", "withdrawal", "funding"]:
                                continue

                            # Skip if type indicates a transfer
                            trade_type = trade.get("type", "").lower()
                            if trade_type in ["transfer", "deposit", "withdrawal", "internal_transfer", "funding", "rebate"]:
                                continue

                            # Check if trade already exists
                            existing = await db.execute(
                                select(OrderRecord).filter(
                                    OrderRecord.account_id == account.account_id,
                                    OrderRecord.platform_order_id == str(trade.get("orderId"))
                                )
                            )
                            if existing.scalar_one_or_none():
                                continue

                            # Get actual commission from trade
                            commission = abs(float(trade.get("commission", 0)))  # Use abs() to handle negative values
                            commission_asset = trade.get("commissionAsset", "USDT")

                            # Convert commission to USDT if needed
                            if commission_asset != "USDT":
                                # For simplicity, if commission is in other asset, estimate in USDT
                                qty = float(trade.get("qty", 0))
                                price = float(trade.get("price", 0))
                                # Estimate based on order type: Maker 0.02%, Taker 0.04%
                                if trade_type and trade_type.lower() == 'limit':
                                    commission = qty * price * 0.0002  # Maker
                                else:
                                    commission = qty * price * 0.0004  # Taker

                            # Ensure commission is positive
                            commission = abs(commission)

                            # Create order record
                            order_record = OrderRecord(
                                account_id=account.account_id,
                                symbol=symbol,
                                order_side=side,
                                order_type=trade_type,
                                price=float(trade.get("price", 0)),
                                qty=float(trade.get("qty", 0)),
                                filled_qty=float(trade.get("qty", 0)),
                                fee=commission,
                                status="filled",
                                source="sync",
                                platform_order_id=str(trade.get("orderId")),
                                create_time=datetime.fromtimestamp(trade.get("time", 0) / 1000),
                            )
                            db.add(order_record)
                            synced_count += 1
                    finally:
                        await client.close()

                elif account.platform_id == 2:
                    # Sync Bybit MT5 trades
                    logger.info(f"开始同步MT5账户 {account.account_name} 的交易记录")

                    # Ensure MT5 is connected
                    from app.services.market_service import market_data_service
                    mt5_client = market_data_service.mt5_client

                    if not mt5_client or not mt5_client.connected:
                        logger.warning(f"MT5未连接，尝试连接...")
                        if mt5_client and not mt5_client.connect():
                            logger.error(f"MT5连接失败，跳过账户 {account.account_name}")
                            errors.append({"account": account.account_name, "error": "MT5 connection failed"})
                            continue

                    loop = asyncio.get_event_loop()

                    # Convert timestamps to datetime objects
                    start_datetime = datetime.fromtimestamp(start_time / 1000)
                    end_datetime = datetime.fromtimestamp(end_time / 1000)

                    logger.info(f"MT5同步时间范围: {start_datetime} 到 {end_datetime}")

                    history_deals = await loop.run_in_executor(
                        None,
                        lambda: mt5.history_deals_get(
                            start_datetime,
                            end_datetime
                        )
                    )

                    if history_deals:
                        logger.info(f"MT5返回 {len(history_deals)} 笔交易记录")

                        # Log first and last deal time for debugging
                        if len(history_deals) > 0:
                            first_deal_time = datetime.fromtimestamp(history_deals[0].time)
                            last_deal_time = datetime.fromtimestamp(history_deals[-1].time)
                            logger.info(f"MT5交易时间范围: {first_deal_time} 到 {last_deal_time}")

                        _, _sym_b = _get_pair_symbols()
                        xauusd_count = 0
                        for deal in history_deals:
                            if deal.symbol != _sym_b:
                                continue
                            xauusd_count += 1

                            # Check if deal already exists using deal ticket (unique identifier)
                            existing = await db.execute(
                                select(OrderRecord).filter(
                                    OrderRecord.account_id == account.account_id,
                                    OrderRecord.platform_order_id == str(deal.ticket)
                                )
                            )
                            if existing.scalar_one_or_none():
                                logger.debug(f"MT5交易 {deal.ticket} 已存在，跳过")
                                continue

                            # Create order record
                            # Estimate MT5 fee (Bybit MT5 ~0.01%)
                            mt5_fee = deal.price * deal.volume * 0.0001
                            order_record = OrderRecord(
                                account_id=account.account_id,
                                symbol=deal.symbol,
                                order_side="buy" if deal.type == mt5.DEAL_TYPE_BUY else "sell",
                                order_type="market",
                                price=deal.price,
                                qty=deal.volume,
                                filled_qty=deal.volume,
                                fee=mt5_fee,
                                status="filled",
                                source="sync",
                                platform_order_id=str(deal.ticket),  # Use deal.ticket as unique identifier
                                create_time=datetime.fromtimestamp(deal.time),
                            )
                            db.add(order_record)
                            synced_count += 1
                            logger.info(f"新增MT5交易记录: ticket={deal.ticket}, symbol={deal.symbol}, "
                                      f"side={'buy' if deal.type == mt5.DEAL_TYPE_BUY else 'sell'}, "
                                      f"qty={deal.volume}, price={deal.price}")
                        logger.info(f"MT5账户 {account.account_name}: 共 {len(history_deals)} 笔交易，"
                                  f"其中 {xauusd_count} 笔XAUUSD+交易")
                    else:
                        logger.warning(f"MT5账户 {account.account_name} 未返回交易记录，错误: {mt5.last_error()}")

            except Exception as e:
                errors.append({"account": account.account_name, "error": str(e)})

        await db.commit()
        return {
            "success": True,
            "synced_count": synced_count,
            "errors": errors if errors else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ClosePositionRequest(BaseModel):
    exchange: str  # "binance" or "bybit"
    quantity: float


@router.post("/manual/close-short")
async def close_short_position(
    req: ClosePositionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """空仓平多：平掉空头仓位

    Binance: 持有的空仓以ask价挂单
    Bybit: 持有的空仓以bid价挂单
    """
    try:
        # Get user accounts
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            raise HTTPException(status_code=404, detail="No trading accounts found")

        # Find the correct account via pair-account binding
        target_account = await _resolve_manual_target_account(db, current_user.user_id, req.exchange)
        if not target_account:
            raise HTTPException(status_code=404, detail=f"No {req.exchange} account found")

        # Get current market prices
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Determine price based on exchange
        if req.exchange == "binance":
            # Binance: 空仓以ask价挂单平仓
            price = spread_data.binance_quote.ask_price
            _sym_a, _sym_b = _get_pair_symbols()
            symbol = _sym_a
        else:  # bybit
            symbol = _sym_b

        # Import order executor
        from app.services.order_executor import order_executor

        # Place order to close short position (buy to close)
        if req.exchange == "binance":
            result = await order_executor.place_binance_order(
                account=target_account,
                symbol=symbol,
                side="BUY",
                position_side="SHORT",
                order_type="LIMIT",
                quantity=str(req.quantity),
                price=str(price),
            )
        else:  # bybit — Market Taker单平空仓，close_position=True关联持仓ticket
            bybit_qty = round(float(req.quantity), 2)
            result = await order_executor.place_bybit_order(
                account=target_account,
                symbol=symbol,
                side="Buy",
                order_type="Market",
                quantity=str(bybit_qty),
                price=None,
                close_position=True,
            )

        return {
            "success": result.get("success"),
            "order_id": result.get("order_id"),
            "quantity": req.quantity,
            "exchange": req.exchange,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Close short position error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual/close-long")
async def close_long_position(
    req: ClosePositionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """多仓平空：平掉多头仓位

    Binance: 持有的多仓以bid价挂单
    Bybit: 持有的多仓以ask价挂单
    """
    try:
        # Get user accounts
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            raise HTTPException(status_code=404, detail="No trading accounts found")

        # Find the correct account via pair-account binding
        target_account = await _resolve_manual_target_account(db, current_user.user_id, req.exchange)
        if not target_account:
            raise HTTPException(status_code=404, detail=f"No {req.exchange} account found")

        # Get current market prices
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Determine price based on exchange
        if req.exchange == "binance":
            # Binance: 多仓以bid价挂单平仓
            price = spread_data.binance_quote.bid_price
            _sym_a, _sym_b = _get_pair_symbols()
            symbol = _sym_a
        else:  # bybit
            symbol = _sym_b

        # Import order executor
        from app.services.order_executor import order_executor

        # Place order to close long position (sell to close)
        if req.exchange == "binance":
            result = await order_executor.place_binance_order(
                account=target_account,
                symbol=symbol,
                side="SELL",
                position_side="LONG",
                order_type="LIMIT",
                quantity=str(req.quantity),
                price=str(price),
            )
        else:  # bybit — Market Taker单平多仓，close_position=True关联持仓ticket
            bybit_qty = round(float(req.quantity), 2)
            result = await order_executor.place_bybit_order(
                account=target_account,
                symbol=symbol,
                side="Sell",
                order_type="Market",
                quantity=str(bybit_qty),
                price=None,
                close_position=True,
            )

        return {
            "success": result.get("success"),
            "order_id": result.get("order_id"),
            "quantity": req.quantity,
            "exchange": req.exchange,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Close long position error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/manual/cancel-all")
async def cancel_all_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel all pending orders on both exchanges"""
    try:
        # Get user accounts
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            raise HTTPException(status_code=404, detail="No trading accounts found")

        # Import order executor
        from app.services.order_executor import order_executor

        results = []

        # Cancel Binance orders
        binance_account = None
        for account in accounts:
            if account.platform_id == 1:
                binance_account = account
                break

        if binance_account:
            try:
                from app.services.binance_client import BinanceFuturesClient
                client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret,
                                               proxy_url=build_proxy_url(binance_account.proxy_config))
                try:
                    _sym_a, _ = _get_pair_symbols()
                    open_orders = await client.get_open_orders(_sym_a)

                    for order in open_orders:
                        order_id = order.get("orderId")
                        result = await order_executor.cancel_binance_order(
                            binance_account,
                            _sym_a,
                            order_id
                        )

                        results.append({
                            "exchange": "binance",
                            "order_id": order_id,
                            "success": result.get("success") if isinstance(result, dict) else True,
                        })
                finally:
                    await client.close()
            except Exception as e:
                logger.error(f"Binance cancel orders error: {str(e)}", exc_info=True)
                results.append({"exchange": "binance", "error": str(e)})

        # Cancel Bybit orders
        bybit_account = None
        for account in accounts:
            if account.platform_id == 2:
                bybit_account = account
                break

        if bybit_account:
            try:
                # Get Bybit MT5 open orders
                import MetaTrader5 as mt5
                loop = asyncio.get_event_loop()
                _, _sym_b = _get_pair_symbols()
                orders = await loop.run_in_executor(None, mt5.orders_get, _sym_b)

                if orders:
                    for order in orders:
                        order_id = str(order.ticket)
                        result = await order_executor.cancel_bybit_order(
                            bybit_account,
                            _sym_b,
                            order_id
                        )

                        results.append({
                            "exchange": "bybit",
                            "order_id": order_id,
                            "success": result.get("success") if isinstance(result, dict) else True,
                        })
            except Exception as e:
                logger.error(f"Bybit cancel orders error: {str(e)}", exc_info=True)
                results.append({"exchange": "bybit", "error": str(e)})

        return {
            "success": True,
            "results": results,
            "message": f"Cancelled {len(results)} orders"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel all orders error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/{order_id}/manual-process")
async def manual_process_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a specific order as manually processed"""
    try:
        # Get user accounts to verify ownership
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        account_ids = list(accounts_map.keys())

        # Find the order
        result = await db.execute(
            select(OrderRecord).filter(
                OrderRecord.order_id == uuid.UUID(order_id),
                OrderRecord.account_id.in_(account_ids)
            )
        )
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Update status to manually_processed
        order.status = "manually_processed"
        await db.commit()

        return {"success": True, "order_id": order_id, "new_status": "manually_processed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# 实时交易历史查询（不依赖数据库，直接从平台API获取）
# ============================================================================

@router.get("/history/realtime")
async def get_realtime_trading_history(
    start_time: str = Query(..., description="Start time in Beijing timezone (YYYY-MM-DD HH:MM:SS)"),
    end_time: str = Query(..., description="End time in Beijing timezone (YYYY-MM-DD HH:MM:SS)"),
    pair_code: str = Query("XAU", description="Trading pair code (XAU/XAG/BZ/CL/NG/BXAU/ICXAU)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    实时从平台获取交易历史（不依赖数据库）

    - 根据 pair_code 动态获取对应的 Binance symbol 和 MT5 symbol
    - 主账号：platform_id=1 Binance（所有主账号成交汇总）
    - 对冲账户：platform_id=2 Bybit MT5 + platform_id=3 IC Markets MT5
    时间参数：北京时间（UTC+8）
    """
    try:
        from app.utils.time_utils import beijing_to_utc_ms, utc_ms_to_beijing, mt5_time_to_beijing
        from app.services.hedging_pair_service import hedging_pair_service

        # 转换查询时间：北京时间 → UTC毫秒时间戳
        try:
            start_utc_ms = beijing_to_utc_ms(start_time)
            end_utc_ms = beijing_to_utc_ms(end_time)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid time format: {str(e)}")

        # 根据 pair_code 获取对应 symbol
        pair = hedging_pair_service.get_pair(pair_code)
        if pair:
            binance_symbol = pair.symbol_a.symbol   # e.g. XAUUSDT
            mt5_symbol     = pair.symbol_b.symbol   # e.g. XAUUSD+
        else:
            binance_symbol, mt5_symbol = "XAUUSDT", "XAUUSD+"

        # pair 的 A 侧平台 ID：决定主账号查询方式
        # XAU/XAG/BZ/CL/NG/ICXAU → A 侧 platform_id=1 (Binance)
        # BXAU                    → A 侧 platform_id=2 (Bybit Linear 合约 API)
        a_platform_id = pair.symbol_a.platform_id if pair else 1
        b_platform_id = pair.symbol_b.platform_id if pair else 2
        logger.info(f"[realtime] pair={pair_code} binance_sym={binance_symbol} mt5_sym={mt5_symbol} "                    f"A侧平台={a_platform_id} B侧平台={b_platform_id}")

        # 获取用户账户
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"binanceTrades": [], "mt5Trades": [], "stats": {}, "timeZone": "Asia/Shanghai (UTC+8)"}

        # 按 pair 的 A 侧平台筛选主账号，B 侧筛选对冲账户
        primary_accs = [a for a in accounts if a.platform_id == a_platform_id and not a.is_mt5_account]
        mt5_accs     = [a for a in accounts if a.is_mt5_account and a.platform_id == b_platform_id]
        logger.info(f"[realtime] user={current_user.username}, "                    f"primary={[a.account_name for a in primary_accs]}, "                    f"mt5={[a.account_name for a in mt5_accs]}")

        # 实时获取主账号成交历史（按 A 侧平台类型分发）
        binance_trades = []
        binance_realized_pnl = 0.0
        binance_funding_fee = 0.0
        for account in primary_accs:
            if a_platform_id == 1:
                # Binance 永续合约：XAU/XAG/BZ/CL/NG/ICXAU
                try:
                    raw_trades = await _get_binance_trades_realtime(account, start_utc_ms, end_utc_ms, symbol=binance_symbol)
                    binance_trades.extend([(t, account.account_name) for t in raw_trades])
                    pnl = await _get_binance_realized_pnl(account, start_utc_ms, end_utc_ms, symbol=binance_symbol)
                    binance_realized_pnl += pnl
                    funding = await _get_binance_funding_fee(account, start_utc_ms, end_utc_ms, symbol=binance_symbol)
                    binance_funding_fee += funding
                except Exception as e:
                    logger.error(f"Binance trades error [{account.account_name}]: {str(e)}")
            elif a_platform_id == 2:
                # Bybit Linear 合约（PostOnly）：BXAU
                try:
                    raw_trades = await _get_bybit_trades_realtime(account, start_utc_ms, end_utc_ms, symbol=binance_symbol)
                    binance_trades.extend([(t, account.account_name) for t in raw_trades])
                    pnl = await _get_bybit_realized_pnl(account, start_utc_ms, end_utc_ms, symbol=binance_symbol)
                    binance_realized_pnl += pnl
                except Exception as e:
                    logger.error(f"Bybit A-side trades error [{account.account_name}]: {str(e)}")

        # 实时获取对冲账户成交历史（MT5 Bridge，按 B 侧平台筛选）
        mt5_trades = []
        for account in mt5_accs:
            try:
                trades = await _get_mt5_trades_realtime(
                    account, start_utc_ms, end_utc_ms, db, mt5_symbol=mt5_symbol
                )
                mt5_trades.extend(trades)
            except Exception as e:
                logger.error(f"MT5 trades error [{account.account_name}]: {str(e)}")

        # 格式化数据
        formatted_binance = _format_binance_trades(binance_trades)
        formatted_mt5 = _format_mt5_trades(mt5_trades)

        # 计算统计数据
        stats = _calculate_stats(formatted_binance, formatted_mt5, binance_realized_pnl, binance_funding_fee)

        return {
            "accountTrades": formatted_binance,
            "mt5Trades": formatted_mt5,
            "stats": stats,
            "pair_code": pair_code,
            "timeZone": "Asia/Shanghai (UTC+8)"
        }
    except Exception as e:
        logger.error(f"Realtime history error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _get_binance_trades_realtime(account, start_time_ms, end_time_ms, symbol=None):
    """获取Binance交易历史（使用userTrades API获取准确的手续费）。

    Binance /fapi/v1/userTrades 单次最多查 7 天，超出范围静默返回空列表。
    超过 7 天时自动分段查询后合并去重。
    """
    from app.services.binance_client import BinanceFuturesClient
    _SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000  # 7天毫秒数

    client = BinanceFuturesClient(account.api_key, account.api_secret,
                                   proxy_url=build_proxy_url(account.proxy_config))
    try:
        _sym_a = symbol or _get_pair_symbols()[0]
        all_trades = []
        seen_ids = set()

        # 分段：每段 ≤ 7 天（6天23小时59分 避免边界问题）
        chunk_ms = 6 * 24 * 60 * 60 * 1000 + 23 * 60 * 60 * 1000 + 59 * 60 * 1000
        chunk_start = start_time_ms
        while chunk_start < end_time_ms:
            chunk_end = min(chunk_start + chunk_ms, end_time_ms)
            trades = await client.get_user_trades(
                symbol=_sym_a,
                start_time=chunk_start,
                end_time=chunk_end,
                limit=1000,
            )
            for t in trades:
                tid = t.get("id")
                if tid and tid not in seen_ids and t.get("symbol", "").upper() == _sym_a:
                    seen_ids.add(tid)
                    all_trades.append(t)
            chunk_start = chunk_end + 1

        logger.info(f"Binance userTrades [{account.account_name}]: {len(all_trades)} trades for {_sym_a}")
        return all_trades
    finally:
        await client.close()


async def _get_binance_realized_pnl(account, start_time_ms, end_time_ms, symbol=None):
    """获取Binance已实现盈亏（income API，自动分7天段查询）"""
    from app.services.binance_client import BinanceFuturesClient
    _CHUNK_MS = 6 * 24 * 60 * 60 * 1000 + 23 * 60 * 60 * 1000 + 59 * 60 * 1000
    client = BinanceFuturesClient(account.api_key, account.api_secret,
                                   proxy_url=build_proxy_url(account.proxy_config))
    try:
        _sym_a = symbol or _get_pair_symbols()[0]
        total_pnl = 0.0
        total_count = 0
        chunk_start = start_time_ms
        while chunk_start < end_time_ms:
            chunk_end = min(chunk_start + _CHUNK_MS, end_time_ms)
            income_data = await client.get_income(
                symbol=_sym_a,
                income_type="REALIZED_PNL",
                start_time=chunk_start,
                end_time=chunk_end,
                limit=1000,
            )
            total_pnl += sum(float(item.get("income", 0)) for item in income_data)
            total_count += len(income_data)
            chunk_start = chunk_end + 1
        logger.info(f"Binance realized PnL: {total_pnl:.2f} USDT ({total_count} records)")
        return total_pnl
    except Exception as e:
        logger.error(f"Failed to get Binance realized PnL: {str(e)}")
        return 0.0
    finally:
        await client.close()



async def _get_binance_funding_fee(account, start_time_ms, end_time_ms, symbol=None):
    """获取Binance资金费汇总（FUNDING_FEE income type，自动分7天段查询）。
    资金费每8小时结算，正数=收入，负数=支出（USDT）。
    """
    from app.services.binance_client import BinanceFuturesClient
    _CHUNK_MS = 6 * 24 * 60 * 60 * 1000 + 23 * 60 * 60 * 1000 + 59 * 60 * 1000
    client = BinanceFuturesClient(account.api_key, account.api_secret,
                                   proxy_url=build_proxy_url(account.proxy_config))
    try:
        _sym_a = symbol or _get_pair_symbols()[0]
        total_funding = 0.0
        total_count = 0
        chunk_start = start_time_ms
        while chunk_start < end_time_ms:
            chunk_end = min(chunk_start + _CHUNK_MS, end_time_ms)
            income_data = await client.get_income(
                symbol=_sym_a,
                income_type="FUNDING_FEE",
                start_time=chunk_start,
                end_time=chunk_end,
                limit=1000,
            )
            total_funding += sum(float(item.get("income", 0)) for item in income_data)
            total_count += len(income_data)
            chunk_start = chunk_end + 1
        logger.info(f"Binance funding fee: {total_funding:.4f} USDT ({total_count} records)")
        return total_funding
    except Exception as e:
        logger.error(f"Failed to get Binance funding fee: {str(e)}")
        return 0.0
    finally:
        await client.close()


async def _get_mt5_trades_realtime(account, start_time_ms, end_time_ms, db=None, mt5_symbol=None):
    """通过该账户关联的 MT5 Bridge 获取成交历史。

    每个 MT5 账户在 mt5_clients 表中记录了 bridge_service_port，
    不同用户的 Bridge 运行在不同端口，必须按账户动态选择端口，
    否则会查到其他用户的交易数据（数据隔离问题）。
    """
    import os
    import httpx
    from sqlalchemy import select as sa_select
    from app.models.mt5_client import MT5Client

    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
    api_key     = os.getenv("MT5_API_KEY", "")
    headers     = {"X-Api-Key": api_key} if api_key else {}

    # 查询该账户关联的 MT5 客户端，获取 bridge_service_port
    bridge_port = None
    if db:
        try:
            result = await db.execute(
                sa_select(MT5Client.bridge_service_port).where(
                    MT5Client.account_id == account.account_id,
                    MT5Client.is_active == True,
                    MT5Client.is_system_service == False,   # 排除系统服务账户（无交易）
                    MT5Client.bridge_service_port.isnot(None),
                ).order_by(MT5Client.priority).limit(1)
            )
            bridge_port = result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Failed to query mt5_clients for account {account.account_id}: {e}")

    if not bridge_port:
        logger.info(f"No Bridge port found for MT5 account {account.account_name} ({account.account_id}), skipping")
        return []

    bridge_url = f"{bridge_host}:{bridge_port}"

    # 查询天数：从 start_time_ms 到现在
    from datetime import datetime as _dt, timezone as _tz
    start_dt = _dt.fromtimestamp(start_time_ms / 1000, tz=_tz.utc)
    now_dt   = _dt.now(tz=_tz.utc)
    # days = 从 start_time 到当前时间的天数，确保 Bridge 能覆盖查询范围
    # Bridge API 只支持"最近N天"，精确过滤由时间戳在代码中完成
    days = max(1, int((now_dt - start_dt).total_seconds() / 86400) + 2)
    days = min(days, 365)

    logger.info(f"Fetching MT5 deals via Bridge :{bridge_port}, days={days}, account={account.account_name}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{bridge_url}/mt5/history/deals",
                                    headers=headers, params={"days": days})
            resp.raise_for_status()
            all_deals = resp.json().get("deals", [])
    except Exception as e:
        logger.error(f"MT5 Bridge deals request failed: {e}")
        return []

    # 时间过滤（Bridge 返回 unix timestamp，单位秒）
    start_ts = start_time_ms / 1000
    end_ts   = end_time_ms   / 1000
    _sym_b = mt5_symbol or _get_pair_symbols()[1]
    target_symbols = {_sym_b, _sym_b.replace("+", ".s")}
    filtered = [
        d for d in all_deals
        if d.get("symbol") in target_symbols
        and start_ts <= d.get("time", 0) <= end_ts
    ]
    logger.info(f"MT5 Bridge: {len(filtered)} deals in range out of {len(all_deals)} total")

    # 转换为与 MT5Client 返回格式兼容的对象（dict → namedtuple-like）
    class _Deal:
        __slots__ = ["ticket","symbol","type","volume","price","profit","swap","commission","time","comment","entry"]
        def __init__(self, d):
            self.ticket     = d.get("ticket", 0)
            self.symbol     = d.get("symbol", "")
            self.type       = d.get("type", 2)       # 0=Buy, 1=Sell, 2=Balance
            self.volume     = float(d.get("volume", 0))
            self.price      = float(d.get("price", 0))
            self.profit     = float(d.get("profit", 0))
            self.swap       = float(d.get("swap", 0))
            self.commission = float(d.get("commission", 0))
            self.time       = int(d.get("time", 0))
            self.comment    = d.get("comment", "")
            self.entry      = int(d.get("entry", 0))  # 0=In(开仓), 1=Out(平仓)

    return [(_Deal(d), account.account_name) for d in filtered]



async def _get_bybit_trades_realtime(account, start_time_ms, end_time_ms, symbol=None):
    """获取 Bybit V5 API 主账号成交历史（非MT5账户，Bybit Linear合约）。
    使用 GET /v5/execution/list 获取成交明细。
    """
    from app.services.bybit_client import BybitV5Client
    from app.core.proxy_utils import build_proxy_url
    client = BybitV5Client(account.api_key, account.api_secret,
                           proxy_url=build_proxy_url(account.proxy_config))
    try:
        bybit_symbol = symbol or "XAUUSDT"
        params = {
            "category": "linear",
            "symbol": bybit_symbol,
            "startTime": str(start_time_ms),
            "endTime": str(end_time_ms),
            "limit": 200,
        }
        resp = await client._request("GET", "/v5/execution/list", signed=True, params=params)
        result = resp.get("result", {})
        rows = result.get("list", [])
        trades = []
        for r in rows:
            exec_time = int(r.get("execTime", 0))
            qty = float(r.get("execQty", 0))
            price = float(r.get("execPrice", 0))
            fee = float(r.get("execFee", 0))
            side = r.get("side", "").upper()
            is_maker = r.get("isMaker", False)
            trades.append({
                "time": exec_time,
                "commission": str(abs(fee)),
                "commissionAsset": "USDT",
                "side": side,
                "price": str(price),
                "qty": str(qty),
                "maker": is_maker,
                "symbol": bybit_symbol,
                "id": r.get("execId", ""),
            })
        logger.info(f"Bybit V5 trades: {len(trades)} records for {account.account_name}")
        return trades
    except Exception as e:
        logger.error(f"Bybit V5 trades error [{account.account_name}]: {e}")
        return []
    finally:
        await client.close()


async def _get_bybit_realized_pnl(account, start_time_ms, end_time_ms, symbol=None):
    """获取 Bybit V5 主账号已实现盈亏 — /v5/position/closed-pnl。"""
    from app.services.bybit_client import BybitV5Client
    from app.core.proxy_utils import build_proxy_url
    client = BybitV5Client(account.api_key, account.api_secret,
                           proxy_url=build_proxy_url(account.proxy_config))
    try:
        result = await client.get_profit_loss(
            category="linear",
            symbol=symbol or "",
            start_time=start_time_ms,
            end_time=end_time_ms,
        )
        rows = result.get("result", {}).get("list", [])
        total_pnl = sum(float(r.get("closedPnl", 0)) for r in rows)
        logger.info(f"Bybit V5 realized PnL: {total_pnl:.2f} USDT ({len(rows)} records) for {account.account_name}")
        return total_pnl
    except Exception as e:
        logger.error(f"Bybit V5 realized PnL error [{account.account_name}]: {e}")
        return 0.0
    finally:
        await client.close()


def _format_binance_trades(trades):
    """格式化Binance交易数据，支持 (trade, account_name) 元组或裸 trade dict"""
    from app.utils.time_utils import utc_ms_to_beijing
    formatted = []
    for item in trades:
        if isinstance(item, tuple):
            trade, account_name = item
        else:
            trade, account_name = item, "主账号"

        # 获取交易时间
        trade_time = trade.get("time", 0)
        beijing_time = utc_ms_to_beijing(trade_time)

        # 获取手续费（userTrades API返回准确的commission）
        commission = abs(float(trade.get("commission", 0)))
        commission_asset = trade.get("commissionAsset", "USDT")  # BNB 或 USDT

        # 获取方向（side字段：BUY或SELL）
        side = trade.get("side", "").lower()

        # 获取价格和数量
        price = float(trade.get("price", 0))
        quantity = float(trade.get("qty", 0))
        amount = price * quantity  # 成交额

        # 判断是否为Maker（挂单）还是Taker（吃单）
        is_maker = trade.get("maker", False)

        formatted.append({
            "timestamp": beijing_time,
            "account_name": account_name,
            "symbol": trade.get("symbol", ""),
            "side": side,
            "price": price,
            "quantity": quantity,
            "amount": round(amount, 2),
            "maker": is_maker,
            "fee": round(commission, 2) if commission_asset == "USDT" else 0.0,
            "fee_bnb": round(commission, 6) if commission_asset == "BNB" else 0.0,
            "commission_asset": commission_asset,
            "id": str(trade.get("id")),
        })

    # 降序排序（最新的在最上面）
    return sorted(formatted, key=lambda x: x["timestamp"], reverse=True)


def _format_mt5_trades(deals):
    """格式化MT5交易数据，支持 (deal, account_name) 元组或裸deal对象。

    entry 字段：0=In(开仓), 1=Out(平仓)
    只有平仓交易(entry==1)的 profit 才是已实现盈亏。
    """
    from app.utils.time_utils import mt5_time_to_beijing
    formatted = []
    realized_pnl = 0.0  # 仅统计平仓交易的已实现盈亏
    for item in deals:
        if isinstance(item, tuple):
            deal, account_name = item
        else:
            deal, account_name = item, "对冲账户"

        beijing_time = mt5_time_to_beijing(deal.time)

        if deal.type == 0:
            side = "buy"
        elif deal.type == 1:
            side = "sell"
        else:
            side = "unknown"

        price = deal.price
        quantity = deal.volume
        amount = price * quantity

        fee = abs(float(deal.commission)) if hasattr(deal, 'commission') and deal.commission != 0 else 0.00
        profit = float(deal.profit) if hasattr(deal, 'profit') else 0.00
        overnight_fee = float(deal.swap) if hasattr(deal, 'swap') else 0.00
        entry = int(deal.entry) if hasattr(deal, 'entry') else 0

        # 只有平仓交易(entry==1)的profit为已实现盈亏
        if entry == 1:
            realized_pnl += profit

        formatted.append({
            "timestamp": beijing_time,
            "account_name": account_name,
            "symbol": deal.symbol,
            "side": side,
            "price": price,
            "quantity": quantity,
            "amount": round(amount, 2),
            "overnight_fee": round(overnight_fee, 2),
            "fee": round(fee, 2),
            "profit": round(profit, 2),
            "entry": entry,  # 0=开仓, 1=平仓
            "id": str(deal.ticket),
        })

    logger.info(f"Formatted {len(formatted)} MT5 trades, realized PnL (close deals): {realized_pnl:.2f}")
    return sorted(formatted, key=lambda x: x["timestamp"], reverse=True)


def _calculate_stats(binance_trades, mt5_trades, binance_realized_pnl=0.0, binance_funding_fee=0.0):
    """计算交易统计数据（含资金费汇总）

    MT5已实现盈亏: 仅统计平仓交易(entry==1)的native profit
    套利组合总盈亏: Binance已实现盈亏 + MT5已实现平仓盈亏
    """
    stats = {
        "totalVolume": 0,
        "totalAmount": 0,
        "takerAmount": 0,  # 吃单成交额
        "makerAmount": 0,  # 挂单成交额
        "totalFees": 0,
        "bnbFees": 0,  # BNB手续费
        "realizedPnL": binance_realized_pnl,  # 使用从income API获取的已实现盈亏
        "fundingFee": binance_funding_fee,     # Binance资金费汇总（FUNDING_FEE）
        "mt5Volume": 0,  # MT5成交量
        "mt5Amount": 0,  # MT5成交额
        "mt5OvernightFee": 0,
        "mt5Fee": 0,
        "mt5RealizedPnL": 0,
    }

    # 计算Binance统计
    for trade in binance_trades:
        qty = trade.get("quantity", 0)
        amount = trade.get("amount", 0)
        fee_usdt = trade.get("fee", 0)         # USDT手续费
        fee_bnb = trade.get("fee_bnb", 0)      # BNB手续费
        is_maker = trade.get("maker", False)

        stats["totalVolume"] += qty
        stats["totalAmount"] += amount

        # 区分吃单和挂单成交额
        if is_maker:
            stats["makerAmount"] += amount
        else:
            stats["takerAmount"] += amount

        stats["totalFees"] += fee_usdt        # 只累计USDT手续费
        stats["bnbFees"] += fee_bnb           # BNB手续费单独汇总

    # 计算MT5统计
    for trade in mt5_trades:
        qty = trade.get("quantity", 0)
        amount = trade.get("amount", 0)
        fee = trade.get("fee", 0)
        overnight_fee = trade.get("overnight_fee", 0)
        profit = trade.get("profit", 0)
        entry = trade.get("entry", 0)  # 0=开仓, 1=平仓, 2=余额充值

        # 只统计真实交易（开仓/平仓，排除余额充值entry==2）
        if entry not in (0, 1):
            continue

        stats["mt5Volume"] += qty
        stats["mt5Amount"] += amount
        stats["mt5Fee"] += fee

        # MT5过夜费（swap）在每笔deal中都有，需全部汇总
        if overnight_fee != 0:
            stats["mt5OvernightFee"] += overnight_fee

        # 只有平仓交易(entry==1)的profit才是已实现平仓盈亏（MT5平台直接提供）
        if entry == 1:
            stats["mt5RealizedPnL"] += profit

    stats["totalVolume"] = round(stats["totalVolume"], 4)
    stats["totalAmount"] = round(stats["totalAmount"], 2)
    stats["takerAmount"] = round(stats["takerAmount"], 2)
    stats["makerAmount"] = round(stats["makerAmount"], 2)
    stats["totalFees"] = round(stats["totalFees"], 2)
    stats["bnbFees"] = round(stats["bnbFees"], 6)
    stats["mt5Volume"] = round(stats["mt5Volume"], 4)
    stats["mt5Amount"] = round(stats["mt5Amount"], 2)
    stats["mt5Fee"] = round(stats["mt5Fee"], 2)
    stats["mt5OvernightFee"] = round(stats["mt5OvernightFee"], 2)
    stats["mt5RealizedPnL"] = round(stats["mt5RealizedPnL"], 2)

    logger.info(f"Stats calculated: Binance trades={len(binance_trades)}, MT5 trades={len(mt5_trades)}, "
                f"Binance realizedPnL={stats['realizedPnL']:.2f}, fundingFee={stats['fundingFee']:.4f}, "
                f"bnbFees={stats['bnbFees']:.6f} BNB, MT5 realizedPnL={stats['mt5RealizedPnL']:.2f}, "
                f"MT5 overnightFee={stats['mt5OvernightFee']:.2f}")
    return stats


"""Profit Chart Summary endpoint — replaces per-day realtime loop."""
from fastapi import Query as FQuery
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
from collections import defaultdict


@router.get("/profit-chart-summary")
async def get_profit_chart_summary(
    start: str = FQuery(..., description="Start date YYYY-MM-DD (Beijing)"),
    end:   str = FQuery(None, description="End date YYYY-MM-DD (Beijing, inclusive)"),
    granularity: str = FQuery("day", description="day | week | month"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    收益图表聚合接口 — 低频高效版本。

    关键优化：
    - 直接调 Binance /fapi/v1/income（全期间分7天段拉取后内存聚合）
    - 直接调 MT5 Bridge /mt5/history/deals（一次拉取后内存过滤）
    - API 调用次数：~39次（Binance） + 1次（MT5）
    - 避免了原 V2 实现的 N天 × 7对 × 3类型 = 数千次调用

    日收益公式：realized_pnl + mt5_realized + funding_fee + mt5_overnight + unrealized_pnl
    """
    from app.services.binance_client import BinanceFuturesClient
    from app.core.proxy_utils import build_proxy_url
    from app.models.mt5_client import MT5Client
    from sqlalchemy import text as sa_text
    import os, httpx

    cst = _tz(offset=_td(hours=8))
    now_cst = _dt.now(tz=cst)

    def parse_date(s, default):
        if not s:
            return default
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return _dt.strptime(s, fmt).replace(tzinfo=cst)
            except ValueError:
                continue
        return default

    start_dt = parse_date(start, now_cst - _td(days=7))
    end_dt   = parse_date(end, now_cst)
    end_dt   = end_dt.replace(hour=23, minute=59, second=59)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp()   * 1000)
    # Binance income max window = 7 days; use 6d23h59m to be safe
    CHUNK_MS = 6 * 24 * 60 * 60 * 1000 + 23 * 60 * 60 * 1000 + 59 * 60 * 1000

    accounts, _ = await _get_user_accounts(db, current_user.user_id)
    if not accounts:
        return {"data": [], "summary": {}}

    # date_key -> {realized, funding, mt5_pnl, mt5_overnight, unrealized}
    day_data: dict = defaultdict(lambda: {
        "realized": 0.0, "funding": 0.0,
        "mt5_pnl": 0.0, "mt5_overnight": 0.0, "unrealized": 0.0
    })

    # ── 1. Binance income (platform_id=1) ────────────────────────────────────
    binance_accs = [a for a in accounts if a.platform_id == 1]
    for acc in binance_accs:
        client = BinanceFuturesClient(
            acc.api_key, acc.api_secret,
            proxy_url=build_proxy_url(acc.proxy_config)
        )
        try:
            for income_type, field in [("REALIZED_PNL", "realized"), ("FUNDING_FEE", "funding")]:
                cs = start_ms
                while cs < end_ms:
                    ce = min(cs + CHUNK_MS, end_ms)
                    try:
                        items = await client.get_income(
                            symbol=None, income_type=income_type,
                            start_time=cs, end_time=ce, limit=1000,
                        )
                        for item in items:
                            t_cst = _dt.fromtimestamp(int(item.get("time", 0)) / 1000, tz=cst)
                            dk = t_cst.strftime("%Y-%m-%d")
                            day_data[dk][field] += float(item.get("income", 0))
                    except Exception as e:
                        logger.warning(f"[profit-chart] {income_type} chunk error: {e}")
                    cs = ce + 1
        except Exception as e:
            logger.error(f"[profit-chart] Binance {acc.account_name}: {e}")
        finally:
            await client.close()

    # ── 2. MT5 deals (platform_id 2/3, is_mt5_account) ──────────────────────
    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
    api_key_mt5 = os.getenv("MT5_API_KEY", "")
    mt5_headers = {"X-Api-Key": api_key_mt5} if api_key_mt5 else {}

    mt5_accs = [a for a in accounts if a.is_mt5_account and a.platform_id in (2, 3)]
    for acc in mt5_accs:
        try:
            res = await db.execute(
                __import__("sqlalchemy").select(MT5Client.bridge_service_port).where(
                    MT5Client.account_id == acc.account_id,
                    MT5Client.is_active == True,
                    MT5Client.is_system_service == False,
                    MT5Client.bridge_service_port.isnot(None),
                ).order_by(MT5Client.priority).limit(1)
            )
            port = res.scalar_one_or_none()
            if not port:
                continue

            total_days = max(1, int((end_dt - start_dt).total_seconds() / 86400) + 2)
            total_days = min(total_days, 365)
            start_ts = start_ms / 1000
            end_ts   = end_ms   / 1000

            async with httpx.AsyncClient(timeout=15.0) as hc:
                resp = await hc.get(
                    f"{bridge_host}:{port}/mt5/history/deals",
                    headers=mt5_headers, params={"days": total_days}
                )
                if resp.status_code != 200:
                    continue
                deals = resp.json().get("deals", [])

            for deal in deals:
                t = deal.get("time", 0)
                if not (start_ts <= t <= end_ts):
                    continue
                if not deal.get("symbol"):
                    continue
                entry = int(deal.get("entry", 2))
                if entry not in (0, 1):
                    continue
                dk = _dt.fromtimestamp(t, tz=cst).strftime("%Y-%m-%d")
                swap = float(deal.get("swap", 0))
                if swap != 0:
                    day_data[dk]["mt5_overnight"] += swap
                if entry == 1:
                    day_data[dk]["mt5_pnl"] += float(deal.get("profit", 0))
        except Exception as e:
            logger.error(f"[profit-chart] MT5 {acc.account_name}: {e}")

    # ── 3. Unrealized PnL from account_snapshots (last per day) ─────────────
    try:
        snap_res = await db.execute(sa_text("""
            SELECT
                to_char(
                    date_trunc('day', s.timestamp) AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai',
                    'YYYY-MM-DD'
                ) AS dk,
                COALESCE(SUM(last_v), 0) AS unrealized
            FROM (
                SELECT DISTINCT ON (a.account_id, date_trunc('day', s.timestamp))
                    a.account_id,
                    date_trunc('day', s.timestamp) AS day,
                    s.unrealized_pnl AS last_v
                FROM account_snapshots s
                JOIN accounts a ON a.account_id = s.account_id
                WHERE a.user_id = :uid
                  AND s.timestamp >= :st AND s.timestamp <= :en
                ORDER BY a.account_id, date_trunc('day', s.timestamp), s.timestamp DESC
            ) t
            GROUP BY dk ORDER BY dk
        """), {"uid": str(current_user.user_id), "st": start_dt, "en": end_dt})
        for row in snap_res:
            day_data[row.dk]["unrealized"] = float(row.unrealized)
    except Exception as e:
        logger.warning(f"[profit-chart] unrealized snapshot error: {e}")

    # ── 4. Aggregate by granularity ──────────────────────────────────────────
    def period_key(dk: str) -> str:
        d = _dt.strptime(dk, "%Y-%m-%d")
        if granularity == "week":
            return (d - _td(days=d.weekday())).strftime("%Y-%m-%d")
        if granularity == "month":
            return d.strftime("%Y-%m")
        return dk

    period_agg: dict = defaultdict(lambda: {
        "realized": 0.0, "funding": 0.0,
        "mt5_pnl": 0.0, "mt5_overnight": 0.0, "unrealized": 0.0
    })
    start_key = start_dt.strftime("%Y-%m-%d")
    end_key   = end_dt.strftime("%Y-%m-%d")
    for dk in sorted(dk for dk in day_data if start_key <= dk <= end_key):
        pk = period_key(dk)
        for k in ("realized", "funding", "mt5_pnl", "mt5_overnight"):
            period_agg[pk][k] += day_data[dk][k]
        period_agg[pk]["unrealized"] = day_data[dk]["unrealized"]  # last day wins

    # ── 5. Build output ──────────────────────────────────────────────────────
    cum = 0.0
    data_points = []
    for pk in sorted(period_agg):
        ag = period_agg[pk]
        pnl = (ag["realized"] + ag["funding"] +
               ag["mt5_pnl"] + ag["mt5_overnight"] + ag["unrealized"])
        cum += pnl
        data_points.append({
            "Period":        pk + "T00:00:00",
            "PnL":           round(pnl, 4),
            "RealizedPnL":   round(ag["realized"], 4),
            "FundingFee":    round(ag["funding"], 4),
            "Mt5PnL":        round(ag["mt5_pnl"], 4),
            "Mt5Overnight":  round(ag["mt5_overnight"], 4),
            "UnrealizedPnL": round(ag["unrealized"], 4),
            "CumPnL":        round(cum, 4),
        })

    last_unrealized = (
        period_agg[sorted(period_agg)[-1]]["unrealized"] if period_agg else 0.0
    )
    summary_out = {
        "total_pnl":      round(cum, 4),
        "realized_pnl":   round(sum(a["realized"]     for a in period_agg.values()), 4),
        "funding_fee":    round(sum(a["funding"]       for a in period_agg.values()), 4),
        "mt5_pnl":        round(sum(a["mt5_pnl"]       for a in period_agg.values()), 4),
        "mt5_overnight":  round(sum(a["mt5_overnight"]  for a in period_agg.values()), 4),
        "unrealized_pnl": round(last_unrealized, 4),
        "net_profit":     round(cum, 4),
        "total_fee":      0,
        "total_trades":   len(data_points),
    }
    return {"data": data_points, "summary": summary_out}
