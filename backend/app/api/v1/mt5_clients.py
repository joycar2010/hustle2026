"""
MT5客户端管理API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional, Dict, Any
import os
import uuid
import logging

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.mt5_client import MT5Client
from app.models.account import Account
from app.models.user import User
from app.models.platform import Platform
from app.services.mt5_http_client import get_mt5_http_client

ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}

async def _is_admin(user_id: str, db: AsyncSession) -> bool:
    try:
        r = await db.execute(select(User).where(User.user_id == uuid.UUID(user_id)))
        u = r.scalar_one_or_none()
        return u is not None and u.role in ADMIN_ROLES
    except Exception:
        return False
from app.schemas.mt5_client import (
    MT5ClientCreate,
    MT5ClientUpdate,
    MT5ClientResponse,
    MT5ClientStatusUpdate,
    MT5PathDetection
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/accounts/{account_id}/mt5-clients", response_model=List[MT5ClientResponse])
async def get_mt5_clients(
    account_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取指定账户的所有MT5客户端"""
    try:
        logger.info(f"Getting MT5 clients for account {account_id}")

        # 验证账户是否存在且属于当前用户（管理员可访问所有账户）
        is_admin = await _is_admin(user_id, db)
        where_clause = (Account.account_id == account_id) if is_admin else and_(
            Account.account_id == account_id,
            Account.user_id == uuid.UUID(user_id)
        )
        result = await db.execute(select(Account).where(where_clause))
        account = result.scalar_one_or_none()
        if not account:
            logger.warning(f"Account {account_id} not found for user {user_id}")
            raise HTTPException(status_code=404, detail="Account not found")

        if not account.is_mt5_account:
            logger.warning(f"Account {account_id} is not an MT5 account")
            raise HTTPException(status_code=400, detail="Account is not an MT5 account")

        # 获取所有客户端（附带用户名和平台信息）
        result = await db.execute(
            select(MT5Client, User.username, Account.platform_id, Platform.display_name, Account.account_name)
            .join(Account, MT5Client.account_id == Account.account_id)
            .join(User, Account.user_id == User.user_id)
            .join(Platform, Account.platform_id == Platform.platform_id)
            .where(MT5Client.account_id == account_id)
            .order_by(MT5Client.priority, MT5Client.client_id)
        )
        rows = result.all()
        out = []
        for client, username, platform_id, platform_name, account_name in rows:
            d = MT5ClientResponse.from_orm(client)
            d.username = username
            d.platform_id = platform_id
            d.platform_name = platform_name
            d.account_name = account_name
            out.append(d)

        logger.info(f"Found {len(out)} MT5 clients for account {account_id}")
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting MT5 clients: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/accounts/{account_id}/mt5-clients", response_model=MT5ClientResponse)
async def create_mt5_client(
    account_id: uuid.UUID,
    client_data: MT5ClientCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """创建新的MT5客户端"""
    try:
        logger.info(f"Creating MT5 client for account {account_id}")

        # 验证账户（管理员可访问所有账户）
        is_admin = await _is_admin(user_id, db)
        where_clause = (Account.account_id == account_id) if is_admin else and_(
            Account.account_id == account_id,
            Account.user_id == uuid.UUID(user_id)
        )
        result = await db.execute(select(Account).where(where_clause))
        account = result.scalar_one_or_none()

        if not account:
            logger.warning(f"Account {account_id} not found for user {user_id}")
            raise HTTPException(status_code=404, detail="Account not found")

        if not account.is_mt5_account:
            logger.warning(f"Account {account_id} is not an MT5 account")
            raise HTTPException(status_code=400, detail="Account is not an MT5 account")

        # 检查客户端名称是否重复
        result = await db.execute(
            select(MT5Client).where(
                and_(
                    MT5Client.account_id == account_id,
                    MT5Client.client_name == client_data.client_name
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.warning(f"Client name '{client_data.client_name}' already exists for account {account_id}")
            raise HTTPException(status_code=400, detail="Client name already exists for this account")

        # 从平台获取 MT5 模板路径，并用账户登录信息填充默认值
        platform_result = await db.execute(
            select(Platform).where(Platform.platform_id == account.platform_id)
        )
        platform = platform_result.scalar_one_or_none()

        client_dict = client_data.dict()

        # 若请求体未提供 mt5_path，使用平台的 mt5_template_path
        if not client_dict.get("mt5_path") and platform and platform.mt5_template_path:
            client_dict["mt5_path"] = platform.mt5_template_path

        # 若请求体未提供登录凭证，从账户自动填充
        if not client_dict.get("mt5_login") and account.mt5_id:
            client_dict["mt5_login"] = account.mt5_id
        if not client_dict.get("mt5_password") and account.mt5_primary_pwd:
            client_dict["mt5_password"] = account.mt5_primary_pwd
        if not client_dict.get("mt5_server") and account.mt5_server:
            client_dict["mt5_server"] = account.mt5_server

        # 创建客户端
        client = MT5Client(
            account_id=account_id,
            created_by=uuid.UUID(user_id),
            **client_dict
        )

        db.add(client)
        await db.commit()
        await db.refresh(client)

        logger.info(f"MT5 client created successfully: {client.client_id}")
        return client
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating MT5 client: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


async def _get_client_for_user(client_id: int, user_id: str, db: AsyncSession) -> MT5Client:
    """按 client_id 查客户端，管理员不受 user_id 限制。"""
    is_admin = await _is_admin(user_id, db)
    if is_admin:
        result = await db.execute(select(MT5Client).where(MT5Client.client_id == client_id))
    else:
        result = await db.execute(
            select(MT5Client).join(Account).where(
                and_(MT5Client.client_id == client_id, Account.user_id == uuid.UUID(user_id))
            )
        )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="MT5 client not found")
    return client


@router.get("/mt5-clients/all", response_model=List[MT5ClientResponse])
async def get_all_mt5_clients(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取所有MT5客户端（管理员返回全部用户，普通用户返回自己的），附带用户名和平台信息"""
    is_admin = await _is_admin(user_id, db)
    if is_admin:
        result = await db.execute(
            select(MT5Client, User.username, Account.platform_id, Platform.display_name, Account.account_name)
            .join(Account, MT5Client.account_id == Account.account_id)
            .join(User, Account.user_id == User.user_id)
            .join(Platform, Account.platform_id == Platform.platform_id)
            .order_by(User.username, Account.account_name, MT5Client.priority)
        )
    else:
        result = await db.execute(
            select(MT5Client, User.username, Account.platform_id, Platform.display_name, Account.account_name)
            .join(Account, MT5Client.account_id == Account.account_id)
            .join(User, Account.user_id == User.user_id)
            .join(Platform, Account.platform_id == Platform.platform_id)
            .where(Account.user_id == uuid.UUID(user_id))
            .order_by(Account.account_name, MT5Client.priority)
        )
    rows = result.all()
    out = []
    for client, username, platform_id, platform_name, account_name in rows:
        d = MT5ClientResponse.from_orm(client)
        d.username = username
        d.platform_id = platform_id
        d.platform_name = platform_name
        d.account_name = account_name
        out.append(d)
    return out


@router.get("/mt5-clients/{client_id}", response_model=MT5ClientResponse)
async def get_mt5_client(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取单个MT5客户端详情"""
    return await _get_client_for_user(client_id, user_id, db)


@router.put("/mt5-clients/{client_id}", response_model=MT5ClientResponse)
async def update_mt5_client(
    client_id: int,
    client_data: MT5ClientUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """更新MT5客户端配置（管理员可更改所属账户）"""
    client = await _get_client_for_user(client_id, user_id, db)

    # 更新字段（account_id 仅管理员可修改）
    is_admin = await _is_admin(user_id, db)
    update_data = client_data.dict(exclude_unset=True)
    if "account_id" in update_data and not is_admin:
        del update_data["account_id"]  # 非管理员忽略 account_id 变更

    for field, value in update_data.items():
        setattr(client, field, value)

    await db.commit()
    await db.refresh(client)

    return client


@router.delete("/mt5-clients/{client_id}")
async def delete_mt5_client(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """删除MT5客户端"""
    client = await _get_client_for_user(client_id, user_id, db)

    # 如果客户端正在连接，先断开
    if client.connection_status == 'connected':
        raise HTTPException(status_code=400, detail="Cannot delete connected client. Please disconnect first.")

    await db.delete(client)
    await db.commit()

    return {"message": "MT5 client deleted successfully"}


@router.post("/mt5-clients/{client_id}/connect")
async def connect_mt5_client(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """连接MT5客户端 — 更新状态为 connected"""
    client = await _get_client_for_user(client_id, user_id, db)
    client.connection_status = 'connected'
    from datetime import datetime
    client.last_connected_at = datetime.utcnow()
    client.total_connections = (client.total_connections or 0) + 1
    await db.commit()
    await db.refresh(client)
    return {"message": "MT5客户端已连接", "client_id": client_id, "connection_status": "connected"}


@router.post("/mt5-clients/{client_id}/disconnect")
async def disconnect_mt5_client(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """断开MT5客户端 — 更新状态为 disconnected"""
    client = await _get_client_for_user(client_id, user_id, db)
    client.connection_status = 'disconnected'
    from datetime import datetime
    client.last_disconnected_at = datetime.utcnow()
    await db.commit()
    await db.refresh(client)
    return {"message": "MT5客户端已断开", "client_id": client_id, "connection_status": "disconnected"}


@router.get("/mt5-clients/{client_id}/status", response_model=MT5ClientResponse)
async def get_mt5_client_status(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取MT5客户端连接状态"""
    return await _get_client_for_user(client_id, user_id, db)


@router.get("/mt5-clients/{client_id}/password")
async def get_mt5_client_password(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取MT5客户端密码（敏感操作）"""
    try:
        logger.info(f"User {user_id} requesting password for MT5 client {client_id}")

        result = await db.execute(
            select(MT5Client)
            .join(Account)
            .where(
                and_(
                    MT5Client.client_id == client_id,
                    Account.user_id == uuid.UUID(user_id)
                )
            )
        )
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="MT5 client not found")

        return {"mt5_password": client.mt5_password}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting MT5 client password: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/mt5/detect-installations", response_model=List[MT5PathDetection])
async def detect_mt5_installations(
    user_id: str = Depends(get_current_user_id)
):
    """自动检测系统中的MT5安装"""
    common_paths = [
        "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
        "C:\\MT5\\terminal64.exe",
        "D:\\MT5\\terminal64.exe",
    ]

    results = []
    for path in common_paths:
        exists = os.path.exists(path)
        results.append(MT5PathDetection(
            path=path,
            exists=exists,
            is_valid=exists and path.endswith('.exe')
        ))

    return results


# ─── MT5 Bridge 代理端点 ─── 直接转发到 MT5 Bridge 微服务，绕过慢速中间层 ───

@router.get("/mt5/connection/status")
async def get_mt5_connection_status(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """获取 MT5 Bridge 连接状态（直接代理到微服务 8001）"""
    try:
        client = get_mt5_http_client()
        data = await client.get_connection_status()
        return data
    except Exception as e:
        logger.error(f"Failed to get MT5 connection status: {e}")
        return {"connected": False, "error": str(e)}


@router.get("/mt5/account/info")
async def get_mt5_account_info(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """获取 MT5 账户信息（直接代理到微服务 8001）"""
    try:
        client = get_mt5_http_client()
        data = await client.get_account_info()
        return data or {}
    except Exception as e:
        logger.error(f"Failed to get MT5 account info: {e}")
        return {"error": str(e)}
