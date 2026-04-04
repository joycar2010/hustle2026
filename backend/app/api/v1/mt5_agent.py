"""MT5 Agent 代理 API - 提供前端访问 Windows Agent 的接口"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import get_current_user
from app.core.database import get_db
from app.models.mt5_client import MT5Client
from typing import Optional
import httpx
import os
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# MT5 Agent 配置
MT5_AGENT_URL = os.getenv("MT5_AGENT_URL", "http://172.31.14.113:8765")
MT5_AGENT_API_KEY = os.getenv("MT5_AGENT_API_KEY", "HustleXAU_MT5_Agent_Key_2026")

async def call_agent_api(method: str, path: str, **kwargs):
    """
    调用 Windows Agent API

    Args:
        method: HTTP 方法 (GET, POST, etc.)
        path: API 路径
        **kwargs: 其他参数传递给 httpx

    Returns:
        API 响应的 JSON 数据
    """
    headers = {"X-API-Key": MT5_AGENT_API_KEY}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"{MT5_AGENT_URL}{path}",
                headers=headers,
                timeout=30.0,
                **kwargs
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to call Agent API: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"MT5 Agent 服务不可用: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error calling Agent API: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"调用 MT5 Agent 失败: {str(e)}"
        )

@router.get("/health")
async def agent_health():
    """检查 Agent 健康状态"""
    try:
        return await call_agent_api("GET", "/health")
    except HTTPException:
        return {
            "status": "error",
            "agent": "MT5 Windows Agent",
            "message": "Agent 不可用"
        }

@router.get("/instances")
async def get_instances(current_user: dict = Depends(get_current_user)):
    """
    获取所有 MT5 实例状态

    Returns:
        实例列表，包含运行状态和健康信息。Agent 不可用时返回空列表而非 503。
    """
    try:
        return await call_agent_api("GET", "/instances")
    except HTTPException as e:
        if e.status_code == 503:
            logger.warning(f"MT5 Agent 不可用，返回空实例列表: {e.detail}")
            return []
        raise

@router.get("/instances/{instance_name}")
async def get_instance(
    instance_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    获取单个实例状态

    Args:
        instance_name: 实例名称

    Returns:
        实例详细状态信息
    """
    return await call_agent_api("GET", f"/instances/{instance_name}")

@router.post("/instances/{instance_name}/start")
async def start_instance(
    instance_name: str,
    wait_seconds: int = 5,
    current_user: dict = Depends(get_current_user)
):
    """
    启动 MT5 实例

    Args:
        instance_name: 实例名称
        wait_seconds: 启动后等待时间（秒）

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    logger.info(f"User {current_user.username} starting instance {instance_name}")

    return await call_agent_api(
        "POST",
        f"/instances/{instance_name}/start",
        params={"wait_seconds": wait_seconds}
    )

@router.post("/instances/{instance_name}/stop")
async def stop_instance(
    instance_name: str,
    force: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """
    停止 MT5 实例

    Args:
        instance_name: 实例名称
        force: 是否强制停止

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    logger.info(f"User {current_user.username} stopping instance {instance_name}")

    return await call_agent_api(
        "POST",
        f"/instances/{instance_name}/stop",
        params={"force": force}
    )

