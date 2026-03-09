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
import asyncio
import MetaTrader5 as mt5
import logging
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


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
        if is_binance:
            # Binance: Only allow XAUUSDT
            if not order.symbol or order.symbol.upper() != 'XAUUSDT':
                continue
        elif is_mt5:
            # MT5: Only allow XAUUSD.s
            if not order.symbol or order.symbol != 'XAUUSD.s':
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
            "platform": "Bybit MT5" if is_mt5 else "Binance",
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
                    platform_name = "Binance"
                elif acc.platform_id == 2:
                    platform_name = "Bybit MT5" if acc.is_mt5_account else "Bybit"

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


@router.get("/orders/realtime")
async def get_realtime_pending_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    实时从Binance API获取挂单（不依赖数据库）

    返回所有未成交的挂单
    """
    try:
        from app.utils.time_utils import utc_ms_to_beijing

        # 获取用户账户
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return []

        # 实时获取 Binance 挂单
        pending_orders = []
        for account in accounts:
            if account.platform_id == 1:  # Binance
                try:
                    from app.services.binance_client import BinanceFuturesClient
                    client = BinanceFuturesClient(account.api_key, account.api_secret)
                    try:
                        # 获取所有未成交订单
                        open_orders = await client.get_open_orders(symbol="XAUUSDT")

                        for order in open_orders:
                            # 转换时间为北京时间
                            order_time = order.get("time", 0)
                            beijing_time = utc_ms_to_beijing(order_time)

                            pending_orders.append({
                                "id": str(order.get("orderId")),
                                "timestamp": beijing_time,
                                "exchange": "Binance",
                                "side": order.get("side", "").lower(),
                                "quantity": float(order.get("origQty", 0)),
                                "price": float(order.get("price", 0)),
                                "status": order.get("status", "").lower(),
                                "symbol": order.get("symbol", ""),
                            })
                    finally:
                        await client.close()
                except Exception as e:
                    logger.error(f"Failed to fetch Binance open orders: {str(e)}")

        # 按时间降序排序
        pending_orders.sort(key=lambda x: x["timestamp"], reverse=True)

        return pending_orders
    except Exception as e:
        logger.error(f"Realtime pending orders error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


class ManualOrderRequest(BaseModel):
    exchange: str  # "binance" or "bybit"
    side: str      # "buy" or "sell"
    quantity: float
    account_id: Optional[str] = None


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

        # Find the account for the specified exchange
        target_account = None
        for account in accounts:
            if req.exchange == "binance" and account.platform_id == 1:
                target_account = account
                break
            elif req.exchange == "bybit" and account.platform_id == 2:
                target_account = account
                break

        if not target_account:
            raise HTTPException(status_code=404, detail=f"No {req.exchange} account found")

        # Get current market prices
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Determine price based on side and exchange
        if req.exchange == "binance":
            # Binance: 买入开多用bid价，卖出开空用ask价
            if req.side == "buy":
                price = spread_data.binance_quote.bid_price
            else:  # sell
                price = spread_data.binance_quote.ask_price
            symbol = "XAUUSDT"
        else:  # bybit
            # Bybit: 买入开多用bid价，卖出开空用ask价
            if req.side == "buy":
                price = spread_data.bybit_quote.bid_price
            else:  # sell
                price = spread_data.bybit_quote.ask_price
            symbol = "XAUUSD.s"

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
        else:  # bybit
            result = await order_executor.place_bybit_order(
                account=target_account,
                symbol=symbol,
                side="Buy" if req.side == "buy" else "Sell",
                order_type="Limit",
                quantity=str(req.quantity),
                price=str(price),
                close_position=False,
            )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Order failed"))

        return {
            "success": True,
            "exchange": req.exchange,
            "side": req.side,
            "quantity": req.quantity,
            "price": price,
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
                client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret)
                try:
                    positions = await client.get_position_risk("XAUUSDT")

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
                            symbol="XAUUSDT",
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
                positions = await loop.run_in_executor(None, mt5.positions_get, "XAUUSD.s")

                if positions:
                    for pos in positions:
                        volume = pos.volume
                        if volume == 0:
                            continue

                        # 多单用ask价平仓，空单用bid价平仓
                        if pos.type == mt5.POSITION_TYPE_BUY:  # LONG position
                            price = spread_data.bybit_quote.ask_price
                            side = "Sell"
                        else:  # SHORT position
                            price = spread_data.bybit_quote.bid_price
                            side = "Buy"

                        result = await order_executor.place_bybit_order(
                            account=bybit_account,
                            symbol="XAUUSD.s",
                            side=side,
                            order_type="Limit",
                            quantity=str(volume),
                            price=str(price),
                            close_position=True,
                        )

                        results.append({
                            "exchange": "bybit",
                            "position_type": "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT",
                            "quantity": volume,
                            "price": price,
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
                    client = BinanceFuturesClient(account.api_key, account.api_secret)
                    try:
                        trades = await client.get_user_trades(
                            symbol="XAUUSDT",
                            start_time=start_time,
                            end_time=end_time,
                            limit=500
                        )

                        for trade in trades:
                            # Skip non-XAUUSDT trades (including transfers)
                            symbol = trade.get("symbol", "")
                            if symbol.upper() != "XAUUSDT":
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

                        xauusd_count = 0
                        for deal in history_deals:
                            if deal.symbol != "XAUUSD.s":
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
                                  f"其中 {xauusd_count} 笔XAUUSD.s交易")
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
                client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret)
                try:
                    # Get all open orders
                    open_orders = await client.get_open_orders("XAUUSDT")

                    for order in open_orders:
                        order_id = order.get("orderId")
                        result = await order_executor.cancel_binance_order(
                            binance_account,
                            "XAUUSDT",
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
                orders = await loop.run_in_executor(None, mt5.orders_get, "XAUUSD.s")

                if orders:
                    for order in orders:
                        order_id = str(order.ticket)
                        result = await order_executor.cancel_bybit_order(
                            bybit_account,
                            "XAUUSD.s",
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    实时从平台获取交易历史（不依赖数据库）
    
    时间参数：北京时间（UTC+8）
    返回数据：统一转换为北京时间显示
    """
    try:
        from app.utils.time_utils import beijing_to_utc_ms, utc_ms_to_beijing, mt5_time_to_beijing
        
        # 转换查询时间：北京时间 → UTC毫秒时间戳
        try:
            start_utc_ms = beijing_to_utc_ms(start_time)
            end_utc_ms = beijing_to_utc_ms(end_time)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid time format: {str(e)}")
        
        # 获取用户账户
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"binanceTrades": [], "mt5Trades": [], "timeZone": "Asia/Shanghai (UTC+8)"}

        # 实时获取 Binance 订单和已实现盈亏
        binance_trades = []
        binance_realized_pnl = 0.0
        for account in accounts:
            if account.platform_id == 1:
                try:
                    trades = await _get_binance_trades_realtime(account, start_utc_ms, end_utc_ms)
                    binance_trades.extend(trades)
                    # 获取Binance已实现盈亏
                    pnl = await _get_binance_realized_pnl(account, start_utc_ms, end_utc_ms)
                    binance_realized_pnl += pnl
                except Exception as e:
                    logger.error(f"Binance trades error: {str(e)}")

        # 实时获取 MT5 订单
        mt5_trades = []
        for account in accounts:
            if account.platform_id == 2 and account.is_mt5_account:
                try:
                    trades = await _get_mt5_trades_realtime(account, start_utc_ms, end_utc_ms)
                    mt5_trades.extend(trades)
                except Exception as e:
                    logger.error(f"MT5 trades error: {str(e)}")

        # 格式化数据
        formatted_binance = _format_binance_trades(binance_trades)
        formatted_mt5 = _format_mt5_trades(mt5_trades)

        # 计算统计数据
        stats = _calculate_stats(formatted_binance, formatted_mt5, binance_realized_pnl)

        # 返回数据（字段名与前端期望一致）
        return {
            "accountTrades": formatted_binance,  # 前端期望的字段名
            "mt5Trades": formatted_mt5,
            "stats": stats,
            "timeZone": "Asia/Shanghai (UTC+8)"
        }
    except Exception as e:
        logger.error(f"Realtime history error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _get_binance_trades_realtime(account, start_time_ms, end_time_ms):
    """获取Binance交易历史（使用userTrades API获取准确的手续费）"""
    from app.services.binance_client import BinanceFuturesClient
    client = BinanceFuturesClient(account.api_key, account.api_secret)
    try:
        # 使用userTrades API获取交易历史（包含准确的手续费信息）
        trades = await client.get_user_trades(symbol="XAUUSDT", start_time=start_time_ms, end_time=end_time_ms, limit=1000)
        return [t for t in trades if t.get("symbol", "").upper() == "XAUUSDT"]
    finally:
        await client.close()


async def _get_binance_realized_pnl(account, start_time_ms, end_time_ms):
    """获取Binance已实现盈亏（使用income API获取准确的平仓盈亏）"""
    from app.services.binance_client import BinanceFuturesClient
    client = BinanceFuturesClient(account.api_key, account.api_secret)
    try:
        # 使用income API获取平仓盈亏（incomeType=REALIZED_PNL）
        income_data = await client.get_income(
            symbol="XAUUSDT",
            income_type="REALIZED_PNL",
            start_time=start_time_ms,
            end_time=end_time_ms,
            limit=1000
        )
        # 累加所有平仓盈亏
        total_pnl = sum(float(item.get("income", 0)) for item in income_data)
        logger.info(f"Binance realized PnL: {total_pnl:.2f} USDT ({len(income_data)} records)")
        return total_pnl
    except Exception as e:
        logger.error(f"Failed to get Binance realized PnL: {str(e)}")
        return 0.0
    finally:
        await client.close()


async def _get_mt5_trades_realtime(account, start_time_ms, end_time_ms):
    from app.services.market_service import market_data_service
    mt5_client = market_data_service.mt5_client
    if not mt5_client or not mt5_client.connected:
        if not mt5_client or not mt5_client.connect():
            logger.warning("MT5 client not connected")
            return []
    start_dt = datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_time_ms / 1000, tz=timezone.utc)
    logger.info(f"Fetching MT5 deals from {start_dt} to {end_dt}")
    loop = asyncio.get_event_loop()
    history_deals = await loop.run_in_executor(None, lambda: mt5.history_deals_get(start_dt, end_dt))
    if not history_deals:
        logger.warning("No MT5 deals found")
        return []
    filtered_deals = [d for d in history_deals if d.symbol == "XAUUSD.s"]
    logger.info(f"Found {len(filtered_deals)} MT5 deals for XAUUSD.s (total deals: {len(history_deals)})")
    return filtered_deals


