"""
代理管理Schema定义
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime, date


class ProxyPoolBase(BaseModel):
    """代理池基础Schema"""
    proxy_type: str = Field(..., description="代理类型: http, https, socks5")
    host: str = Field(..., description="代理主机地址")
    port: int = Field(..., ge=1, le=65535, description="代理端口")
    username: Optional[str] = Field(None, description="代理用户名")
    password: Optional[str] = Field(None, description="代理密码")
    provider: str = Field(default="qingguo", description="代理提供商")
    region: Optional[str] = Field(None, description="代理地区")
    ip_address: Optional[str] = Field(None, description="代理IP地址")
    expire_time: Optional[datetime] = Field(None, description="过期时间")


class ProxyPoolCreate(ProxyPoolBase):
    """创建代理"""
    pass


class ProxyPoolUpdate(BaseModel):
    """更新代理"""
    proxy_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    region: Optional[str] = None
    ip_address: Optional[str] = None
    expire_time: Optional[datetime] = None
    status: Optional[str] = Field(None, description="状态: active, inactive, expired, failed")


class ProxyPoolResponse(ProxyPoolBase):
    """代理响应"""
    id: int
    status: str
    health_score: int
    last_check_time: Optional[datetime]
    total_requests: int
    failed_requests: int
    avg_latency_ms: Optional[float]
    success_rate: float
    proxy_url: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountProxyBindingBase(BaseModel):
    """账户代理绑定基础Schema"""
    account_id: str = Field(..., description="账户ID")
    proxy_id: int = Field(..., description="代理ID")
    platform_id: int = Field(..., ge=1, le=2, description="平台ID: 1=Binance, 2=Bybit")
    is_active: bool = Field(default=True, description="是否启用")
    priority: int = Field(default=0, description="优先级")


class AccountProxyBindingCreate(AccountProxyBindingBase):
    """创建账户代理绑定"""
    pass


class AccountProxyBindingUpdate(BaseModel):
    """更新账户代理绑定"""
    is_active: Optional[bool] = None
    priority: Optional[int] = None


class AccountProxyBindingResponse(AccountProxyBindingBase):
    """账户代理绑定响应"""
    id: int
    bind_time: datetime
    unbind_time: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProxyHealthLogResponse(BaseModel):
    """代理健康检查日志响应"""
    id: int
    proxy_id: int
    check_time: datetime
    is_success: bool
    latency_ms: Optional[float]
    error_message: Optional[str]
    check_type: str
    target_url: Optional[str]
    response_code: Optional[int]

    class Config:
        from_attributes = True


class ProxyUsageStatsResponse(BaseModel):
    """代理使用统计响应"""
    id: int
    proxy_id: int
    account_id: str
    platform_id: int
    date: date
    total_requests: int
    success_requests: int
    failed_requests: int
    avg_latency_ms: Optional[float]
    total_data_mb: float
    success_rate: float

    class Config:
        from_attributes = True


class ProxyHealthCheckRequest(BaseModel):
    """代理健康检查请求"""
    proxy_ids: Optional[List[int]] = Field(None, description="要检查的代理ID列表，为空则检查所有")
    check_type: str = Field(default="manual", description="检查类型: auto, manual")


class QingguoProxyRequest(BaseModel):
    """青果网络代理请求"""
    num: int = Field(default=1, ge=1, le=100, description="提取数量")
    region: Optional[str] = Field(None, description="地区")
    protocol: str = Field(default="http", description="协议类型: http, https, socks5")
    format: str = Field(default="json", description="返回格式: json, txt")
    expire_time: int = Field(default=3600, description="有效期(秒)")


class AccountProxyConfigRequest(BaseModel):
    """账户代理配置请求"""
    account_id: str = Field(..., description="账户ID")
    platform_id: int = Field(..., ge=1, le=2, description="平台ID: 1=Binance, 2=Bybit")
    proxy_id: Optional[int] = Field(None, description="代理ID，为空则解绑")
    auto_create: bool = Field(default=False, description="如果没有可用代理，是否自动从青果网络获取")
