"""Authentication API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import logging
import time
import uuid
import asyncio
from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user_id,
)
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, Token, UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)


class PasswordVerification(BaseModel):
    password: str


class PasswordVerificationResponse(BaseModel):
    valid: bool


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user"""
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email already exists
    if user_data.email:
        result = await db.execute(select(User).where(User.email == user_data.email))
        existing_email = result.scalar_one_or_none()

        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    # Create new user
    new_user = User(
        user_id=uuid.uuid4(),
        username=user_data.username,
        password_hash=get_password_hash(user_data.password),
        email=user_data.email,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """User login with timeout control and detailed logging"""
    start_time = time.time()
    logger.info(f"Login request received: username={credentials.username}")

    try:
        # Database query with timeout control (5 seconds max)
        try:
            query_start = time.time()
            result = await asyncio.wait_for(
                db.execute(select(User).where(User.username == credentials.username)),
                timeout=5.0
            )
            user = result.scalar_one_or_none()
            logger.info(f"Database query completed in {time.time() - query_start:.2f}s")
        except asyncio.TimeoutError:
            logger.error(f"Database query timeout after {time.time() - start_time:.2f}s")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Login failed: database query timeout"
            )

        # Verify user and password
        if not user or not verify_password(credentials.password, user.password_hash):
            logger.warning(f"Invalid credentials for username: {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            logger.warning(f"Inactive user attempted login: {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )

        # Create access token
        token_start = time.time()
        access_token = create_access_token(data={"sub": str(user.user_id)})
        logger.info(f"Token created in {time.time() - token_start:.2f}s")

        total_time = time.time() - start_time
        logger.info(f"Login successful for {credentials.username}, total time: {total_time:.2f}s")

        return Token(
            access_token=access_token,
            user_id=user.user_id,
            username=user.username,
        )

    except HTTPException:
        raise
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Login error after {total_time:.2f}s: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/verify-password", response_model=PasswordVerificationResponse)
async def verify_user_password(
    verification: PasswordVerification,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """Verify user's password for sensitive operations"""
    # Get current user
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Verify password
    is_valid = verify_password(verification.password, user.password_hash)

    return PasswordVerificationResponse(valid=is_valid)
