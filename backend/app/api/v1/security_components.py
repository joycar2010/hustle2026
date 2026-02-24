"""安全组件管理API路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from uuid import UUID
import logging
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.security_component import SecurityComponent, SecurityComponentLog
from app.schemas.security import (
    SecurityComponentResponse, SecurityComponentUpdate,
    SecurityComponentStatusResponse, SecurityComponentLogResponse,
    ComponentEnableRequest, ComponentConfigUpdate
)
from app.services.permission_cache import permission_cache

router = APIRouter()
logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def log_component_action(
    db: AsyncSession,
    component_id: UUID,
    action: str,
    result: str,
    user_id: str,
    ip_address: str,
    old_config: dict = None,
    new_config: dict = None,
    error_message: str = None
):
    """记录安全组件操作日志"""
    log = SecurityComponentLog(
        component_id=component_id,
        action=action,
        old_config=old_config,
        new_config=new_config,
        result=result,
        error_message=error_message,
        performed_by=UUID(user_id),
        ip_address=ip_address
    )
    db.add(log)
    await db.commit()


# ==================== 安全组件列表与详情 ====================

@router.get("/components", response_model=List[SecurityComponentResponse])
async def get_security_components(
    component_type: Optional[str] = Query(None, description="组件类型: middleware, service, protection"),
    is_enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取安全组件列表"""
    try:
        query = select(SecurityComponent)

        if component_type:
            query = query.where(SecurityComponent.component_type == component_type)
        if is_enabled is not None:
            query = query.where(SecurityComponent.is_enabled == is_enabled)

        query = query.order_by(SecurityComponent.priority.desc(), SecurityComponent.component_name)

        result = await db.execute(query)
        components = result.scalars().all()

        logger.info(f"获取安全组件列表成功，共 {len(components)} 个组件")
        return components
    except Exception as e:
        logger.error(f"获取安全组件列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取安全组件列表失败")