def _format_binance_trades(trades):
    """格式化Binance交易数据"""
    from app.utils.time_utils import utc_ms_to_beijing
    formatted = []
    for trade in trades:
        # 获取交易时间
        trade_time = trade.get("time", 0)
        beijing_time = utc_ms_to_beijing(trade_time)

        # 获取手续费（userTrades API返回准确的commission）
        commission = abs(float(trade.get("commission", 0)))

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
            "account_name": "Binance",
            "symbol": "XAUUSDT",  # 交易对
            "product": "产品",  # 产品名称
            "side": side,
            "price": price,
            "quantity": quantity,
            "amount": round(amount, 2),  # 成交额
            "maker": is_maker,  # True=挂单，False=吃单
            "fee": round(commission, 2),  # 保留2位小数
            "id": str(trade.get("id")),
        })

    # 降序排序（最新的在最上面）
    return sorted(formatted, key=lambda x: x["timestamp"], reverse=True)


def _format_mt5_trades(deals):
    """格式化MT5交易数据"""
    from app.utils.time_utils import mt5_time_to_beijing
    formatted = []
    total_profit = 0.0
    for deal in deals:
        # MT5时间戳转北京时间
        beijing_time = mt5_time_to_beijing(deal.time)

        # 获取交易方向
        # MT5的deal.type: 0=BUY, 1=SELL
        if deal.type == 0:  # mt5.DEAL_TYPE_BUY
            side = "buy"
        elif deal.type == 1:  # mt5.DEAL_TYPE_SELL
            side = "sell"
        else:
            side = "unknown"

        # 获取价格和数量
        price = deal.price
        quantity = deal.volume
        amount = price * quantity  # 成交额

        # 获取手续费（优先使用commission字段）
        if hasattr(deal, 'commission') and deal.commission != 0:
            fee = abs(float(deal.commission))
        else:
            # 如果没有commission字段，显示0.00
            fee = 0.00

        # 获取盈亏（profit字段）
        profit = float(deal.profit) if hasattr(deal, 'profit') else 0.00
        total_profit += profit

        # 过夜费（暂时设为0，后续可以从其他地方获取）
        overnight_fee = 0.00

        formatted.append({
            "timestamp": beijing_time,
            "account_name": "Bybit MT5",
            "symbol": "XAUUSD.s",  # 交易对
            "product": "产品",  # 产品名称
            "side": side,
            "price": price,
            "quantity": quantity,
            "amount": round(amount, 2),  # 成交额
            "overnight_fee": round(overnight_fee, 2),  # 过夜费
            "fee": round(fee, 2),  # 保留2位小数
            "profit": round(profit, 2),  # 已实现盈亏
            "id": str(deal.ticket),
        })

    logger.info(f"Formatted {len(formatted)} MT5 trades, total profit: {total_profit:.2f}")
    # 降序排序（最新的在最上面）
    return sorted(formatted, key=lambda x: x["timestamp"], reverse=True)