@router.post("/instances/{instance_name}/restart")
async def restart_instance(
    instance_name: str,
    wait_seconds: int = 5,
    current_user: dict = Depends(get_current_user)
):
    """
    重启 MT5 实例

    Args:
        instance_name: 实例名称
        wait_seconds: 重启后等待时间（秒）

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    logger.info(f"User {current_user.username} restarting instance {instance_name}")

    return await call_agent_api(
        "POST",
        f"/instances/{instance_name}/restart",
        params={"wait_seconds": wait_seconds}
    )

@router.post("/instances")
async def create_instance(
    instance_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    创建/更新实例配置

    Args:
        instance_data: 实例配置数据

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员"]:
        raise HTTPException(status_code=403, detail="需要系统管理员权限")

    logger.info(f"User {current_user.username} creating/updating instance")

    return await call_agent_api(
        "POST",
        "/instances",
        json=instance_data
    )

@router.delete("/instances/{instance_name}")
async def delete_instance(
    instance_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    删除实例配置

    Args:
        instance_name: 实例名称

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员"]:
        raise HTTPException(status_code=403, detail="需要系统管理员权限")

    logger.info(f"User {current_user.username} deleting instance {instance_name}")

    return await call_agent_api(
        "DELETE",
        f"/instances/{instance_name}"
    )


# ====================== 基于 Client ID 的控制端点 ======================

@router.post("/clients/{client_id}/start")
async def start_client(
    client_id: int,
    wait_seconds: int = 5,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    通过 client_id 启动 MT5 客户端

    Args:
        client_id: MT5客户端ID
        wait_seconds: 启动后等待时间（秒）

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.agent_instance_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置远程控制实例"
        )

    logger.info(
        f"User {current_user.username} starting MT5 client {client.client_name} "
        f"(login: {client.mt5_login}, instance: {client.agent_instance_name})"
    )

    return await call_agent_api(
        "POST",
        f"/instances/{client.agent_instance_name}/start",
        params={"wait_seconds": wait_seconds}
    )


@router.post("/clients/{client_id}/stop")
async def stop_client(
    client_id: int,
    force: bool = True,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    通过 client_id 停止 MT5 客户端

    Args:
        client_id: MT5客户端ID
        force: 是否强制停止

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.agent_instance_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置远程控制实例"
        )

    logger.info(
        f"User {current_user.username} stopping MT5 client {client.client_name} "
        f"(login: {client.mt5_login}, instance: {client.agent_instance_name})"
    )

    return await call_agent_api(
        "POST",
        f"/instances/{client.agent_instance_name}/stop",
        params={"force": force}
    )


@router.post("/clients/{client_id}/restart")
async def restart_client(
    client_id: int,
    wait_seconds: int = 5,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    通过 client_id 重启 MT5 客户端

    Args:
        client_id: MT5客户端ID
        wait_seconds: 重启后等待时间（秒）

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.agent_instance_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置远程控制实例"
        )

    logger.info(
        f"User {current_user.username} restarting MT5 client {client.client_name} "
        f"(login: {client.mt5_login}, instance: {client.agent_instance_name})"
    )

    return await call_agent_api(
        "POST",
        f"/instances/{client.agent_instance_name}/restart",
        params={"wait_seconds": wait_seconds}
    )


@router.get("/debug/processes")
async def debug_processes(current_user: dict = Depends(get_current_user)):
    """
    调试端点：列出所有MT5进程

    Returns:
        所有 terminal64.exe 进程的详细信息
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    return await call_agent_api("GET", "/debug/processes")


# ====================== Bridge 实例控制 ======================
@router.get("/bridge/{client_id}/status")
async def get_bridge_status(
    client_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取 Bridge 服务状态

    Args:
        client_id: MT5客户端ID

    Returns:
        Bridge 服务状态信息
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.bridge_service_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置 Bridge 服务"
        )

    logger.info(
        f"User {current_user.username} checking bridge status for {client.client_name} "
        f"(service: {client.bridge_service_name})"
    )

    try:
        return await call_agent_api("GET", f"/bridge/{client.bridge_service_name}/status")
    except HTTPException as e:
        if e.status_code in (503, 502):
            return {
                "service_name": client.bridge_service_name,
                "status": "UNAVAILABLE",
                "is_running": False,
                "error": f"Agent 服务不可用: {e.detail}"
            }
        raise


@router.post("/bridge/{client_id}/start")
async def start_bridge(
    client_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    启动 Bridge 服务

    Args:
        client_id: MT5客户端ID

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.bridge_service_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置 Bridge 服务"
        )

    logger.info(
        f"User {current_user.username} starting bridge for {client.client_name} "
        f"(service: {client.bridge_service_name})"
    )

    return await call_agent_api("POST", f"/bridge/{client.bridge_service_name}/start")


@router.post("/bridge/{client_id}/stop")
async def stop_bridge(
    client_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    停止 Bridge 服务

    Args:
        client_id: MT5客户端ID

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.bridge_service_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置 Bridge 服务"
        )

    logger.info(
        f"User {current_user.username} stopping bridge for {client.client_name} "
        f"(service: {client.bridge_service_name})"
    )

    return await call_agent_api("POST", f"/bridge/{client.bridge_service_name}/stop")


@router.post("/bridge/{client_id}/restart")
async def restart_bridge(
    client_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    重启 Bridge 服务

    Args:
        client_id: MT5客户端ID

    Returns:
        操作结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.bridge_service_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置 Bridge 服务"
        )

    logger.info(
        f"User {current_user.username} restarting bridge for {client.client_name} "
        f"(service: {client.bridge_service_name})"
    )

    return await call_agent_api("POST", f"/bridge/{client.bridge_service_name}/restart")


