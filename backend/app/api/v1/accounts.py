"""Account management API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.account import Account
from app.models.mt5_client import MT5Client
from app.models.user import User
from app.schemas.account import AccountCreate, AccountUpdate, AccountResponse
from app.services.account_service import account_data_service

router = APIRouter()


class AccountSecretResponse(BaseModel):
    api_secret: str
    mt5_primary_pwd: Optional[str] = None


@router.get("", response_model=List[AccountResponse])
async def list_accounts(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List accounts.  Admin roles return all users' accounts; others see only their own."""
    ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
    user_result = await db.execute(select(User).where(User.user_id == user_id))
    caller = user_result.scalar_one_or_none()
    is_admin = caller is not None and caller.role in ADMIN_ROLES

    if is_admin:
        result = await db.execute(select(Account))
    else:
        result = await db.execute(
            select(Account).where(Account.user_id == UUID(user_id))
        )
    accounts = result.scalars().all()
    return accounts


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new account. Admin can specify target user via user_id in body."""
    # Determine effective user_id (admin can create for other users)
    ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
    user_result = await db.execute(select(User).where(User.user_id == user_id))
    caller = user_result.scalar_one_or_none()
    is_admin = caller is not None and caller.role in ADMIN_ROLES

    target_user_id = account_data.user_id if (is_admin and account_data.user_id) else user_id

    # If this is set as default, unset other default accounts of the same platform type
    if account_data.is_default:
        result = await db.execute(
            select(Account).where(
                Account.user_id == UUID(target_user_id),
                Account.is_default == True,
                Account.platform_id == account_data.platform_id,
                Account.is_mt5_account == account_data.is_mt5_account,
            )
        )
        existing_defaults = result.scalars().all()

        for acc in existing_defaults:
            acc.is_default = False

    # Handle account_role uniqueness (one primary and one hedge per user)
    if account_data.account_role in ('primary', 'hedge'):
        result = await db.execute(
            select(Account).where(
                Account.user_id == UUID(target_user_id),
                Account.account_role == account_data.account_role,
            )
        )
        existing_role = result.scalars().all()
        for acc in existing_role:
            acc.account_role = None

    # Create new account
    new_account = Account(
        user_id=UUID(target_user_id),
        platform_id=account_data.platform_id,
        account_name=account_data.account_name,
        api_key=account_data.api_key,
        api_secret=account_data.api_secret,
        passphrase=account_data.passphrase,
        mt5_id=account_data.mt5_id,
        mt5_server=account_data.mt5_server,
        mt5_primary_pwd=account_data.mt5_primary_pwd,
        is_mt5_account=account_data.is_mt5_account,
        is_default=account_data.is_default,
        account_role=account_data.account_role,
        leverage=account_data.leverage or (20 if account_data.platform_id == 1 else 100),
    )

    db.add(new_account)
    await db.commit()
    await db.refresh(new_account)

    return new_account


@router.get("/summary")
async def get_accounts_summary(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get account summary for www frontend.
    Alias for /dashboard/aggregated — MUST be before /{account_id} route.
    """
    return await get_aggregated_dashboard(user_id=user_id, db=db)


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get account details"""
    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    return account


@router.get("/{account_id}/secret", response_model=AccountSecretResponse)
async def get_account_secret(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get account API secret (requires password verification first)"""
    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    return AccountSecretResponse(
        api_secret=account.api_secret,
        mt5_primary_pwd=account.mt5_primary_pwd
    )


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    account_update: AccountUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update account. Admin can update any account; regular users only their own."""
    ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
    user_result = await db.execute(select(User).where(User.user_id == user_id))
    caller = user_result.scalar_one_or_none()
    is_admin = caller is not None and caller.role in ADMIN_ROLES

    if is_admin:
        result = await db.execute(
            select(Account).where(Account.account_id == account_id)
        )
    else:
        result = await db.execute(
            select(Account).where(
                Account.account_id == account_id,
                Account.user_id == UUID(user_id),
            )
        )
    account = result.scalar_one_or_none()
    account_owner_id = str(account.user_id) if account else user_id

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Transfer account to another user (admin only)
    if account_update.user_id is not None and is_admin:
        new_user_id = UUID(account_update.user_id)
        if new_user_id != account.user_id:
            # Clear role on old user side to avoid unique constraint violation
            account.account_role = None
            account.user_id = new_user_id

    # Update fields
    if account_update.account_name is not None:
        account.account_name = account_update.account_name

    # platform_id and is_mt5_account: admin-only, update together to keep consistency
    if account_update.platform_id is not None and is_admin:
        account.platform_id = account_update.platform_id

    if account_update.is_mt5_account is not None and is_admin:
        account.is_mt5_account = account_update.is_mt5_account

    if account_update.api_key is not None:
        account.api_key = account_update.api_key

    if account_update.api_secret is not None:
        account.api_secret = account_update.api_secret

    if account_update.passphrase is not None:
        account.passphrase = account_update.passphrase

    if account_update.is_default is not None:
        if account_update.is_default:
            # Unset other default accounts of the same platform type
            result = await db.execute(
                select(Account).where(
                    Account.user_id == account.user_id,
                    Account.is_default == True,
                    Account.account_id != account_id,
                    Account.platform_id == account.platform_id,
                    Account.is_mt5_account == account.is_mt5_account,
                )
            )
            existing_defaults = result.scalars().all()

            for acc in existing_defaults:
                acc.is_default = False

        account.is_default = account_update.is_default

    # Handle account_role update
    # Use model_fields_set to detect when account_role is explicitly sent (even as null/empty)
    if 'account_role' in account_update.model_fields_set:
        new_role = account_update.account_role if account_update.account_role in ('primary', 'hedge') else None
        if new_role:
            # Unset other accounts with the same role for this user
            result = await db.execute(
                select(Account).where(
                    Account.user_id == account.user_id,
                    Account.account_role == new_role,
                    Account.account_id != account_id,
                )
            )
            existing_role_accounts = result.scalars().all()
            for acc in existing_role_accounts:
                acc.account_role = None
        account.account_role = new_role

    if account_update.is_active is not None:
        account.is_active = account_update.is_active

    if account_update.leverage is not None:
        account.leverage = account_update.leverage

    if account_update.proxy_config is not None:
        account.proxy_config = account_update.proxy_config

    await db.commit()
    await db.refresh(account)

    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete account.
    Admin roles (超级管理员/系统管理员/安全管理员/管理员) can delete any account;
    regular users can only delete their own.
    """
    # Determine whether the caller is an admin
    ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
    user_result = await db.execute(select(User).where(User.user_id == user_id))
    caller = user_result.scalar_one_or_none()
    is_admin = caller is not None and caller.role in ADMIN_ROLES

    if is_admin:
        # Admin: fetch account by id only (no owner restriction)
        result = await db.execute(
            select(Account).where(Account.account_id == account_id)
        )
    else:
        result = await db.execute(
            select(Account).where(
                Account.account_id == account_id,
                Account.user_id == UUID(user_id),
            )
        )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # 先删除关联的 mt5_clients 记录（ORM 没有 cascade delete-orphan，直接删子行避免 NOT NULL 违约）
    mt5_result = await db.execute(
        select(MT5Client).where(MT5Client.account_id == account_id)
    )
    mt5_clients = mt5_result.scalars().all()
    for mt5_client in mt5_clients:
        await db.delete(mt5_client)

    await db.delete(account)
    await db.commit()

    return None


