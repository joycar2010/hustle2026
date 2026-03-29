from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
from uuid import UUID
import re


class UserCreate(BaseModel):
    """Schema for user registration"""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Username (alphanumeric, underscore, hyphen only)"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (8-128 characters)"
    )
    email: Optional[EmailStr] = Field(default=None, max_length=100)
    role: Optional[str] = Field(default='交易员', max_length=50)
    is_active: Optional[bool] = True
    feishu_open_id: Optional[str] = Field(default=None, max_length=100)
    feishu_mobile: Optional[str] = Field(default=None, max_length=20)
    feishu_union_id: Optional[str] = Field(default=None, max_length=100)

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('密码至少需要8个字符')
        return v

    class Config:
        str_strip_whitespace = True


class UserLogin(BaseModel):
    """Schema for user login"""

    username: str = Field(..., max_length=50)
    password: str = Field(..., max_length=128)


class UserUpdate(BaseModel):
    """Schema for updating user information"""

    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8, max_length=100)
    role: Optional[str] = None
    feishu_open_id: Optional[str] = Field(default=None, max_length=100)
    feishu_mobile: Optional[str] = Field(default=None, max_length=20)
    feishu_union_id: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None

    @field_validator('feishu_open_id', 'feishu_mobile', 'feishu_union_id', 'role', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None"""
        if v == '' or (isinstance(v, str) and not v.strip()):
            return None
        return v

    class Config:
        str_strip_whitespace = True


class PasswordChange(BaseModel):
    """Schema for changing password"""

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('密码至少需要8个字符')
        return v

    class Config:
        str_strip_whitespace = True


class UserResponse(BaseModel):
    """Schema for user response"""

    user_id: UUID
    username: str
    email: Optional[str]
    role: str
    feishu_open_id: Optional[str] = None
    feishu_mobile: Optional[str] = None
    feishu_union_id: Optional[str] = None
    rbac_roles: Optional[List[dict]] = []  # RBAC角色列表
    is_active: bool
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Schema for JWT token response"""

    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    username: str
