from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID

class StrategyConfigBase(BaseModel):
    strategy_type: str
    target_spread: float
    order_qty: float
    retry_times: int = 3
    mt5_stuck_threshold: int = 5
    is_enabled: bool = False

class StrategyConfigCreate(StrategyConfigBase):
    pass

class StrategyConfigUpdate(BaseModel):
    target_spread: Optional[float] = None
    order_qty: Optional[float] = None
    retry_times: Optional[int] = None
    mt5_stuck_threshold: Optional[int] = None
    is_enabled: Optional[bool] = None

class StrategyConfigResponse(StrategyConfigBase):
    config_id: UUID
    user_id: UUID
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True
