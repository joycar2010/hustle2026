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
        实例列表，包含运行状态和健康信息
    """
    return await call_agent_api("GET", "/instances")

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

    return await call_agent_api("GET", f"/bridge/{client.bridge_service_name}/status")


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
    mt5_path = "D:\\MetaTrader 5-01\\terminal64.exe"  # 默认路径
    if client.agent_instance_name == "bybit_system_service":
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

    # 更新数据库中的 bridge_service_name 和 bridge_service_port
    if deploy_result.get("success"):
        client.bridge_service_name = service_name
        client.bridge_service_port = service_port
        await db.commit()
        logger.info(f"Updated bridge config for client {client_id}: {service_name}:{service_port}")

    return deploy_result


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

    # 调用 Windows Agent 删除（传递端口号和登录账号用于删除 MT5 客户端目录和桌面快捷方式）
    params = {}
    if client.bridge_service_port:
        params["mt5_client_port"] = client.bridge_service_port
    if client.mt5_login:
        params["mt5_login"] = str(client.mt5_login)

    delete_result = await call_agent_api(
        "DELETE",
        f"/bridge/{client.bridge_service_name}",
        params=params
    )

    # 更新数据库，清空 bridge_service_name 和 bridge_service_port
    if delete_result.get("success"):
        client.bridge_service_name = None
        client.bridge_service_port = None
        await db.commit()
        logger.info(f"Cleared bridge config for client {client_id}")

    return delete_result
