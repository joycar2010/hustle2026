from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class FeishuConfigUpdate(BaseModel):
    webhook_url: Optional[str] = None
    secret_key: Optional[str] = None
    alert_interval_sec: Optional[int] = None
    alert_count: Optional[int] = None
    margin_rate_alert: Optional[Decimal] = None
    leverage_risk_alert: Optional[Decimal] = None
    enable_transfer_fail_alert: Optional[bool] = None
    enable_new_borrow_alert: Optional[bool] = None


class FeishuConfigResponse(BaseModel):
    id: int
    webhook_url: Optional[str] = None
    secret_key_masked: Optional[str] = None
    alert_interval_sec: int
    alert_count: int
    margin_rate_alert: Decimal
    leverage_risk_alert: Decimal
    enable_transfer_fail_alert: bool
    enable_new_borrow_alert: bool
    updated_at: datetime

    model_config = {"from_attributes": True}