@router.post("/bridge/{client_id}/deploy")
async def deploy_bridge(
    client_id: int,
    request_body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    部署 Bridge 实例

    Args:
        client_id: MT5客户端ID
        request_body: 包含 service_port 的请求体

    Returns:
        部署结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 获取 service_port
    service_port = request_body.get("service_port")
    if not service_port:
        raise HTTPException(status_code=422, detail="缺少 service_port 参数")

    try:
        service_port = int(service_port)
        if service_port < 8000 or service_port > 9000:
            raise HTTPException(status_code=422, detail="端口号必须在 8000-9000 之间")
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="service_port 必须是有效的整数")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    # 生成服务名称
    service_name = f"hustle-mt5-{client.client_name.lower().replace(' ', '-')}"

    # 获取 MT5 路径
    # 根据服务器名称判断MT5路径
    mt5_path = "D:\\MetaTrader 5-01\\terminal64.exe"  # 默认路径
    if client.mt5_server and "Bybit" in client.mt5_server:
        # Bybit服务器使用系统安装的MT5
        mt5_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
    elif client.is_system_service:
        # 系统服务账户使用系统安装的MT5
        mt5_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

    logger.info(
        f"User {current_user.username} deploying bridge for {client.client_name} "
        f"(service: {service_name}, port: {service_port})"
    )

    # 调用 Windows Agent 部署
    deploy_result = await call_agent_api(
        "POST",
        "/bridge/deploy",
        json={
            "service_name": service_name,
            "mt5_login": str(client.mt5_login),
            "mt5_password": client.mt5_password,
            "mt5_server": client.mt5_server,
            "mt5_path": mt5_path,
            "service_port": service_port
        }
    )

    # 更新数据库中的 bridge_service_name、bridge_service_port 和 agent_instance_name
    if deploy_result.get("success"):
        client.bridge_service_name = service_name
        client.bridge_service_port = service_port
        # 设置 agent_instance_name 以启用远程控制
        # 格式: {client_name}-{port}，例如: mt5-02-8003
        agent_instance_name = f"{client.client_name.lower().replace(' ', '-')}-{service_port}"
        client.agent_instance_name = agent_instance_name

        # 创建或更新 MT5Instance 记录
        from app.models.mt5_instance import MT5Instance
        instance_result = await db.execute(
            select(MT5Instance).where(MT5Instance.client_id == client_id)
        )
        instance = instance_result.scalar_one_or_none()

        mt5_client_path = deploy_result.get("mt5_path", f"D:\\MetaTrader 5-{service_port}\\terminal64.exe")
        bridge_deploy_path = deploy_result.get("deploy_dir", f"D:\\{service_name}")

        if instance:
            # 更新现有实例
            instance.instance_name = agent_instance_name
            instance.mt5_path = mt5_client_path
            instance.deploy_path = bridge_deploy_path
            instance.service_port = service_port
            logger.info(f"Updated MT5Instance for client {client_id}")
        else:
            # 创建新实例
            new_instance = MT5Instance(
                instance_name=agent_instance_name,
                server_ip="172.31.14.113",  # Windows Agent IP
                service_port=service_port,
                mt5_path=mt5_client_path,
                deploy_path=bridge_deploy_path,
                is_portable=True,
                auto_start=True,
                status="running",
                is_active=True,
                instance_type="primary",
                client_id=client_id
            )
            db.add(new_instance)
            logger.info(f"Created MT5Instance for client {client_id}")

        await db.commit()
        await db.refresh(client)
        logger.info(f"Updated bridge config for client {client_id}: {service_name}:{service_port}, agent_instance: {agent_instance_name}")

    # 返回部署结果和更新后的客户端信息
    deploy_result["client_data"] = {
        "client_id": client.client_id,
        "agent_instance_name": client.agent_instance_name,
        "bridge_service_name": client.bridge_service_name,
        "bridge_service_port": client.bridge_service_port,
        "mt5_path": mt5_client_path,
        "deploy_path": bridge_deploy_path
    }
    return deploy_result


