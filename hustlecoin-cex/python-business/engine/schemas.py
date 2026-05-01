from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class PositionResponse(BaseModel):
    id: int
    sub_account_id: int
    symbol: str
    base_asset: str
    status: str
    open_spread: Optional[Decimal] = None
    borrow_qty: Optional[Decimal] = None
    spot_sell_price: Optional[Decimal] = None
    futures_long_price: Optional[Decimal] = None
    open_usdt_amount: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    futures_close_price: Optional[Decimal] = None
    spot_buy_price: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    fee_total: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class TradeLogResponse(BaseModel):
    id: int
    position_id: Optional[int] = None
    sub_account_id: int
    action: str
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    order_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EngineStateResponse(BaseModel):
    scope: str
    status: str
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    active_positions: int
    total_cycles: int
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class PositionSummary(BaseModel):
    total_open: int
    total_closed: int
    total_pnl: Decimal


class DashboardResponse(BaseModel):
    engine_status: str
    workers: list[EngineStateResponse]
    positions_summary: PositionSummary
    recent_trades: list[TradeLogResponse]
