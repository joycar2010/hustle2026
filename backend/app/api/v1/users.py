"""User management API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from uuid import UUID
from typing import List
from app.core.database import get_db
from app.core.security import get_current_user_id, get_password_hash
from app.models.user import User
from app.models.position import Position
from app.schemas.user import UserResponse, UserUpdate, UserCreate

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current user information"""
    result = await db.execute(select(User).where(User.user_id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    return user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update current user information"""
    result = await db.execute(select(User).where(User.user_id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # Update fields
    if user_update.email is not None:
        # Check if email already exists
        result = await db.execute(
            select(User).where(User.email == user_update.email, User.user_id != UUID(user_id))
        )
        existing_email = result.scalar_one_or_none()

        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被使用",
            )

        user.email = user_update.email

    if user_update.password is not None:
        user.password_hash = get_password_hash(user_update.password)

    await db.commit()
    await db.refresh(user)

    return user


@router.get("/", response_model=List[UserResponse])
async def get_all_users(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get all users (admin only)"""
    from app.models.user_role import UserRole
    from app.models.role import Role
    from sqlalchemy.orm import selectinload

    # Get all users with their RBAC roles
    result = await db.execute(
        select(User).options(selectinload(User.user_roles))
    )
    users = result.scalars().all()

    # Format response with RBAC roles
    users_response = []
    for user in users:
        user_dict = {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "role": user.role,  # 保留旧的role字段以兼容
            "rbac_roles": [],
            "is_active": user.is_active,
            "create_time": user.create_time,
            "update_time": user.update_time
        }

        # Get RBAC roles for this user
        for user_role in user.user_roles:
            role_result = await db.execute(
                select(Role).where(Role.role_id == user_role.role_id)
            )
            role = role_result.scalar_one_or_none()
            if role:
                user_dict["rbac_roles"].append({
                    "role_id": str(role.role_id),
                    "role_name": role.role_name,
                    "role_code": role.role_code
                })

        users_response.append(user_dict)

    return users_response


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_create: UserCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only)"""
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_create.username))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_create.email))
    existing_email = result.scalar_one_or_none()

    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已存在",
        )

    # Create new user
    new_user = User(
        username=user_create.username,
        email=user_create.email,
        password_hash=get_password_hash(user_create.password),
        role=user_create.role if hasattr(user_create, 'role') and user_create.role else '交易员',
        is_active=user_create.is_active if hasattr(user_create, 'is_active') else True,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user


@router.put("/{target_user_id}", response_model=UserResponse)
async def update_user(
    target_user_id: UUID,
    user_update: UserUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a user (admin only)"""
    result = await db.execute(select(User).where(User.user_id == target_user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # Update fields
    if user_update.email is not None:
        # Check if email already exists
        result = await db.execute(
            select(User).where(User.email == user_update.email, User.user_id != target_user_id)
        )
        existing_email = result.scalar_one_or_none()

        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被使用",
            )

        user.email = user_update.email

    if user_update.password is not None:
        user.password_hash = get_password_hash(user_update.password)

    if hasattr(user_update, 'role') and user_update.role is not None:
        user.role = user_update.role

    if hasattr(user_update, 'is_active') and user_update.is_active is not None:
        user.is_active = user_update.is_active

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    target_user_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user (admin only)"""
    try:
        # Get current user to check permissions
        current_user_result = await db.execute(select(User).where(User.user_id == UUID(user_id)))
        current_user = current_user_result.scalar_one_or_none()

        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="当前用户未找到",
            )

        # Check if current user is admin
        if current_user.role not in ['系统管理员', '管理员', 'admin', 'super_admin']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只有管理员可以删除用户",
            )

        # Get target user
        result = await db.execute(select(User).where(User.user_id == target_user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在",
            )

        # Prevent deleting yourself
        if target_user_id == UUID(user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能删除自己的账户",
            )

        # Delete all related data before deleting user
        # Order matters: child records must be deleted before parent (user)
        from app.models.strategy import Strategy
        from app.models.strategy_performance import StrategyPerformance
        from sqlalchemy import text

        # Step 1: Delete strategy_performance (FK -> strategies.id, no cascade from users)
        strategies_result = await db.execute(
            select(Strategy.id).where(Strategy.user_id == target_user_id)
        )
        strategy_ids = [row[0] for row in strategies_result.all()]
        if strategy_ids:
            await db.execute(
                delete(StrategyPerformance).where(
                    StrategyPerformance.strategy_id.in_(strategy_ids)
                )
            )

        uid = str(target_user_id)

        # Step 2: Null out soft FK references (roles, security_components, ssl_certificates)
        await db.execute(text("UPDATE role_permissions SET granted_by = NULL WHERE granted_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("UPDATE roles SET created_by = NULL WHERE created_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("UPDATE roles SET updated_by = NULL WHERE updated_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("UPDATE security_components SET created_by = NULL WHERE created_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("UPDATE security_components SET updated_by = NULL WHERE updated_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("UPDATE ssl_certificates SET uploaded_by = NULL WHERE uploaded_by = :uid::uuid"), {"uid": uid})

        # Step 3: Delete log/audit records referencing this user
        await db.execute(text("DELETE FROM security_component_logs WHERE performed_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("DELETE FROM ssl_certificate_logs WHERE performed_by = :uid::uuid"), {"uid": uid})
        await db.execute(text("DELETE FROM trades WHERE user_id = :uid::uuid"), {"uid": uid})
        await db.execute(text("DELETE FROM system_alerts WHERE user_id = :uid::uuid"), {"uid": uid})

        # Step 4: Delete positions (FK -> users.user_id, NO ACTION, no ORM cascade)
        await db.execute(delete(Position).where(Position.user_id == target_user_id))

        # Step 5: Null out user_roles.assigned_by (self-referential FK)
        await db.execute(text("UPDATE user_roles SET assigned_by = NULL WHERE assigned_by = :uid::uuid"), {"uid": uid})

        # Step 6: Delete user - ORM cascade handles accounts, strategies, strategy_configs,
        # arbitrage_tasks, risk_alerts, risk_settings, user_roles
        await db.delete(user)
        await db.commit()

        return None
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to delete user {target_user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除用户失败: {str(e)}",
        )
