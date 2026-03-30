"""
MT5客户端管理API
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update
from typing import List, Optional
import os
import uuid
import logging

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.mt5_client import MT5Client
from app.models.account import Account
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

        # 检查调用者是否是管理员
        from app.models.user import User
        ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
        user_result = await db.execute(select(User).where(User.user_id == user_id))
        caller = user_result.scalar_one_or_none()
        is_admin = caller is not None and caller.role in ADMIN_ROLES

        # 验证账户是否存在
        result = await db.execute(
            select(Account).where(Account.account_id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            logger.warning(f"Account {account_id} not found")
            raise HTTPException(status_code=404, detail="Account not found")

        # 非管理员只能访问自己的账户
        if not is_admin and account.user_id != uuid.UUID(user_id):
            logger.warning(f"User {user_id} attempted to access account {account_id} owned by {account.user_id}")
            raise HTTPException(status_code=403, detail="Access denied")

        if not account.is_mt5_account:
            logger.warning(f"Account {account_id} is not an MT5 account")
            raise HTTPException(status_code=400, detail="Account is not an MT5 account")

        # 获取所有客户端
        result = await db.execute(
            select(MT5Client)
            .where(MT5Client.account_id == account_id)
            .order_by(MT5Client.priority, MT5Client.client_id)
        )
        clients = result.scalars().all()

        logger.info(f"Found {len(clients)} MT5 clients for account {account_id}")
        return clients
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

        # 验证账户
        result = await db.execute(
            select(Account).where(
                and_(
                    Account.account_id == account_id,
                    Account.user_id == uuid.UUID(user_id)
                )
            )
        )
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

        # 创建客户端
        client = MT5Client(
            account_id=account_id,
            created_by=uuid.UUID(user_id),
            **client_data.dict()
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


@router.get("/mt5-clients/{client_id}", response_model=MT5ClientResponse)
async def get_mt5_client(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取单个MT5客户端详情"""
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

    return client


@router.put("/mt5-clients/{client_id}", response_model=MT5ClientResponse)
async def update_mt5_client(
    client_id: int,
    client_data: MT5ClientUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """更新MT5客户端配置"""
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

    # 更新字段
    update_data = client_data.dict(exclude_unset=True)
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
    """连接MT5客户端"""
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

    if not client.is_active:
        raise HTTPException(status_code=400, detail="客户端未激活")

    # 验证MT5路径
    if not client.mt5_path:
        raise HTTPException(status_code=400, detail="MT5安装路径未设置")

    import os
    if not os.path.exists(client.mt5_path):
        raise HTTPException(status_code=400, detail=f"MT5安装路径不存在: {client.mt5_path}")

    # 检查terminal64.exe是否存在
    terminal_exe = os.path.join(client.mt5_path, "terminal64.exe")
    if not os.path.exists(terminal_exe):
        raise HTTPException(status_code=400, detail=f"未找到MT5可执行文件: {terminal_exe}")

    # 实际的MT5连接逻辑
    try:
        from app.services.mt5_client import MT5Client as MT5ClientService

        mt5_service = MT5ClientService(
            login=int(client.mt5_login),
            password=client.mt5_password,
            server=client.mt5_server,
            path=client.mt5_path
        )

        if not mt5_service.connect():
            error_msg = mt5_service.get_last_error() or "连接失败，请检查账号、密码和服务器设置"
            raise HTTPException(status_code=400, detail=error_msg)

        # 连接成功后断开（这里只是测试连接）
        mt5_service.disconnect()

        return {"message": "MT5客户端连接测试成功", "client_id": client_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MT5 connection error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"连接失败: {str(e)}")


@router.post("/mt5-clients/{client_id}/disconnect")
async def disconnect_mt5_client(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """断开MT5客户端"""
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

    # TODO: 实际的MT5断开逻辑

    return {"message": "MT5 client disconnected", "client_id": client_id}


@router.get("/mt5-clients/{client_id}/status", response_model=MT5ClientResponse)
async def get_mt5_client_status(
    client_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取MT5客户端连接状态"""
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

    return client


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


@router.get("/mt5-clients/all", response_model=List[MT5ClientResponse])
async def get_all_mt5_clients(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取当前用户的所有MT5客户端"""
    result = await db.execute(
        select(MT5Client)
        .join(Account)
        .where(Account.user_id == uuid.UUID(user_id))
        .order_by(Account.account_name, MT5Client.priority)
    )
    clients = result.scalars().all()

    return clients


@router.patch("/mt5-clients/{client_id}/system-service")
async def set_system_service(
    client_id: int,
    enabled: bool = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """设置MT5客户端为系统服务账户"""
    # 获取客户端
    result = await db.execute(
        select(MT5Client).where(MT5Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 client {client_id} not found"
        )

    # 如果设置为系统服务，先取消其他系统服务账户
    if enabled:
        await db.execute(
            update(MT5Client)
            .where(MT5Client.is_system_service == True)
            .values(is_system_service=False)
        )

    # 更新目标客户端
    client.is_system_service = enabled
    await db.commit()
    await db.refresh(client)

    return {
        "success": True,
        "client_id": client_id,
        "is_system_service": enabled
    }


@router.get("/mt5-clients/system-service/status")
async def get_system_service_status(
    db: AsyncSession = Depends(get_db)
):
    """获取系统服务MT5客户端状态"""
    # 查询系统服务客户端
    result = await db.execute(
        select(MT5Client)
        .where(MT5Client.is_system_service == True)
        .where(MT5Client.is_active == True)
        .limit(1)
    )
    client = result.scalar_one_or_none()

    if not client:
        return {
            "connected": False,
            "mt5_login": "--",
            "mt5_server": "--",
            "balance": None,
            "equity": None
        }

    # 获取关联的MT5实例
    from app.models.mt5_instance import MT5Instance
    instance_result = await db.execute(
        select(MT5Instance)
        .where(MT5Instance.client_id == client.client_id)
        .where(MT5Instance.is_active == True)
        .limit(1)
    )
    instance = instance_result.scalar_one_or_none()

    if not instance:
        return {
            "connected": False,
            "mt5_login": str(client.mt5_login),
            "mt5_server": client.mt5_server,
            "balance": None,
            "equity": None
        }

    # 获取MT5桥接服务状态
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as http_client:
            health_response = await http_client.get(
                f"http://{instance.server_ip}:{instance.service_port}/health"
            )
            health_data = health_response.json()
            mt5_connected = health_data.get("mt5", False)

            # 如果MT5已连接，获取账户信息
            balance = None
            equity = None
            if mt5_connected:
                try:
                    # 注意：这里需要API key，暂时跳过
                    # account_response = await http_client.get(
                    #     f"http://{instance.server_ip}:{instance.service_port}/mt5/account/info"
                    # )
                    # account_data = account_response.json()
                    # balance = account_data.get("balance")
                    # equity = account_data.get("equity")
                    pass
                except Exception:
                    pass

            return {
                "connected": mt5_connected,
                "mt5_login": str(client.mt5_login),
                "mt5_server": client.mt5_server,
                "balance": balance,
                "equity": equity
            }
    except Exception as e:
        logger.error(f"Failed to get system service status: {e}")
        return {
            "connected": False,
            "mt5_login": str(client.mt5_login),
            "mt5_server": client.mt5_server,
            "balance": None,
            "equity": None
        }