@router.get("/components/{component_id}", response_model=SecurityComponentResponse)
async def get_security_component(
    component_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取安全组件详情"""
    try:
        result = await db.execute(
            select(SecurityComponent).where(SecurityComponent.component_id == component_id)
        )
        component = result.scalar_one_or_none()

        if not component:
            raise HTTPException(status_code=404, detail="安全组件不存在")

        return component
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取安全组件详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取安全组件详情失败")


# ==================== 启用/禁用组件 ====================

@router.post("/components/{component_id}/enable", status_code=status.HTTP_200_OK)
async def enable_security_component(
    component_id: UUID,
    enable_data: ComponentEnableRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """启用安全组件"""
    try:
        result = await db.execute(
            select(SecurityComponent).where(SecurityComponent.component_id == component_id)
        )
        component = result.scalar_one_or_none()

        if not component:
            raise HTTPException(status_code=404, detail="安全组件不存在")

        if component.is_enabled:
            raise HTTPException(status_code=400, detail="组件已处于启用状态")

        # 更新组件状态
        old_config = component.config_json
        component.is_enabled = True
        component.status = 'active'
        component.last_check_at = datetime.utcnow()
        component.error_message = None
        component.updated_by = UUID(current_user_id)

        await db.commit()
        await db.refresh(component)

        # 更新Redis缓存
        await permission_cache.set_component_status(
            component.component_code,
            {
                "is_enabled": True,
                "status": "active",
                "config": component.config_json
            }
        )

        # 记录操作日志
        await log_component_action(
            db=db,
            component_id=component_id,
            action="enable",
            result="success",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            old_config=old_config,
            new_config=component.config_json
        )

        logger.info(f"安全组件启用成功: {component.component_code}")
        return {"message": "安全组件已启用", "component_code": component.component_code}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"启用安全组件失败: {e}")

        # 记录失败日志
        await log_component_action(
            db=db,
            component_id=component_id,
            action="enable",
            result="failure",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            error_message=str(e)
        )

        raise HTTPException(status_code=500, detail=f"启用安全组件失败: {str(e)}")


@router.post("/components/{component_id}/disable", status_code=status.HTTP_200_OK)
async def disable_security_component(
    component_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """禁用安全组件"""
    try:
        result = await db.execute(
            select(SecurityComponent).where(SecurityComponent.component_id == component_id)
        )
        component = result.scalar_one_or_none()

        if not component:
            raise HTTPException(status_code=404, detail="安全组件不存在")

        if not component.is_enabled:
            raise HTTPException(status_code=400, detail="组件已处于禁用状态")

        # 更新组件状态
        old_config = component.config_json
        component.is_enabled = False
        component.status = 'inactive'
        component.last_check_at = datetime.utcnow()
        component.updated_by = UUID(current_user_id)

        await db.commit()
        await db.refresh(component)

        # 更新Redis缓存
        await permission_cache.set_component_status(
            component.component_code,
            {
                "is_enabled": False,
                "status": "inactive",
                "config": component.config_json
            }
        )

        # 记录操作日志
        await log_component_action(
            db=db,
            component_id=component_id,
            action="disable",
            result="success",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            old_config=old_config,
            new_config=component.config_json
        )

        logger.info(f"安全组件禁用成功: {component.component_code}")
        return {"message": "安全组件已禁用", "component_code": component.component_code}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"禁用安全组件失败: {e}")

        # 记录失败日志
        await log_component_action(
            db=db,
            component_id=component_id,
            action="disable",
            result="failure",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            error_message=str(e)
        )

        raise HTTPException(status_code=500, detail=f"禁用安全组件失败: {str(e)}")


# ==================== 更新组件配置 ====================

@router.put("/components/{component_id}/config", response_model=SecurityComponentResponse)
async def update_component_config(
    component_id: UUID,
    config_data: ComponentConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """更新安全组件配置"""
    try:
        result = await db.execute(
            select(SecurityComponent).where(SecurityComponent.component_id == component_id)
        )
        component = result.scalar_one_or_none()

        if not component:
            raise HTTPException(status_code=404, detail="安全组件不存在")

        # 保存旧配置
        old_config = component.config_json

        # 更新配置
        component.config_json = config_data.config_json
        if config_data.priority is not None:
            component.priority = config_data.priority
        component.updated_by = UUID(current_user_id)

        await db.commit()
        await db.refresh(component)

        # 更新Redis缓存
        await permission_cache.set_component_status(
            component.component_code,
            {
                "is_enabled": component.is_enabled,
                "status": component.status,
                "config": component.config_json
            }
        )

        # 记录操作日志
        await log_component_action(
            db=db,
            component_id=component_id,
            action="config_update",
            result="success",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            old_config=old_config,
            new_config=component.config_json
        )

        logger.info(f"安全组件配置更新成功: {component.component_code}")
        return component

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"更新组件配置失败: {e}")

        # 记录失败日志
        await log_component_action(
            db=db,
            component_id=component_id,
            action="config_update",
            result="failure",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            error_message=str(e)
        )

        raise HTTPException(status_code=500, detail=f"更新组件配置失败: {str(e)}")


# ==================== 获取组件状态 ====================

@router.get("/components/{component_id}/status", response_model=SecurityComponentStatusResponse)
async def get_component_status(
    component_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取安全组件运行状态"""
    try:
        result = await db.execute(
            select(SecurityComponent).where(SecurityComponent.component_id == component_id)
        )
        component = result.scalar_one_or_none()

        if not component:
            raise HTTPException(status_code=404, detail="安全组件不存在")

        # 尝试从Redis获取实时状态
        cached_status = await permission_cache.get_component_status(component.component_code)

        return {
            "component_id": component.component_id,
            "component_code": component.component_code,
            "component_name": component.component_name,
            "is_enabled": component.is_enabled,
            "status": component.status,
            "last_check_at": component.last_check_at,
            "error_message": component.error_message,
            "cached_status": cached_status
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取组件状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取组件状态失败")


# ==================== 获取操作日志 ====================

@router.get("/components/{component_id}/logs", response_model=List[SecurityComponentLogResponse])
async def get_component_logs(
    component_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    action: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取安全组件操作日志"""
    try:
        query = select(SecurityComponentLog).where(
            SecurityComponentLog.component_id == component_id
        )

        if action:
            query = query.where(SecurityComponentLog.action == action)

        query = query.order_by(SecurityComponentLog.performed_at.desc()).offset(skip).limit(limit)

        result = await db.execute(query)
        logs = result.scalars().all()

        return logs

    except Exception as e:
        logger.error(f"获取组件日志失败: {e}")
        raise HTTPException(status_code=500, detail="获取组件日志失败")
