from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class SubAccountCreate(BaseModel):
    note: str
    email: str
    api_key: str
    api_secret: str
    margin_enabled: bool = False
    futures_enabled: bool = False
    spot_enabled: bool = False
    bnb_burn_enabled: bool = False
    bnb_interest_enabled: bool = False


class SubAccountUpdate(BaseModel):
    note: Optional[str] = None
    email: Optional[str] = None
    margin_enabled: Optional[bool] = None
    futures_enabled: Optional[bool] = None
    spot_enabled: Optional[bool] = None
    bnb_burn_enabled: Optional[bool] = None
    bnb_interest_enabled: Optional[bool] = None
    order_amount: Optional[Decimal] = None
    base_margin_amount: Optional[Decimal] = None
    single_transfer_amount: Optional[Decimal] = None
    risk_threshold: Optional[Decimal] = None
    min_balance: Optional[Decimal] = None
    single_order_amount: Optional[Decimal] = None
    max_positions: Optional[int] = None
    max_borrow_amount: Optional[Decimal] = None


class SubAccountFundPatch(BaseModel):
    risk_threshold: Optional[Decimal] = None
    single_transfer_amount: Optional[Decimal] = None
    min_balance: Optional[Decimal] = None
    single_order_amount: Optional[Decimal] = None
    max_positions: Optional[int] = None
    max_borrow_amount: Optional[Decimal] = None


class SubAccountKeyUpdate(BaseModel):
    api_key: str
    api_secret: str


class SubAccountResponse(BaseModel):
    id: int
    note: str
    email: str
    api_key: str
    api_secret_masked: str
    is_enabled: bool
    margin_enabled: bool
    futures_enabled: bool
    spot_enabled: bool
    bnb_burn_enabled: bool
    bnb_interest_enabled: bool
    order_amount: Optional[Decimal] = None
    base_margin_amount: Optional[Decimal] = None
    single_transfer_amount: Optional[Decimal] = None
    risk_threshold: Optional[Decimal] = None
    min_balance: Optional[Decimal] = None
    single_order_amount: Optional[Decimal] = None
    max_positions: Optional[int] = None
    max_borrow_amount: Optional[Decimal] = None
    last_validated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubAccountValidation(BaseModel):
    is_valid: bool
    can_trade: bool = False
    can_withdraw: bool = False
    permissions: list[str] = []
    error: Optional[str] = None


class SubAccountClearRequest(BaseModel):
    mode: str  # "disable_only" or "disable_and_close"


class IpWhitelistUpdate(BaseModel):
    ip_restrict: bool = True
    ip_list: list[str] = []
