from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


class StrategyConfigCreate(BaseModel):
    """Schema for creating strategy configuration"""

    strategy_type: str = Field(..., pattern="^(forward|reverse)$")
    target_spread: float = Field(..., gt=0)
    order_qty: float = Field(..., gt=0)
    retry_times: int = Field(default=3, ge=1, le=10)
    mt5_stuck_threshold: int = Field(default=5, ge=1, le=20)
    opening_sync_count: int = Field(default=3, ge=1, le=100)
    closing_sync_count: int = Field(default=3, ge=1, le=100)
    is_enabled: bool = False


class StrategyConfigUpdate(BaseModel):
    """Schema for updating strategy configuration"""

    target_spread: Optional[float] = Field(None, gt=0)
    order_qty: Optional[float] = Field(None, gt=0)
    retry_times: Optional[int] = Field(None, ge=1, le=10)
    mt5_stuck_threshold: Optional[int] = Field(None, ge=1, le=20)
    opening_sync_count: Optional[int] = Field(None, ge=1, le=100)
    closing_sync_count: Optional[int] = Field(None, ge=1, le=100)
    is_enabled: Optional[bool] = None


class StrategyConfigResponse(BaseModel):
    """Schema for strategy configuration response"""

    config_id: UUID
    user_id: UUID
    strategy_type: str
    target_spread: float
    order_qty: float
    retry_times: int
    mt5_stuck_threshold: int
    opening_sync_count: int
    closing_sync_count: int
    is_enabled: bool
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True


class StrategyAutomationResponse(BaseModel):
    """Schema for strategy automation response"""

    success: bool
    message: str
    strategy_id: int
