"""Base strategy class for arbitrage strategies"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.account import Account
from app.models.strategy import StrategyConfig
from app.services.market_service import market_data_service
from app.services.order_executor import order_executor
from app.websocket.manager import manager


class BaseStrategy(ABC):
    """Abstract base class for arbitrage strategies"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.is_running = False

    @abstractmethod
    async def check_entry_condition(self, spread_data: Dict[str, Any]) -> bool:
        """Check if entry conditions are met"""
        pass

    @abstractmethod
    async def check_exit_condition(self, spread_data: Dict[str, Any]) -> bool:
        """Check if exit conditions are met"""
        pass

    @abstractmethod
    async def execute_entry(
        self,
        binance_account: Account,
        bybit_account: Account,
        spread_data: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute entry orders"""
        pass

    @abstractmethod
    async def execute_exit(
        self,
        binance_account: Account,
        bybit_account: Account,
        spread_data: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute exit orders"""
        pass

    async def send_notification(self, user_id: UUID, message: str, level: str = "info"):
        """Send notification to user via WebSocket"""
        await manager.send_to_user(
            {
                "type": "strategy_notification",
                "level": level,
                "message": message,
                "strategy_type": self.config.strategy_type,
            },
            str(user_id),
        )

    async def get_user_accounts(
        self,
        user_id: UUID,
        db: AsyncSession,
    ) -> tuple[Optional[Account], Optional[Account]]:
        """Get user's Binance and Bybit accounts"""
        result = await db.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.is_active == True,
            )
        )
        accounts = result.scalars().all()

        binance_account = None
        bybit_account = None

        for account in accounts:
            if account.platform_id == 1:  # Binance
                binance_account = account
            elif account.platform_id == 2:  # Bybit
                bybit_account = account

        return binance_account, bybit_account
