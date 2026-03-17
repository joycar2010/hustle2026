"""
MT5客户端Schema定义
"""
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import os


class MT5ClientBase(BaseModel):
    """MT5客户端基础Schema"""
    client_name: str = Field(..., min_length=1, max_length=100, description="客户端名称")
    mt5_path: str = Field(..., min_length=1, max_length=500, description="MT5可执行文件路径")
    mt5_data_path: Optional[str] = Field(None, max_length=500, description="MT5数据目录路径")
    mt5_login: str = Field(..., min_length=1, max_length=100, description="MT5账号")
    mt5_password: str = Field(..., min_length=1, max_length=256, description="MT5密码")
    mt5_server: str = Field(..., min_length=1, max_length=100, description="MT5服务器地址")
    password_type: str = Field(default="primary", description="密码类型: primary/readonly")
    proxy_id: Optional[int] = Field(None, description="绑定的代理ID")
    is_active: bool = Field(default=True, description="是否启用")
    priority: int = Field(default=0, ge=0, description="优先级（数字越小优先级越高）")

    @validator('password_type')
    def validate_password_type(cls, v):
        if v not in ['primary', 'readonly']:
            raise ValueError('password_type must be primary or readonly')
        return v

    @validator('mt5_path')
    def validate_mt5_path(cls, v):
        """验证MT5路径格式"""
        if not v.endswith('.exe') and not v.endswith('terminal64'):
            raise ValueError('MT5 path must point to an executable file')
        return v


class MT5ClientCreate(MT5ClientBase):
    """创建MT5客户端"""
    pass


class MT5ClientUpdate(BaseModel):
    """更新MT5客户端"""
    client_name: Optional[str] = Field(None, min_length=1, max_length=100)
    mt5_path: Optional[str] = Field(None, min_length=1, max_length=500)
    mt5_data_path: Optional[str] = Field(None, max_length=500)
    mt5_login: Optional[str] = Field(None, min_length=1, max_length=100)
    mt5_password: Optional[str] = Field(None, min_length=1, max_length=256)
    mt5_server: Optional[str] = Field(None, min_length=1, max_length=100)
    password_type: Optional[str] = None
    proxy_id: Optional[int] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0)

    @validator('password_type')
    def validate_password_type(cls, v):
        if v is not None and v not in ['primary', 'readonly']:
            raise ValueError('password_type must be primary or readonly')
        return v


class MT5ClientResponse(MT5ClientBase):
    """MT5客户端响应"""
    client_id: int
    account_id: str
    connection_status: str
    last_connected_at: Optional[datetime] = None
    last_disconnected_at: Optional[datetime] = None
    total_connections: int = 0
    failed_connections: int = 0
    avg_latency_ms: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MT5ClientStatusUpdate(BaseModel):
    """MT5客户端状态更新"""
    connection_status: str = Field(..., description="连接状态: connected/disconnected/error")
    avg_latency_ms: Optional[float] = Field(None, description="平均延迟")

    @validator('connection_status')
    def validate_status(cls, v):
        if v not in ['connected', 'disconnected', 'error']:
            raise ValueError('connection_status must be connected, disconnected, or error')
        return v


class MT5PathDetection(BaseModel):
    """MT5路径检测结果"""
    path: str
    exists: bool
    is_valid: bool
    version: Optional[str] = None
