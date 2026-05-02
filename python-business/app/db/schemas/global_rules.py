from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class GlobalRulesUpdate(BaseModel):
    auto_push_spread: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
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
    max_loss_per_position: Optional[Decimal] = None
    circuit_breaker_spread_pct: Optional[Decimal] = None
    circuit_breaker_pause_sec: Optional[int] = None
    max_daily_interest_rate: Optional[Decimal] = None
    repay_spread: Optional[Decimal] = None
    max_positions: Optional[int] = None
    auto_start_on_boot: Optional[bool] = None
    futures_liquidation_threshold: Optional[Decimal] = None


class GlobalRulesResponse(BaseModel):
    id: int
    auto_push_spread: Decimal
    remove_spread: Decimal
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
    max_loss_per_position: Optional[Decimal] = None
    circuit_breaker_spread_pct: Optional[Decimal] = None
    circuit_breaker_pause_sec: int = 300
    max_daily_interest_rate: Optional[Decimal] = None
    repay_spread: Optional[Decimal] = None
    max_positions: int = 10
    auto_start_on_boot: bool = False
    futures_liquidation_threshold: Optional[Decimal] = None
    updated_at: datetime

    model_config = {"from_attributes": True}
