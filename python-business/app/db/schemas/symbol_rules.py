from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class SymbolRuleUpdate(BaseModel):
    open_spread: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    order_amount: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
    close_funding_ratio: Optional[Decimal] = None
    repay_funding_ratio: Optional[Decimal] = None
    allow_remove: Optional[bool] = None
    allow_repay: Optional[bool] = None
    max_daily_interest_rate: Optional[Decimal] = None
    repay_spread: Optional[Decimal] = None


class SymbolRuleResponse(BaseModel):
    id: int
    symbol: str
    open_spread: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    order_amount: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
    close_funding_ratio: Optional[Decimal] = None
    repay_funding_ratio: Optional[Decimal] = None
    allow_remove: bool
    allow_repay: bool
    max_daily_interest_rate: Optional[Decimal] = None
    repay_spread: Optional[Decimal] = None
    source: str
    effective_open_spread: Optional[Decimal] = None
    effective_close_spread: Optional[Decimal] = None
    effective_order_amount: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
