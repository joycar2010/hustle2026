"""User management API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
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
            detail="User not found",
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
            detail="User not found",
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
                detail="Email already in use",
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
    result = await db.execute(select(User))
    users = result.scalars().all()
    return users


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
            detail="Username already exists",
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_create.email))
    existing_email = result.scalar_one_or_none()

    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
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
            detail="User not found",
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
                detail="Email already in use",
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
    result = await db.execute(select(User).where(User.user_id == target_user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Delete related data not covered by cascade
    from sqlalchemy import text
    await db.execute(text("DELETE FROM positions WHERE user_id = :uid"), {"uid": target_user_id})
    await db.execute(text("DELETE FROM trades WHERE user_id = :uid"), {"uid": target_user_id})
    await db.execute(text("DELETE FROM system_alerts WHERE user_id = :uid"), {"uid": target_user_id})

    await db.delete(user)
    await db.commit()

    return None
