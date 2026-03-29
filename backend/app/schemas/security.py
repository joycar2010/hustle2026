"""安全组件相关Pydantic Schemas"""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID


# ==================== 安全组件 Schemas ====================

class SecurityComponentBase(BaseModel):
    """安全组件基础Schema"""
    component_name: str = Field(..., min_length=2, max_length=100, description="组件名称")
    component_code: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z_]+$", description="组件代码")
    component_type: str = Field(..., description="组件类型: middleware, service, protection")
    description: Optional[str] = Field(None, max_length=1000, description="组件描述")


class SecurityComponentCreate(SecurityComponentBase):
    """创建安全组件Schema"""
    config_json: Optional[Dict[str, Any]] = Field(default_factory=dict, description="组件配置（JSON格式）")
    priority: int = Field(default=0, ge=0, le=100, description="执行优先级（0-100）")
    is_enabled: bool = Field(default=False, description="是否启用")


class SecurityComponentUpdate(BaseModel):
    """更新安全组件Schema"""
    component_name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    priority: Optional[int] = Field(None, ge=0, le=100)


class SecurityComponentResponse(SecurityComponentBase):
    """安全组件响应Schema"""
    component_id: UUID
    is_enabled: bool
    config_json: Optional[Dict[str, Any]]
    priority: int
    status: str
    last_check_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID]
    updated_by: Optional[UUID]

    class Config:
        from_attributes = True


# ==================== 组件操作 Schemas ====================

class ComponentEnableRequest(BaseModel):
    """启用组件请求Schema"""
    force: bool = Field(default=False, description="是否强制启用（忽略依赖检查）")


class ComponentConfigUpdate(BaseModel):
    """更新组件配置Schema"""
    config_json: Dict[str, Any] = Field(..., description="组件配置（JSON格式）")
    priority: Optional[int] = Field(None, ge=0, le=100, description="执行优先级")


class SecurityComponentStatusResponse(BaseModel):
    """安全组件状态响应Schema"""
    component_id: UUID
    component_code: str
    component_name: str
    is_enabled: bool
    status: str
    last_check_at: Optional[datetime]
    error_message: Optional[str]
    cached_status: Optional[Dict[str, Any]] = Field(None, description="Redis缓存的状态")


# ==================== 组件日志 Schemas ====================

class SecurityComponentLogResponse(BaseModel):
    """安全组件日志响应Schema"""
    log_id: UUID
    component_id: UUID
    action: str
    old_config: Optional[Dict[str, Any]]
    new_config: Optional[Dict[str, Any]]
    result: str
    error_message: Optional[str]
    performed_by: Optional[UUID]
    performed_at: datetime
    ip_address: Optional[str]

    class Config:
        from_attributes = True


# ==================== 批量操作 Schemas ====================

class ComponentBatchEnableRequest(BaseModel):
    """批量启用组件请求Schema"""
    component_ids: list[UUID] = Field(..., min_items=1, description="组件ID列表")
    force: bool = Field(default=False, description="是否强制启用")


class ComponentBatchOperationResponse(BaseModel):
    """批量操作响应Schema"""
    success_count: int = Field(..., description="成功数量")
    failure_count: int = Field(..., description="失败数量")
    failed_components: list[Dict[str, str]] = Field(default_factory=list, description="失败的组件列表")
