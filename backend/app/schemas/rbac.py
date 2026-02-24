"""RBAC相关Pydantic Schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from uuid import UUID


# ==================== 角色 Schemas ====================

class RoleBase(BaseModel):
    """角色基础Schema"""
    role_name: str = Field(..., min_length=2, max_length=50, description="角色名称")
    role_code: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z_]+$", description="角色代码（小写字母和下划线）")
    description: Optional[str] = Field(None, max_length=500, description="角色描述")


class RoleCreate(RoleBase):
    """创建角色Schema"""
    is_active: bool = Field(default=True, description="是否启用")


class RoleUpdate(BaseModel):
    """更新角色Schema"""
    role_name: Optional[str] = Field(None, min_length=2, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class RoleResponse(RoleBase):
    """角色响应Schema"""
    role_id: UUID
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID]

    class Config:
        from_attributes = True


class RoleCopy(BaseModel):
    """复制角色Schema"""
    new_role_name: str = Field(..., min_length=2, max_length=50, description="新角色名称")
    new_role_code: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z_]+$", description="新角色代码")
    copy_permissions: bool = Field(default=True, description="是否复制权限")


# ==================== 权限 Schemas ====================

class PermissionBase(BaseModel):
    """权限基础Schema"""
    permission_name: str = Field(..., min_length=2, max_length=100, description="权限名称")
    permission_code: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z:_]+$", description="权限代码")
    resource_type: str = Field(..., description="资源类型: api, menu, button")
    resource_path: Optional[str] = Field(None, max_length=255, description="资源路径")
    http_method: Optional[str] = Field(None, max_length=10, description="HTTP方法")
    description: Optional[str] = Field(None, max_length=500)


class PermissionCreate(PermissionBase):
    """创建权限Schema"""
    parent_id: Optional[UUID] = None
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True)


class PermissionUpdate(BaseModel):
    """更新权限Schema"""
    permission_name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class PermissionResponse(PermissionBase):
    """权限响应Schema"""
    permission_id: UUID
    parent_id: Optional[UUID]
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== 角色权限关联 Schemas ====================

class RolePermissionAssign(BaseModel):
    """角色权限分配Schema"""
    permission_ids: List[UUID] = Field(..., min_items=0, description="权限ID列表")


class RoleWithPermissions(RoleResponse):
    """角色及其权限Schema"""
    permissions: List[PermissionResponse] = Field(default_factory=list, description="角色拥有的权限列表")


# ==================== 用户角色关联 Schemas ====================

class UserRoleAssign(BaseModel):
    """用户角色分配Schema"""
    role_ids: List[UUID] = Field(..., min_items=1, description="角色ID列表")
    expires_at: Optional[datetime] = Field(None, description="角色过期时间，NULL表示永久")


class UserRoleResponse(BaseModel):
    """用户角色响应Schema"""
    id: UUID
    user_id: UUID
    role_id: UUID
    assigned_at: datetime
    expires_at: Optional[datetime]
    role: RoleResponse

    class Config:
        from_attributes = True


# ==================== 权限检查 Schemas ====================

class PermissionCheckRequest(BaseModel):
    """权限检查请求Schema"""
    permission_codes: List[str] = Field(..., min_items=1, description="需要检查的权限代码列表")


class PermissionCheckResponse(BaseModel):
    """权限检查响应Schema"""
    has_permission: bool = Field(..., description="是否拥有所有权限")
    missing_permissions: List[str] = Field(default_factory=list, description="缺失的权限代码")
