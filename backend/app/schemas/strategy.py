from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from uuid import UUID


class LadderConfig(BaseModel):
    enabled: bool = True
    openPrice: float = Field(default=3.0)
    threshold: float = Field(default=2.0)
    qtyLimit: float = Field(default=3.0, gt=0)


class StrategyConfigCreate(BaseModel):
    """Schema for creating strategy configuration"""
    strategy_type: str = Field(..., pattern="^(forward|reverse)$")
    target_spread: float = Field(default=1.0, gt=0)
    order_qty: float = Field(default=1.0, gt=0)
    retry_times: int = Field(default=3, ge=1, le=10)
    mt5_stuck_threshold: int = Field(default=5, ge=1, le=20)
    opening_sync_count: int = Field(default=3, ge=1, le=100)
    closing_sync_count: int = Field(default=3, ge=1, le=100)
    m_coin: Optional[float] = Field(default=None, gt=0)  # Deprecated, kept for backward compatibility
    opening_m_coin: float = Field(default=5.0, gt=0)
    closing_m_coin: float = Field(default=5.0, gt=0)
    ladders: List[LadderConfig] = Field(default_factory=lambda: [
        LadderConfig(enabled=True, openPrice=3.0, threshold=2.0, qtyLimit=3.0),
        LadderConfig(enabled=True, openPrice=3.0, threshold=3.0, qtyLimit=3.0),
        LadderConfig(enabled=False, openPrice=3.0, threshold=4.0, qtyLimit=3.0),
    ])
    is_enabled: bool = False


class StrategyConfigUpdate(BaseModel):
    """Schema for updating strategy configuration"""
    target_spread: Optional[float] = Field(None, gt=0)
    order_qty: Optional[float] = Field(None, gt=0)
    retry_times: Optional[int] = Field(None, ge=1, le=10)
    mt5_stuck_threshold: Optional[int] = Field(None, ge=1, le=20)
    opening_sync_count: Optional[int] = Field(None, ge=1, le=100)
    closing_sync_count: Optional[int] = Field(None, ge=1, le=100)
    m_coin: Optional[float] = Field(None, gt=0)  # Deprecated
    opening_m_coin: Optional[float] = Field(None, gt=0)
    closing_m_coin: Optional[float] = Field(None, gt=0)
    ladders: Optional[List[LadderConfig]] = None
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
    m_coin: float  # Kept for backward compatibility
    opening_m_coin: float
    closing_m_coin: float
    ladders: List[Any]
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
