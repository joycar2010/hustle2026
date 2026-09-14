from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class BlacklistCreate(BaseModel):
    symbol: str
    reason: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()


class BlacklistBulkCreate(BaseModel):
    symbols: list[str]
    reason: Optional[str] = None

    @field_validator("symbols")
    @classmethod
    def uppercase_symbols(cls, v: list[str]) -> list[str]:
        return [s.upper().strip() for s in v]


class BlacklistResponse(BaseModel):
    id: int
    symbol: str
    reason: Optional[str] = None
    created_at: datetime
    user_id: Optional[int] = None   # None=全局系统黑名单(不可由用户删除);有值=本人个人黑名单

    model_config = {"from_attributes": True}
