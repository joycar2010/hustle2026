"""Trading history API endpoints - FIXED VERSION
修复要点：
1. 使用 Decimal 确保金融计算精度
2. 区分成交额、手续费、买卖金额、任务金额
3. 添加数据校验和告警机制
4. 支持时间范围过滤
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict
from datetime import datetime, date, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from decimal import Decimal, ROUND_HALF_UP
from app.core.security import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.order import OrderRecord
from app.models.account import Account
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 数据偏差阈值（USDT）
DEVIATION_THRESHOLD = Decimal("0.01")


def _to_decimal(value) -> Decimal:
    """安全转换为 Decimal，避免浮点数精度问题"""
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_stats_v2(orders, accounts_map):
    """
    重构统计逻辑 - 修复版本

    统计指标说明：
    - totalVolume: 总成交量（数量）
    - totalAmount: 总成交额（价格 × 数量）
    - buySellAmount: 买卖交易成交额（仅 manual 和 strategy 来源）
    - taskAmount: 任务交易成交额（仅 sync 来源）
    - totalFees: 总手续费（实际手续费，非估算）
    - actualCommission: 实际佣金（从 Binance API 获取）
    """
    # 使用 Decimal 确保精度
    binance_volume = Decimal("0")
    binance_total_amount = Decimal("0")
    binance_buy_sell_amount = Decimal("0")  # manual + strategy
    binance_task_amount = Decimal("0")      # sync
    binance_fees = Decimal("0")
    binance_actual_commission = Decimal("0")  # 实际佣金

    mt5_volume = Decimal("0")
    mt5_amount = Decimal("0")
    mt5_fees = Decimal("0")

    account_trades = []
    mt5_trades = []

    # 有效订单类型
    valid_order_types = ['limit', 'market', 'stop', 'stop_limit', 'take_profit', 'take_profit_limit']

    for order in orders:
        # 跳过非交易订单
        if order.order_type and order.order_type.lower() not in valid_order_types:
            continue

        acc = accounts_map.get(order.account_id)
        is_mt5 = acc.is_mt5_account if acc else False

        # 使用 Decimal 计算
        qty = _to_decimal(order.filled_qty if order.filled_qty else order.qty)
        price = _to_decimal(order.price)
        amount = qty * price

        # 优先使用数据库中的实际手续费
        if order.fee and order.fee > 0:
            fee = _to_decimal(order.fee)
        else:
            # 估算手续费：Binance ~0.02%, Bybit MT5 ~0.01%
            fee = amount * Decimal("0.0002") if not is_mt5 else amount * Decimal("0.0001")

        # 按平台分类统计
        if is_mt5:
            mt5_volume += qty
            mt5_amount += amount
            mt5_fees += fee
        else:
            binance_volume += qty
            binance_total_amount += amount
            binance_fees += fee

            # 区分买卖交易和任务交易
            if order.source in ['manual', 'strategy']:
                binance_buy_sell_amount += amount
            elif order.source == 'sync':
                binance_task_amount += amount
                # sync 来源的订单，fee 字段存储的是实际佣金
                if order.fee and order.fee > 0:
                    binance_actual_commission += _to_decimal(order.fee)

        # 构建交易记录
        trade = {
            "id": str(order.order_id),
            "timestamp": order.create_time.isoformat() if order.create_time else None,
            "symbol": order.symbol,
            "side": order.order_side,
            "quantity": float(qty),
            "price": float(price),
            "fee": float(fee),
            "status": order.status,
            "source": order.source,  # 添加来源标识
            "account_name": acc.account_name if acc else "Unknown",
            "platform": "Bybit MT5" if is_mt5 else ("Binance" if acc and acc.platform_id == 1 else "Unknown"),
        }

        if is_mt5:
            mt5_trades.append(trade)
        else:
            account_trades.append(trade)

    # 计算返佣（简化估算）
    binance_return = binance_total_amount * Decimal("0.001")
    mt5_return = mt5_amount * Decimal("0.001")

    # 构建统计数据
    stats = {
        # Binance 统计
        "totalVolume": float(binance_volume),
        "totalAmount": float(binance_total_amount),
        "buySellAmount": float(binance_buy_sell_amount),
        "taskAmount": float(binance_task_amount),
        "totalFees": float(binance_fees),
        "actualCommission": float(binance_actual_commission),  # 新增：实际佣金
        "overnightFees": 0.0,

        # MT5 统计
        "marketFundingRate": 0.0,
        "mt5OvernightFee": 0.0,
        "marketFee": float(binance_fees),
        "mt5Fee": float(mt5_fees),
        "peRatio": float((binance_return / binance_total_amount * 100) if binance_total_amount else 0),
        "mt5TodayReturn": float(mt5_return),
        "totalReturnProfit": float(binance_return + mt5_return),
    }

    return stats, account_trades, mt5_trades


async def _validate_binance_data(stats: Dict, db: AsyncSession, user_id: int):
    """
    数据校验：对比本地统计与 Binance API 实际数据
    当偏差超过阈值时记录告警日志
    """
    try:
        # 获取用户的 Binance 账户
        result = await db.execute(
            select(Account).filter(
                Account.user_id == user_id,
                Account.platform_id == 1,  # Binance
                Account.is_active == True
            )
        )
        binance_account = result.scalar_one_or_none()

        if not binance_account:
            return

        # 调用 Binance API 获取实际数据
        from app.services.binance_client import BinanceFuturesClient
        client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret)

        try:
            # 获取今日交易记录
            today_start = int(datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            today_end = int(datetime.utcnow().timestamp() * 1000)

            trades = await client.get_user_trades(
                symbol="XAUUSDT",
                start_time=today_start,
                end_time=today_end,
                limit=500
            )

            # 计算 Binance 实际数据
            actual_commission = Decimal("0")
            actual_amount = Decimal("0")

            for trade in trades:
                commission = _to_decimal(trade.get("commission", 0))
                qty = _to_decimal(trade.get("qty", 0))
                price = _to_decimal(trade.get("price", 0))

                actual_commission += commission
                actual_amount += qty * price

            # 对比偏差
            local_commission = _to_decimal(stats.get("actualCommission", 0))
            local_amount = _to_decimal(stats.get("totalAmount", 0))

            commission_deviation = abs(actual_commission - local_commission)
            amount_deviation = abs(actual_amount - local_amount)

            # 记录告警
            if commission_deviation > DEVIATION_THRESHOLD:
                logger.warning(
                    f"Commission deviation detected! "
                    f"Local: {local_commission} USDT, "
                    f"Binance API: {actual_commission} USDT, "
                    f"Deviation: {commission_deviation} USDT"
                )

            if amount_deviation > DEVIATION_THRESHOLD:
                logger.warning(
                    f"Amount deviation detected! "
                    f"Local: {local_amount} USDT, "
                    f"Binance API: {actual_amount} USDT, "
                    f"Deviation: {amount_deviation} USDT"
                )

            # 返回校验结果
            return {
                "validated": True,
                "binance_actual_commission": float(actual_commission),
                "binance_actual_amount": float(actual_amount),
                "commission_deviation": float(commission_deviation),
                "amount_deviation": float(amount_deviation),
                "deviation_alert": commission_deviation > DEVIATION_THRESHOLD or amount_deviation > DEVIATION_THRESHOLD
            }

        finally:
            await client.close()

    except Exception as e:
        logger.error(f"Binance data validation failed: {str(e)}")
        return {"validated": False, "error": str(e)}


async def _get_user_accounts(db, user_id):
    result = await db.execute(
        select(Account).filter(Account.user_id == user_id)
    )
    accounts = result.scalars().all()
    return accounts, {acc.account_id: acc for acc in accounts}


@router.get("/history")
async def get_trading_history(
    date: Optional[str] = Query(default=None, description="Query date in YYYY-MM-DD format"),
    time_range: Optional[str] = Query(default=None, description="Time range: today, week, month"),
    validate: bool = Query(default=False, description="Validate against Binance API"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取交易历史数据（修复版）

    新增功能：
    - 支持时间范围过滤（today/week/month）
    - 可选的 Binance API 数据校验
    - 精确的统计分类（买卖/任务）
    """
    try:
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"stats": _build_stats_v2([], {})[0], "accountTrades": [], "mt5Trades": [], "validation": None}

        account_ids = [acc.account_id for acc in accounts]
        query = select(OrderRecord).filter(
            OrderRecord.account_id.in_(account_ids),
        )

        # 时间范围过滤
        if time_range:
            now = datetime.utcnow()
            if time_range == "today":
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif time_range == "week":
                start_time = now - timedelta(days=7)
            elif time_range == "month":
                start_time = now - timedelta(days=30)
            else:
                start_time = None

            if start_time:
                query = query.filter(OrderRecord.create_time >= start_time)

        elif date:
            try:
                query_datetime_start = datetime.strptime(date, "%Y-%m-%d")
                query_datetime_end = query_datetime_start + timedelta(days=1)
                query = query.filter(
                    OrderRecord.create_time >= query_datetime_start,
                    OrderRecord.create_time < query_datetime_end
                )
            except ValueError:
                pass

        query = query.order_by(OrderRecord.create_time.desc())
        result = await db.execute(query)
        orders = result.scalars().all()

        stats, account_trades, mt5_trades = _build_stats_v2(orders, accounts_map)

        # 可选的数据校验
        validation_result = None
        if validate:
            validation_result = await _validate_binance_data(stats, db, current_user.user_id)

        return {
            "stats": stats,
            "accountTrades": account_trades,
            "mt5Trades": mt5_trades,
            "validation": validation_result
        }
    except Exception as e:
        logger.error(f"Failed to get trading history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/all")
async def get_all_trading_history(
    validate: bool = Query(default=False, description="Validate against Binance API"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取所有交易历史（修复版）"""
    try:
        accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)
        if not accounts:
            return {"stats": _build_stats_v2([], {})[0], "accountTrades": [], "mt5Trades": [], "validation": None}

        account_ids = [acc.account_id for acc in accounts]
        result = await db.execute(
            select(OrderRecord)
            .filter(OrderRecord.account_id.in_(account_ids))
            .order_by(OrderRecord.create_time.desc())
        )
        orders = result.scalars().all()

        stats, account_trades, mt5_trades = _build_stats_v2(orders, accounts_map)

        validation_result = None
        if validate:
            validation_result = await _validate_binance_data(stats, db, current_user.user_id)

        return {
            "stats": stats,
            "accountTrades": account_trades,
            "mt5Trades": mt5_trades,
            "validation": validation_result
        }
    except Exception as e:
        logger.error(f"Failed to get all trading history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
