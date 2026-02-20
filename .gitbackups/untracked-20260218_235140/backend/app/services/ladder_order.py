"""
Ladder Order Service
Implements ladder order strategy for gradual position building
"""
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.order import Order, OrderStatus
from app.models.arbitrage import ArbitrageTask
from app.services.order_executor import OrderExecutor
from app.services.market_service import MarketDataService
import logging

logger = logging.getLogger(__name__)


class LadderOrderService:
    """Manages ladder order execution"""

    def __init__(self):
        self.order_executor = OrderExecutor()
        self.market_service = MarketDataService()

    async def execute_ladder_orders(
        self,
        task_id: int,
        symbol: str,
        total_quantity: float,
        num_orders: int,
        price_range: float,
        direction: str,
        binance_account_id: int,
        bybit_account_id: int,
        db: AsyncSession
    ) -> List[Dict]:
        """
        Execute ladder orders across a price range

        Args:
            task_id: Arbitrage task ID
            symbol: Trading symbol
            total_quantity: Total quantity to trade
            num_orders: Number of ladder orders
            price_range: Price range percentage (e.g., 0.5 for 0.5%)
            direction: 'forward' or 'reverse'
            binance_account_id: Binance account ID
            bybit_account_id: Bybit account ID
            db: Database session

        Returns:
            List of order results
        """
        logger.info(
            f"Executing ladder orders: {num_orders} orders, "
            f"total qty {total_quantity}, range {price_range}%"
        )

        # Get current market price
        market_data = await self.market_service.get_market_data(symbol)
        if not market_data:
            raise ValueError("Cannot get market data")

        # Calculate order sizes
        order_quantity = total_quantity / num_orders

        # Calculate price levels
        if direction == "forward":
            base_price = market_data.get("binance_bid", 0)
        else:
            base_price = market_data.get("binance_ask", 0)

        price_step = (base_price * price_range / 100) / (num_orders - 1) if num_orders > 1 else 0

        # Execute orders at different price levels
        results = []
        for i in range(num_orders):
            # Calculate target price for this level
            if direction == "forward":
                # For forward, buy at lower prices
                target_price = base_price - (price_step * i)
            else:
                # For reverse, sell at higher prices
                target_price = base_price + (price_step * i)

            # Execute order at this level
            try:
                result = await self._execute_ladder_level(
                    task_id=task_id,
                    symbol=symbol,
                    quantity=order_quantity,
                    target_price=target_price,
                    direction=direction,
                    binance_account_id=binance_account_id,
                    bybit_account_id=bybit_account_id,
                    level=i + 1,
                    db=db
                )
                results.append(result)

                # Small delay between orders
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error executing ladder level {i + 1}: {e}")
                results.append({
                    "level": i + 1,
                    "success": False,
                    "error": str(e)
                })

        return results

    async def _execute_ladder_level(
        self,
        task_id: int,
        symbol: str,
        quantity: float,
        target_price: float,
        direction: str,
        binance_account_id: int,
        bybit_account_id: int,
        level: int,
        db: AsyncSession
    ) -> Dict:
        """Execute a single ladder level"""
        logger.info(f"Executing ladder level {level} at price {target_price}")

        # Determine order sides
        if direction == "forward":
            binance_side = "BUY"
            bybit_side = "Sell"
        else:
            binance_side = "SELL"
            bybit_side = "Buy"

        # Execute dual order with limit price
        result = await self.order_executor.execute_dual_order(
            symbol=symbol,
            quantity=quantity,
            binance_side=binance_side,
            bybit_side=bybit_side,
            binance_account_id=binance_account_id,
            bybit_account_id=bybit_account_id,
            task_id=task_id,
            limit_price=target_price,
            db=db
        )

        return {
            "level": level,
            "success": result["success"],
            "target_price": target_price,
            "quantity": quantity,
            "binance_order_id": result.get("binance_order_id"),
            "bybit_order_id": result.get("bybit_order_id")
        }

    async def cancel_unfilled_ladder_orders(
        self,
        task_id: int,
        db: AsyncSession
    ) -> Dict:
        """Cancel all unfilled ladder orders for a task"""
        logger.info(f"Cancelling unfilled ladder orders for task {task_id}")

        # Get all pending orders for this task
        result = await db.execute(
            select(Order).where(
                Order.task_id == task_id,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED])
            )
        )
        orders = result.scalars().all()

        cancelled_count = 0
        for order in orders:
            try:
                # Cancel order on exchange
                if order.platform == "binance":
                    # Cancel Binance order
                    pass  # Implement Binance cancel logic
                elif order.platform == "bybit":
                    # Cancel Bybit order
                    pass  # Implement Bybit cancel logic

                # Update order status
                order.status = OrderStatus.CANCELLED
                cancelled_count += 1

            except Exception as e:
                logger.error(f"Error cancelling order {order.id}: {e}")

        await db.commit()

        return {
            "success": True,
            "cancelled_count": cancelled_count,
            "total_orders": len(orders)
        }


# Global instance
ladder_order_service = LadderOrderService()
