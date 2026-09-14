from pydantic import BaseModel
from decimal import Decimal
from typing import Optional


class SpreadData(BaseModel):
    symbol: str
    spot_bid: Decimal
    spot_ask: Decimal
    fut_bid: Decimal
    fut_ask: Decimal
    spread_long: Decimal
    spread_short: Decimal
    ts: int


class HealthResponse(BaseModel):
    status: str
    redis_connected: bool
    active_symbols: int
    last_update_age_ms: Optional[int] = None
