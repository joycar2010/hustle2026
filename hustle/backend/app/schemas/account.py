from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID

class AccountBase(BaseModel):
    account_name: str
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None
    mt5_id: Optional[str] = None
    mt5_server: Optional[str] = None
    mt5_primary_pwd: Optional[str] = None
    is_mt5_account: bool = False
    is_default: bool = False
    is_active: bool = True

class AccountCreate(AccountBase):
    platform_id: int

class AccountUpdate(BaseModel):
    account_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None
    mt5_id: Optional[str] = None
    mt5_server: Optional[str] = None
    mt5_primary_pwd: Optional[str] = None
    is_mt5_account: Optional[bool] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None

class AccountResponse(AccountBase):
    account_id: UUID
    user_id: UUID
    platform_id: int
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True
