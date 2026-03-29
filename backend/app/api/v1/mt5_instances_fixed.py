"""
MT5实例管理 API (异步版本)
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.schemas.mt5_instance import (
    MT5InstanceCreate,
    MT5InstanceUpdate,
    MT5InstanceResponse,
    MT5InstanceControl
)
from app.models.mt5_instance import MT5Instance
from app.services.mt5_agent_service import MT5AgentService

router = APIRouter(prefix="/mt5/instances", tags=["MT5 Instances"])


@router.get("", response_model=List[MT5InstanceResponse])
async def list_instances(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取所有MT5实例列表"""
    result = await db.execute(
        select(MT5Instance).offset(skip).limit(limit)
    )
    instances = result.scalars().all()
    return instances


@router.get("/{instance_id}", response_model=MT5InstanceResponse)
async def get_instance(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取单个MT5实例详情"""
    result = await db.execute(
        select(MT5Instance).filter(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )

    return instance


@router.post("", response_model=MT5InstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_instance(
    instance_data: MT5InstanceCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建新的MT5实例"""
    # 检查端口是否已被使用
    result = await db.execute(
        select(MT5Instance).filter(MT5Instance.service_port == instance_data.service_port)
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Port {instance_data.service_port} already in use"
        )

    # 创建实例记录
    instance = MT5Instance(**instance_data.dict())
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    # 调用 Windows Agent 部署实例
    agent_service = MT5AgentService(instance.server_ip)
    try:
        await agent_service.deploy_instance(
            port=instance.service_port,
            mt5_path=instance.mt5_path,
            deploy_path=instance.deploy_path,
            auto_start=instance.auto_start
        )
    except Exception as e:
        # 部署失败，删除数据库记录
        await db.delete(instance)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deploy instance: {str(e)}"
        )

    return instance


@router.put("/{instance_id}", response_model=MT5InstanceResponse)
async def update_instance(
    instance_id: UUID,
    instance_data: MT5InstanceUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新MT5实例配置"""
    result = await db.execute(
        select(MT5Instance).filter(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )

    # 更新字段
    for field, value in instance_data.dict(exclude_unset=True).items():
        setattr(instance, field, value)

    await db.commit()
    await db.refresh(instance)

    return instance


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除MT5实例"""
    result = await db.execute(
        select(MT5Instance).filter(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )

    # 调用 Windows Agent 删除实例
    agent_service = MT5AgentService(instance.server_ip)
    try:
        await agent_service.delete_instance(instance.service_port)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete instance: {str(e)}"
        )

    # 删除数据库记录
    await db.delete(instance)
    await db.commit()


@router.post("/{instance_id}/control")
async def control_instance(
    instance_id: UUID,
    control: MT5InstanceControl,
    db: AsyncSession = Depends(get_db)
):
    """控制MT5实例（启动/停止/重启）"""
    result = await db.execute(
        select(MT5Instance).filter(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )

    agent_service = MT5AgentService(instance.server_ip)

    try:
        if control.action == "start":
            await agent_service.start_instance(instance.service_port)
            instance.status = "running"
        elif control.action == "stop":
            await agent_service.stop_instance(instance.service_port)
            instance.status = "stopped"
        elif control.action == "restart":
            await agent_service.restart_instance(instance.service_port)
            instance.status = "running"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid action: {control.action}"
            )

        await db.commit()
        await db.refresh(instance)

        return {"status": "ok", "message": f"Instance {control.action}ed successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to {control.action} instance: {str(e)}"
        )


@router.get("/{instance_id}/status")
async def get_instance_status(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取MT5实例实时状态"""
    result = await db.execute(
        select(MT5Instance).filter(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )

    agent_service = MT5AgentService(instance.server_ip)

    try:
        status_data = await agent_service.get_instance_status(instance.service_port)

        # 更新数据库状态
        instance.status = status_data.get("status", "unknown")
        await db.commit()

        return status_data

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get instance status: {str(e)}"
        )
