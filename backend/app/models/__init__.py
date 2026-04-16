"""Core database models initialization"""
from app.core.database import Base
from app.models.user import User
from app.models.platform import Platform, PlatformSymbol, HedgingPair
from app.models.account import Account
from app.models.strategy import StrategyConfig
from app.models.order import OrderRecord
from app.models.arbitrage import ArbitrageTask
from app.models.risk_alert import RiskAlert
from app.models.market_data import MarketData, SpreadRecord
from app.models.arbitrage_opportunity import ArbitrageOpportunity
from app.models.position import Position
from app.models.strategy_performance import StrategyPerformance
from app.models.account_snapshot import AccountSnapshot
from app.models.system_log import SystemLog
from app.models.notification import Notification
from app.models.risk_settings import RiskSettings
from app.models.role import Role
from app.models.permission import Permission
from app.models.user_role import UserRole
from app.models.role_permission import RolePermission
from app.models.security_component import SecurityComponent, SecurityComponentLog
from app.models.ssl_certificate import SSLCertificate, SSLCertificateLog
from app.models.system_alert import SystemAlert
from app.models.trade import Trade
from app.models.version_backup import VersionBackup
from app.models.proxy import ProxyPool, AccountProxyBinding, ProxyHealthLog, ProxyUsageStats
from app.models.mt5_client import MT5Client

__all__ = [
    "Base",
    "User",
    "Platform",
    "PlatformSymbol",
    "HedgingPair",
    "Account",
    "StrategyConfig",
    "OrderRecord",
    "ArbitrageTask",
    "RiskAlert",
    "MarketData",
    "SpreadRecord",
    "ArbitrageOpportunity",
    "Position",
    "StrategyPerformance",
    "AccountSnapshot",
    "SystemLog",
    "Notification",
    "RiskSettings",
    "Role",
    "Permission",
    "UserRole",
    "RolePermission",
    "SecurityComponent",
    "SSLCertificate",
    "SecurityComponentLog",
    "SSLCertificateLog",
    "SystemAlert",
    "Trade",
    "VersionBackup",
    "ProxyPool",
    "AccountProxyBinding",
    "ProxyHealthLog",
    "ProxyUsageStats",
    "MT5Client",
]
