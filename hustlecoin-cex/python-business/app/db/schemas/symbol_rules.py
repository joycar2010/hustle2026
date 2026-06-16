from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.db.schemas import validators as V


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
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = None
    note: Optional[str] = None

    @field_validator("open_spread", "close_spread", "remove_spread", "repay_spread", "slippage_pct")
    @classmethod
    def _v_pct(cls, v, info):
        return V.rng(v, 0, 100, info.field_name)

    @field_validator("close_funding_ratio", "repay_funding_ratio", "max_daily_interest_rate")
    @classmethod
    def _v_ratio(cls, v, info):
        return V.rng(v, 0, 1000, info.field_name)

    @field_validator("order_amount")
    @classmethod
    def _v_amount(cls, v, info):
        return V.rng(v, 0, 1_000_000_000_000, info.field_name)

    @field_validator("follow_type")
    @classmethod
    def _v_follow(cls, v):
        return V.follow_type(v)

    @field_validator("note")
    @classmethod
    def _v_note(cls, v):
        if v is not None and len(str(v)) > 120:
            raise ValueError("备注最长 120 字")
        return v


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
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = None
    note: Optional[str] = None
    source: str
    effective_open_spread: Optional[Decimal] = None
    effective_close_spread: Optional[Decimal] = None
    effective_order_amount: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
