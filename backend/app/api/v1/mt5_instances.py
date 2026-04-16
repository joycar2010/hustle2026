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
from app.models.account import Account
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

    # 获取关联的 MT5 客户端信息（用于删除 MT5 目录和快捷方式）
    mt5_login = None
    if instance.client_id:
        client_result = await db.execute(
            select(MT5Client).where(MT5Client.client_id == instance.client_id)
        )
        client = client_result.scalar_one_or_none()
        if client:
            mt5_login = client.mt5_login

    # 调用 Windows Agent 删除 Bridge + MT5 客户端目录 + 快捷方式
    agent_service = MT5AgentService(instance.server_ip)
    try:
        await agent_service.bridge_delete(
            instance.deploy_path,
            service_port=instance.service_port,
            mt5_login=mt5_login,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Agent bridge delete failed (continuing): {e}")

    # 删除数据库记录
    await db.delete(instance)
    await db.commit()


@router.post("/{instance_id}/control")
async def control_instance(
    instance_id: UUID,
    control: MT5InstanceControl,
    db: AsyncSession = Depends(get_db)
):
    """控制MT5 Bridge实例（启动/停止/重启）通过 Windows Agent"""
    result = await db.execute(
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance {instance_id} not found")

    agent = MT5AgentService(instance.server_ip)
    action = control.action.lower()

    try:
        if action == "start":
            resp = await agent.bridge_start(instance.deploy_path)
        elif action == "stop":
            resp = await agent.bridge_stop(instance.deploy_path)
        elif action == "restart":
            resp = await agent.bridge_restart(instance.deploy_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

        new_status = "running" if action in ("start", "restart") else "stopped"
        instance.status = new_status
        await db.commit()

        return {"status": "ok", "action": action, "instance_id": str(instance_id), "result": resp}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"控制失败: {str(e)}")


@router.get("/{instance_id}/status")
async def get_instance_status(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取MT5实例实时状态 — 从 Windows Agent bridge 接口获取"""
    result = await db.execute(
        select(MT5Instance).where(MT5Instance.instance_id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance {instance_id} not found")

    agent = MT5AgentService(instance.server_ip)
    try:
        status_data = await agent.bridge_status(instance.deploy_path)
        is_running = status_data.get("is_running", False)
        new_status = "running" if is_running else "stopped"

        instance.status = new_status
        await db.commit()

        return {"status": new_status, "is_running": is_running, "detail": status_data}
    except Exception as e:
        return {"status": "error", "is_running": False, "error": str(e)}


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
    symbols = instance_dict.pop("symbols", [])  # symbols 不存 DB，仅传给 Agent
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

    # 从平台表获取 MT5 模板路径
    from app.models.platform import Platform
    acct_result = await db.execute(
        select(Account).where(Account.account_id == client.account_id)
    )
    acct = acct_result.scalar_one_or_none()
    mt5_template_path = ""
    if acct:
        plat_result = await db.execute(
            select(Platform).where(Platform.platform_id == acct.platform_id)
        )
        plat = plat_result.scalar_one_or_none()
        if plat and plat.mt5_template_path:
            mt5_template_path = plat.mt5_template_path

    # 调用 Windows Agent 部署 Bridge 服务
    agent_service = MT5AgentService(instance.server_ip)
    try:
        deploy_result = await agent_service.bridge_deploy(
            deploy_path=instance.deploy_path,
            port=instance.service_port,
            mt5_path=instance.mt5_path,
            mt5_login=client.mt5_login,
            mt5_password=client.mt5_password,
            mt5_server=client.mt5_server,
            auto_start=instance.auto_start,
            symbols=symbols,
            mt5_template_path=mt5_template_path,
        )
        # 部署成功后，写回 mt5_clients 表，让 Agent 能识别此实例
        import ntpath
        bridge_service_name = ntpath.basename(instance.deploy_path.rstrip('/\\'))
        client.agent_instance_name = bridge_service_name
        client.bridge_service_name = bridge_service_name
        client.bridge_service_port = instance.service_port
        client.bridge_url = f"http://{instance.server_ip}:{instance.service_port}"
        # 使用 Agent 返回的实际 MT5 路径（Agent 按 port 生成客户端目录）
        actual_mt5_path = deploy_result.get("mt5_path") if isinstance(deploy_result, dict) else None
        client.mt5_path = actual_mt5_path or instance.mt5_path
        client.mt5_data_path = instance.mt5_data_path
        await db.commit()
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


# ==================== MT5 终端进程控制（RDP 会话层） ====================

@router.get("/terminal/list")
async def list_mt5_terminals():
    """列出 Windows Agent 管理的所有 MT5 终端进程"""
    import os
    agent_ip = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113").replace("http://", "").replace("https://", "")
    agent = MT5AgentService(agent_ip)
    try:
        instances = await agent._http_request("/instances")
        return instances if isinstance(instances, list) else []
    except Exception as e:
        return []


@router.post("/terminal/{instance_name}/control")
async def control_mt5_terminal(
    instance_name: str,
    control: MT5InstanceControl,
):
    """控制 MT5 终端进程（RDP 会话层启动/停止/重启）"""
    import os
    agent_ip = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113").replace("http://", "").replace("https://", "")
    agent = MT5AgentService(agent_ip)
    action = control.action.lower()

    try:
        if action == "start":
            resp = await agent.instance_start(instance_name)
        elif action == "stop":
            resp = await agent.instance_stop(instance_name)
        elif action == "restart":
            resp = await agent.instance_restart(instance_name)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        return {"status": "ok", "action": action, "instance_name": instance_name, "result": resp}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"终端控制失败: {str(e)}")
