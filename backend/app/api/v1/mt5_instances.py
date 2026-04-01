"""
MT5实例管理 API
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.schemas.mt5_instance import (
    MT5InstanceCreate,
    MT5InstanceUpdate,
    MT5InstanceResponse,
    MT5InstanceControl
)
from app.models.mt5_instance import MT5Instance
from app.models.mt5_client import MT5Client
from app.services.mt5_agent_service import MT5AgentService

router = APIRouter(prefix="/mt5/instances", tags=["MT5 Instances"])


@router.get("", response_model=List[MT5InstanceResponse])
async def list_instances(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取所有MT5实例列表"""
    result = await db.execute(select(MT5Instance).offset(skip).limit(limit))
    instances = result.scalars().all()
    return instances


@router.get("/{instance_id}", response_model=MT5InstanceResponse)
async def get_instance(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取单个MT5实例详情"""
    result = await db.execute(
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
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
        select(MT5Instance).where(MT5Instance.service_port == instance_data.service_port)
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
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
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
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
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
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
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
            await agent_service.start_instance_by_name(instance.instance_name)
            instance.status = "running"
        elif control.action == "stop":
            await agent_service.stop_instance_by_name(instance.instance_name)
            instance.status = "stopped"
        elif control.action == "restart":
            await agent_service.restart_instance_by_name(instance.instance_name)
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
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
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


# ==================== 客户端关联功能 ====================

@router.get("/client/{client_id}", response_model=List[MT5InstanceResponse])
async def list_instances_by_client(
    client_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取指定MT5客户端的所有实例"""
    result = await db.execute(
        select(MT5Instance).where(MT5Instance.client_id == client_id)
    )
    instances = result.scalars().all()
    return instances


@router.post("/client/{client_id}/deploy", response_model=MT5InstanceResponse, status_code=status.HTTP_201_CREATED)
async def deploy_instance_for_client(
    client_id: int,
    instance_data: MT5InstanceCreate,
    db: AsyncSession = Depends(get_db)
):
    """为指定MT5客户端部署新实例"""
    # 检查客户端是否存在
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 检查该客户端的实例数量（最多2个）
    count_result = await db.execute(
        select(func.count(MT5Instance.instance_id)).where(MT5Instance.client_id == client_id)
    )
    instance_count = count_result.scalar()

    if instance_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 2 instances per client (primary and backup)"
        )

    # 检查该类型的实例是否已存在
    type_result = await db.execute(
        select(MT5Instance).where(
            MT5Instance.client_id == client_id,
            MT5Instance.instance_type == instance_data.instance_type
        )
    )
    existing_type = type_result.scalar_one_or_none()

    if existing_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instance type '{instance_data.instance_type}' already exists for this client"
        )

    # 检查端口是否已被使用
    port_result = await db.execute(
        select(MT5Instance).where(MT5Instance.service_port == instance_data.service_port)
    )
    existing_port = port_result.scalar_one_or_none()

    if existing_port:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Port {instance_data.service_port} already in use"
        )

    # 创建实例记录
    instance_dict = instance_data.dict()
    instance_dict['client_id'] = client_id

    # 如果是第一个实例，自动设为启用
    if instance_count == 0:
        instance_dict['is_active'] = True
    else:
        instance_dict['is_active'] = False

    instance = MT5Instance(**instance_dict)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    # 调用 Windows Agent 部署实例
    agent_service = MT5AgentService(instance.server_ip)
    try:
        # 从客户端获取 MT5 登录信息
        await agent_service.deploy_instance(
            port=instance.service_port,
            mt5_path=instance.mt5_path,
            deploy_path=instance.deploy_path,
            auto_start=instance.auto_start,
            account=client.mt5_login,
            server=client.mt5_server
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


@router.post("/client/{client_id}/switch", response_model=dict)
async def switch_active_instance(
    client_id: int,
    target_instance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """切换活动实例（主备切换）"""
    # 检查客户端是否存在
    client_result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 检查目标实例是否存在且属于该客户端
    target_result = await db.execute(
        select(MT5Instance).where(
            MT5Instance.instance_id == target_instance_id,
            MT5Instance.client_id == client_id
        )
    )
    target_instance = target_result.scalar_one_or_none()

    if not target_instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {target_instance_id} not found or does not belong to client {client_id}"
        )

    # 如果目标实例已经是活动的，直接返回
    if target_instance.is_active:
        return {"status": "ok", "message": "Target instance is already active"}

    # 获取当前活动的实例
    active_result = await db.execute(
        select(MT5Instance).where(
            MT5Instance.client_id == client_id,
            MT5Instance.is_active == True
        )
    )
    current_active = active_result.scalar_one_or_none()

    try:
        # 停止当前活动实例
        if current_active:
            agent_service = MT5AgentService(current_active.server_ip)
            try:
                await agent_service.stop_instance(current_active.service_port)
                current_active.is_active = False
                current_active.status = "stopped"
            except Exception as e:
                # 记录错误但继续切换
                print(f"Warning: Failed to stop current instance: {str(e)}")

        # 启动目标实例
        agent_service = MT5AgentService(target_instance.server_ip)
        await agent_service.start_instance(target_instance.service_port)
        target_instance.is_active = True
        target_instance.status = "running"

        # 更新客户端连接状态
        client.connection_status = "connected"

        await db.commit()

        return {
            "status": "ok",
            "message": "Instance switched successfully",
            "previous_instance": str(current_active.instance_id) if current_active else None,
            "current_instance": str(target_instance.instance_id)
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to switch instance: {str(e)}"
        )


@router.get("/client/{client_id}/health", response_model=dict)
async def check_client_health(
    client_id: int,
    db: AsyncSession = Depends(get_db)
):
    """检查MT5客户端的健康状态（包括所有实例）"""
    # 检查客户端是否存在
    client_result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 获取所有实例
    instances_result = await db.execute(
        select(MT5Instance).where(MT5Instance.client_id == client_id)
    )
    instances = instances_result.scalars().all()

    health_data = {
        "client_id": client_id,
        "client_name": client.client_name,
        "is_connected": client.is_connected,
        "instances": []
    }

    # 检查每个实例的状态
    for instance in instances:
        agent_service = MT5AgentService(instance.server_ip)
        try:
            status_data = await agent_service.get_instance_status(instance.service_port)
            instance_health = {
                "instance_id": str(instance.instance_id),
                "instance_name": instance.instance_name,
                "instance_type": instance.instance_type,
                "is_active": instance.is_active,
                "status": status_data.get("status", "unknown"),
                "healthy": status_data.get("status") == "running"
            }
        except Exception as e:
            instance_health = {
                "instance_id": str(instance.instance_id),
                "instance_name": instance.instance_name,
                "instance_type": instance.instance_type,
                "is_active": instance.is_active,
                "status": "error",
                "healthy": False,
                "error": str(e)
            }

        health_data["instances"].append(instance_health)

    # 判断整体健康状态
    active_instances = [i for i in health_data["instances"] if i["is_active"]]
    health_data["overall_healthy"] = any(i["healthy"] for i in active_instances) if active_instances else False

    return health_data


@router.post("/client/{client_id}/auto-failover", response_model=dict)
async def auto_failover(
    client_id: int,
    db: AsyncSession = Depends(get_db)
):
    """自动故障转移：如果主实例失败，自动切换到备用实例"""
    # 检查客户端是否存在
    client_result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 获取当前活动实例
    active_result = await db.execute(
        select(MT5Instance).where(
            MT5Instance.client_id == client_id,
            MT5Instance.is_active == True
        )
    )
    active_instance = active_result.scalar_one_or_none()

    if not active_instance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active instance found"
        )

    # 检查活动实例健康状态
    agent_service = MT5AgentService(active_instance.server_ip)
    try:
        status_data = await agent_service.get_instance_status(active_instance.service_port)
        if status_data.get("status") == "running":
            return {
                "status": "ok",
                "message": "Active instance is healthy, no failover needed",
                "active_instance": str(active_instance.instance_id)
            }
    except Exception:
        # 活动实例不健康，需要故障转移
        pass

    # 获取备用实例
    backup_result = await db.execute(
        select(MT5Instance).where(
            MT5Instance.client_id == client_id,
            MT5Instance.is_active == False
        )
    )
    backup_instance = backup_result.scalar_one_or_none()

    if not backup_instance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No backup instance available for failover"
        )

    # 执行故障转移
    try:
        # 停用当前实例
        active_instance.is_active = False
        active_instance.status = "error"

        # 启动备用实例
        backup_agent = MT5AgentService(backup_instance.server_ip)
        await backup_agent.start_instance(backup_instance.service_port)
        backup_instance.is_active = True
        backup_instance.status = "running"

        await db.commit()

        return {
            "status": "ok",
            "message": "Failover completed successfully",
            "failed_instance": str(active_instance.instance_id),
            "new_active_instance": str(backup_instance.instance_id)
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failover failed: {str(e)}"
        )
