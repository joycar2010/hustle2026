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
    futures_long_qty: Optional[Decimal] = None
    futures_long_price: Optional[Decimal] = None
    open_usdt_amount: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    futures_close_price: Optional[Decimal] = None
    spot_buy_price: Optional[Decimal] = None
    cumulative_funding_fee: Optional[Decimal] = None
    cumulative_interest: Optional[Decimal] = None
    funding_rate_ratio: Optional[Decimal] = None
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


class FundingSummary(BaseModel):
    total_funding_fee: Decimal = Decimal("0")
    total_interest: Decimal = Decimal("0")
    avg_funding_ratio: Optional[Decimal] = None
    position_count: int = 0


class DashboardResponse(BaseModel):
    engine_status: str
    workers: list[EngineStateResponse]
    positions_summary: PositionSummary
    funding_summary: Optional[FundingSummary] = None
    recent_trades: list[TradeLogResponse]


class PositionHistoryResponse(BaseModel):
    positions: list[PositionResponse]
    total_pnl: Decimal = Decimal("0")
    total_funding_fee: Decimal = Decimal("0")
    total_interest: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    count: int = 0


class WorkerHealth(BaseModel):
    scope: str
    status: str
    last_heartbeat: Optional[datetime] = None
    heartbeat_stale: bool = False
    active_positions: int = 0
    total_cycles: int = 0
    error_message: Optional[str] = None


class StuckPosition(BaseModel):
    id: int
    symbol: str
    sub_account_id: int
    status: str
    stuck_minutes: int
    error_message: Optional[str] = None


class APIMetricsResponse(BaseModel):
    total_calls: int = 0
    total_errors: int = 0
    rate_limited: int = 0
    error_rate: float = 0
    last_error_ago_sec: Optional[int] = None
    last_error_msg: Optional[str] = None
    last_success_ago_sec: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    engine_status: str
    workers: list[WorkerHealth]
    stuck_positions: list[StuckPosition]
    open_positions: int = 0
    api_metrics: dict[str, APIMetricsResponse] = {}
    spread_count: int = 0
    uptime_sec: Optional[int] = None
    used_weight_1m: int = 0
    weight_limit: int = 6000
    weight_age_sec: Optional[int] = None
    uid_used_1m: int = 0           # 借币 UID 权重用量(1500/次,顶栏「UID」显示)
    uid_limit: int = 180000        # 单 UID 权重上限
    throttle_rate: float = 0.0  # per-symbol borrow throughput (req/s) under current weight headroom
    agg_borrow_rate: float = 0.0  # Σ per-account effective borrow rate (req/s)
    single_borrow_rate: float = 0.0  # 单UID建仓速率: 单账户配速 min(borrow_rate_per_sec, UID硬顶) (req/s)
