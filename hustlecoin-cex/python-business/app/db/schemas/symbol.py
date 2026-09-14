from pydantic import BaseModel
from datetime import datetime


class SymbolResponse(BaseModel):
    id: int
    symbol: str
    base_asset: str
    quote_asset: str
    margin_tradable: bool
    futures_tradable: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SymbolSyncResult(BaseModel):
    total_fetched: int
    new_added: int
    updated: int
    deactivated: int


class SymbolStats(BaseModel):
    total: int
    active: int
    margin_tradable: int
    futures_tradable: int
    both_tradable: int
