from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.db.schemas import validators as V


class AccountSymbolRuleUpsert(BaseModel):
    open_spread: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    order_amount: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
    close_funding_ratio: Optional[Decimal] = None
    repay_funding_ratio: Optional[Decimal] = None
    max_daily_interest_rate: Optional[Decimal] = None
    repay_spread: Optional[Decimal] = None
    max_borrow_amount: Optional[Decimal] = None
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = None
    note: Optional[str] = None
    is_enabled: Optional[bool] = None

    @field_validator("open_spread", "close_spread", "remove_spread", "repay_spread", "slippage_pct")
    @classmethod
    def _v_pct(cls, v, info):
        return V.rng(v, 0, 100, info.field_name)

    @field_validator("close_funding_ratio", "repay_funding_ratio", "max_daily_interest_rate")
    @classmethod
    def _v_ratio(cls, v, info):
        return V.rng(v, 0, 1000, info.field_name)

    @field_validator("order_amount", "max_borrow_amount")
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


class AccountSymbolRuleResponse(BaseModel):
    id: int
    sub_account_id: int
    symbol: str
    open_spread: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    order_amount: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
    close_funding_ratio: Optional[Decimal] = None
    repay_funding_ratio: Optional[Decimal] = None
    max_daily_interest_rate: Optional[Decimal] = None
    repay_spread: Optional[Decimal] = None
    max_borrow_amount: Optional[Decimal] = None
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = None
    note: Optional[str] = None
    is_enabled: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchAccountSymbolRuleItem(BaseModel):
    sub_account_id: int
    symbol: str
    data: AccountSymbolRuleUpsert


class BatchAccountSymbolRuleRequest(BaseModel):
    items: list[BatchAccountSymbolRuleItem]
