from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.db.schemas import validators as V


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

    @field_validator("bnb_buy_trigger_pct")
    @classmethod
    def _v_pct(cls, v, info):
        return V.rng(v, 0, 100, info.field_name)

    @field_validator("bnb_min_quantity", "bnb_buy_amount", "bnb_debt_threshold", "usdt_debt_threshold",
                     "single_transfer_amount", "base_margin_amount", "risk_value_threshold")
    @classmethod
    def _v_amount(cls, v, info):
        return V.rng(v, 0, 1_000_000_000_000, info.field_name)

    @field_validator("usdt_debt_interval_sec", "bnb_convert_interval_sec", "debt_convert_interval_sec")
    @classmethod
    def _v_interval(cls, v, info):
        return V.rng(v, 0, 10_000_000, info.field_name)

    @field_validator("transfer_order")
    @classmethod
    def _v_order(cls, v):
        return V.transfer_order(v)


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
    version: Optional[int] = 0
    updated_at: datetime

    model_config = {"from_attributes": True}
