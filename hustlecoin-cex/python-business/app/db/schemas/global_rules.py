from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class GlobalRulesUpdate(BaseModel):
    auto_push_spread: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
    borrow_spread: Optional[Decimal] = None
    open_spread: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    order_amount: Optional[Decimal] = None
    close_funding_ratio: Optional[Decimal] = None
    repay_funding_ratio: Optional[Decimal] = None
    borrow_delay_sec: Optional[int] = None
    confirm_delay_sec: Optional[int] = None
    confirm_skip_spread: Optional[Decimal] = None
    repay_ban_minutes: Optional[int] = None
    interest_filter: Optional[Decimal] = None
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = None
    stabilize_sec: Optional[Decimal] = None
    tier_ratios: Optional[str] = None
    borrow_rate_per_sec: Optional[Decimal] = None


class GlobalRulesResponse(BaseModel):
    id: int
    auto_push_spread: Decimal
    remove_spread: Decimal
    borrow_spread: Optional[Decimal] = None
    open_spread: Decimal
    close_spread: Decimal
    order_amount: Decimal
    close_funding_ratio: Decimal
    repay_funding_ratio: Decimal
    borrow_delay_sec: int
    confirm_delay_sec: int
    confirm_skip_spread: Decimal
    repay_ban_minutes: int
    interest_filter: Decimal
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = "market"
    stabilize_sec: Optional[Decimal] = None
    tier_ratios: Optional[str] = ""
    borrow_rate_per_sec: Optional[Decimal] = 2
    updated_at: datetime

    model_config = {"from_attributes": True}
