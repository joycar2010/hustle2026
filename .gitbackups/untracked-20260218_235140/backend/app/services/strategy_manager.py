"""
Strategy Manager Service
Handles automated strategy execution based on spread conditions
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.strategy import Strategy, StrategyStatus
from app.models.arbitrage import ArbitrageTask, TaskStatus
from app.models.account import Account
from app.services.market_service import MarketDataService
from app.services.arbitrage_strategy import ArbitrageStrategy
from app.services.risk_monitor import RiskMonitor
from app.core.database import get_db
from app.core.redis_client import redis_client
import logging

logger = logging.getLogger(__name__)


class StrategyManager:
    """Manages automated strategy execution"""

    def __init__(self):
        self.market_service = MarketDataService()
        self.risk_monitor = RiskMonitor()
        self.running_strategies: Dict[int, asyncio.Task] = {}

    async def start_strategy(self, strategy_id: int, db: AsyncSession):
        """Start automated strategy execution"""
        if strategy_id in self.running_strategies:
            logger.warning(f"Strategy {strategy_id} is already running")
            return False

        # Load strategy
        result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
        strategy = result.scalar_one_or_none()
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")

        # Update status
        strategy.status = StrategyStatus.RUNNING
        await db.commit()

        # Start monitoring task
        task = asyncio.create_task(self._monitor_strategy(strategy_id))
        self.running_strategies[strategy_id] = task
        logger.info(f"Started strategy {strategy_id}")
        return True

    async def stop_strategy(self, strategy_id: int, db: AsyncSession):
        """Stop automated strategy execution"""
        if strategy_id not in self.running_strategies:
            logger.warning(f"Strategy {strategy_id} is not running")
            return False

        # Cancel task
        task = self.running_strategies.pop(strategy_id)
        task.cancel()

        # Update status
        result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
        strategy = result.scalar_one_or_none()
        if strategy:
            strategy.status = StrategyStatus.STOPPED
            await db.commit()

        logger.info(f"Stopped strategy {strategy_id}")
        return True

    async def _monitor_strategy(self, strategy_id: int):
        """Monitor strategy and execute when conditions are met"""
        logger.info(f"Monitoring strategy {strategy_id}")

        try:
            while True:
                async for db in get_db():
                    try:
                        # Load strategy
                        result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
                        strategy = result.scalar_one_or_none()
                        if not strategy or strategy.status != StrategyStatus.RUNNING:
                            break

                        # Check if strategy should execute
                        should_execute = await self._check_execution_conditions(strategy, db)
                        if should_execute:
                            await self._execute_strategy(strategy, db)

                    except Exception as e:
                        logger.error(f"Error monitoring strategy {strategy_id}: {e}")

                await asyncio.sleep(1)  # Check every second

        except asyncio.CancelledError:
            logger.info(f"Strategy {strategy_id} monitoring cancelled")

    async def _check_execution_conditions(self, strategy: Strategy, db: AsyncSession) -> bool:
        """Check if strategy execution conditions are met"""
        # Get market data
        market_data = await self.market_service.get_market_data(strategy.symbol)
        if not market_data:
            return False

        spread = market_data.get("spread", 0)
        direction = market_data.get("direction")

        # Check spread threshold
        if strategy.direction == "forward":
            if direction != "forward" or spread < strategy.min_spread:
                return False
        elif strategy.direction == "reverse":
            if direction != "reverse" or spread < strategy.min_spread:
                return False

        # Check risk conditions
        risk_check = await self.risk_monitor.check_all_risks(strategy.user_id, db)
        if not risk_check["passed"]:
            logger.warning(f"Risk check failed for strategy {strategy.id}: {risk_check['reasons']}")
            return False

        # Check cooldown
        last_execution_key = f"strategy:{strategy.id}:last_execution"
        last_execution = await redis_client.get(last_execution_key)
        if last_execution:
            cooldown = strategy.params.get("cooldown_seconds", 60)
            elapsed = (datetime.utcnow().timestamp() - float(last_execution))
            if elapsed < cooldown:
                return False

        return True

    async def _execute_strategy(self, strategy: Strategy, db: AsyncSession):
        """Execute strategy"""
        logger.info(f"Executing strategy {strategy.id}")

        try:
            # Load accounts
            binance_result = await db.execute(
                select(Account).where(
                    and_(
                        Account.user_id == strategy.user_id,
                        Account.platform == "binance",
                        Account.is_active == True
                    )
                )
            )
            binance_account = binance_result.scalar_one_or_none()

            bybit_result = await db.execute(
                select(Account).where(
                    and_(
                        Account.user_id == strategy.user_id,
                        Account.platform == "bybit",
                        Account.is_active == True
                    )
                )
            )
            bybit_account = bybit_result.scalar_one_or_none()

            if not binance_account or not bybit_account:
                logger.error(f"Missing accounts for strategy {strategy.id}")
                return

            # Calculate position size
            position_size = await self._calculate_position_size(strategy, binance_account, bybit_account, db)
            if position_size <= 0:
                logger.warning(f"Invalid position size for strategy {strategy.id}")
                return

            # Execute arbitrage
            arbitrage_strategy = ArbitrageStrategy()
            task = await arbitrage_strategy.execute_arbitrage(
                user_id=strategy.user_id,
                symbol=strategy.symbol,
                direction=strategy.direction,
                quantity=position_size,
                binance_account_id=binance_account.id,
                bybit_account_id=bybit_account.id,
                db=db
            )

            # Update last execution time
            last_execution_key = f"strategy:{strategy.id}:last_execution"
            await redis_client.set(last_execution_key, str(datetime.utcnow().timestamp()), ex=3600)

            logger.info(f"Strategy {strategy.id} executed, task {task.id} created")

        except Exception as e:
            logger.error(f"Error executing strategy {strategy.id}: {e}")

    async def _calculate_position_size(
        self,
        strategy: Strategy,
        binance_account: Account,
        bybit_account: Account,
        db: AsyncSession
    ) -> float:
        """Calculate position size based on risk parameters"""
        # Get account balances
        from app.services.account_service import AccountDataService
        account_service = AccountDataService()

        binance_balance = await account_service.get_account_balance(binance_account.id, db)
        bybit_balance = await account_service.get_account_balance(bybit_account.id, db)

        if not binance_balance or not bybit_balance:
            return 0

        # Get available balance (USDT)
        binance_usdt = next((b["free"] for b in binance_balance if b["asset"] == "USDT"), 0)
        bybit_usdt = next((b["free"] for b in bybit_balance if b["asset"] == "USDT"), 0)

        # Use minimum of both accounts
        available_balance = min(binance_usdt, bybit_usdt)

        # Apply risk percentage
        risk_percentage = strategy.params.get("risk_percentage", 10) / 100
        max_position_value = available_balance * risk_percentage

        # Get current price
        market_data = await self.market_service.get_market_data(strategy.symbol)
        if not market_data:
            return 0

        price = market_data.get("binance_bid", 0)
        if price <= 0:
            return 0

        # Calculate quantity
        quantity = max_position_value / price

        # Apply max quantity limit
        max_quantity = strategy.params.get("max_quantity", 1.0)
        quantity = min(quantity, max_quantity)

        # Round to appropriate precision
        precision = strategy.params.get("quantity_precision", 3)
        quantity = round(quantity, precision)

        return quantity


# Global instance
strategy_manager = StrategyManager()

