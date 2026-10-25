from pydantic import BaseModel
from decimal import Decimal
from typing import Optional


class SpreadData(BaseModel):
    symbol: str
    spot_bid: Decimal | None = None
    spot_ask: Decimal | None = None
    fut_bid: Decimal | None = None
    fut_ask: Decimal | None = None
    spread_long: Decimal | None = None
    spread_short: Decimal | None = None
    ts: int
    spot_recv_ts_ms: int = 0
    fut_recv_ts_ms: int = 0
    spot_symbol: str | None = None
    futures_symbol: str | None = None
    custom_monitor_id: int | None = None
    is_custom: bool = False
    data_status: str | None = None
    execution_eligible: bool = True


class HealthResponse(BaseModel):
    status: str
    redis_connected: bool
    active_symbols: int
    last_update_age_ms: Optional[int] = None
