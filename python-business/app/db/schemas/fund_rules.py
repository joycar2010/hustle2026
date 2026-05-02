from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class FundRulesUpdate(BaseModel):
    bnb_min_quantity: Optional[Decimal] = None
    bnb_buy_trigger_pct: Optional[Decimal] = None
    bnb_buy_amount: Optional[Decimal] = None
    bnb_debt_auto_repay: Optional[bool] = None
    bnb_debt_threshold: Optional[Decimal] = None
    usdt_debt_auto_repay: Optional[bool] = None
    usdt_debt_threshold: Optional[Decimal] = None
    usdt_debt_interval_sec: Optional[int] = None
    bnb_convert_interval_sec: Optional[int] = None
    debt_convert_interval_sec: Optional[int] = None
    risk_value_threshold: Optional[Decimal] = None
    single_transfer_amount: Optional[Decimal] = None
    base_margin_amount: Optional[Decimal] = None
    transfer_order: Optional[str] = None


class FundRulesResponse(BaseModel):
    id: int
    bnb_min_quantity: Decimal
    bnb_buy_trigger_pct: Decimal
    bnb_buy_amount: Decimal
    bnb_debt_auto_repay: bool
    bnb_debt_threshold: Decimal
    usdt_debt_auto_repay: bool
    usdt_debt_threshold: Decimal
    usdt_debt_interval_sec: int
    bnb_convert_interval_sec: int
    debt_convert_interval_sec: int
    risk_value_threshold: Decimal
    single_transfer_amount: Decimal
    base_margin_amount: Decimal
    transfer_order: str
    updated_at: datetime

    model_config = {"from_attributes": True}
