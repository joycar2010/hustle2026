"""
Position Monitor Service
Monitors open positions and auto-closes based on conditions
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.arbitrage import ArbitrageTask, TaskStatus
from app.models.order import Order, OrderStatus
from app.services.market_service import MarketDataService
from app.services.order_executor import OrderExecutor
from app.core.database import get_db
import logging

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Monitors positions and executes auto-close logic"""

    def __init__(self):
        self.market_service = MarketDataService()
        self.order_executor = OrderExecutor()
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self):
        """Start position monitoring"""
        if self.monitoring:
            logger.warning("Position monitoring already running")
            return

        self.monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Position monitoring started")

    async def stop_monitoring(self):
        """Stop position monitoring"""
        if not self.monitoring:
            return

        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
        logger.info("Position monitoring stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        try:
            while self.monitoring:
                # 使用单个数据库会话，而不是每次循环都创建新的
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    try:
                        await self._check_all_positions(db)
                    except Exception as e:
                        logger.error(f"Error in position monitoring: {e}")

                await asyncio.sleep(2)  # Check every 2 seconds

        except asyncio.CancelledError:
            logger.info("Position monitoring cancelled")

    async def _check_all_positions(self, db: AsyncSession):
        """Check all open positions"""
        # Get all open arbitrage tasks
        result = await db.execute(
            select(ArbitrageTask).where(
                ArbitrageTask.status == TaskStatus.OPEN
            )
        )
        tasks = result.scalars().all()

        for task in tasks:
            await self._check_position(task, db)

    async def _check_position(self, task: ArbitrageTask, db: AsyncSession):
        """Check individual position and close if conditions met"""
        try:
            # Get current market data
            market_data = await self.market_service.get_market_data(task.symbol)
            if not market_data:
                return

            # Calculate current P&L
            current_pnl = await self._calculate_current_pnl(task, market_data, db)

            # Check close conditions
            should_close, reason = await self._should_close_position(task, current_pnl, db)

            if should_close:
                logger.info(f"Closing position for task {task.id}, reason: {reason}")
                await self._close_position(task, reason, db)

        except Exception as e:
            logger.error(f"Error checking position for task {task.id}: {e}")

    async def _calculate_current_pnl(self, task: ArbitrageTask, market_data: Dict, db: AsyncSession) -> float:
        """Calculate current unrealized P&L"""
        # Get entry prices from orders
        result = await db.execute(
            select(Order).where(
                and_(
                    Order.task_id == task.id,
                    Order.status == OrderStatus.FILLED
                )
            )
        )
        orders = result.scalars().all()

        binance_order = next((o for o in orders if o.platform == "binance"), None)
        bybit_order = next((o for o in orders if o.platform == "bybit"), None)

        if not binance_order or not bybit_order:
            return 0

        # Calculate P&L based on direction
        if task.direction == "forward":
            # Bought on Binance, sold on Bybit
            binance_entry = float(binance_order.avg_price)
            bybit_entry = float(bybit_order.avg_price)
            binance_current = market_data.get("binance_ask", binance_entry)
            bybit_current = market_data.get("bybit_bid", bybit_entry)

            # P&L = (sell_exit - sell_entry) - (buy_exit - buy_entry)
            pnl = (bybit_current - bybit_entry) - (binance_current - binance_entry)
            pnl *= float(task.quantity)

        else:  # reverse
            # Sold on Binance, bought on Bybit
            binance_entry = float(binance_order.avg_price)
            bybit_entry = float(bybit_order.avg_price)
            binance_current = market_data.get("binance_bid", binance_entry)
            bybit_current = market_data.get("bybit_ask", bybit_entry)

            # P&L = (sell_exit - sell_entry) - (buy_exit - buy_entry)
            pnl = (binance_current - binance_entry) - (bybit_current - bybit_entry)
            pnl *= float(task.quantity)

        return pnl

    async def _should_close_position(
        self,
        task: ArbitrageTask,
        current_pnl: float,
        db: AsyncSession
    ) -> tuple[bool, str]:
        """Determine if position should be closed"""
        # Check profit target
        profit_target = task.params.get("profit_target")
        if profit_target and current_pnl >= profit_target:
            return True, f"Profit target reached: {current_pnl:.2f} >= {profit_target}"

        # Check stop loss
        stop_loss = task.params.get("stop_loss")
        if stop_loss and current_pnl <= -abs(stop_loss):
            return True, f"Stop loss triggered: {current_pnl:.2f} <= {-abs(stop_loss)}"

        # Check time limit
        max_hold_time = task.params.get("max_hold_minutes")
        if max_hold_time:
            hold_time = (datetime.utcnow() - task.created_at).total_seconds() / 60
            if hold_time >= max_hold_time:
                return True, f"Max hold time reached: {hold_time:.1f} >= {max_hold_time} minutes"

        # Check spread reversal
        check_spread_reversal = task.params.get("close_on_spread_reversal", True)
        if check_spread_reversal:
            market_data = await self.market_service.get_market_data(task.symbol)
            if market_data:
                current_direction = market_data.get("direction")
                # If spread reversed, close position
                if task.direction == "forward" and current_direction == "reverse":
                    return True, "Spread reversed to opposite direction"
                elif task.direction == "reverse" and current_direction == "forward":
                    return True, "Spread reversed to opposite direction"

        return False, ""

    async def _close_position(self, task: ArbitrageTask, reason: str, db: AsyncSession):
        """Close position by executing reverse orders"""
        try:
            # Get original orders
            result = await db.execute(
                select(Order).where(
                    and_(
                        Order.task_id == task.id,
                        Order.status == OrderStatus.FILLED
                    )
                )
            )
            orders = result.scalars().all()

            binance_order = next((o for o in orders if o.platform == "binance"), None)
            bybit_order = next((o for o in orders if o.platform == "bybit"), None)

            if not binance_order or not bybit_order:
                logger.error(f"Cannot find orders for task {task.id}")
                return

            # Execute reverse orders
            if task.direction == "forward":
                # Original: buy Binance, sell Bybit
                # Close: sell Binance, buy Bybit
                binance_side = "SELL"
                bybit_side = "Buy"
            else:
                # Original: sell Binance, buy Bybit
                # Close: buy Binance, sell Bybit
                binance_side = "BUY"
                bybit_side = "Sell"

            # Execute close orders
            close_result = await self.order_executor.execute_dual_order(
                symbol=task.symbol,
                quantity=float(task.quantity),
                binance_side=binance_side,
                bybit_side=bybit_side,
                binance_account_id=binance_order.account_id,
                bybit_account_id=bybit_order.account_id,
                task_id=task.id,
                db=db
            )

            # Update task status
            task.status = TaskStatus.CLOSED
            task.close_reason = reason
            task.closed_at = datetime.utcnow()

            # Calculate final P&L
            task.realized_pnl = await self._calculate_realized_pnl(task, db)

            await db.commit()

            logger.info(f"Position closed for task {task.id}, P&L: {task.realized_pnl:.2f}")

        except Exception as e:
            logger.error(f"Error closing position for task {task.id}: {e}")
            await db.rollback()

    async def _calculate_realized_pnl(self, task: ArbitrageTask, db: AsyncSession) -> float:
        """Calculate realized P&L from filled orders"""
        result = await db.execute(
            select(Order).where(
                and_(
                    Order.task_id == task.id,
                    Order.status == OrderStatus.FILLED
                )
            )
        )
        orders = result.scalars().all()

        # Separate entry and exit orders
        entry_orders = [o for o in orders if o.order_type == "entry"]
        exit_orders = [o for o in orders if o.order_type == "exit"]

        if len(entry_orders) != 2 or len(exit_orders) != 2:
            return 0

        # Calculate P&L
        binance_entry = next((o for o in entry_orders if o.platform == "binance"), None)
        bybit_entry = next((o for o in entry_orders if o.platform == "bybit"), None)
        binance_exit = next((o for o in exit_orders if o.platform == "binance"), None)
        bybit_exit = next((o for o in exit_orders if o.platform == "bybit"), None)

        if not all([binance_entry, bybit_entry, binance_exit, bybit_exit]):
            return 0

        if task.direction == "forward":
            # Buy Binance, Sell Bybit
            binance_pnl = (float(binance_exit.avg_price) - float(binance_entry.avg_price)) * float(task.quantity)
            bybit_pnl = (float(bybit_entry.avg_price) - float(bybit_exit.avg_price)) * float(task.quantity)
        else:
            # Sell Binance, Buy Bybit
            binance_pnl = (float(binance_entry.avg_price) - float(binance_exit.avg_price)) * float(task.quantity)
            bybit_pnl = (float(bybit_exit.avg_price) - float(bybit_entry.avg_price)) * float(task.quantity)

        total_pnl = binance_pnl + bybit_pnl

        # Subtract fees
        total_fees = sum(float(o.fee) for o in orders)
        total_pnl -= total_fees

        return total_pnl


# Global instance
position_monitor = PositionMonitor()