@router.get("/{account_id}/balance")
async def get_account_balance(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get account balance"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"API: Getting balance for account {account_id}")

    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        if account.platform_id == 1:  # Binance
            from app.core.proxy_utils import build_proxy_url
            balance = await account_data_service.get_binance_balance(
                account.api_key,
                account.api_secret,
                proxy_url=build_proxy_url(account.proxy_config),
            )
        elif account.platform_id == 2:  # Bybit
            logger.info(f"API: Fetching Bybit balance for account {account_id}, is_mt5={account.is_mt5_account}")
            if account.is_mt5_account:
                # MT5 账户: 通过 mt5_clients 找到对应 Bridge，走 HTTP 获取余额
                import os, httpx
                from app.models.mt5_client import MT5Client as MT5ClientModel
                bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
                api_key_mt5 = os.getenv("MT5_API_KEY", "")
                headers = {"X-Api-Key": api_key_mt5} if api_key_mt5 else {}
                mc_res = await db.execute(
                    select(MT5ClientModel)
                    .where(MT5ClientModel.account_id == account.account_id)
                    .where(MT5ClientModel.is_active == True)
                    .order_by(MT5ClientModel.priority).limit(1)
                )
                mc = mc_res.scalar_one_or_none()
                if mc and mc.bridge_service_port:
                    bridge_url = mc.bridge_url or f"{bridge_host}:{mc.bridge_service_port}"
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as hc:
                            info_resp = await hc.get(f"{bridge_url}/mt5/account/info", headers=headers)
                            info = info_resp.json() if info_resp.status_code == 200 else {}
                        from app.schemas.account import AccountBalance
                        bal = float(info.get("balance", 0))
                        eq = float(info.get("equity", bal))
                        free = float(info.get("margin_free", bal))
                        margin = float(info.get("margin", 0))
                        return AccountBalance(
                            total_assets=eq, available_balance=free, net_assets=eq,
                            margin_balance=eq, frozen_assets=margin,
                            unrealized_pnl=float(info.get("profit", 0)),
                            equity=eq, volume=None, entry_price=None, leverage=None,
                            risk_ratio=(eq/margin*100) if margin > 0.01 else 0,
                        )
                    except Exception as bridge_err:
                        logger.warning(f"MT5 Bridge balance failed: {bridge_err}")
                raise HTTPException(status_code=500, detail="MT5 Bridge not available")
            from app.core.proxy_utils import build_proxy_url
            balance = await account_data_service.get_bybit_balance(
                account.api_key,
                account.api_secret,
                "UNIFIED",
                proxy_url=build_proxy_url(account.proxy_config),
            )
            logger.info(f"API: Bybit balance retrieved")
        elif account.platform_id == 3:  # IC Markets (MT5-only)
            # Use get_account_data which handles MT5 bridge for IC Markets
            account_data = await account_data_service.get_account_data(account)
            return account_data.get("balance", {})
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown platform",
            )

        return balance
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{account_id}/positions")
async def get_account_positions(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get account positions"""
    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        if account.platform_id == 1:  # Binance
            positions = await account_data_service.get_binance_positions(
                account.api_key,
                account.api_secret,
            )
        elif account.platform_id == 2:  # Bybit
            positions = await account_data_service.get_bybit_positions(
                account.api_key,
                account.api_secret,
            )
        elif account.platform_id == 3:  # IC Markets (MT5-only)
            account_data = await account_data_service.get_account_data(account)
            return account_data.get("positions", [])
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown platform",
            )

        return positions
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{account_id}/pnl")
async def get_account_pnl(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get account daily P&L"""
    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        if account.platform_id == 1:  # Binance
            daily_pnl = await account_data_service.get_binance_daily_pnl(
                account.api_key,
                account.api_secret,
            )
        elif account.platform_id == 2:  # Bybit
            account_type = "UNIFIED" if not account.is_mt5_account else "CONTRACT"
            daily_pnl = await account_data_service.get_bybit_daily_pnl(
                account.api_key,
                account.api_secret,
                account_type,
            )
        elif account.platform_id == 3:  # IC Markets (MT5-only)
            account_data = await account_data_service.get_account_data(account)
            return {"daily_pnl": account_data.get("daily_pnl", 0)}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown platform",
            )

        return {"daily_pnl": daily_pnl}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/dashboard/aggregated")
