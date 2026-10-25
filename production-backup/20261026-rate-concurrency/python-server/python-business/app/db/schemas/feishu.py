from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any


class FeishuConfigUpdate(BaseModel):
    webhook_url: Optional[str] = None
    secret_key: Optional[str] = None
    alert_interval_sec: Optional[int] = None
    alert_count: Optional[int] = None
    risk_alert_cooldown_sec: Optional[int] = None
    margin_rate_alert: Optional[Decimal] = None
    leverage_risk_alert: Optional[Decimal] = None
    enable_transfer_fail_alert: Optional[bool] = None
    enable_new_borrow_alert: Optional[bool] = None
    enable_borrow_success_alert: Optional[bool] = None
    enable_repay_success_alert: Optional[bool] = None
    alert_overrides: Optional[Dict[str, Any]] = None   # {alert_type:{count,interval}} 每类型覆盖

    @field_validator("alert_interval_sec")
    @classmethod
    def _v_interval(cls, v):
        if v is None:
            return v
        if v < 0 or v > 86400:
            raise ValueError("alert_interval_sec must be between 0 and 86400")
        return v

    @field_validator("alert_count")
    @classmethod
    def _v_count(cls, v):
        if v is None:
            return v
        if v < 1 or v > 100:
            raise ValueError("alert_count must be between 1 and 100")
        return v

    @field_validator("risk_alert_cooldown_sec")
    @classmethod
    def _v_risk_cooldown(cls, v):
        if v is None:
            return v
        if v < 0 or v > 604800:
            raise ValueError("risk_alert_cooldown_sec must be between 0 and 604800")
        return v

    @field_validator("margin_rate_alert")
    @classmethod
    def _v_margin_rate(cls, v):
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("margin_rate_alert must be between 0 and 100")
        return v

    @field_validator("leverage_risk_alert")
    @classmethod
    def _v_leverage_risk(cls, v):
        if v is None:
            return v
        if v < 0 or v > 1000:
            raise ValueError("leverage_risk_alert must be between 0 and 1000")
        return v


class FeishuConfigResponse(BaseModel):
    id: int
    webhook_url: Optional[str] = None
    secret_key_masked: Optional[str] = None
    alert_interval_sec: int
    alert_count: int
    risk_alert_cooldown_sec: Optional[int] = 1800
    margin_rate_alert: Decimal
    leverage_risk_alert: Decimal
    enable_transfer_fail_alert: bool
    enable_new_borrow_alert: bool
    enable_borrow_success_alert: Optional[bool] = True
    enable_repay_success_alert: Optional[bool] = True
    alert_overrides: Optional[Dict[str, Any]] = None
    updated_at: datetime

    model_config = {"from_attributes": True}
