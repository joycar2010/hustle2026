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

    model_config = {"from_attributes": True}
