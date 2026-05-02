from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


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
    is_enabled: Optional[bool] = None


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
