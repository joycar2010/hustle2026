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
from app.services.order_executor import order_executor
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
            # Binance maker fee ~0.02%, Bybit MT5 ~0.01% estimate
            fee = amount * 0.0002 if is_binance else amount * 0.0001

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
    """Place a manual order on a single exchange with auto-price logic"""
    try:
        # Get user accounts
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)

        # Find matching account
        account = None
        if req.account_id:
            account = accounts_map.get(req.account_id)
        else:
            # Auto-select first matching platform account
            for acc in accounts:
                if req.exchange == "binance" and acc.platform_id == 1 and acc.is_active:
                    account = acc
                    break
                if req.exchange == "bybit" and acc.platform_id == 2 and acc.is_active:
                    account = acc
                    break

        if not account:
            raise HTTPException(status_code=404, detail=f"No active {req.exchange} account found")

        # Get current market prices
        if req.exchange == "binance":
            quote = await market_data_service.get_binance_quote("XAUUSDT")
            symbol = "XAUUSDT"
            # buy: bid + 0.01, sell: ask - 0.01
            price = round(quote.bid_price + 0.01, 2) if req.side == "buy" else round(quote.ask_price - 0.01, 2)
            position_side = "LONG" if req.side == "buy" else "SHORT"
            result = await order_executor.place_binance_order(
                account, symbol, req.side.upper(), "LIMIT", req.quantity, price, position_side=position_side
            )
        else:
            quote = await market_data_service.get_bybit_quote("XAUUSD.s")
            symbol = "XAUUSD.s"
            price = round(quote.bid_price + 0.01, 2) if req.side == "buy" else round(quote.ask_price - 0.01, 2)
            result = await order_executor.place_bybit_order(
                account, symbol, req.side, "Limit", str(req.quantity), str(price)
            )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Order failed"))

        # Save order to database
        order_record = OrderRecord(
            account_id=account.account_id,
            symbol=symbol,
            order_side=req.side.lower(),
            order_type="limit",
            price=price,
            qty=req.quantity,
            status="new",
            source="manual",
            platform_order_id=str(result.get("order_id", "")),
        )
        db.add(order_record)
        await db.commit()

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual/close-all")
async def close_all_positions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close all open positions at market price on both exchanges"""
    try:
        accounts, _ = await _get_user_accounts(db, current_user.user_id)
        results = []

        for account in accounts:
            if not account.is_active:
                continue

            if account.platform_id == 1:
                # Binance: get positions and close each
                from app.services.binance_client import BinanceFuturesClient
                client = BinanceFuturesClient(account.api_key, account.api_secret)
                try:
                    positions = await client.get_position_risk("XAUUSDT")
                    for pos in positions:
                        amt = float(pos.get("positionAmt", 0))
                        if amt == 0:
                            continue
                        side = "SELL" if amt > 0 else "BUY"
                        position_side = "LONG" if amt > 0 else "SHORT"
                        qty = abs(amt)
                        quote = await market_data_service.get_binance_quote("XAUUSDT")
                        price = round(quote.ask_price - 0.01, 2) if side == "SELL" else round(quote.bid_price + 0.01, 2)
                        r = await order_executor.place_binance_order(
                            account, "XAUUSDT", side, "LIMIT", qty, price, position_side=position_side
                        )
                        # Save order to database
                        if r.get("success"):
                            order_record = OrderRecord(
                                account_id=account.account_id,
                                symbol="XAUUSDT",
                                order_side=side.lower(),
                                order_type="limit",
                                price=price,
                                qty=qty,
                                status="new",
                                source="manual",
                                platform_order_id=str(r.get("order_id", "")),
                            )
                            db.add(order_record)
                        results.append({"exchange": "binance", "account": account.account_name, **r})
                finally:
                    await client.close()

            elif account.platform_id == 2:
                # Bybit MT5: get positions and close each
                loop = asyncio.get_event_loop()
                mt5_client = market_data_service.mt5_client
                positions = await loop.run_in_executor(
                    None, lambda: mt5.positions_get(symbol="XAUUSD.s")
                )
                if positions:
                    quote = await market_data_service.get_bybit_quote("XAUUSD.s")
                    for pos in positions:
                        # Close opposite side at counter price
                        side = "Sell" if pos.type == mt5.POSITION_TYPE_BUY else "Buy"
                        price = round(quote.ask_price - 0.01, 2) if side == "Sell" else round(quote.bid_price + 0.01, 2)
                        r = await order_executor.place_bybit_order(
                            account, "XAUUSD.s", side, "Limit", str(pos.volume), str(price)
                        )
                        # Save order to database
                        if r.get("success"):
                            order_record = OrderRecord(
                                account_id=account.account_id,
                                symbol="XAUUSD.s",
                                order_side=side.lower(),
                                order_type="limit",
                                price=price,
                                qty=pos.volume,
                                status="new",
                                source="manual",
                                platform_order_id=str(r.get("order_id", "")),
                            )
                            db.add(order_record)
                        results.append({"exchange": "bybit", "account": account.account_name, **r})

        # Commit all order records
        await db.commit()
        return {"success": True, "results": results}
    except Exception as e:
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
                            commission = float(trade.get("commission", 0))
                            commission_asset = trade.get("commissionAsset", "USDT")

                            # Convert commission to USDT if needed
                            if commission_asset != "USDT":
                                # For simplicity, if commission is in other asset, estimate in USDT
                                qty = float(trade.get("qty", 0))
                                price = float(trade.get("price", 0))
                                commission = qty * price * 0.0002  # Fallback to estimate

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
                    loop = asyncio.get_event_loop()
                    history_deals = await loop.run_in_executor(
                        None,
                        lambda: mt5.history_deals_get(
                            datetime.fromtimestamp(start_time / 1000),
                            datetime.fromtimestamp(end_time / 1000)
                        )
                    )

                    if history_deals:
                        for deal in history_deals:
                            if deal.symbol != "XAUUSD.s":
                                continue

                            # Check if deal already exists
                            existing = await db.execute(
                                select(OrderRecord).filter(
                                    OrderRecord.account_id == account.account_id,
                                    OrderRecord.platform_order_id == str(deal.order)
                                )
                            )
                            if existing.scalar_one_or_none():
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
                                platform_order_id=str(deal.order),
                                create_time=datetime.fromtimestamp(deal.time),
                            )
                            db.add(order_record)
                            synced_count += 1

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
    """Cancel all pending orders on both exchanges and mark database orders as manually processed"""
    try:
        accounts, _ = await _get_user_accounts(db, current_user.user_id)
        results = []

        for account in accounts:
            if not account.is_active:
                continue

            if account.platform_id == 1:
                from app.services.binance_client import BinanceFuturesClient
                client = BinanceFuturesClient(account.api_key, account.api_secret)
                try:
                    r = await client.cancel_all_orders("XAUUSDT")
                    results.append({"exchange": "binance", "account": account.account_name, "success": True, "data": r})
                except Exception as e:
                    results.append({"exchange": "binance", "account": account.account_name, "success": False, "error": str(e)})
                finally:
                    await client.close()

            elif account.platform_id == 2:
                loop = asyncio.get_event_loop()
                orders = await loop.run_in_executor(
                    None, lambda: mt5.orders_get(symbol="XAUUSD.s")
                )
                if orders:
                    for order in orders:
                        r = await order_executor.cancel_bybit_order(account, "XAUUSD.s", str(order.ticket))
                        results.append({"exchange": "bybit", "account": account.account_name, **r})
                else:
                    results.append({"exchange": "bybit", "account": account.account_name, "success": True, "data": "no orders"})

        # Mark all pending/new orders in database as manually_processed
        account_ids = [acc.account_id for acc in accounts if acc.is_active]
        if account_ids:
            pending_orders_result = await db.execute(
                select(OrderRecord).filter(
                    OrderRecord.account_id.in_(account_ids),
                    OrderRecord.status.in_(["new", "pending"])
                )
            )
            pending_orders = pending_orders_result.scalars().all()
            for order in pending_orders:
                order.status = "manually_processed"
            await db.commit()

        return {"success": True, "results": results, "db_orders_processed": len(pending_orders) if account_ids else 0}
    except Exception as e:
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

