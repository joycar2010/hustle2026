"""MT5 Agent 代理 API - 提供前端访问 Windows Agent 的接口"""
from fastapi import APIRouter, HTTPException, Depends
from app.core.security import get_current_user
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

    logger.info(f"User {current_user.username}} stopping instance {instance_name}")

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

    logger.info(f"User {current_user.username}} restarting instance {instance_name}")

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

    logger.info(f"User {current_user.username}} creating/updating instance")

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

    logger.info(f"User {current_user.username}} deleting instance {instance_name}")

    return await call_agent_api(
        "DELETE",
        f"/instances/{instance_name}"
    )