def _calculate_stats(binance_trades, mt5_trades, binance_realized_pnl=0.0):
    """计算交易统计数据"""
    stats = {
        "totalVolume": 0,
        "totalAmount": 0,
        "takerAmount": 0,  # 吃单成交额
        "makerAmount": 0,  # 挂单成交额
        "totalFees": 0,
        "bnbFees": 0,  # BNB手续费
        "realizedPnL": binance_realized_pnl,  # 使用从income API获取的已实现盈亏
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
        fee = trade.get("fee", 0)
        is_maker = trade.get("maker", False)

        stats["totalVolume"] += qty
        stats["totalAmount"] += amount

        # 区分吃单和挂单成交额
        if is_maker:
            stats["makerAmount"] += amount
        else:
            stats["takerAmount"] += amount

        stats["totalFees"] += fee

    # 计算MT5统计
    for trade in mt5_trades:
        qty = trade.get("quantity", 0)
        amount = trade.get("amount", 0)
        fee = trade.get("fee", 0)
        overnight_fee = trade.get("overnight_fee", 0)
        profit = trade.get("profit", 0)  # 获取profit字段

        stats["mt5Volume"] += qty
        stats["mt5Amount"] += amount
        stats["mt5Fee"] += fee
        stats["mt5OvernightFee"] += overnight_fee
        stats["mt5RealizedPnL"] += profit  # 累加已实现盈亏
        stats["totalFees"] += fee

    logger.info(f"Stats calculated: Binance trades={len(binance_trades)}, MT5 trades={len(mt5_trades)}, "
                f"Binance realizedPnL={stats['realizedPnL']:.2f}, MT5 realizedPnL={stats['mt5RealizedPnL']:.2f}")
    return stats

