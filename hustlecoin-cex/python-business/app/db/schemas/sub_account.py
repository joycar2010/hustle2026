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
