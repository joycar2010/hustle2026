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
    """List all accounts for current user (regardless of status)"""
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
    """Create a new account"""
    # If this is set as default, unset other default accounts
    if account_data.is_default:
        result = await db.execute(
            select(Account).where(Account.user_id == UUID(user_id), Account.is_default == True)
        )
        existing_defaults = result.scalars().all()

        for acc in existing_defaults:
            acc.is_default = False

    # Create new account
    new_account = Account(
        user_id=UUID(user_id),
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
    )

    db.add(new_account)
    await db.commit()
    await db.refresh(new_account)

    return new_account


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
    """Update account"""
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

    # Update fields
    if account_update.account_name is not None:
        account.account_name = account_update.account_name

    if account_update.api_key is not None:
        account.api_key = account_update.api_key

    if account_update.api_secret is not None:
        account.api_secret = account_update.api_secret

    if account_update.passphrase is not None:
        account.passphrase = account_update.passphrase

    if account_update.is_default is not None:
        if account_update.is_default:
            # Unset other default accounts
            result = await db.execute(
                select(Account).where(
                    Account.user_id == UUID(user_id),
                    Account.is_default == True,
                    Account.account_id != account_id,
                )
            )
            existing_defaults = result.scalars().all()

            for acc in existing_defaults:
                acc.is_default = False

        account.is_default = account_update.is_default

    if account_update.is_active is not None:
        account.is_active = account_update.is_active

    await db.commit()
    await db.refresh(account)

    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete account"""
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
            balance = await account_data_service.get_binance_balance(
                account.api_key,
                account.api_secret,
            )
        elif account.platform_id == 2:  # Bybit
            balance = await account_data_service.get_bybit_balance(
                account.api_key,
                account.api_secret,
                "UNIFIED",
                mt5_id=account.mt5_id if account.is_mt5_account else None,
                mt5_password=account.mt5_primary_pwd if account.is_mt5_account else None,
                mt5_server=account.mt5_server if account.is_mt5_account else None,
            )
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


@router.get("/dashboard/aggregated")
async def get_aggregated_dashboard(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated dashboard data for all user accounts"""
    result = await db.execute(
        select(Account).where(
            Account.user_id == UUID(user_id),
        )
    )
    accounts = result.scalars().all()

    # Filter active accounts for data fetching
    active_accounts = [acc for acc in accounts if acc.is_active]

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
                "error": "账户未激活"
            })

        return aggregated_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