@router.put("/bridge/{client_id}")
async def update_bridge(
    client_id: int,
    bridge_service_name: str = None,
    bridge_service_port: int = None,
    mt5_path: str = None,
    deploy_path: str = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    更新 Bridge 配置

    Args:
        client_id: MT5客户端ID
        bridge_service_name: Bridge服务名称
        bridge_service_port: Bridge服务端口
        mt5_path: MT5客户端路径
        deploy_path: Bridge部署路径

    Returns:
        更新结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    # 更新 MT5Client 表
    if bridge_service_name is not None:
        client.bridge_service_name = bridge_service_name
    if bridge_service_port is not None:
        client.bridge_service_port = bridge_service_port

    # 更新 MT5Instance 表
    from app.models.mt5_instance import MT5Instance
    instance_result = await db.execute(
        select(MT5Instance).where(MT5Instance.client_id == client_id)
    )
    instance = instance_result.scalar_one_or_none()

    if instance:
        if mt5_path is not None:
            instance.mt5_path = mt5_path
        if deploy_path is not None:
            instance.deploy_path = deploy_path
    elif mt5_path or deploy_path:
        # 如果没有实例但提供了路径，创建新实例
        logger.warning(f"No MT5Instance found for client {client_id}, skipping path update")

    await db.commit()

    logger.info(
        f"User {current_user.username} updated bridge config for {client.client_name}"
    )

    return {
        "success": True,
        "message": "Bridge 配置已更新",
        "client_id": client_id
    }


@router.put("/bridge/{client_id}")
async def update_bridge(
    client_id: int,
    request_body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    更新 Bridge 配置

    Args:
        client_id: MT5客户端ID
        request_body: 包含配置信息的请求体

    Returns:
        更新结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    # 更新 MT5Client 表
    if "bridge_service_name" in request_body:
        client.bridge_service_name = request_body["bridge_service_name"]
    if "bridge_service_port" in request_body:
        client.bridge_service_port = request_body["bridge_service_port"]

    # 更新 MT5Instance 表
    from app.models.mt5_instance import MT5Instance
    instance_result = await db.execute(
        select(MT5Instance).where(MT5Instance.client_id == client_id)
    )
    instance = instance_result.scalar_one_or_none()

    if instance:
        if "mt5_path" in request_body and request_body["mt5_path"]:
            instance.mt5_path = request_body["mt5_path"]
        if "deploy_path" in request_body and request_body["deploy_path"]:
            instance.deploy_path = request_body["deploy_path"]

    await db.commit()

    logger.info(
        f"User {current_user.username} updated bridge config for {client.client_name}"
    )

    return {
        "success": True,
        "message": "Bridge 配置已更新"
    }


@router.delete("/bridge/{client_id}")
async def delete_bridge(
    client_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    删除 Bridge 实例

    Args:
        client_id: MT5客户端ID

    Returns:
        删除结果
    """
    # 权限检查
    if current_user.role not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查询客户端信息
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail=f"MT5客户端 {client_id} 不存在")

    if not client.bridge_service_name:
        raise HTTPException(
            status_code=400,
            detail=f"MT5客户端 {client.client_name} 未配置 Bridge 服务"
        )

    logger.info(
        f"User {current_user.username} deleting bridge for {client.client_name} "
        f"(service: {client.bridge_service_name}, port: {client.bridge_service_port})"
    )

    # 调用 Windows Agent 删除
    params = {}
    if client.bridge_service_port:
        params["mt5_client_port"] = client.bridge_service_port
    if client.mt5_login:
        params["mt5_login"] = str(client.mt5_login)

    agent_success = False
    agent_error = None

    try:
        delete_result = await call_agent_api(
            "DELETE",
            f"/bridge/{client.bridge_service_name}",
            params=params
        )
        agent_success = delete_result.get("success", False)

        if not agent_success:
            agent_error = delete_result.get("message", "Windows Agent 删除失败")
            logger.warning(f"Windows Agent delete failed: {agent_error}")
    except HTTPException as e:
        # Windows Agent 不可用或返回错误
        agent_error = str(e.detail)
        logger.error(f"Failed to call Windows Agent: {agent_error}")
    except Exception as e:
        agent_error = str(e)
        logger.error(f"Unexpected error calling Windows Agent: {agent_error}")

    # 无论 Windows Agent 是否成功，都清理数据库记录
    # 这样可以避免数据库和实际状态不一致
    client.bridge_service_name = None
    client.bridge_service_port = None
    client.agent_instance_name = None

    # 删除 MT5Instance 记录
    from app.models.mt5_instance import MT5Instance
    instance_result = await db.execute(
        select(MT5Instance).where(MT5Instance.client_id == client_id)
    )
    instance = instance_result.scalar_one_or_none()
    if instance:
        await db.delete(instance)
        logger.info(f"Deleted MT5Instance for client {client_id}")

    await db.commit()
    logger.info(f"Cleared bridge config for client {client_id}")

    # 返回结果
    if agent_success:
        return {
            "success": True,
            "message": "Bridge 删除成功"
        }
    else:
        # Windows Agent 失败，但数据库已清理
        return {
            "success": True,
            "message": "数据库记录已清理",
            "warning": f"Windows Agent 清理失败: {agent_error}。请手动检查并清理 Windows 服务器上的残留文件。",
            "manual_cleanup_required": True,
            "cleanup_info": {
                "bridge_directory": f"D:\\{client.bridge_service_name}" if client.bridge_service_name else None,
                "mt5_directory": f"D:\\MetaTrader 5-{client.bridge_service_port}" if client.bridge_service_port else None,
                "service_name": client.bridge_service_name
            }
        }
