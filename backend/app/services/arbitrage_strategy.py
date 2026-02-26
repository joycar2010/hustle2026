"""Arbitrage strategy service for executing trading strategies"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.account import Account
from app.models.strategy import StrategyConfig
from app.models.arbitrage import ArbitrageTask
from app.services.order_executor import order_executor
from app.services.market_service import market_data_service
from app.websocket.manager import manager


class ArbitrageStrategy:
    """Service for executing arbitrage strategies"""

    async def execute_forward_arbitrage(
        self,
        user_id: UUID,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        target_spread: float,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute forward arbitrage (long Binance, short Bybit)

        Entry: Sell Bybit (ask - 0.01), Buy Binance (bid + 0.01)
        """
        # Get current market data
        spread_data = await market_data_service.get_current_spread(
            use_cache=False  # Always get fresh data for trading
        )

        # Check if spread meets target
        if spread_data.forward_entry_spread < target_spread:
            return {
                "success": False,
                "error": f"Spread {spread_data.forward_entry_spread} below target {target_spread}",
            }

        # Calculate order prices (adjust by 0.01 for better fill rate, with precision handling)
        # MT5 limit order rules:
        # - BUY limit: price must be BELOW current ask
        # - SELL limit: price must be ABOVE current bid
        # For Binance BUY limit, use ask - 0.01 to ensure price is below ask
        binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
        # For Bybit SELL limit, use bid + 0.01 to ensure price is above bid
        bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)

        # Create arbitrage task
        task = ArbitrageTask(
            user_id=user_id,
            strategy_type="forward",
            open_spread=spread_data.forward_entry_spread,
            status="open",
            open_time=datetime.utcnow(),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        # Execute dual order
        result = await order_executor.execute_dual_order(
            binance_account=binance_account,
            bybit_account=bybit_account,
            binance_symbol="XAUUSDT",
            bybit_symbol="XAUUSD.s",
            binance_side="BUY",
            bybit_side="Sell",
            quantity=quantity,
            binance_price=binance_buy_price,
            bybit_price=bybit_sell_price,
            order_type="LIMIT",
            db=db,
        )

        # Update task status
        if result["success"]:
            task.status = "open"
        else:
            task.status = "failed"

        await db.commit()

        # Send WebSocket notification
        await manager.send_order_update(
            str(user_id),
            {
                "task_id": str(task.task_id),
                "strategy": "forward",
                "status": task.status,
                "spread": spread_data.forward_entry_spread,
                "result": result,
            },
        )

        return {
            "success": result["success"],
            "task_id": str(task.task_id),
            "spread": spread_data.forward_entry_spread,
            "execution_result": result,
        }

    async def execute_reverse_arbitrage(
        self,
        user_id: UUID,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        target_spread: float,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute reverse arbitrage (short Binance, long Bybit)

        Entry: Sell Binance (ask - 0.01), Buy Bybit (bid + 0.01)
        """
        # Get current market data
        spread_data = await market_data_service.get_current_spread(
            use_cache=False
        )

        # Check if spread meets target (reverse_entry_spread = binance_ask - bybit_bid, should be >= target)
        if spread_data.reverse_entry_spread < target_spread:
            return {
                "success": False,
                "error": f"Spread {spread_data.reverse_entry_spread} below target {target_spread}",
            }

        # Calculate order prices (with precision handling to avoid floating point errors)
        # MT5 limit order rules:
        # - BUY limit: price must be BELOW current ask
        # - SELL limit: price must be ABOVE current bid
        binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
        # For Bybit BUY limit, use ask - 0.01 to ensure price is below ask
        bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)

        # Create arbitrage task
        task = ArbitrageTask(
            user_id=user_id,
            strategy_type="reverse",
            open_spread=spread_data.reverse_entry_spread,
            status="open",
            open_time=datetime.utcnow(),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        # Execute dual order
        result = await order_executor.execute_dual_order(
            binance_account=binance_account,
            bybit_account=bybit_account,
            binance_symbol="XAUUSDT",
            bybit_symbol="XAUUSD.s",
            binance_side="SELL",
            bybit_side="Buy",
            quantity=quantity,
            binance_price=binance_sell_price,
            bybit_price=bybit_buy_price,
            order_type="LIMIT",
            db=db,
        )

        # Update task status
        if result["success"]:
            task.status = "open"
        else:
            task.status = "failed"

        await db.commit()

        # Send WebSocket notification
        await manager.send_order_update(
            str(user_id),
            {
                "task_id": str(task.task_id),
                "strategy": "reverse",
                "status": task.status,
                "spread": spread_data.reverse_entry_spread,
                "result": result,
            },
        )

        return {
            "success": result["success"],
            "task_id": str(task.task_id),
            "spread": spread_data.reverse_entry_spread,
            "execution_result": result,
        }

    async def close_forward_arbitrage(
        self,
        task_id: UUID,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Close forward arbitrage position

        Exit: Sell Binance (ask - 0.01), Buy Bybit (bid + 0.01)
        """
        # Get task
        result = await db.execute(
            select(ArbitrageTask).where(ArbitrageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task or task.status != "open":
            return {
                "success": False,
                "error": "Task not found or not open",
            }

        # Get current market data
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Calculate exit prices (with precision handling)
        # MT5 limit order rules:
        # - BUY limit: price must be BELOW current ask
        # - SELL limit: price must be ABOVE current bid
        # For Binance SELL limit, use bid + 0.01 to ensure price is above bid
        binance_sell_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
        # For Bybit BUY limit, use ask - 0.01 to ensure price is below ask
        bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)

        # Execute closing orders (reverse of opening)
        result = await order_executor.execute_dual_order(
            binance_account=binance_account,
            bybit_account=bybit_account,
            binance_symbol="XAUUSDT",
            bybit_symbol="XAUUSD.s",
            binance_side="SELL",  # Close long position
            bybit_side="Buy",  # Close short position
            quantity=quantity,
            binance_price=binance_sell_price,
            bybit_price=bybit_buy_price,
            order_type="LIMIT",
            db=db,
        )

        # Update task
        if result["success"]:
            task.status = "closed"
            task.close_spread = spread_data.forward_exit_spread
            task.close_time = datetime.utcnow()
            # Calculate profit (simplified - should include fees)
            task.profit = (task.open_spread - spread_data.forward_exit_spread) * quantity

        await db.commit()

        return {
            "success": result["success"],
            "task_id": str(task.task_id),
            "close_spread": spread_data.forward_exit_spread,
            "profit": task.profit,
            "execution_result": result,
        }

    async def close_reverse_arbitrage(
        self,
        task_id: UUID,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Close reverse arbitrage position

        Exit: Buy Binance (bid + 0.01), Sell Bybit (ask - 0.01)
        """
        # Get task
        result = await db.execute(
            select(ArbitrageTask).where(ArbitrageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task or task.status != "open":
            return {
                "success": False,
                "error": "Task not found or not open",
            }

        # Get current market data
        spread_data = await market_data_service.get_current_spread(use_cache=False)

        # Calculate exit prices (with precision handling)
        # MT5 limit order rules:
        # - BUY limit: price must be BELOW current ask
        # - SELL limit: price must be ABOVE current bid
        # For Binance BUY limit, use ask - 0.01 to ensure price is below ask
        binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
        # For Bybit SELL limit, use bid + 0.01 to ensure price is above bid
        bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)

        # Execute closing orders
        result = await order_executor.execute_dual_order(
            binance_account=binance_account,
            bybit_account=bybit_account,
            binance_symbol="XAUUSDT",
            bybit_symbol="XAUUSD.s",
            binance_side="BUY",  # Close short position
            bybit_side="Sell",  # Close long position
            quantity=quantity,
            binance_price=binance_buy_price,
            bybit_price=bybit_sell_price,
            order_type="LIMIT",
            db=db,
        )

        # Update task
        if result["success"]:
            task.status = "closed"
            task.close_spread = spread_data.reverse_exit_spread
            task.close_time = datetime.utcnow()
            # Calculate profit: open_spread (binance_ask - bybit_bid) minus exit cost (bybit_ask - binance_bid)
            task.profit = (task.open_spread - spread_data.reverse_exit_spread) * quantity

        await db.commit()

        return {
            "success": result["success"],
            "task_id": str(task.task_id),
            "close_spread": spread_data.reverse_exit_spread,
            "profit": task.profit,
            "execution_result": result,
        }


# Global instance
arbitrage_strategy = ArbitrageStrategy()
