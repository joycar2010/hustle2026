"""
MT5实例 Schema
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum


class InstanceType(str, Enum):
    """实例类型枚举"""
    PRIMARY = "primary"
    BACKUP = "backup"


class MT5InstanceBase(BaseModel):
    """MT5实例基础Schema"""
    instance_name: str = Field(..., description="实例名称")
    server_ip: str = Field(..., description="Windows服务器IP")
    service_port: int = Field(..., description="服务端口", ge=1024, le=65535)
    mt5_path: str = Field(..., description="MT5可执行文件路径")
    mt5_data_path: Optional[str] = Field(None, description="MT5数据目录")
    is_portable: bool = Field(False, description="是否为便携版")
    deploy_path: str = Field(..., description="服务部署路径")
    auto_start: bool = Field(True, description="开机自启")


class MT5InstanceCreate(MT5InstanceBase):
    """创建MT5实例"""
    client_id: Optional[int] = Field(None, description="关联的MT5客户端ID")
    instance_type: InstanceType = Field(InstanceType.PRIMARY, description="实例类型")


class MT5InstanceUpdate(BaseModel):
    """更新MT5实例"""
    instance_name: Optional[str] = None
    mt5_path: Optional[str] = None
    mt5_data_path: Optional[str] = None
    is_portable: Optional[bool] = None
    deploy_path: Optional[str] = None
    auto_start: Optional[bool] = None
    is_active: Optional[bool] = None
    instance_type: Optional[InstanceType] = None


class MT5InstanceResponse(MT5InstanceBase):
    """MT5实例响应"""
    instance_id: UUID
    client_id: Optional[int] = None
    instance_type: str
    status: str = Field(..., description="运行状态")
    is_active: bool
    mt5_connected: Optional[bool] = Field(default=False, description="MT5客户端连接状态")
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None

    class Config:
        from_attributes = True


class MT5InstanceControl(BaseModel):
    """MT5实例控制操作"""
    action: str = Field(..., description="操作类型: start/stop/restart")


class MT5InstanceSwitch(BaseModel):
    """切换活动实例"""
    target_instance_id: UUID = Field(..., description="目标实例ID")
