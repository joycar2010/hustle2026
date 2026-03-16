"""Timing Configuration Schemas"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TimingConfigBase(BaseModel):
    """Base timing configuration schema"""
    # Trigger control
    trigger_check_interval: float = Field(default=0.5, ge=0.1, le=10.0, description="触发检查间隔(秒)")
    opening_trigger_count: int = Field(default=3, ge=1, le=10, description="开仓触发次数")
    closing_trigger_count: int = Field(default=3, ge=1, le=10, description="平仓触发次数")

    # Order execution
    binance_timeout: float = Field(default=5.0, ge=0.1, le=60.0, description="Binance订单监控超时(秒)")
    bybit_timeout: float = Field(default=0.1, ge=0.01, le=10.0, description="Bybit订单执行超时(秒)")
    order_check_interval: float = Field(default=0.2, ge=0.05, le=5.0, description="订单检查间隔(秒)")
    spread_check_interval: float = Field(default=2.0, ge=0.1, le=30.0, description="点差检查间隔(秒)")
    mt5_deal_sync_wait: float = Field(default=3.0, ge=0.1, le=30.0, description="MT5成交数据同步等待(秒)")

    # Flow control
    api_spam_prevention_delay: float = Field(default=3.0, ge=0.5, le=30.0, description="API防止频繁调用延迟(秒)")
    delayed_single_leg_check_delay: float = Field(default=10.0, ge=1.0, le=60.0, description="单腿延迟检查延迟(秒)")
    delayed_single_leg_second_check_delay: float = Field(default=1.0, ge=0.1, le=10.0, description="单腿第二次检查延迟(秒)")

    # Retry configuration
    api_retry_times: int = Field(default=3, ge=1, le=10, description="API重试次数")
    api_retry_delay: float = Field(default=0.5, ge=0.1, le=10.0, description="API重试延迟(秒)")
    max_binance_limit_retries: int = Field(default=25, ge=5, le=100, description="Binance限价单最大重试次数")

    # Wait delay
    open_wait_after_cancel_no_trade: float = Field(default=3.0, ge=0.5, le=30.0, description="开仓取消未成交后等待(秒)")
    open_wait_after_cancel_part: float = Field(default=2.0, ge=0.5, le=30.0, description="开仓取消部分成交后等待(秒)")
    close_wait_after_cancel_no_trade: float = Field(default=3.0, ge=0.5, le=30.0, description="平仓取消未成交后等待(秒)")
    close_wait_after_cancel_part: float = Field(default=2.0, ge=0.5, le=30.0, description="平仓取消部分成交后等待(秒)")

    # Frontend interaction
    status_polling_interval: float = Field(default=5.0, ge=1.0, le=30.0, description="状态轮询间隔(秒)")
    debounce_delay: float = Field(default=0.5, ge=0.1, le=2.0, description="防抖延迟(秒)")


class TimingConfigCreate(TimingConfigBase):
    """Create timing configuration schema"""
    config_level: str = Field(..., description="配置级别: global, strategy_type, instance")
    strategy_type: Optional[str] = Field(None, description="策略类型")
    strategy_instance_id: Optional[int] = Field(None, description="策略实例ID")


class TimingConfigUpdate(BaseModel):
    """Update timing configuration schema - all fields optional"""
    trigger_check_interval: Optional[float] = Field(None, ge=0.1, le=10.0)
    opening_trigger_count: Optional[int] = Field(None, ge=1, le=10)
    closing_trigger_count: Optional[int] = Field(None, ge=1, le=10)
    binance_timeout: Optional[float] = Field(None, ge=0.1, le=60.0)
    bybit_timeout: Optional[float] = Field(None, ge=0.01, le=10.0)
    order_check_interval: Optional[float] = Field(None, ge=0.05, le=5.0)
    spread_check_interval: Optional[float] = Field(None, ge=0.1, le=30.0)
    mt5_deal_sync_wait: Optional[float] = Field(None, ge=0.1, le=30.0)
    api_spam_prevention_delay: Optional[float] = Field(None, ge=0.5, le=30.0)
    delayed_single_leg_check_delay: Optional[float] = Field(None, ge=1.0, le=60.0)
    delayed_single_leg_second_check_delay: Optional[float] = Field(None, ge=0.1, le=10.0)
    api_retry_times: Optional[int] = Field(None, ge=1, le=10)
    api_retry_delay: Optional[float] = Field(None, ge=0.1, le=10.0)
    max_binance_limit_retries: Optional[int] = Field(None, ge=5, le=100)
    open_wait_after_cancel_no_trade: Optional[float] = Field(None, ge=0.5, le=30.0)
    open_wait_after_cancel_part: Optional[float] = Field(None, ge=0.5, le=30.0)
    close_wait_after_cancel_no_trade: Optional[float] = Field(None, ge=0.5, le=30.0)
    close_wait_after_cancel_part: Optional[float] = Field(None, ge=0.5, le=30.0)
    status_polling_interval: Optional[float] = Field(None, ge=1.0, le=30.0)
    debounce_delay: Optional[float] = Field(None, ge=0.1, le=2.0)
    template: Optional[str] = Field(None, description="配置模板名称")
    is_locked: Optional[bool] = Field(None, description="是否锁定配置")


class TimingConfigResponse(TimingConfigBase):
    """Timing configuration response schema"""
    id: int
    config_level: str
    strategy_type: Optional[str]
    strategy_instance_id: Optional[int]
    template: Optional[str]
    is_locked: bool
    locked_by: Optional[int]
    locked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int]

    class Config:
        from_attributes = True


class TimingConfigHistoryResponse(BaseModel):
    """Timing configuration history response schema"""
    id: int
    config_id: int
    config_level: str
    strategy_type: Optional[str]
    strategy_instance_id: Optional[int]
    config_data: dict
    template: Optional[str]
    created_at: datetime
    created_by: Optional[int]
    change_reason: Optional[str]

    class Config:
        from_attributes = True


class TimingConfigTemplateCreate(BaseModel):
    """Create custom template schema"""
    strategy_type: str = Field(..., description="策略类型")
    name: str = Field(..., min_length=1, max_length=100, description="模板名称")
    description: Optional[str] = Field(None, max_length=200, description="模板描述")
    config_data: dict = Field(..., description="配置数据")


class TimingConfigTemplateResponse(BaseModel):
    """Custom template response schema"""
    id: int
    strategy_type: str
    name: str
    description: Optional[str]
    config_data: dict
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True
