"""RBAC权限管理API路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional
from uuid import UUID
import logging

from app.core.database import get_db
from app.core.security import get_current_user_id_optional
from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.user_role import UserRole
from app.schemas.rbac import (
    RoleCreate, RoleUpdate, RoleResponse, RoleWithPermissions,
    PermissionResponse, PermissionCreate, PermissionUpdate,
    RolePermissionAssign, UserRoleAssign,
    RoleCopy
)
from app.services.permission_cache import permission_cache

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== 角色管理 ====================

@router.get("/roles", response_model=List[RoleResponse])
async def get_roles(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
    # current_user_id: Optional[str] = Depends(get_current_user_id_optional)  # Temporarily disabled
):
    """获取角色列表"""
    try:
        query = select(Role)

        if is_active is not None:
            query = query.where(Role.is_active == is_active)

        query = query.offset(skip).limit(limit).order_by(Role.created_at.desc())

        result = await db.execute(query)
        roles = result.scalars().all()

        return roles
    except Exception as e:
        logger.error(f"获取角色列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取角色列表失败")


@router.get("/roles/{role_id}", response_model=RoleWithPermissions)
async def get_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """获取角色详情（包含权限）"""
    try:
        # 获取角色
        result = await db.execute(select(Role).where(Role.role_id == role_id))
        role = result.scalar_one_or_none()

        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 获取角色权限
        result = await db.execute(
            select(Permission)
            .join(RolePermission, Permission.permission_id == RolePermission.permission_id)
            .where(RolePermission.role_id == role_id)
        )
        permissions = result.scalars().all()

        return {
            **role.__dict__,
            "permissions": permissions
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取角色详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取角色详情失败")


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """创建角色"""
    try:
        # 检查角色代码是否已存在
        result = await db.execute(select(Role).where(Role.role_code == role_data.role_code))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="角色代码已存在")

        # 创建角色
        new_role = Role(
            role_name=role_data.role_name,
            role_code=role_data.role_code,
            description=role_data.description,
            is_active=role_data.is_active,
            created_by=UUID(current_user_id)
        )

        db.add(new_role)
        await db.commit()
        await db.refresh(new_role)

        logger.info(f"角色创建成功: {new_role.role_code}")
        return new_role
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"创建角色失败: {e}")
        raise HTTPException(status_code=500, detail="创建角色失败")


@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    role_data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """更新角色"""
    try:
        result = await db.execute(select(Role).where(Role.role_id == role_id))
        role = result.scalar_one_or_none()

        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")

        if role.is_system:
            raise HTTPException(status_code=403, detail="系统内置角色不可修改")

        # 更新字段
        if role_data.role_name is not None:
            role.role_name = role_data.role_name
        if role_data.description is not None:
            role.description = role_data.description
        if role_data.is_active is not None:
            role.is_active = role_data.is_active

        role.updated_by = UUID(current_user_id)

        await db.commit()
        await db.refresh(role)

        # 清除角色权限缓存
        await permission_cache.delete_role_permissions(str(role_id))

        logger.info(f"角色更新成功: {role.role_code}")
        return role
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"更新角色失败: {e}")
        raise HTTPException(status_code=500, detail="更新角色失败")


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """删除角色"""
    try:
        result = await db.execute(select(Role).where(Role.role_id == role_id))
        role = result.scalar_one_or_none()

        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")

        if role.is_system:
            raise HTTPException(status_code=403, detail="系统内置角色不可删除")

        # 检查是否有用户使用该角色
        result = await db.execute(select(UserRole).where(UserRole.role_id == role_id).limit(1))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="该角色正在被使用，无法删除")

        await db.delete(role)
        await db.commit()

        # 清除缓存
        await permission_cache.delete_role_permissions(str(role_id))

        logger.info(f"角色删除成功: {role.role_code}")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"删除角色失败: {e}")
        raise HTTPException(status_code=500, detail="删除角色失败")


@router.post("/roles/{role_id}/copy", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def copy_role(
    role_id: UUID,
    copy_data: RoleCopy,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """复制角色（包含权限）"""
    try:
        # 获取源角色
        result = await db.execute(select(Role).where(Role.role_id == role_id))
        source_role = result.scalar_one_or_none()

        if not source_role:
            raise HTTPException(status_code=404, detail="源角色不存在")

        # 检查新角色代码是否已存在
        result = await db.execute(select(Role).where(Role.role_code == copy_data.new_role_code))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="新角色代码已存在")

        # 创建新角色
        new_role = Role(
            role_name=copy_data.new_role_name,
            role_code=copy_data.new_role_code,
            description=source_role.description,
            is_active=True,
            created_by=UUID(current_user_id)
        )
        db.add(new_role)
        await db.flush()

        # 复制权限
        if copy_data.copy_permissions:
            result = await db.execute(
                select(RolePermission).where(RolePermission.role_id == role_id)
            )
            source_permissions = result.scalars().all()

            for perm in source_permissions:
                new_perm = RolePermission(
                    role_id=new_role.role_id,
                    permission_id=perm.permission_id,
                    granted_by=UUID(current_user_id)
                )
                db.add(new_perm)

        await db.commit()
        await db.refresh(new_role)

        logger.info(f"角色复制成功: {source_role.role_code} -> {new_role.role_code}")
        return new_role
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"复制角色失败: {e}")
        raise HTTPException(status_code=500, detail="复制角色失败")


# ==================== 权限管理 ====================

@router.get("/permissions", response_model=List[PermissionResponse])
async def get_permissions(
    resource_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """获取权限列表"""
    try:
        query = select(Permission)

        if resource_type:
            query = query.where(Permission.resource_type == resource_type)
        if is_active is not None:
            query = query.where(Permission.is_active == is_active)

        query = query.order_by(Permission.sort_order, Permission.permission_name)

        result = await db.execute(query)
        permissions = result.scalars().all()

        return permissions
    except Exception as e:
        logger.error(f"获取权限列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取权限列表失败")


@router.get("/permissions/{permission_id}", response_model=PermissionResponse)
async def get_permission(
    permission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """获取权限详情"""
    try:
        result = await db.execute(select(Permission).where(Permission.permission_id == permission_id))
        permission = result.scalar_one_or_none()

        if not permission:
            raise HTTPException(status_code=404, detail="权限不存在")

        return permission
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取权限详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取权限详情失败")


@router.post("/permissions", response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
async def create_permission(
    permission_data: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """创建权限"""
    try:
        # 检查权限代码是否已存在
        result = await db.execute(select(Permission).where(Permission.permission_code == permission_data.permission_code))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="权限代码已存在")

        # 如果有父权限，检查父权限是否存在
        if permission_data.parent_id:
            result = await db.execute(select(Permission).where(Permission.permission_id == permission_data.parent_id))
            if not result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="父权限不存在")

        # 创建权限
        new_permission = Permission(
            permission_name=permission_data.permission_name,
            permission_code=permission_data.permission_code,
            resource_type=permission_data.resource_type,
            resource_path=permission_data.resource_path,
            http_method=permission_data.http_method,
            description=permission_data.description,
            parent_id=permission_data.parent_id,
            sort_order=permission_data.sort_order,
            is_active=permission_data.is_active
        )

        db.add(new_permission)
        await db.commit()
        await db.refresh(new_permission)

        logger.info(f"权限创建成功: {new_permission.permission_code}")
        return new_permission
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"创建权限失败: {e}")
        raise HTTPException(status_code=500, detail="创建权限失败")


@router.put("/permissions/{permission_id}", response_model=PermissionResponse)
async def update_permission(
    permission_id: UUID,
    permission_data: PermissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """更新权限"""
    try:
        result = await db.execute(select(Permission).where(Permission.permission_id == permission_id))
        permission = result.scalar_one_or_none()

        if not permission:
            raise HTTPException(status_code=404, detail="权限不存在")

        # 更新字段
        if permission_data.permission_name is not None:
            permission.permission_name = permission_data.permission_name
        if permission_data.description is not None:
            permission.description = permission_data.description
        if permission_data.sort_order is not None:
            permission.sort_order = permission_data.sort_order
        if permission_data.is_active is not None:
            permission.is_active = permission_data.is_active

        await db.commit()
        await db.refresh(permission)

        # 清除相关缓存
        await permission_cache.clear_all_user_permissions()

        logger.info(f"权限更新成功: {permission.permission_code}")
        return permission
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"更新权限失败: {e}")
        raise HTTPException(status_code=500, detail="更新权限失败")


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """删除权限"""
    try:
        result = await db.execute(select(Permission).where(Permission.permission_id == permission_id))
        permission = result.scalar_one_or_none()

        if not permission:
            raise HTTPException(status_code=404, detail="权限不存在")

        # 检查是否有子权限
        result = await db.execute(select(Permission).where(Permission.parent_id == permission_id).limit(1))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="该权限存在子权限，无法删除")

        # 检查是否有角色使用该权限
        result = await db.execute(select(RolePermission).where(RolePermission.permission_id == permission_id).limit(1))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="该权限正在被角色使用，无法删除")

        await db.delete(permission)
        await db.commit()

        # 清除缓存
        await permission_cache.clear_all_user_permissions()

        logger.info(f"权限删除成功: {permission.permission_code}")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"删除权限失败: {e}")
        raise HTTPException(status_code=500, detail="删除权限失败")


# ==================== 角色权限分配 ====================

@router.post("/roles/{role_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
async def assign_permissions_to_role(
    role_id: UUID,
    assign_data: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """为角色分配权限（批量）"""
    try:
        # 检查角色是否存在
        result = await db.execute(select(Role).where(Role.role_id == role_id))
        role = result.scalar_one_or_none()

        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")

        if role.is_system:
            raise HTTPException(status_code=403, detail="系统内置角色不可修改权限")

        # 删除现有权限
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))

        # 添加新权限
        for permission_id in assign_data.permission_ids:
            role_permission = RolePermission(
                role_id=role_id,
                permission_id=permission_id,
                granted_by=UUID(current_user_id) if current_user_id else None
            )
            db.add(role_permission)

        await db.commit()

        # 清除缓存
        await permission_cache.delete_role_permissions(str(role_id))
        await permission_cache.clear_all_user_permissions()  # 清除所有用户权限缓存

        logger.info(f"角色权限分配成功: {role.role_code}, 共 {len(assign_data.permission_ids)} 个权限")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"分配角色权限失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分配角色权限失败: {str(e)}")


# ==================== 用户角色分配 ====================

@router.post("/users/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
async def assign_roles_to_user(
    user_id: UUID,
    assign_data: UserRoleAssign,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """为用户分配角色（批量）"""
    try:
        # 删除现有角色
        await db.execute(delete(UserRole).where(UserRole.user_id == user_id))

        # 添加新角色
        for role_id in assign_data.role_ids:
            user_role = UserRole(
                user_id=user_id,
                role_id=role_id,
                assigned_by=UUID(current_user_id) if current_user_id else None,
                expires_at=assign_data.expires_at
            )
            db.add(user_role)

        await db.commit()

        # 清除用户权限缓存
        await permission_cache.delete_user_permissions(str(user_id))

        logger.info(f"用户角色分配成功: user_id={user_id}, 共 {len(assign_data.role_ids)} 个角色")
    except Exception as e:
        await db.rollback()
        logger.error(f"分配用户角色失败: {e}")
        raise HTTPException(status_code=500, detail="分配用户角色失败")


@router.get("/users/{user_id}/permissions", response_model=List[PermissionResponse])
async def get_user_permissions(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """获取用户的所有权限（通过角色）"""
    try:
        # 先尝试从缓存获取
        cached_permissions = await permission_cache.get_user_permissions(str(user_id))

        if cached_permissions:
            # 从数据库获取权限详情
            result = await db.execute(
                select(Permission).where(Permission.permission_code.in_(cached_permissions))
            )
            return result.scalars().all()

        # 从数据库查询
        result = await db.execute(
            select(Permission)
            .join(RolePermission, Permission.permission_id == RolePermission.permission_id)
            .join(UserRole, RolePermission.role_id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .where(Permission.is_active == True)
            .distinct()
        )
        permissions = result.scalars().all()

        # 更新缓存
        permission_codes = {p.permission_code for p in permissions}
        await permission_cache.set_user_permissions(str(user_id), permission_codes)

        return permissions
    except Exception as e:
        logger.error(f"获取用户权限失败: {e}")
        raise HTTPException(status_code=500, detail="获取用户权限失败")