async def get_aggregated_dashboard(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated dashboard data for all user accounts.

    IMPORTANT: This route MUST be defined BEFORE /{account_id}/dashboard
    to prevent FastAPI from matching 'dashboard' as an account_id parameter.
    Admin users see ALL users' accounts; regular users see only their own.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"API: /dashboard/aggregated called for user {user_id}")

    # Admin check — admin sees all accounts
    ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
    user_result = await db.execute(select(User).where(User.user_id == user_id))
    caller = user_result.scalar_one_or_none()
    is_admin = caller is not None and caller.role in ADMIN_ROLES

    if is_admin:
        result = await db.execute(select(Account))
    else:
        result = await db.execute(
            select(Account).where(Account.user_id == UUID(user_id))
        )
    accounts = result.scalars().all()

    # Filter active accounts for data fetching
    active_accounts = [acc for acc in accounts if acc.is_active]

    logger.info(f"API: Found {len(active_accounts)} active accounts")

    if not active_accounts:
        return {
            "summary": {
                "total_assets": 0,
                "available_balance": 0,
                "net_assets": 0,
                "frozen_assets": 0,
                "margin_balance": 0,
                "unrealized_pnl": 0,
                "daily_pnl": 0,
                "risk_ratio": None,
                "account_count": 0,
                "position_count": 0,
            },
            "accounts": [],
            "positions": [],
            "failed_accounts": [],
        }

    try:
        aggregated_data = await account_data_service.get_aggregated_account_data(list(active_accounts))

        # Add inactive accounts to the response
        inactive_accounts = [acc for acc in accounts if not acc.is_active]
        for inactive_acc in inactive_accounts:
            aggregated_data.setdefault("failed_accounts", []).append({
                "account_id": str(inactive_acc.account_id),
                "account_name": inactive_acc.account_name,
                "platform_id": inactive_acc.platform_id,
                "is_mt5_account": inactive_acc.is_mt5_account,
                "is_active": False,
                "account_role": inactive_acc.account_role,
                "proxy_config": inactive_acc.proxy_config,
                "error": "账户未激活"
            })

        return aggregated_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{account_id}/dashboard")
async def get_account_dashboard(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get comprehensive account dashboard data"""
    result = await db.execute(
        select(Account).where(
            Account.account_id == account_id,
            Account.user_id == UUID(user_id),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    try:
        account_data = await account_data_service.get_account_data(account)
        return account_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
