from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class MasterAccountCreate(BaseModel):
    account_name: str | None = None
    api_key: str
    api_secret: str


class MasterAccountResponse(BaseModel):
    id: int
    account_name: str | None = None
    api_key: str
    api_secret_masked: str
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
