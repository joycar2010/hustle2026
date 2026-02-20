"""Core database models initialization"""
from app.core.database import Base
from app.models.user import User
from app.models.platform import Platform
from app.models.account import Account
from app.models.strategy import StrategyConfig
from app.models.order import OrderRecord
from app.models.arbitrage import ArbitrageTask
from app.models.risk_alert import RiskAlert
from app.models.market_data import MarketData, SpreadRecord
from app.models.position import Position
from app.models.strategy_performance import StrategyPerformance
from app.models.account_snapshot import AccountSnapshot
from app.models.system_log import SystemLog
from app.models.api_credential import ApiCredential
from app.models.notification import Notification

__all__ = [
    "Base",
    "User",
    "Platform",
    "Account",
    "StrategyConfig",
    "OrderRecord",
    "ArbitrageTask",
    "RiskAlert",
    "MarketData",
    "SpreadRecord",
    "Position",
    "StrategyPerformance",
    "AccountSnapshot",
    "SystemLog",
    "ApiCredential",
    "Notification",
]
