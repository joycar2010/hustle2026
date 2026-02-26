from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


class AccountCreate(BaseModel):
    """Schema for creating a new account"""

    platform_id: int = Field(..., ge=1, le=2)  # 1: Binance, 2: Bybit
    account_name: str = Field(..., min_length=1, max_length=50)
    api_key: str = Field(..., min_length=1, max_length=256)
    api_secret: str = Field(..., min_length=1, max_length=256)
    passphrase: Optional[str] = Field(None, max_length=100)

    # MT5-specific fields
    mt5_id: Optional[str] = Field(None, max_length=100)
    mt5_server: Optional[str] = Field(None, max_length=100)
    mt5_primary_pwd: Optional[str] = Field(None, max_length=256)
    is_mt5_account: bool = False

    is_default: bool = False
    leverage: Optional[int] = Field(None, ge=1, le=500)  # Leverage multiplier


class AccountUpdate(BaseModel):
    """Schema for updating account"""

    account_name: Optional[str] = Field(None, min_length=1, max_length=50)
    api_key: Optional[str] = Field(None, min_length=1, max_length=256)
    api_secret: Optional[str] = Field(None, min_length=1, max_length=256)
    passphrase: Optional[str] = Field(None, max_length=100)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    leverage: Optional[int] = Field(None, ge=1, le=500)  # Leverage multiplier


class AccountResponse(BaseModel):
    """Schema for account response"""

    account_id: UUID
    user_id: UUID
    platform_id: int
    account_name: str
    api_key: Optional[str] = None  # API Key (for editing)
    api_secret: Optional[str] = None  # API Secret (for editing)
    passphrase: Optional[str] = None  # Passphrase (for OKX)
    mt5_id: Optional[str] = None  # MT5 account ID
    mt5_server: Optional[str] = None  # MT5 server
    mt5_primary_pwd: Optional[str] = None  # MT5 password
    is_mt5_account: bool
    is_default: bool
    is_active: bool
    leverage: Optional[int] = None  # Leverage multiplier
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True


class AccountBalance(BaseModel):
    """Schema for account balance data"""

    total_assets: float  # 总资产 (equity for Bybit)
    available_balance: float  # 可用资产 (availableToTrade)
    net_assets: float  # 净资产 (equity for Bybit)
    frozen_assets: float  # 冻结资产 (walletBalance - availableToTrade)
    margin_balance: float  # 保证金余额 (marginBalance from account-info)
    unrealized_pnl: float  # 未实现盈亏
    risk_ratio: Optional[float] = None  # 风险率 (riskRatio from account-info)
    total_positions: Optional[float] = None  # 总持仓 (sum from position/list)
    daily_pnl: Optional[float] = None  # 当日盈亏 (from profit-loss)
    funding_fee: Optional[float] = None  # 资金费 (from funding-fee)


class AccountPosition(BaseModel):
    """Schema for account position data"""

    symbol: str
    side: str  # Buy/Sell
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int
