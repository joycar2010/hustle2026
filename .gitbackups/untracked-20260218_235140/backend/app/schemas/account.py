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


class AccountUpdate(BaseModel):
    """Schema for updating account"""

    account_name: Optional[str] = Field(None, min_length=1, max_length=50)
    api_key: Optional[str] = Field(None, min_length=1, max_length=256)
    api_secret: Optional[str] = Field(None, min_length=1, max_length=256)
    passphrase: Optional[str] = Field(None, max_length=100)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class AccountResponse(BaseModel):
    """Schema for account response"""

    account_id: UUID
    user_id: UUID
    platform_id: int
    account_name: str
    is_mt5_account: bool
    is_default: bool
    is_active: bool
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True


class AccountBalance(BaseModel):
    """Schema for account balance data"""

    total_assets: float
    available_balance: float
    net_assets: float
    frozen_assets: float
    margin_balance: float
    unrealized_pnl: float
    risk_ratio: Optional[float] = None


class AccountPosition(BaseModel):
    """Schema for account position data"""

    symbol: str
    side: str  # Buy/Sell
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int
