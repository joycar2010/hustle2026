from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.db.schemas import validators as V


class InventoryProbeRateMixin(BaseModel):
    inventory_probe_rate_per_sec: Optional[Decimal] = None

    @field_validator("inventory_probe_rate_per_sec")
    @classmethod
    def _v_inventory_probe_rate(cls, v, info):
        if v is not None and Decimal(str(v)) <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return V.rng(v, 0, 10, info.field_name)


class SubAccountCreate(InventoryProbeRateMixin):
    note: str
    email: str
    api_key: str
    api_secret: str
    margin_enabled: bool = False
    futures_enabled: bool = False
    spot_enabled: bool = False
    # Historical account-level flags. They remain round-trippable for older
    # clients, but are not an active Worker setting; BNB policy is the
    # tenant-scoped GlobalRules.bnb_burn_enabled switch.
    bnb_burn_enabled: bool = False
    bnb_interest_enabled: bool = False


class SubAccountUpdate(InventoryProbeRateMixin):
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
    # Kept in the response for backward compatibility; not consumed by the
    # Worker. Use GlobalRules.bnb_burn_enabled for the active BNB policy.
    bnb_burn_enabled: bool
    bnb_interest_enabled: bool
    last_validated_at: Optional[datetime] = None
    # Fund controls are returned as strings by the API so decimal precision
    # survives JSON round-trips.  Keep explicit zero values visible: zero is a
    # deliberate disable/limit, not an omitted field.
    order_amount: Optional[str] = None
    base_margin_amount: Optional[str] = None
    single_transfer_amount: Optional[str] = None
    risk_threshold: Optional[str] = None
    min_balance: Optional[str] = None
    single_order_amount: Optional[str] = None
    max_positions: Optional[int] = None
    max_borrow_amount: Optional[str] = None
    max_order_count: Optional[int] = None
    borrow_rate_per_sec: Optional[str] = None
    inventory_probe_rate_per_sec: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubAccountValidation(BaseModel):
    is_valid: bool
    can_trade: bool = False
    can_withdraw: bool = False
    permissions: list[str] = []
    error: Optional[str] = None
