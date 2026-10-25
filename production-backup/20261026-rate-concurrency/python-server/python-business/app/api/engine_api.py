import asyncio
from contextvars import ContextVar
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from functools import wraps

import redis
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.db.models import (
    SubAccount,
    MasterAccount,
    CustomMonitorSymbol,
)
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services.pushed_symbols import (
    auto_global_rules_key,
    custom_monitor_candidate_key,
    custom_monitor_id_from_candidate,
    custom_monitor_source_key,
    is_custom_monitor_candidate,
    manual_push_marker_key,
    mutate_pushed_symbols,
)
from app.services.custom_monitor_push import custom_monitor_block_reason
from engine.models import Position, TradeLog, EngineState, canonical_position_symbol
from engine.fund.residual_dust import is_terminal_position_status
from engine.schemas import (
    PositionResponse, TradeLogResponse, EngineStateResponse,
    PositionSummary, DashboardResponse, FundingSummary,
    PositionHistoryResponse, HealthResponse, WorkerHealth,
    StuckPosition, APIMetricsResponse,
)
from engine.trading.borrow_coordination import (
    ACCOUNT_OPERATION_LOCK_TTL_SEC,
    AccountOperationLockBusy,
    AccountOperationLockUnavailable,
    account_operation_lock,
    account_operation_lock_key,
    master_symbol_lock,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engine", tags=["engine"])

# ``cex-worker.service`` is the long-lived command consumer.  The dashboard
# start/stop buttons enqueue a tenant command for that process; an API that is
# alive while the consumer is stopped must not claim that the command was
# accepted.  ``engine.main`` refreshes this key every loop with a 30-second
# expiry, so a short age window also catches a wedged event loop.
WORKER_COMMAND_HEARTBEAT_KEY = "engine:worker:heartbeat"
WORKER_COMMAND_HEARTBEAT_MAX_AGE_SEC = 45
# A transition is an intent, not a durable running state.  If no Worker
# acknowledgement updates the row within this window, readers must expose an
# error/retry state instead of leaving the dashboard's toggle stuck forever.
ENGINE_TRANSITION_MAX_AGE_SEC = 45


def _command_consumer_alive(redis_client, *, now: float | None = None) -> bool:
    """Return whether the host Worker can consume an engine command.

    This is deliberately fail-closed.  Redis clients used by tests may only
    implement ``get``; a missing ``ttl`` method is therefore treated as valid
    when the timestamp itself is fresh.  Production clients expose both and
    must also report a non-expired key.
    """
    try:
        raw = redis_client.get(WORKER_COMMAND_HEARTBEAT_KEY)
        if raw is None:
            return False
        # Current Workers publish ``<unix-seconds>|<owner-token>`` so a
        # restarted process can safely compare-and-delete its own marker.
        # Older Workers published only the numeric timestamp; keep that wire
        # format readable while ignoring the opaque owner suffix.
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        stamp_text = str(raw).strip().split("|", 1)[0]
        stamp = float(stamp_text)
        current = time.time() if now is None else float(now)
        age = current - stamp
        if age < 0 or age > WORKER_COMMAND_HEARTBEAT_MAX_AGE_SEC:
            return False
        ttl_fn = getattr(redis_client, "ttl", None)
        if callable(ttl_fn):
            ttl = ttl_fn(WORKER_COMMAND_HEARTBEAT_KEY)
            # Redis returns -1 for a key without expiry and -2 for a missing
            # key.  A persistent key is acceptable only for legacy test
            # doubles; production's heartbeat always has a positive TTL.
            if ttl is not None and int(ttl) == -2:
                return False
            if ttl is not None and int(ttl) == 0:
                return False
        return True
    except Exception:
        return False


def _engine_transition_age(state, *, now: datetime | None = None) -> float | None:
    """Return the age of an EngineState transition, handling legacy naive UTC."""
    stamp = getattr(state, "updated_at", None)
    if stamp is None:
        # Some pre-migration rows have no updated_at.  These fields are less
        # precise but still preferable to treating an old transition as fresh.
        stamp = getattr(state, "last_heartbeat", None) or getattr(state, "started_at", None)
    if stamp is None:
        return None
    try:
        if getattr(stamp, "tzinfo", None) is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if getattr(current, "tzinfo", None) is None:
            current = current.replace(tzinfo=timezone.utc)
        age = (current - stamp).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return None
    return age if age >= 0 else 0.0


def _display_engine_status(
    state,
    *,
    command_consumer: bool = True,
    now: datetime | None = None,
) -> str:
    """Expose a recoverable status for API readers without mutating the DB.

    STARTING/STOPPING rows are written before a Redis command is published.
    If the command is lost (or the Worker host is down), the persisted row can
    otherwise survive indefinitely and disable the only dashboard control.
    Aged transitions are therefore surfaced as ERROR; the next explicit start
    or stop request can safely replace the intent.  Fresh transitions retain
    their original value even while a Worker host is briefly restarting.
    """
    if state is None:
        return "STOPPED"
    status = str(getattr(state, "status", "STOPPED") or "STOPPED").strip().upper()
    # A persisted RUNNING row is not proof that the host process still owns
    # the command queue.  Without a fresh heartbeat the toggle must expose a
    # recoverable error instead of inviting a stop command that no process
    # can consume.
    if status == "RUNNING" and not command_consumer:
        return "ERROR"
    if status in {"STARTING", "STOPPING"}:
        age = _engine_transition_age(state, now=now)
        # A transition without any trustworthy timestamp cannot be proven
        # fresh (legacy rows and failed partial migrations exist), so fail
        # closed and let the operator retry it explicitly.
        if age is None or age > ENGINE_TRANSITION_MAX_AGE_SEC:
            return "ERROR"
    return status


def _fresh_engine_transition(state, *, now: datetime | None = None) -> str | None:
    """Return a live STARTING/STOPPING intent, or ``None`` when replaceable.

    The API endpoints are also called by scripts and multiple browser tabs, so
    the frontend transition lock cannot be the only duplicate-command guard.
    A stale or timestamp-less legacy row is deliberately replaceable: readers
    already expose it as ``ERROR`` and an operator must be able to recover it.
    """
    status = str(getattr(state, "status", "") or "").strip().upper()
    if status not in {"STARTING", "STOPPING"}:
        return None
    age = _engine_transition_age(state, now=now)
    if age is None or age > ENGINE_TRANSITION_MAX_AGE_SEC:
        return None
    return status

# FastAPI requests expose ``request.state``.  A few internal callers and
# lightweight endpoint tests invoke handlers with a plain object instead;
# keep the lease available to those callers without weakening the final
# Binance guard or sharing it across concurrent requests.
_account_operation_lock_context: ContextVar[tuple | None] = ContextVar(
    "account_operation_lock_context", default=None
)


def _request_operation_lock(request: Request):
    state = getattr(request, "state", None)
    value = getattr(state, "account_operation_lock", None)
    return value if value is not None else _account_operation_lock_context.get()


def _bind_request_operation_lock(request: Request, value: tuple) -> None:
    state = getattr(request, "state", None)
    if state is not None:
        try:
            state.account_operation_lock = value
        except (AttributeError, TypeError):
            # ContextVar remains the authoritative fallback for test doubles
            # and custom ASGI request wrappers with immutable state objects.
            pass


def _worker_account_id(scope: str) -> int | None:
    try:
        prefix, value = str(scope).split(":", 1)
        return int(value) if prefix == "sub" else None
    except (TypeError, ValueError):
        return None


def _inventory_probe_rates_by_account(
    sub_accounts,
    default_rate: float,
) -> dict[str, float]:
    """Build the read-only health metric without applying borrow POST limits."""
    result: dict[str, float] = {}
    for account in sub_accounts:
        raw_rate = getattr(account, "inventory_probe_rate_per_sec", None)
        try:
            rate = float(default_rate if raw_rate is None else raw_rate)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(rate) or rate <= 0 or rate > 10:
            continue
        result[str(account.id)] = round(rate, 3)
    return result


def _worker_payload(state: EngineState, db: Session, user_id: int) -> dict:
    """Return a user-scoped worker row with the account identity needed by UI controls."""
    account_id = _worker_account_id(state.scope)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id,
        SubAccount.user_id == user_id,
    ).first() if account_id is not None else None
    payload = EngineStateResponse.model_validate(state).model_dump()
    payload.update({
        "id": state.id,
        "account_id": account_id or 0,
        "account_note": account.note if account and account.note else ("未命名子账户" if account_id is not None else state.scope),
        "user_id": user_id,
    })
    return payload


class BalanceResponse(BaseModel):
    spot_usdt_free: str = "0"
    spot_usdt_locked: str = "0"
    funding_usdt: str = "0"
    earn_total: str = "0"
    margin_level: str = "0"
    margin_usdt_free: str = "0"
    margin_usdt_borrowed: str = "0"
    futures_total_balance: str = "0"
    futures_available: str = "0"
    futures_unrealized_pnl: str = "0"
    bnb_free: str = "0"
    bnb_interest: str = "0"


class TransferRequest(BaseModel):
    from_wallet: str
    to_wallet: str
    asset: str = "USDT"
    amount: Decimal


def _user_positions(db: Session, user_id: int):
    return db.query(Position).filter(Position.user_id == user_id)


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(
    request: Request,
    sub_account_id: int = Query(None),
    status: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = _user_positions(db, user_id)
    if sub_account_id:
        q = q.filter(Position.sub_account_id == sub_account_id)
    if status:
        st = status.upper()
        if st == "ACTIVE":
            # All non-terminal lifecycle rows must remain visible, especially
            # ambiguous borrow submissions that require operator review.
            q = q.filter(Position.status.notin_(("CLOSED", "FAILED")))
        else:
            q = q.filter(Position.status == st)
    if symbol:
        q = q.filter(Position.symbol == _normalize_usdt_symbol(symbol))
    q = q.order_by(Position.id.desc())
    rows = q.offset((page - 1) * size).limit(size).all()
    # 注入子账户备注名(account_note):借到币的真实 position 也带名,前端不再 fallback 显示 #N
    note_map = {
        s.id: s.note for s in db.query(SubAccount.id, SubAccount.note).filter(
            SubAccount.user_id == user_id,
        ).all()
    }
    for p in rows:
        p.account_note = note_map.get(p.sub_account_id)
    return rows


@router.get("/positions/summary", response_model=PositionSummary)
def positions_summary(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    total_open = _user_positions(db, user_id).filter(Position.status == "OPEN").count()
    total_closed = _user_positions(db, user_id).filter(Position.status == "CLOSED").count()
    total_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.user_id == user_id, Position.status == "CLOSED"
    ).scalar()
    return {
        "total_open": total_open,
        "total_closed": total_closed,
        "total_pnl": Decimal(str(total_pnl)),
    }


@router.get("/positions/{position_id:int}", response_model=PositionResponse)
def get_position(position_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    pos = _user_positions(db, user_id).filter(Position.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return pos


@router.get("/trade-logs", response_model=list[TradeLogResponse])
def list_trade_logs(
    request: Request,
    sub_account_id: int = Query(None),
    action: str = Query(None),
    position_id: int = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = db.query(TradeLog).filter(TradeLog.user_id == user_id)
    if sub_account_id:
        q = q.filter(TradeLog.sub_account_id == sub_account_id)
    if action:
        q = q.filter(TradeLog.action == action.upper())
    if position_id:
        q = q.filter(TradeLog.position_id == position_id)
    q = q.order_by(TradeLog.id.desc())
    return q.offset((page - 1) * size).limit(size).all()


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    global_state = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope == "global",
    ).first()
    try:
        command_consumer = _command_consumer_alive(_redis())
    except Exception:
        command_consumer = False
    engine_status = _display_engine_status(
        global_state,
        command_consumer=command_consumer,
    )

    # 仅当前存在子账户对应的 worker(过滤已删账户残留行;顶栏「引擎 X/Y」分母据此)
    _scopes = _live_worker_scopes(db, user_id)
    workers = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope.in_(_scopes),
    ).all() if _scopes else []

    total_open = _user_positions(db, user_id).filter(Position.status == "OPEN").count()
    total_closed = _user_positions(db, user_id).filter(Position.status == "CLOSED").count()
    total_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.user_id == user_id, Position.status == "CLOSED"
    ).scalar()

    recent = db.query(TradeLog).filter(TradeLog.user_id == user_id).order_by(TradeLog.id.desc()).limit(10).all()

    open_positions = _user_positions(db, user_id).filter(Position.status == "OPEN").all()
    total_funding = sum(Decimal(str(p.cumulative_funding_fee or 0)) for p in open_positions)
    total_interest = sum(Decimal(str(p.cumulative_interest or 0)) for p in open_positions)
    ratios = [p.funding_rate_ratio for p in open_positions if p.funding_rate_ratio]
    avg_ratio = sum(ratios) / len(ratios) if ratios else None

    return {
        "engine_status": engine_status,
        "command_consumer": command_consumer,
        "workers": [_worker_payload(w, db, user_id) for w in workers],
        "positions_summary": {
            "total_open": total_open,
            "total_closed": total_closed,
            "total_pnl": Decimal(str(total_pnl)),
        },
        "funding_summary": {
            "total_funding_fee": total_funding,
            "total_interest": total_interest,
            "avg_funding_ratio": avg_ratio,
            "position_count": len(open_positions),
        },
        "recent_trades": recent,
    }


@router.get("/positions/history", response_model=PositionHistoryResponse)
def positions_history(
    request: Request,
    start_date: str = Query(None),
    end_date: str = Query(None),
    sub_account_id: int = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    user_id = get_current_user_id(request)
    q = _user_positions(db, user_id).filter(Position.status == "CLOSED")
    if sub_account_id:
        q = q.filter(Position.sub_account_id == sub_account_id)
    if start_date:
        q = q.filter(Position.closed_at >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(Position.closed_at <= datetime.fromisoformat(end_date))

    total_q = q
    total_pnl = Decimal(str(db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.id.in_(total_q.with_entities(Position.id))
    ).scalar()))
    total_funding = Decimal(str(db.query(func.coalesce(func.sum(Position.cumulative_funding_fee), 0)).filter(
        Position.id.in_(total_q.with_entities(Position.id))
    ).scalar()))
    total_interest = Decimal(str(db.query(func.coalesce(func.sum(Position.cumulative_interest), 0)).filter(
        Position.id.in_(total_q.with_entities(Position.id))
    ).scalar()))
    count = total_q.count()

    positions = q.order_by(Position.closed_at.desc()).offset((page - 1) * size).limit(size).all()

    return {
        "positions": positions,
        "total_pnl": total_pnl,
        "total_funding_fee": total_funding,
        "total_interest": total_interest,
        "net_pnl": total_pnl + total_funding - total_interest,
        "count": count,
    }


@router.get("/funding-fees")
def funding_fees_summary(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    positions = _user_positions(db, user_id).filter(Position.status == "OPEN").all()
    result = []
    for p in positions:
        result.append({
            "position_id": p.id,
            "symbol": p.symbol,
            "sub_account_id": p.sub_account_id,
            "borrow_qty": str(p.borrow_qty or 0),
            "cumulative_funding_fee": str(p.cumulative_funding_fee or 0),
            "cumulative_interest": str(p.cumulative_interest or 0),
            "funding_rate_ratio": str(p.funding_rate_ratio) if p.funding_rate_ratio else None,
            "opened_at": str(p.opened_at) if p.opened_at else None,
        })
    return result


@router.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
async def get_account_balance(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        spot, margin, futures, funding, earn = await asyncio.gather(
            client.get_spot_account(),
            client.get_margin_account(),
            client.get_futures_account(),
            client.get_funding_account(),
            client.get_simple_earn_account(),
        )

    spot_free = "0"
    spot_locked = "0"
    for a in spot.get("balances", []):
        if a["asset"] == "USDT":
            spot_free = a.get("free", "0")
            spot_locked = a.get("locked", "0")
            break

    funding_usdt = "0"
    for a in (funding if isinstance(funding, list) else []):
        if a.get("asset") == "USDT":
            funding_usdt = a.get("free", "0")
            break

    earn_total = "0"
    if isinstance(earn, dict):
        earn_total = earn.get("totalAmountInUSDT", "0")

    margin_free = "0"
    margin_borrowed = "0"
    bnb_free = "0"
    bnb_interest = "0"
    for a in margin.get("userAssets", []):
        if a["asset"] == "USDT":
            margin_free = a.get("free", "0")
            margin_borrowed = a.get("borrowed", "0")
        elif a["asset"] == "BNB":
            bnb_free = a.get("free", "0")
            bnb_interest = a.get("interest", "0")

    return BalanceResponse(
        spot_usdt_free=spot_free,
        spot_usdt_locked=spot_locked,
        funding_usdt=funding_usdt,
        earn_total=earn_total,
        margin_level=margin.get("marginLevel", "0"),
        margin_usdt_free=margin_free,
        margin_usdt_borrowed=margin_borrowed,
        futures_total_balance=futures.get("totalWalletBalance", "0"),
        futures_available=futures.get("availableBalance", "0"),
        futures_unrealized_pnl=futures.get("totalUnrealizedProfit", "0"),
        bnb_free=bnb_free,
        bnb_interest=bnb_interest,
    )


@router.get("/accounts/{account_id}/max-borrowable/{asset}")
async def get_max_borrowable(account_id: int, asset: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        mb = await client.get_max_borrowable(asset.upper())

    # get_max_borrowable 返回 {"amount":Decimal, "borrowLimit":Decimal};过去直接 str(dict) 致前端显示
    # 原始 "{'amount': Decimal('0'), ...}"。这里拆出标量,前端展示纯数字。
    if isinstance(mb, dict):
        return {"asset": asset.upper(),
                "max_borrowable": str(mb.get("amount", 0)),
                "borrow_limit": str(mb.get("borrowLimit", 0))}
    return {"asset": asset.upper(), "max_borrowable": str(mb), "borrow_limit": None}


@router.get("/accounts/{account_id}/loan-history")
async def get_loan_history(
    account_id: int,
    request: Request,
    type: str = Query("BORROW"),
    asset: str = Query(None),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """币安全仓 借/还/利息 原始流水(对账用)。type=BORROW/REPAY/INTEREST。"""
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
    t = (type or "BORROW").upper()
    a = asset.upper() if asset else None
    try:
        async with BinanceTradingClient(account.api_key, account.api_secret) as client:
            if t == "INTEREST":
                data = await client.get_interest_history(asset=a, size=size)
            else:
                data = await client.get_loan_records(txn_type=t, asset=a, size=size)
    except BinanceAPIError as e:
        raise HTTPException(status_code=400, detail=f"查询失败: {e.message}")
    return {"type": t, "rows": data.get("rows", []), "total": data.get("total", 0)}


class TailCleanupRequest(BaseModel):
    max_usdt_amount: Decimal = Decimal("10")


@router.get("/positions/tail")
def list_tail_positions(
    request: Request,
    max_usdt: Decimal = Query(Decimal("10")),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    positions = _user_positions(db, user_id).filter(
        Position.status == "OPEN",
        Position.open_usdt_amount <= max_usdt,
        Position.open_usdt_amount > 0,
    ).all()
    return [
        {
            "id": p.id,
            "symbol": p.symbol,
            "sub_account_id": p.sub_account_id,
            "open_usdt_amount": str(p.open_usdt_amount),
            "borrow_qty": str(p.borrow_qty),
            "opened_at": str(p.opened_at),
        }
        for p in positions
    ]


@router.post("/positions/tail/cleanup")
async def cleanup_tail_positions(
    data: TailCleanupRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    positions = _user_positions(db, user_id).filter(
        Position.status == "OPEN",
        Position.open_usdt_amount <= data.max_usdt_amount,
        Position.open_usdt_amount > 0,
    ).all()

    if not positions:
        return {"message": "No tail positions found", "closed": 0}

    closed = 0
    errors = []
    for pos in positions:
        account = db.query(SubAccount).filter(
            SubAccount.id == pos.sub_account_id, SubAccount.user_id == user_id,
        ).first()
        if not account:
            continue
        try:
            from contextlib import AsyncExitStack
            from engine.trading.binance_trading import BinanceTradingClient
            from engine.notify.feishu_sender import FeishuSender
            from engine.trading.order_executor import execute_close
            from engine.spread_feed import SpreadSnapshot

            async with _account_operation_guard(
                account.id,
                pos.symbol,
                owner=f"tail-cleanup:{user_id}:{pos.id}",
                user_id=user_id,
            ) as lock_context:
                db.refresh(pos)
                if pos.status != "OPEN":
                    errors.append(
                        f"{pos.symbol}#{pos.id}: 持仓状态已变为 {pos.status}，未重复清理"
                    )
                    continue

                master = None
                if getattr(pos, "hedge_account", None) == "master":
                    master = _load_master_account(db, user_id)
                    if not master:
                        errors.append(f"{pos.symbol}#{pos.id}: 合约腿在主账户但主账户未配置")
                        continue

                async with AsyncExitStack() as stack:
                    client = await stack.enter_async_context(
                        BinanceTradingClient(account.api_key, account.api_secret))
                    fc = None
                    if master:
                        fc = await stack.enter_async_context(BinanceTradingClient(
                            master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
                        await _assert_master_one_way(fc)
                    dummy_spread = SpreadSnapshot(
                        symbol=pos.symbol, spot_bid=0, spot_ask=0,
                        fut_bid=0, fut_ask=0, spread_long=0, spread_short=0, ts=0,
                    )
                    # Tail cleanup is explicitly risk-reducing. Force a market
                    # buy-back so a dummy/absent quote cannot strand the hedge
                    # behind the normal freshness fence.
                    completed = await execute_close(
                        pos,
                        dummy_spread,
                        client,
                        FeishuSender(),
                        account.note or f"#{account.id}",
                        futures_client=fc,
                        spot_order_mode="market",
                        allow_emergency_close=True,
                        user_id=user_id,
                        operation_lock_redis=lock_context[0],
                        operation_lock_token=lock_context[1],
                    )
                    db.refresh(pos)
                    if completed and pos.status == "CLOSED":
                        closed += 1
                    else:
                        errors.append(
                            f"{pos.symbol}#{pos.id}: 交易所尚未确认清仓完成"
                        )
        except Exception as e:
            detail = e.detail if isinstance(e, HTTPException) else str(e)
            errors.append(f"{pos.symbol}#{pos.id}: {detail}")

    return {
        "message": f"Cleaned up {closed} tail positions",
        "closed": closed,
        "errors": errors,
    }


@router.post("/accounts/{account_id}/transfer")
async def manual_transfer(account_id: int, data: TransferRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.fund.transfer_manager import TRANSFER_TYPES
    key = (data.from_wallet.lower(), data.to_wallet.lower())
    transfer_type = TRANSFER_TYPES.get(key)
    if not transfer_type:
        raise HTTPException(status_code=400, detail=f"Invalid transfer direction: {data.from_wallet} → {data.to_wallet}")

    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        result = await client.transfer(transfer_type, data.asset, data.amount)

    return {"message": f"Transferred {data.amount} {data.asset} from {data.from_wallet} to {data.to_wallet}", "tranId": result.get("tranId")}


# 钱包 → 币安万向划转账户类型
_UT_ACCT_TYPE = {"spot": "SPOT", "futures": "USDT_FUTURE", "margin": "MARGIN"}


class CrossTransferRequest(BaseModel):
    asset: str = "USDT"
    amount: Decimal
    direction: str = "out"            # out=本账户(account_id)转出, in=本账户转入
    counterparty_type: str = "master"  # master | sub
    counterparty_sub_account_id: int | None = None
    from_wallet: str = "spot"          # spot | futures | margin
    to_wallet: str = "spot"
    # 旧字段兼容(原仅支持 本账户→master / 本账户→sub)
    target_type: str | None = None
    target_sub_account_id: int | None = None


@router.post("/accounts/{account_id}/transfer-cross")
async def cross_account_transfer(account_id: int, data: CrossTransferRequest, request: Request, db: Session = Depends(get_db)):
    """主/子账户互转(master↔sub、sub↔sub)。一律用【主账户】key 调 universalTransfer:
    direction=out 本账户转出, in 本账户转入;对手方 master(email 省略)或另一子账户。"""
    user_id = get_current_user_id(request)
    anchor = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not anchor:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    cp_type = data.counterparty_type or data.target_type or "master"
    cp_sub_id = data.counterparty_sub_account_id or data.target_sub_account_id
    if cp_type not in ("master", "sub"):
        raise HTTPException(status_code=400, detail="counterparty_type 必须是 master 或 sub")
    if data.direction not in ("out", "in"):
        raise HTTPException(status_code=400, detail="direction 必须是 out 或 in")

    # universalTransfer 是主账户专属端点,任何方向都用主账户 key
    master = _load_master_account(db, user_id)
    if not master:
        raise HTTPException(status_code=400, detail="主账户未配置,无法跨账户划转")

    # 对手方 email(master → None 省略表示主账户)+ 标签
    if cp_type == "master":
        cp_email, cp_label = None, "主账户"
    else:
        if not cp_sub_id:
            raise HTTPException(status_code=400, detail="子↔子划转需指定对手子账户")
        cp = db.query(SubAccount).filter(
            SubAccount.id == cp_sub_id, SubAccount.user_id == user_id,
        ).first()
        if not cp:
            raise HTTPException(status_code=404, detail="对手子账户不存在")
        cp_email, cp_label = cp.email, (cp.note or f"#{cp.id}")

    from_acct = _UT_ACCT_TYPE.get((data.from_wallet or "spot").lower(), "SPOT")
    to_acct = _UT_ACCT_TYPE.get((data.to_wallet or "spot").lower(), "SPOT")

    # from_wallet/to_wallet 恒指实际转账的「源钱包/目标钱包」(与方向无关)
    if data.direction == "out":      # 本账户 → 对手方
        from_email, to_email = anchor.email, cp_email
        src_label, dst_label = (anchor.note or f"#{anchor.id}"), cp_label
    else:                            # 对手方 → 本账户
        from_email, to_email = cp_email, anchor.email
        src_label, dst_label = cp_label, (anchor.note or f"#{anchor.id}")

    if from_email == to_email:
        raise HTTPException(status_code=400, detail="源账户与目标账户不能相同")

    from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
    try:
        async with BinanceTradingClient(master.api_key, master.api_secret) as client:
            result = await client.universal_transfer(
                asset=data.asset, amount=data.amount,
                from_account_type=from_acct, to_account_type=to_acct,
                from_email=from_email, to_email=to_email,
            )
    except BinanceAPIError as e:
        raise HTTPException(status_code=400, detail=f"划转失败: {e.message}")
    return {
        "message": f"已划转 {data.amount} {data.asset}: {src_label} → {dst_label}",
        "tranId": result.get("tranId"),
    }


def _redis():
    # Dashboard control and telemetry must fail fast when the shared Redis
    # endpoint is unavailable; the default redis-py socket timeout is
    # unbounded and would leave the UI showing a spinner for minutes.
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def _user_redis_key(user_id: int, key: str) -> str:
    return f"engine:{user_id}:{key}"


def _normalize_usdt_symbol(symbol: str) -> str:
    return canonical_position_symbol(symbol)


def _position_matches_symbol(position: Position, symbol: str) -> bool:
    """Match both current and legacy Position symbol representations.

    Rolling deployments can expose rows whose ``canonical_symbol`` is still
    NULL (or stale) even though the raw ``symbol`` identifies the same pair.
    The raw value remains a useful fallback; either representation must agree
    with the requested canonical pair before an ownership decision is made.
    """
    normalized = canonical_position_symbol(symbol)
    return any(
        canonical_position_symbol(value) == normalized
        for value in (
            getattr(position, "symbol", None),
            getattr(position, "canonical_symbol", None),
        )
    )


def _new_action_is_paused(user_id: int | None, symbol: str) -> bool:
    """Use the same fail-closed tenant gate as the Worker/executor."""
    from engine.pause_gate import is_symbol_paused_sync

    return is_symbol_paused_sync(user_id, symbol)


@router.get("/pushed-symbols")
def get_pushed_symbols(request: Request):
    user_id = get_current_user_id(request)
    r = _redis()
    pushed_set, _ = mutate_pushed_symbols(
        r,
        _user_redis_key(user_id, "pushed_symbols"),
        reconcile_timestamps=True,
    )
    pushed = sorted(pushed_set)
    # 注:不要在此按「无规则/无持仓」自动剔除推送 —— 推送的币默认跟随全局规则、本就无单一规则,
    # 且刚推送未借到时也无持仓,这都是正常态。曾有过的 ghost 对账会误删所有新推送,已移除。
    # 推送时间戳(engine:{uid}:pushed_at,symbol→unix秒)统一在此回填/清理:
    # 覆盖手动 push(API 已记)与引擎自动推送(此处首次见到即补 now);移除的清掉。
    at_key = _user_redis_key(user_id, "pushed_at")
    try:
        at = r.hgetall(at_key) or {}
        # Float Unix seconds preserve sub-second LIFO order and remain
        # backward compatible with historical integer-second values.
        pushed_at = {s: float(at[s]) for s in pushed if s in at}
    except Exception:
        pushed_at = {}
    # Source is presentation metadata, independent from lifecycle status.
    # Namespaced custom candidates are never executable symbols, so preserve
    # their source even when they were inserted by the automatic scanner.
    push_source = {
        symbol: (
            "custom_monitor"
            if is_custom_monitor_candidate(symbol)
            else ("manual" if r.get(manual_push_marker_key(user_id, symbol)) else "auto")
        )
        for symbol in pushed
    }
    paused = sorted(
        str(value).strip().upper()
        for value in (
            r.smembers(_user_redis_key(user_id, "paused_symbols")) or set()
        )
        if str(value).strip()
    )
    return {
        "pushed_symbols": pushed,
        "pushed_at": pushed_at,
        "push_source": push_source,
        "paused_symbols": paused,
    }


@router.post("/push-symbol/{symbol}")
def push_symbol(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    r = _redis()
    if is_custom_monitor_candidate(symbol):
        raise HTTPException(
            status_code=400,
            detail="Custom monitor candidates must use the custom-monitor push endpoint",
        )
    sym = _normalize_usdt_symbol(symbol)
    # 校验:必须是可交易币种(在 symbols 表且 active/margin/futures)且有点差,
    # 否则推送进去也借不了、看不到数据,徒增「无法推送」困惑。
    from app.db.models import Symbol
    s = db.query(Symbol).filter(Symbol.symbol == sym).first()
    if not s or not (s.is_active and s.margin_tradable and s.futures_tradable):
        raise HTTPException(status_code=400, detail=f"{sym} 不可交易(非借币/合约支持的 USDT 交易对)")
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    current, _ = mutate_pushed_symbols(
        r,
        ps_key,
        add={sym},
        manual_marker_key=manual_push_marker_key(user_id, sym),
        mark_manual=True,
    )
    # A manual push explicitly opts this symbol into the single-rule layer.
    # Remove the automatic-global inheritance marker before notifying Workers.
    try:
        r.hdel(auto_global_rules_key(user_id), sym)
    except Exception:
        logger.warning("Unable to clear automatic rule source for manual push %s", sym, exc_info=True)
    if sym not in current:
        raise HTTPException(status_code=503, detail=f"{sym} 推送未写入，请重试")
    key = _user_redis_key(user_id, "push_commands")
    r.rpush(key, json.dumps({"action": "push", "symbol": sym, "source": "manual"}))
    r.expire(key, 120)
    r.delete(f"engine:{user_id}:repayhold:{sym}")
    # Manual push explicitly lifts a previous operator removal suppression.
    r.delete(f"engine:{user_id}:manual_removed:{sym}")
    r.delete(f"engine:{user_id}:removed_cooldown:{sym}")  # 重新推送=显式再武装,清还币暂停标记允许重借
    # 通知前端 dashboard 实时刷新推送列表(经 WS pushed_update)
    r.publish("pushed:updates", json.dumps({"user_id": user_id, "pushed_symbols": sorted(current)}))
    r.publish("balance:refresh", str(user_id))   # 推送后即时刷余额/借币/现币(绕开10s轮询)
    return {
        "message": f"Pushed {sym}",
        "symbol": sym,
        "source": "manual",
        "pushed_symbols": sorted(current),
    }


@router.post("/push-custom-monitor/{monitor_id}")
def push_custom_monitor(
    monitor_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Idempotently add one tenant-owned custom monitor as a display candidate.

    This endpoint intentionally does not enqueue ``push_commands`` or refresh
    account balances.  ``CUSTOM:<id>`` is consumed only by the dashboard and
    is excluded from every Worker execution path.
    """
    user_id = get_current_user_id(request)
    row = db.query(CustomMonitorSymbol).filter(
        CustomMonitorSymbol.id == int(monitor_id),
        CustomMonitorSymbol.user_id == user_id,
    ).first()
    if row is None:
        # Do not reveal whether another tenant owns this id.
        raise HTTPException(status_code=404, detail="Custom monitor not found")
    if not bool(row.is_active) or bool(row.is_removed):
        raise HTTPException(status_code=409, detail="Custom monitor is inactive")

    blocked_reason = custom_monitor_block_reason(db, user_id, row)
    if blocked_reason:
        raise HTTPException(
            status_code=409,
            detail=f"Custom monitor is blocked ({blocked_reason})",
        )

    candidate = custom_monitor_candidate_key(row.id)
    r = _redis()
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    current, changed = mutate_pushed_symbols(
        r,
        ps_key,
        add={candidate},
    )
    if candidate not in current:
        raise HTTPException(status_code=503, detail="Custom monitor push was not persisted")
    try:
        # The prefix is authoritative for readers; this hash is an auditable
        # source index and lets operational tooling distinguish old rows.
        marker_key = custom_monitor_source_key(user_id)
        try:
            r.hset(marker_key, mapping={candidate: str(row.id)})
        except TypeError:
            # Lightweight Redis doubles and older redis-py wrappers expose
            # only the positional ``hset(name, key, value)`` form.
            r.hset(marker_key, candidate, str(row.id))
    except Exception:
        logger.warning("Unable to persist custom monitor source marker %s", candidate, exc_info=True)
    try:
        r.publish(
            "pushed:updates",
            json.dumps({
                "user_id": user_id,
                "pushed_symbols": sorted(current),
                "source": "custom_monitor",
                "custom_monitor_id": int(row.id),
            }),
        )
    except Exception:
        logger.warning("Unable to publish custom monitor push update %s", candidate, exc_info=True)
    return {
        "message": f"Pushed custom monitor {row.id}",
        "symbol": candidate,
        "custom_monitor_id": int(row.id),
        "source": "custom_monitor",
        "changed": bool(changed),
        "pushed_symbols": sorted(current),
    }


@router.get("/paused-symbols")
def get_paused_symbols(request: Request):
    user_id = get_current_user_id(request)
    r = _redis()
    values = r.smembers(_user_redis_key(user_id, "paused_symbols")) or set()
    return {
        "paused_symbols": sorted(
            str(value).strip().upper()
            for value in values
            if str(value).strip()
        )
    }


@router.post("/pause-symbol/{symbol}")
def pause_symbol(symbol: str, request: Request):
    """Pause new inventory and borrow admission without removing the row."""
    user_id = get_current_user_id(request)
    sym = _normalize_usdt_symbol(symbol)
    r = _redis()
    key = _user_redis_key(user_id, "paused_symbols")
    r.sadd(key, sym)
    paused = sorted(str(value).strip().upper() for value in (r.smembers(key) or set()))
    r.publish(
        "pushed:updates",
        json.dumps({"user_id": user_id, "paused_symbols": paused}),
    )
    return {
        "message": f"Paused new orders for {sym}",
        "symbol": sym,
        "paused": True,
        "paused_symbols": paused,
    }


@router.delete("/pause-symbol/{symbol}")
def resume_symbol(symbol: str, request: Request):
    """Resume new inventory and borrow admission for this tenant/symbol."""
    user_id = get_current_user_id(request)
    sym = _normalize_usdt_symbol(symbol)
    r = _redis()
    key = _user_redis_key(user_id, "paused_symbols")
    r.srem(key, sym)
    paused = sorted(
        str(value).strip().upper()
        for value in (r.smembers(key) or set())
        if str(value).strip()
    )
    r.publish(
        "pushed:updates",
        json.dumps({"user_id": user_id, "paused_symbols": paused}),
    )
    return {
        "message": f"Resumed new orders for {sym}",
        "symbol": sym,
        "paused": False,
        "paused_symbols": paused,
    }


def _purge_symbol_rules(db: Session, user_id: int, symbol: str, sub_account_ids: list[int] = None):
    """清除某币的单一规则(SymbolRule + AccountSymbolRule),使再推进来时回归全局默认。
    供 HTTP DELETE 手动移除 & 引擎平仓后自动下架 两条路径复用。"""
    from app.db.models import SymbolRule, AccountSymbolRule
    try:
        db.query(SymbolRule).filter(
            SymbolRule.user_id == user_id, SymbolRule.symbol == symbol,
        ).delete(synchronize_session=False)
        if sub_account_ids:
            account_rule_query = db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id.in_(sub_account_ids),
                AccountSymbolRule.symbol == symbol,
            )
            # Sub-account ids are expected to be globally unique, but this
            # owner predicate is still required for legacy/imported rows: a
            # symbol removal must never delete another user's override.
            if user_id is None:
                account_rule_query = account_rule_query.filter(AccountSymbolRule.user_id.is_(None))
            else:
                account_rule_query = account_rule_query.filter(AccountSymbolRule.user_id == user_id)
            account_rule_query.delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


# 手动还币只允许两个明确的静止状态。所有其它非终态（包括未来新增状态）均失败关闭。
REPAY_SAFE_STATUSES = ("BORROWED_IDLE", "PENDING_REPAY")
REPAY_BLOCKED_STATUSES = (
    "PENDING_BORROW", "BORROW_SUBMITTING", "BORROW_OUTCOME_UNKNOWN",
    "BORROWING", "BORROWED", "HEDGING", "SPOT_SOLD", "OPEN",
    "CLOSING_FUTURES", "FUTURES_CLOSED", "CLOSING_SPOT", "SPOT_BOUGHT", "REPAYING",
)


REPAY_DEBT_EPSILON = Decimal("0.00000001")
REPAY_RETRY_HOLD_SEC = 60
REPAY_RECONCILE_HOLD_SEC = 1800
# ``execute_repay`` claims a row as REPAYING before doing exchange I/O.  A
# crashed process can leave that claim behind, so it must be old enough that
# the shared account-operation lock would have expired before we recover it.
# Keep a margin over the lock TTL: a slow but healthy request must remain
# blocked, while a deployment/process death can be retried by an operator.
REPAYING_STALE_SEC = max(300, ACCOUNT_OPERATION_LOCK_TTL_SEC + 60)
# An OPEN row is an assertion that both hedge legs are still managed by the
# engine.  Only consider reconciling it after a materially longer quiet
# period than the account-operation lock; a live request must never be
# rewritten while its exchange side effects are still settling.
OPEN_RECONCILE_STALE_SEC = max(600, ACCOUNT_OPERATION_LOCK_TTL_SEC + 60)

_REPAY_HEDGE_QTY_FIELDS = (
    "spot_sell_qty", "futures_long_qty", "spot_buy_qty",
)
_REPAY_HEDGE_ORDER_FIELDS = (
    "spot_sell_order_id", "futures_long_order_id",
    "futures_close_order_id", "spot_buy_order_id",
)


def _decimal_or_zero(value) -> Decimal:
    """Convert a nullable model value without allowing malformed legacy data
    to make a safety decision fail open."""
    try:
        result = Decimal(str(value or 0))
        # A non-finite quantity is malformed/unknown data, never an empty
        # hedge leg.  Returning NaN lets callers' ``is_finite`` checks fail
        # closed instead of accidentally treating it as zero.
        return result if result.is_finite() else Decimal("NaN")
    except Exception:
        # A malformed quantity is evidence we cannot prove the legs are flat.
        return Decimal("NaN")


def _repay_db_legs_empty(position: Position) -> bool:
    """Return true only when the position has no recorded hedge legs.

    This is deliberately stricter than checking status alone.  A historical
    ``REPAYING`` row may still contain the opening/closing order ids; those
    rows require an authoritative futures-position check before recovery.
    """
    for field in _REPAY_HEDGE_QTY_FIELDS:
        quantity = _decimal_or_zero(getattr(position, field, None))
        if not quantity.is_finite() or abs(quantity) > REPAY_DEBT_EPSILON:
            return False
    return all(
        not str(getattr(position, field, None) or "").strip()
        for field in _REPAY_HEDGE_ORDER_FIELDS
    )


def _repaying_is_stale(position: Position, now: datetime | None = None) -> bool:
    """Check the persisted claim age; missing timestamps fail closed."""
    if str(getattr(position, "status", "") or "").upper() != "REPAYING":
        return False
    stamp = getattr(position, "updated_at", None) or getattr(position, "created_at", None)
    if not isinstance(stamp, datetime):
        return False
    now = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    try:
        return (now - stamp).total_seconds() >= REPAYING_STALE_SEC
    except (TypeError, ValueError):
        return False


def _restore_stale_repaying_position(
    db: Session,
    position: Position,
    *,
    reason: str,
    user_id: int,
    sub_account_id: int,
    symbol: str,
) -> bool:
    """CAS a stale repayment claim back to the retryable state.

    The endpoint already owns ``account_operation_lock``.  The DB predicate is
    still required because a lock can expire while a previous process is
    unwinding; it prevents us from overwriting a newer state transition.
    """
    old_error = str(getattr(position, "error_message", None) or "").strip()
    detail = f"stale REPAYING recovered: {reason}"
    if old_error and detail not in old_error:
        detail = f"{old_error}; {detail}"
    values = {
        "status": "PENDING_REPAY",
        "closed_at": None,
        "error_message": detail,
        "updated_at": datetime.now(timezone.utc),
    }
    try:
        changed = db.query(Position).filter(
            Position.id == position.id,
            Position.status == "REPAYING",
        ).update(values, synchronize_session=False)
        if not changed:
            db.rollback()
            return False
        db.commit()
        try:
            db.refresh(position)
        except Exception:
            # Lightweight test doubles and detached rows may not implement
            # refresh; the committed CAS remains authoritative.
            pass
        try:
            _redis().publish("position:updates", json.dumps({
                "id": position.id,
                "status": "PENDING_REPAY",
                "symbol": symbol,
                "sub_account_id": sub_account_id,
                "user_id": user_id,
                "error_message": detail,
            }))
        except Exception:
            pass
        return True
    except Exception as exc:
        db.rollback()
        logger.warning(
            "failed to recover stale REPAYING position %s (%s): %s",
            getattr(position, "id", "?"), symbol, exc,
        )
        return False


async def _confirm_exchange_legs_flat(
    margin_client,
    futures_client,
    symbol: str,
    additional_futures_clients=None,
) -> bool:
    """Require authoritative flat reads for both account types.

    A missing method, malformed response, API error, or non-empty order list
    is treated as *not flat*.  This deliberately uses REST only for recovery;
    normal quote/strategy paths remain WS-driven.

    ``REPAYING`` rows can outlive a rolling deployment.  Older Binance client
    instances do not have the newer ``get_*`` safety helpers, so the readers
    below retain a strictly fail-closed compatibility path through the
    existing ``futures_position_risk``/``_request`` methods.  A compatibility
    path may prove an empty response, but it can never turn an error or an
    ambiguous payload into proof that a hedge is flat.
    """
    async def _invoke(reader, *args):
        result = reader(*args)
        # A few rolling-deployment test/compatibility clients expose ordinary
        # functions while the production client exposes coroutines.
        if hasattr(result, "__await__"):
            result = await result
        return result

    def _flat_row(row) -> bool:
        if not isinstance(row, dict):
            return False
        row_symbol = str(row.get("symbol") or "").upper().strip()
        if row_symbol != str(symbol).upper().strip():
            return False
        raw_amount = row.get("positionAmt")
        if raw_amount is None:
            return False
        amount = _decimal_or_zero(raw_amount)
        return amount.is_finite() and abs(amount) <= REPAY_DEBT_EPSILON

    async def _futures_position_flat(client) -> bool:
        if client is None:
            return False
        # Current client: None is the documented result for a valid zero row.
        reader = getattr(client, "get_futures_position", None)
        if callable(reader):
            try:
                payload = await _invoke(reader, symbol)
                if payload is None:
                    return True
                return _flat_row(payload)
            except Exception:
                # Try the legacy reader below.  If it is also unavailable or
                # malformed the caller receives False (unknown), never True.
                pass

        # Pre-recovery clients expose this method and return one position-risk
        # dict (including a zero ``positionAmt``) or None.  None is treated as
        # unknown because a symbol-filtered response should contain a row.
        reader = getattr(client, "futures_position_risk", None)
        if callable(reader):
            try:
                payload = await _invoke(reader, symbol)
                return _flat_row(payload)
            except Exception:
                pass

        # Last compatibility path for lightweight/older clients that only
        # expose the signed request primitive.  Validate every matching row so
        # hedge-mode LONG/SHORT payloads cannot hide a non-zero leg.
        request = getattr(client, "_request", None)
        if callable(request):
            try:
                from engine.trading.binance_trading import FUTURES_BASE
                payload = await _invoke(
                    request, "GET", f"{FUTURES_BASE}/fapi/v2/positionRisk",
                    {"symbol": symbol},
                )
                if not isinstance(payload, list) or not payload:
                    return False
                matched = [row for row in payload if isinstance(row, dict) and
                           str(row.get("symbol") or "").upper().strip() == str(symbol).upper().strip()]
                return bool(matched) and all(_flat_row(row) for row in matched)
            except Exception:
                pass
        return False

    async def _orders_empty(client, *, futures: bool) -> bool:
        if client is None:
            return False
        if futures:
            reader = getattr(client, "get_futures_open_orders", None)
        else:
            reader = getattr(client, "get_margin_open_orders", None)
        if callable(reader):
            try:
                payload = await _invoke(reader, symbol)
                return isinstance(payload, list) and all(
                    isinstance(row, dict) for row in payload
                ) and len(payload) == 0
            except Exception:
                pass

        request = getattr(client, "_request", None)
        if callable(request):
            try:
                from engine.trading.binance_trading import FUTURES_BASE, SPOT_BASE
                url = (
                    f"{FUTURES_BASE}/fapi/v1/openOrders"
                    if futures else f"{SPOT_BASE}/sapi/v1/margin/openOrders"
                )
                payload = await _invoke(request, "GET", url, {"symbol": symbol})
                return isinstance(payload, list) and all(
                    isinstance(row, dict) for row in payload
                ) and len(payload) == 0
            except Exception:
                pass
        return False

    try:
        clients = []
        for candidate in [futures_client, *(additional_futures_clients or [])]:
            if candidate is not None and all(candidate is not seen for seen in clients):
                clients.append(candidate)
        # At least one futures account must be checked; a missing client is an
        # unknown hedge route, not evidence of a flat position.
        if not clients or margin_client is None:
            return False
        for candidate in clients:
            if not await _futures_position_flat(candidate):
                return False
            if not await _orders_empty(candidate, futures=True):
                return False
        return await _orders_empty(margin_client, futures=False)
    except Exception as exc:
        logger.warning("exchange flat check failed for stale repayment %s: %s", symbol, exc)
        return False


async def _recover_stale_repaying_positions(
    db: Session,
    *,
    user_id: int,
    account: SubAccount,
    symbol: str | None = None,
    margin_client=None,
    futures_client=None,
) -> int:
    """Recover only stale ``REPAYING`` rows whose hedge is provably flat.

    Every candidate is checked against Binance before mutation.  Rows carrying
    historical leg fields additionally require the futures position to be
    flat; DB-empty rows still require empty margin/futures order books so a
    hidden order cannot race the subsequent repayment.  Any unavailable or
    positive result is left as REPAYING so the normal 409 guard remains.
    """
    normalized_symbol = (
        _normalize_usdt_symbol(symbol) if symbol is not None else None
    )
    rows = db.query(Position).filter(
        Position.sub_account_id == account.id,
        Position.status == "REPAYING",
    )
    if normalized_symbol is not None:
        rows = rows.filter(Position.symbol == normalized_symbol)
    rows = rows.all()
    if not rows:
        return 0

    recovered = 0
    for position in rows:
        if not _repaying_is_stale(position):
            continue
        position_symbol = _normalize_usdt_symbol(getattr(position, "symbol", ""))
        if not position_symbol or position_symbol == "USDT":
            # A malformed legacy symbol cannot be safely routed to Binance.
            continue
        db_legs_empty = _repay_db_legs_empty(position)
        # ``hedge_account=master`` is persisted per position; global rules may
        # have changed since it was opened, so route futures reads by the row.
        hedge_account = str(
            getattr(position, "hedge_account", None) or ""
        ).strip().lower()
        if hedge_account not in {"", "master", "sub"}:
            logger.warning(
                "stale repayment has invalid hedge route %r for %s#%s; "
                "keeping REPAYING",
                hedge_account,
                position_symbol,
                getattr(position, "id", "?"),
            )
            continue
        from engine.trading.binance_trading import BinanceTradingClient
        try:
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as stack:
                # Worker callers pass their already-open clients; API callers
                # leave them unset and get short-lived safety-read clients.
                active_margin_client = margin_client
                if active_margin_client is None:
                    active_margin_client = await stack.enter_async_context(BinanceTradingClient(
                        account.api_key,
                        account.api_secret,
                        sub_account_id=account.id,
                    ))
                active_futures_client = active_margin_client
                additional_futures_clients = []
                if hedge_account == "master":
                    active_futures_client = futures_client
                    if active_futures_client is None:
                        master = _load_master_account(db, user_id)
                        if not master or not master.api_key or not master.api_secret:
                            continue
                        active_futures_client = await stack.enter_async_context(BinanceTradingClient(
                            master.api_key,
                            master.api_secret,
                            sub_account_id=-(user_id or 1),
                        ))
                elif not hedge_account:
                    # Rows created before ``hedge_account`` was persisted do
                    # not identify which futures account owns the hedge. This
                    # remains ambiguous even when legacy leg fields are empty:
                    # a process may have crashed before recording its first
                    # fill. Never infer the sub-account route, because that
                    # can release a row while a master-account hedge remains
                    # open. Require both possible futures accounts to prove
                    # flat; if the master cannot be read, keep the row blocked
                    # (fail closed).
                    master = _load_master_account(db, user_id)
                    if not master or not master.api_key or not master.api_secret:
                        continue
                    master_client = futures_client
                    if master_client is None:
                        master_client = await stack.enter_async_context(BinanceTradingClient(
                            master.api_key,
                            master.api_secret,
                            sub_account_id=-(user_id or 1),
                        ))
                    additional_futures_clients.append(master_client)
                flat = await _confirm_exchange_legs_flat(
                    active_margin_client,
                    active_futures_client,
                    position_symbol,
                    additional_futures_clients=additional_futures_clients,
                )
        except Exception as exc:
            logger.warning(
                "stale repayment exchange check failed %s#%s: %s",
                position_symbol, getattr(position, "id", "?"), exc,
            )
            flat = False
        if not flat:
            continue
        reason = (
            "DB hedge legs empty; Binance futures position and margin/futures "
            "open orders confirmed flat"
            if db_legs_empty
            else "Binance futures position and margin/futures open orders confirmed flat"
        )
        if _restore_stale_repaying_position(
            db,
            position,
            reason=reason,
            user_id=user_id,
            sub_account_id=account.id,
            symbol=position_symbol,
        ):
            recovered += 1
    return recovered


def _open_position_is_stale(position: Position, now: datetime | None = None) -> bool:
    """Return whether an ``OPEN`` row is old enough for a read-only repair.

    Missing or malformed timestamps fail closed.  This helper intentionally
    does not infer staleness from an exchange response; the age fence is what
    prevents a slow, healthy close request from racing reconciliation.
    """
    if str(getattr(position, "status", "") or "").upper() != "OPEN":
        return False
    stamp = getattr(position, "updated_at", None) or getattr(position, "created_at", None)
    if not isinstance(stamp, datetime):
        return False
    now = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    try:
        return (now - stamp).total_seconds() >= OPEN_RECONCILE_STALE_SEC
    except (TypeError, ValueError):
        return False


async def _read_authoritative_margin_debt(client, base_asset: str) -> Decimal:
    """Read one asset's total cross-margin debt with fail-closed validation.

    Binance omits zero-balance assets from ``userAssets``; a valid list with no
    matching asset therefore proves zero debt.  Any malformed response or
    non-finite/negative number raises so callers never close a row on an
    unknown balance state.
    """
    getter = getattr(client, "get_margin_account", None)
    if not callable(getter):
        raise ValueError("margin account read is unavailable")
    payload = await getter()
    if not isinstance(payload, dict) or not isinstance(payload.get("userAssets"), list):
        raise ValueError("margin account response has no userAssets list")
    wanted = str(base_asset or "").upper().strip()
    if not wanted:
        raise ValueError("position has no base asset")
    for item in payload["userAssets"]:
        if not isinstance(item, dict):
            raise ValueError("margin account row is not an object")
        if str(item.get("asset") or "").upper().strip() != wanted:
            continue
        try:
            borrowed = Decimal(str(item.get("borrowed", "0") or "0"))
            interest = Decimal(str(item.get("interest", "0") or "0"))
        except Exception as exc:
            raise ValueError(f"invalid margin debt for {wanted}") from exc
        if (
            not borrowed.is_finite()
            or not interest.is_finite()
            or borrowed < 0
            or interest < 0
        ):
            raise ValueError(f"invalid margin debt for {wanted}")
        return borrowed + interest
    return Decimal("0")


def _restore_stale_open_position(
    db: Session,
    position: Position,
    *,
    reason: str,
    user_id: int,
    sub_account_id: int,
    symbol: str,
) -> bool:
    """CAS a proven-flat stale OPEN row to CLOSED.

    This is deliberately a terminal *database reconciliation* only.  It is
    used after Binance has already confirmed no hedge/order/debt remains, so
    no exchange mutation is needed and no PnL fields are fabricated.
    """
    detail = f"stale OPEN reconciled: {reason}"
    old_error = str(getattr(position, "error_message", None) or "").strip()
    if old_error and detail not in old_error:
        detail = f"{old_error}; {detail}"
    values = {
        "status": "CLOSED",
        "closed_at": datetime.now(timezone.utc),
        "error_message": detail,
        "updated_at": datetime.now(timezone.utc),
    }
    try:
        changed = db.query(Position).filter(
            Position.id == position.id,
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
            Position.status == "OPEN",
        ).update(values, synchronize_session=False)
        if not changed:
            db.rollback()
            return False
        db.commit()
        try:
            db.refresh(position)
        except Exception:
            pass
        try:
            _redis().publish("position:updates", json.dumps({
                "id": position.id,
                "status": "CLOSED",
                "symbol": symbol,
                "sub_account_id": sub_account_id,
                "user_id": user_id,
                "error_message": detail,
            }))
            _redis().publish("balance:refresh", str(user_id))
        except Exception:
            pass
        return True
    except Exception as exc:
        db.rollback()
        logger.warning(
            "failed to reconcile stale OPEN position %s (%s): %s",
            getattr(position, "id", "?"), symbol, exc,
        )
        return False


async def _recover_stale_open_positions(
    db: Session,
    *,
    user_id: int,
    account: SubAccount,
    symbol: str | None = None,
    margin_client=None,
    futures_client=None,
) -> int:
    """Close only stale OPEN rows proven flat by authoritative read-only checks.

    The helper intentionally handles *zero debt only*.  If Binance still owes
    the asset, the row may represent a naked spot short and requires an
    explicit buy-back/repay workflow; silently marking it closed would hide
    real exposure.  Query failures, malformed responses, non-flat positions,
    or any open order all leave the row untouched.
    """
    normalized_symbol = _normalize_usdt_symbol(symbol) if symbol is not None else None
    rows = db.query(Position).filter(
        Position.sub_account_id == account.id,
        Position.status == "OPEN",
    )
    if normalized_symbol is not None:
        rows = rows.filter(Position.symbol == normalized_symbol)
    rows = rows.all()
    if not rows:
        return 0

    recovered = 0
    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient

    # Reuse caller-owned clients (Worker path); API callers get short-lived
    # read-only clients.  A master hedge is routed by the persisted position
    # ownership, never by the current global setting.
    for position in rows:
        if not _open_position_is_stale(position):
            continue
        position_symbol = _normalize_usdt_symbol(getattr(position, "symbol", ""))
        base_asset = str(getattr(position, "base_asset", "") or "").upper().strip()
        if not position_symbol or position_symbol == "USDT" or not base_asset:
            continue
        hedge_account = str(
            getattr(position, "hedge_account", None) or ""
        ).strip().lower()
        if hedge_account not in {"", "master", "sub"}:
            logger.warning(
                "stale OPEN has invalid hedge route %r for %s#%s; keeping OPEN",
                hedge_account,
                position_symbol,
                getattr(position, "id", "?"),
            )
            continue
        try:
            async with AsyncExitStack() as stack:
                active_margin_client = margin_client
                if active_margin_client is None:
                    active_margin_client = await stack.enter_async_context(BinanceTradingClient(
                        account.api_key,
                        account.api_secret,
                        sub_account_id=account.id,
                    ))
                active_futures_client = active_margin_client
                additional_futures_clients = []
                if hedge_account == "master":
                    active_futures_client = futures_client
                    if active_futures_client is None:
                        master = _load_master_account(db, user_id)
                        if not master or not master.api_key or not master.api_secret:
                            continue
                        active_futures_client = await stack.enter_async_context(BinanceTradingClient(
                            master.api_key,
                            master.api_secret,
                            sub_account_id=-(user_id or 1),
                        ))
                elif hedge_account == "":
                    # Legacy OPEN rows without a persisted route are ambiguous.
                    # Prove both possible futures accounts are flat before
                    # closing the database row; otherwise a master hedge could
                    # be hidden by the sub-account read.
                    master = _load_master_account(db, user_id)
                    if not master or not master.api_key or not master.api_secret:
                        continue
                    master_client = futures_client
                    if master_client is None:
                        master_client = await stack.enter_async_context(BinanceTradingClient(
                            master.api_key,
                            master.api_secret,
                            sub_account_id=-(user_id or 1),
                        ))
                    additional_futures_clients.append(master_client)
                if not await _confirm_exchange_legs_flat(
                    active_margin_client,
                    active_futures_client,
                    position_symbol,
                    additional_futures_clients=additional_futures_clients,
                ):
                    continue
                debt = await _read_authoritative_margin_debt(
                    active_margin_client, base_asset,
                )
                if debt > REPAY_DEBT_EPSILON:
                    # A flat futures leg with outstanding margin debt is a
                    # naked short, not a harmless stale row.  Keep OPEN.
                    continue
        except Exception as exc:
            logger.warning(
                "stale OPEN exchange check failed %s#%s: %s",
                position_symbol, getattr(position, "id", "?"), exc,
            )
            continue
        reason = (
            "Binance futures position flat; futures and margin open orders "
            "empty; margin debt confirmed zero"
        )
        if _restore_stale_open_position(
            db,
            position,
            reason=reason,
            user_id=user_id,
            sub_account_id=account.id,
            symbol=position_symbol,
        ):
            recovered += 1
    return recovered


async def _auto_close_open_positions_for_repay(
    db: Session,
    *,
    user_id: int,
    account: SubAccount,
    symbol: str,
) -> tuple[int, list[str]]:
    """Explicitly close OPEN rows before a full repayment request.

    ``partial_repay`` historically rejected every OPEN row because blindly
    buying back spot and repaying can strand the futures hedge.  A user who
    explicitly chooses the full-repay action may instead request this narrow,
    risk-reducing sequence: spot buy-back -> futures close -> repay.  The
    persisted ``hedge_account`` is the only routing authority.  Missing or
    unknown routes, failed exchange calls, and any non-terminal state are
    returned to the caller and remain blocked; this helper never fabricates a
    CLOSED row.
    """
    normalized_symbol = _normalize_usdt_symbol(symbol)
    rows = db.query(Position).filter(
        Position.sub_account_id == account.id,
        Position.symbol == normalized_symbol,
        Position.status == "OPEN",
    ).all()
    if not rows:
        return 0, []

    from contextlib import AsyncExitStack
    from engine.spread_feed import SpreadSnapshot
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_close
    from engine.notify.feishu_sender import FeishuSender

    closed = 0
    unresolved: list[str] = []
    routed_rows: list[tuple[Position, str]] = []
    for row in sorted(rows, key=lambda item: int(getattr(item, "id", 0) or 0)):
        route = str(getattr(row, "hedge_account", None) or "").strip().lower()
        if route not in {"sub", "master"}:
            unresolved.append(
                f"#{getattr(row, 'id', '?')} hedge_account 缺失/未知，未自动平仓"
            )
            continue
        routed_rows.append((row, route))
    if not routed_rows:
        return 0, unresolved

    account_note = getattr(account, "note", None) or f"#{account.id}"
    notifier = FeishuSender()

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(BinanceTradingClient(
            account.api_key,
            account.api_secret,
            sub_account_id=account.id,
        ))
        master_client = None
        master_checked = False

        for row, route in routed_rows:
            futures_client = None
            if route == "master":
                if master_client is None:
                    master = _load_master_account(db, user_id)
                    if not master or not master.api_key or not master.api_secret:
                        unresolved.append(
                            f"#{getattr(row, 'id', '?')} 主账户合约密钥未配置，未自动平仓"
                        )
                        continue
                    master_client = await stack.enter_async_context(BinanceTradingClient(
                        master.api_key,
                        master.api_secret,
                        sub_account_id=-(user_id or 1),
                    ))
                if not master_checked:
                    await _assert_master_one_way(master_client)
                    master_checked = True
                futures_client = master_client

            try:
                spread = _build_spread_snapshot(normalized_symbol)
            except Exception:
                spread = None
            if not spread:
                # Emergency market close does not use quote prices.  The
                # zero snapshot is only for bookkeeping; exchange fills are
                # still confirmed by execute_unhedge/execute_repay.
                zero = Decimal("0")
                spread = SpreadSnapshot(
                    normalized_symbol,
                    zero, zero, zero, zero, zero, zero, 0,
                )
            try:
                lock_context = _account_operation_lock_context.get()
                await execute_close(
                    row,
                    spread,
                    client,
                    notifier,
                    account_note,
                    futures_client=futures_client,
                    spot_order_mode="market",
                    allow_emergency_close=True,
                    user_id=user_id,
                    operation_lock_redis=(lock_context[0] if lock_context else None),
                    operation_lock_token=(lock_context[1] if lock_context else None),
                )
            except Exception as exc:
                unresolved.append(
                    f"#{getattr(row, 'id', '?')} 自动平仓异常: {str(exc)[:160]}"
                )
                continue

            # execute_close owns a separate DB session.  Expire this endpoint's
            # identity map before observing its committed status.
            try:
                db.expire_all()
            except Exception:
                pass
            fresh = db.query(Position).filter(Position.id == row.id).first()
            status = str(getattr(fresh, "status", "") or "").upper()
            if status == "CLOSED":
                closed += 1
            elif status in REPAY_SAFE_STATUSES:
                # The hedge is gone; execute_repay may have deferred only on
                # a settlement/debt read.  The outer repayment path can retry.
                continue
            else:
                unresolved.append(
                    f"#{getattr(row, 'id', '?')} 平仓后状态仍为 {status or '未知'}"
                )

    return closed, unresolved


def _set_repay_hold(user_id: int, symbol: str, ttl_sec: int) -> None:
    """Arm the post-repay opening fence, failing closed if Redis cannot write it."""
    normalized = _normalize_usdt_symbol(symbol)
    try:
        written = _redis().set(
            f"engine:{user_id}:repayhold:{normalized}",
            "1",
            ex=max(1, int(ttl_sec)),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{normalized} 还币状态保护写入失败；本次资金操作结果需人工复核，"
                "系统未报告为完成"
            ),
        ) from exc
    if written is False:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{normalized} 还币状态保护未生效；本次资金操作结果需人工复核，"
                "系统未报告为完成"
            ),
        )


def _release_account_operation_lock(redis_client, key: str, token: str) -> None:
    # Never fall back to GET followed by DEL: a replacement owner can acquire
    # the lease between those commands and be deleted by this stale request.
    # Redis TTL expiry is the safe fallback when EVAL is unavailable/fails.
    eval_fn = getattr(redis_client, "eval", None)
    if not callable(eval_fn):
        logger.warning(
            "Cannot release account operation lock %s without atomic EVAL; leaving it for TTL expiry",
            key,
        )
        return
    try:
        eval_fn(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1, key, token,
        )
    except Exception:
        logger.warning(
            "Failed to atomically release account operation lock %s; leaving it for TTL expiry",
            key,
            exc_info=True,
        )


@asynccontextmanager
async def _account_operation_guard(
    sub_account_id: int,
    symbol: str,
    *,
    owner: str,
    user_id: int | None = None,
):
    """Acquire account and tenant-symbol leases for an HTTP operation."""
    normalized = _normalize_usdt_symbol(symbol)
    try:
        lock_redis = _redis()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="交易协调服务不可用，为避免重复借还币，本次操作已中止",
        ) from exc

    try:
        async with account_operation_lock(
            lock_redis,
            sub_account_id,
            normalized,
            owner=owner,
            ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
        ) as lock_token:
            # Keep legacy/unowned rows out of a shared ``None`` tenant bucket.
            # User-scoped operations hold a second lease so sibling
            # sub-accounts cannot submit concurrent commands against a shared
            # one-way master futures position.
            if user_id is None:
                yield lock_redis, lock_token
            else:
                async with master_symbol_lock(
                    lock_redis,
                    user_id,
                    normalized,
                    owner=f"{owner}:master",
                    ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
                ):
                    # Preserve the existing two-item account-lock tuple; the
                    # master lease is held by this context for its full
                    # lifetime and needs no separate Binance callback token.
                    yield lock_redis, lock_token
    except AccountOperationLockBusy as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{normalized} 在子账户 #{sub_account_id} 正由其它借币、对冲、"
                "平仓或还币任务处理，请稍后重试"
            ),
        ) from exc
    except AccountOperationLockUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="交易协调服务不可用，为避免并发资金操作，本次操作已中止",
        ) from exc


def _serialize_account_operation(handler):
    """Fail closed when a Worker owns this account/asset lifecycle."""
    @wraps(handler)
    async def wrapped(data, request, db=Depends(get_db)):
        user_id = get_current_user_id(request)
        symbol = _normalize_usdt_symbol(data.symbol)
        async with _account_operation_guard(
            data.sub_account_id,
            symbol,
            owner=f"{handler.__name__}:{user_id}:{data.sub_account_id}",
            user_id=user_id,
        ) as operation_lock:
            context_token = _account_operation_lock_context.set(operation_lock)
            try:
                _bind_request_operation_lock(request, operation_lock)
                return await handler(data, request, db)
            finally:
                _account_operation_lock_context.reset(context_token)

    return wrapped


def _serialize_position_operation(handler):
    """Resolve a position, then serialize its account/asset before rechecking it."""
    @wraps(handler)
    async def wrapped(data, request, db=Depends(get_db)):
        user_id = get_current_user_id(request)
        position = db.query(Position).filter(
            Position.id == data.position_id,
            Position.user_id == user_id,
        ).first()
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        async with _account_operation_guard(
            position.sub_account_id,
            position.symbol,
            owner=f"{handler.__name__}:{user_id}:{position.id}",
            user_id=user_id,
        ) as operation_lock:
            context_token = _account_operation_lock_context.set(operation_lock)
            try:
                _bind_request_operation_lock(request, operation_lock)
                # The status may have changed between the initial lookup and
                # lock acquisition. Endpoint guards below must observe the
                # locked value.
                db.refresh(position)
                return await handler(data, request, db)
            finally:
                _account_operation_lock_context.reset(context_token)

    return wrapped


def _reconcile_positions_after_repay(
    db: Session,
    user_id: int,
    sub_account_id: int,
    symbol: str,
    repay_qty: Decimal,
    remaining_debt: Decimal = Decimal("0"),
) -> bool:
    """手动还币(/partial-repay)后收口 position 状态:把该子账户该币「无对冲腿」的 position 置 CLOSED
    (否则 BORROWED_IDLE 等永久卡「待对冲」状态孤儿)。
    ⚠只做持仓收口,不下架 pushed、不清规则、也不再写还币暂停标记 —— 「挂单开着=持续借」
    是策略语义,还币后是否暂停自动借币由还币端点按用户勾选(pause_borrow)决定,不在此隐式改变。
    失败回滚不阻断还币主流程。

    只收口 REPAY_SAFE_STATUSES(币在手/待还,无合约腿):绝不抹 OPEN/HEDGING/SPOT_SOLD 等
    对冲在场态 —— 此前 notin_(CLOSED,FAILED) 一刀切,把 OPEN 也标成 CLOSED,主账户合约腿
    就此脱管成永久孤儿(FIL 0.1 合约残留的根因)。对冲在场的还币已被 partial_repay 守卫拦截,
    这里是第二道防线(债务=0 早退路径也会进来)。"""
    if remaining_debt > REPAY_DEBT_EPSILON:
        return False

    from datetime import datetime as _dt, timezone as _tz
    try:
        active = db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
            Position.status.in_(list(REPAY_SAFE_STATUSES)),
        ).all()
        if not active:
            return True
        now = _dt.now(_tz.utc)
        ordered = sorted(active, key=lambda position: int(position.id or 0))
        closed_ids = [p.id for p in ordered]

        # Binance debt is account/asset scoped while Position repayment is row
        # scoped. Allocate this request's accepted quantity exactly once across
        # the safe rows: unrepaid tracked principal first (FIFO by id), with the
        # final row carrying interest and rounding residue. Existing cumulative
        # repay_qty values are preserved and incremented.
        accepted = Decimal(str(repay_qty or 0))
        if not accepted.is_finite() or accepted < 0:
            return False
        remaining = accepted
        allocations: list[tuple[Position, Decimal, Decimal]] = []
        for index, position in enumerate(ordered):
            already_repaid = _decimal_or_zero(getattr(position, "repay_qty", None))
            if not already_repaid.is_finite() or already_repaid < 0:
                return False
            if index == len(ordered) - 1:
                allocated = remaining
            else:
                tracked_principal = _decimal_or_zero(
                    getattr(position, "borrow_qty", None)
                )
                if not tracked_principal.is_finite() or tracked_principal < 0:
                    tracked_principal = Decimal("0")
                outstanding_principal = max(
                    Decimal("0"), tracked_principal - already_repaid
                )
                allocated = min(remaining, outstanding_principal)
            allocations.append((position, already_repaid, allocated))
            remaining -= allocated

        for p, already_repaid, allocated in allocations:
            p.status = "CLOSED"
            if allocated > 0:
                p.repay_qty = already_repaid + allocated
            p.closed_at = now
            p.error_message = None
        db.commit()
        # 发 position:updates(CLOSED)→ 前端 ws:position 即时删该持仓行(整行所有列一起消失),
        # 否则行要等 30s 兜底轮询才掉,期间 风险/保证金/经济参数 等整行级列残留旧值。
        try:
            rp = _redis()
            for pid in closed_ids:
                rp.publish("position:updates", json.dumps({
                    "id": pid, "status": "CLOSED", "symbol": symbol,
                    "sub_account_id": sub_account_id, "user_id": user_id,
                }))
        except Exception:
            pass
        return True
    except Exception as e:
        db.rollback()
        logger.warning(f"reconcile positions after repay failed ({symbol}): {e}")
        return False


def _publish_manual_repay_position_update(
    position: Position,
    user_id: int,
    sub_account_id: int,
    symbol: str,
) -> None:
    """Publish the fields changed by the manual repay state transition."""
    try:
        _redis().publish("position:updates", json.dumps({
            "id": position.id,
            "status": position.status,
            "symbol": symbol,
            "sub_account_id": sub_account_id,
            "user_id": user_id,
            "borrow_qty": (
                str(position.borrow_qty)
                if getattr(position, "borrow_qty", None) is not None
                else None
            ),
            "repay_qty": (
                str(position.repay_qty)
                if getattr(position, "repay_qty", None) is not None
                else None
            ),
            "error_message": getattr(position, "error_message", None),
            "updated_at": (
                position.updated_at.isoformat()
                if getattr(position, "updated_at", None) is not None
                else None
            ),
        }))
    except Exception:
        # REST polling and balance:refresh remain the fallback. A websocket
        # publish failure must not alter the exchange/DB reconciliation result.
        pass


def _stage_borrowed_idle_positions_for_repay(
    db: Session,
    positions: list[Position],
    user_id: int,
    sub_account_id: int,
    symbol: str,
) -> bool:
    """Move unhedged borrowed positions out of the hedgeable state first.

    This commit is deliberately before the Binance mutation. If the API
    process exits after Binance accepts a repayment but before the post-check,
    the Worker can only continue through PENDING_REPAY; it cannot sell spot
    using the stale pre-repayment ``borrow_qty``.
    """
    if not positions:
        return True
    try:
        if any(position.status != "BORROWED_IDLE" for position in positions):
            db.rollback()
            return False
        for position in positions:
            position.status = "PENDING_REPAY"
            position.error_message = "manual repayment awaiting Binance reconciliation"
        db.commit()
        for position in positions:
            _publish_manual_repay_position_update(
                position, user_id, sub_account_id, symbol,
            )
        return True
    except Exception as exc:
        db.rollback()
        logger.warning(
            "failed to stage BORROWED_IDLE positions for manual repay (%s acct %s): %s",
            symbol, sub_account_id, exc,
        )
        return False


def _reconcile_borrowed_idle_after_partial_repay(
    db: Session,
    user_id: int,
    sub_account_id: int,
    symbol: str,
    position_id: int,
    remaining_principal: Decimal,
    remaining_interest: Decimal,
) -> bool:
    """Restore one staged idle position from an authoritative Binance snapshot.

    ``borrow_qty`` represents principal, not principal plus accrued interest.
    The principal delta is accumulated into ``repay_qty``. Replaying the same
    snapshot is idempotent because a second pass observes a zero delta.
    """
    principal = Decimal(str(remaining_principal))
    interest = Decimal(str(remaining_interest))
    if (
        principal <= REPAY_DEBT_EPSILON
        or interest < Decimal("0")
        or principal + interest <= REPAY_DEBT_EPSILON
    ):
        # An interest-only tail must remain PENDING_REPAY. Restoring an idle
        # position with zero hedge quantity would let the lifecycle close with
        # debt still present.
        return False

    try:
        position = db.query(Position).filter(
            Position.id == position_id,
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
        ).first()
        if not position:
            return False

        current_principal = Decimal(str(position.borrow_qty or 0))
        if position.status == "BORROWED_IDLE":
            return abs(current_principal - principal) <= REPAY_DEBT_EPSILON
        if position.status != "PENDING_REPAY":
            return False
        if principal > current_principal + REPAY_DEBT_EPSILON:
            # A repayment reconciliation may only preserve or reduce the
            # Position-owned principal.  Growing it here would silently assign
            # an external/concurrent Binance borrow to this strategy row and
            # let the Worker later sell more spot than this position borrowed.
            return False

        repaid_principal = max(Decimal("0"), current_principal - principal)
        position.borrow_qty = principal
        if repaid_principal > REPAY_DEBT_EPSILON:
            position.repay_qty = (
                Decimal(str(position.repay_qty or 0)) + repaid_principal
            )
        position.status = "BORROWED_IDLE"
        position.closed_at = None
        position.error_message = None
        db.commit()
        _publish_manual_repay_position_update(
            position, user_id, sub_account_id, symbol,
        )
        return True
    except Exception as exc:
        db.rollback()
        logger.warning(
            "failed to reconcile BORROWED_IDLE partial repay (%s pos %s): %s",
            symbol, position_id, exc,
        )
        return False


@router.delete("/push-symbol/{symbol}")
async def remove_pushed_symbol(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    custom_id = custom_monitor_id_from_candidate(symbol)
    if custom_id is not None:
        row = db.query(CustomMonitorSymbol).filter(
            CustomMonitorSymbol.id == custom_id,
            CustomMonitorSymbol.user_id == user_id,
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Custom monitor not found")
        candidate = custom_monitor_candidate_key(custom_id)
        r = _redis()
        current, _ = mutate_pushed_symbols(
            r,
            _user_redis_key(user_id, "pushed_symbols"),
            remove={candidate},
        )
        try:
            r.hdel(custom_monitor_source_key(user_id), candidate)
        except Exception:
            logger.debug("Unable to clear custom monitor source marker %s", candidate, exc_info=True)
        r.publish("pushed:updates", json.dumps({
            "user_id": user_id,
            "pushed_symbols": sorted(current),
            "removed_symbol": candidate,
            "source": "custom_monitor",
        }))
        return {"message": f"Removed {candidate}", "symbol": candidate, "source": "custom_monitor"}
    sym = _normalize_usdt_symbol(symbol)
    sub_ids = [s.id for s in db.query(SubAccount.id).filter(SubAccount.user_id == user_id).all()]
    if sub_ids:
        # 有对冲敞口/正在对冲平仓的状态才拦移除(必须先正常平仓);
        # BORROWED_IDLE(纯借币未对冲,净平无方向敞口)不拦 —— 下方还债块会还清借币并收口该 position,
        # 消除"借了没对冲想移除却撞 409、移除后又留待对冲孤儿"的两难(用户实测 FIL 场景)。
        active_count = db.query(Position).filter(
            Position.sub_account_id.in_(sub_ids),
            Position.symbol == sym,
            Position.status.notin_(("CLOSED", "FAILED", *REPAY_SAFE_STATUSES)),
        ).count()
        if active_count > 0:
            raise HTTPException(status_code=409, detail=f"无法移除 {sym}：仍有 {active_count} 个对冲持仓,请先平仓")

    # ── 防裸空竞态(用户实测 FIL 根因):先切断引擎对该币的借币源,再还债清残 ──
    # 命门:移除在"还债/卖现货残留"期间,引擎主循环仍对同账户同币借币(该币还在 pushed_symbols
    # 直到本函数末尾才摘除),两方无锁并发 → 残留清扫误卖掉引擎并发新借的现货 → 裸空。
    # 故把"摘 pushed + 写 repayhold(worker 见此键即跳过该币不借)"提到还债之前,先关水龙头。
    try:
        _r0 = _redis()
        _ps0 = _user_redis_key(user_id, "pushed_symbols")
        _cur0, _ = mutate_pushed_symbols(
            _r0,
            _ps0,
            remove={sym},
            manual_marker_key=manual_push_marker_key(user_id, sym),
            clear_manual=True,
        )
        try:
            _r0.hdel(auto_global_rules_key(user_id), sym)
        except Exception:
            logger.warning("Unable to clear automatic rule source for removal %s", sym, exc_info=True)
        _r0.set(f"engine:{user_id}:repayhold:{sym}", "1", ex=1800)
        # Keep explicit removal ahead of auto-push even when the configured
        # lifecycle cooldown is disabled. A later manual push clears this key.
        _r0.set(f"engine:{user_id}:manual_removed:{sym}", "1")  # 阻断移除期间自动重借
        _r0.srem(_user_redis_key(user_id, "paused_symbols"), sym)
        _r0.publish("pushed:updates", json.dumps({
            "user_id": user_id,
            "pushed_symbols": sorted(_cur0),
            "removed_symbol": sym,
        }))
    except Exception as _pe:
        logger.error(f"remove {sym}: 预摘除失败,中止还债清理: {_pe}")
        raise HTTPException(
            status_code=503,
            detail=f"无法安全移除 {sym}：交易闸关闭失败，请重试",
        ) from _pe

    # 移除前还清该 symbol 在所有子账户的杠杆账户残留借贷(粉尘/利息),
    # 防止移除后前端"现币/借币"列仍显示残余数据(币安那边债务未清)。
    # 每个账户必须在同一账户/币种锁内完成还币并复核 Binance 实时债务。
    # 任一账户失败时保持交易闸关闭，但不再把清债或 Position 收口报告为成功。
    cleanup_errors: list[str] = []
    try:
        from engine.trading.binance_trading import BinanceTradingClient
        from engine.trading.order_executor import execute_borrow_only_repay, _get_asset_debt
        from engine.notify.feishu_sender import FeishuSender
        base_asset = sym.replace("USDT", "")
        notifier = FeishuSender()
        for sub_id in sub_ids:
            account = db.query(SubAccount).filter(SubAccount.id == sub_id).first()
            if not account:
                continue
            lock_redis = _redis()
            lock_key = account_operation_lock_key(sub_id, sym)
            lock_token = f"remove:{user_id}:{sub_id}:{time.time_ns()}"
            try:
                try:
                    acquired = lock_redis.set(
                        lock_key, lock_token, nx=True,
                        ex=ACCOUNT_OPERATION_LOCK_TTL_SEC,
                    )
                except Exception as lock_error:
                    raise RuntimeError(f"交易协调锁不可用: {lock_error}") from lock_error
                if not acquired:
                    raise RuntimeError("账户正在执行借币、对冲或还币")

                async with BinanceTradingClient(
                    account.api_key, account.api_secret, sub_account_id=sub_id
                ) as client:
                    debt, _ = await _get_asset_debt(client, base_asset)
                    repaid_qty = debt
                    if debt > REPAY_DEBT_EPSILON:
                        completed = await execute_borrow_only_repay(
                            sub_id, sym, client, notifier,
                            account.note or f"#{sub_id}", user_id=user_id,
                        )
                        if not completed:
                            raise RuntimeError("Binance 未确认借币债务归零")

                    debt_after, _ = await _get_asset_debt(client, base_asset)
                    if debt_after > REPAY_DEBT_EPSILON:
                        raise RuntimeError(f"仍有尾债 {debt_after} {base_asset}")

                    # Do not sell arbitrary free assets while removing a pair.
                    # Their provenance cannot be proven here; they may be user
                    # deposits or inventory owned by another strategy.
                    if not _reconcile_positions_after_repay(
                        db, user_id, sub_id, sym, Decimal(str(repaid_qty)),
                        Decimal(str(debt_after)),
                    ):
                        raise RuntimeError("债务已清，但持仓状态收口失败")
            except Exception as _re:
                cleanup_errors.append(f"{account.note or f'#{sub_id}'}: {_re}")
                logger.warning(f"remove {sym} sub{sub_id}: repay residual failed: {_re}")
            finally:
                _release_account_operation_lock(lock_redis, lock_key, lock_token)
    except Exception as _outer:
        cleanup_errors.append(str(_outer))
        logger.warning(f"remove {sym}: residual repay block failed: {_outer}")

    if cleanup_errors:
        try:
            _redis().publish("balance:refresh", str(user_id))
        except Exception:
            pass
        raise HTTPException(
            status_code=409,
            detail=(
                f"{sym} 已停止新借币，但清债未完成，未删除规则："
                + "; ".join(cleanup_errors)
            ),
        )

    r = _redis()
    key = _user_redis_key(user_id, "push_commands")
    r.rpush(key, json.dumps({"action": "remove", "symbol": sym}))
    r.expire(key, 120)
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    current, _ = mutate_pushed_symbols(
        r,
        ps_key,
        remove={sym},
        manual_marker_key=manual_push_marker_key(user_id, sym),
        clear_manual=True,
    )
    r.srem(_user_redis_key(user_id, "paused_symbols"), sym)
    r.set(f"engine:{user_id}:manual_removed:{sym}", "1")
    r.set(f"engine:{user_id}:manual_removed:{sym}", "1")
    try:
        r.hdel(auto_global_rules_key(user_id), sym)
    except Exception:
        logger.warning("Unable to clear automatic rule source for removal %s", sym, exc_info=True)
    r.publish("pushed:updates", json.dumps({
        "user_id": user_id,
        "pushed_symbols": sorted(current),
        "removed_symbol": sym,
    }))

    # 移除即清该币的单一规则覆盖(SymbolRule + AccountSymbolRule)→ 再推进来回归全局参数。
    _purge_symbol_rules(db, user_id, sym, sub_ids)
    r.publish("balance:refresh", str(user_id))   # 移除+还债后即时刷余额/借币/现币(绕开10s轮询)
    return {"message": f"Removed {sym}"}


async def _sell_residual_spot(client, symbol_upper: str, base_asset: str, qty: float) -> tuple[float, str]:
    """把杠杆户里的 base_asset 现币残留市价卖回 USDT。
    权威实现在 engine.trading.order_executor.sell_residual_spot；这里只供用户显式「卖回」
    和本次补买可证明超额的清理流程使用。调用方须保证债务已清且无其它非终态持仓。"""
    from engine.trading.order_executor import sell_residual_spot
    sold, note = await sell_residual_spot(client, symbol_upper, base_asset, qty)
    return float(sold), note


async def _dust_residual_to_bnb(
    client, base_asset: str, qty: float, *, pre_submit_guard=None,
) -> tuple[bool, str]:
    """Convert an already-proven whole margin residual through margin/dust."""
    from decimal import Decimal as _D
    q = _D(str(qty))
    if q <= 0:
        return False, "残留过小无法处理"
    from engine.fund.residual_conversion import (
        ResidualConversionError,
        convert_margin_residual_to_bnb,
    )
    try:
        result = await convert_margin_residual_to_bnb(
            client, base_asset, q, pre_submit_guard=pre_submit_guard,
        )
    except ResidualConversionError as exc:
        return False, str(exc)
    conversion = result.get("conversion") or {}
    tx = conversion.get("tranId") or conversion.get("transId")
    return True, f"{base_asset} 已通过全仓小额兑换转为 BNB" + (f" (tranId={tx})" if tx else "")


class PartialRepayRequest(BaseModel):
    sub_account_id: int
    symbol: str
    # 还币数量(币)。与 amount_usdt 二选一:数量>0 按数量还;否则看金额。
    amount: Decimal = Decimal("0")
    # 还币金额(USDT):后端按现价(REST ticker,回退 Redis spreads)换算成币数量再还。
    # 换算放后端 = 单一权威价格源,避免前端过期价把金额算错。
    amount_usdt: Decimal | None = None
    # 前端「卖回」按钮:债务为 0 但杠杆户仍有现币残留时,显式请求把残留市价卖回 USDT。
    # 默认 False 保持旧行为(仅同步持仓状态),防其它调用方误触发卖出。
    sell_residual: bool = False
    # “全部还”由服务端以实时债务为准，并在成功后再次核对 Binance 债务。
    # 不能依赖前端快照金额，否则请求途中新增的利息会形成不可见尾债。
    repay_all: bool = False
    # Explicit operator consent to close OPEN hedge rows before repaying.
    # Keep this separate from ``repay_all`` so older API callers cannot start
    # exchange orders merely by asking for a full debt amount.
    auto_close: bool = False
    # 还币后暂停该币自动借币 30 分钟(前端勾选,默认不勾)。不勾且挂单差为负 → 还完立即重借
    # 是设计行为(挂单开着=持续借);勾选才写 repayhold 标记,状态列可见可点击解除。
    pause_borrow: bool = False


class ResidualDustRequest(BaseModel):
    """Explicit operator request for a proven sub-minimum residual."""

    sub_account_id: int
    symbol: str


@router.get("/residual-proof")
async def residual_proof(
    request: Request,
    sub_account_id: int = Query(..., ge=1),
    symbol: str = Query(..., min_length=2, max_length=30),
    db: Session = Depends(get_db),
):
    """Return a read-only residual ownership/skip diagnosis.

    The response combines database provenance with a fresh Binance balance
    snapshot.  It never acquires an operation lock and never submits a
    transfer/order/conversion request, so it is safe to use while an account
    is being investigated after the old ``dust conversion disabled`` message.
    """
    user_id = get_current_user_id(request)
    normalized = _normalize_usdt_symbol(symbol)
    if not normalized or normalized == "USDT":
        raise HTTPException(status_code=422, detail="Invalid USDT symbol")
    account = db.query(SubAccount).filter(
        SubAccount.id == sub_account_id,
        SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.fund.residual_dust import (
        DUST_USDT_THRESHOLD,
        EPSILON as RESIDUAL_EPSILON,
        decimal as residual_decimal,
        residual_proof_for_position,
        validate_dust_conversion,
    )

    rows = db.query(Position).filter(Position.sub_account_id == account.id).all()
    matching = [row for row in (rows or []) if _position_matches_symbol(row, normalized)]
    row_proofs = [residual_proof_for_position(row) for row in matching]
    active_count = sum(
        1 for row in matching
        if not is_terminal_position_status(getattr(row, "status", ""))
    )
    proven = sum(
        residual_decimal(item.get("proven_qty")) for item in row_proofs
    )
    base_asset = normalized.removesuffix("USDT")
    result: dict = {
        "sub_account_id": sub_account_id,
        "symbol": normalized,
        "asset": base_asset,
        "positions": row_proofs,
        "active_position_count": active_count,
        "proven_qty": str(proven),
        "margin_free": None,
        "debt": None,
        "spot_free": None,
        "spot_locked": None,
        "spot_same_asset": False,
        "price": None,
        "notional": None,
        "dust_eligible": None,
        "dust_asset": None,
        "decision": "blocked",
        "skip_reason": "active_position" if active_count else (
            "residual_provenance_missing" if proven <= RESIDUAL_EPSILON else "awaiting_binance_snapshot"
        ),
    }

    # There is no safe asset-level diagnosis to perform when ownership is
    # already disproved by the DB.  Returning here also avoids needless
    # Binance calls for active positions and legacy rows with no provenance.
    if active_count or proven <= RESIDUAL_EPSILON:
        return result

    # Binance reads are best-effort diagnostics.  A transient read failure is
    # exposed as ``binance_read_error`` instead of being mistaken for a clean
    # zero balance, and no mutation is attempted on this route.
    try:
        from engine.trading.binance_trading import BinanceTradingClient

        async with BinanceTradingClient(account.api_key, account.api_secret) as client:
            margin = await client.get_margin_account()
            info = next(
                (item for item in margin.get("userAssets", [])
                 if str(item.get("asset") or "").upper() == base_asset),
                {},
            )
            free = residual_decimal(info.get("free"))
            debt = residual_decimal(info.get("borrowed")) + residual_decimal(info.get("interest"))
            result["margin_free"] = str(free)
            result["debt"] = str(debt)

            spot = await client.get_spot_account()
            spot_info = next(
                (item for item in spot.get("balances", [])
                 if str(item.get("asset") or "").upper() == base_asset),
                {},
            )
            spot_free = residual_decimal(spot_info.get("free"))
            spot_locked = residual_decimal(spot_info.get("locked"))
            result["spot_free"] = str(spot_free)
            result["spot_locked"] = str(spot_locked)
            result["spot_same_asset"] = (spot_free + spot_locked) > RESIDUAL_EPSILON

            try:
                price = residual_decimal(await client.ws_spot_price(normalized, "bid"))
            except Exception:
                price = residual_decimal(0)
            result["price"] = str(price)
            result["notional"] = str(free * price)

            allowed, reason = validate_dust_conversion(
                free_margin=free,
                proven_quantity=proven,
                spot_free=spot_free,
                spot_locked=spot_locked,
                price=price,
                min_notional=DUST_USDT_THRESHOLD,
            )
            result["skip_reason"] = reason if not allowed else "ok"

            # Eligibility is queried for display only.  Binance implements
            # this read as a signed POST, but the endpoint does not convert
            # anything; failures are surfaced as unknown eligibility.
            query = getattr(client, "get_margin_dust_assets", None)
            if callable(query):
                try:
                    dust = await query()
                    details = []
                    if isinstance(dust, dict):
                        details = dust.get("details") or dust.get("convertibleAssets") or []
                    candidate = next(
                        (item for item in details
                         if str(item.get("asset") or "").upper() == base_asset),
                        None,
                    )
                    result["dust_asset"] = candidate
                    result["dust_eligible"] = candidate is not None
                    if allowed and candidate is None:
                        result["decision"] = "blocked"
                        result["skip_reason"] = "binance_dust_not_eligible"
                except Exception as exc:
                    result["dust_query_error"] = str(exc)
            if result["skip_reason"] == "ok":
                if result["dust_eligible"] is True:
                    result["decision"] = "eligible"
                elif result["dust_eligible"] is None:
                    # Eligibility is an exchange-side guard.  Unknown must
                    # remain blocked so the diagnostic can never be reused as
                    # an implicit authorization for a conversion write.
                    result["skip_reason"] = "binance_dust_eligibility_unknown"
    except Exception as exc:
        result["skip_reason"] = "binance_read_error"
        result["binance_error"] = str(exc)

    return result


@router.post("/residual-dust-to-bnb")
@_serialize_account_operation
async def residual_dust_to_bnb(
    data: ResidualDustRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Convert one proven residual directly in its Binance margin wallet.

    The endpoint deliberately refuses ambiguous account-level balances.  It
    requires an empty same-asset spot wallet and closed Position rows that
    account for the complete margin quantity. No wallet transfer is submitted.
    """
    user_id = get_current_user_id(request)
    symbol = _normalize_usdt_symbol(data.symbol)
    account = db.query(SubAccount).filter(
        SubAccount.id == data.sub_account_id,
        SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    # Read rows by account and normalize their symbols in Python.  A rolling
    # deployment may still contain ``BTC``/``BTC-USDT`` rows whose canonical
    # column has not been backfilled; an exact SQL equality would miss those
    # rows and could bypass the active-position ownership gate.
    position_rows = db.query(Position).filter(
        Position.sub_account_id == account.id,
    ).all()
    matching_rows = [
        row for row in (position_rows or [])
        if _position_matches_symbol(row, symbol)
    ]
    active_rows = [
        row for row in matching_rows
        if not is_terminal_position_status(getattr(row, "status", ""))
    ]
    if active_rows:
        raise HTTPException(
            status_code=409,
            detail=f"{symbol} 仍有 {len(active_rows)} 笔非终态持仓，暂不能兑换残留",
        )

    from engine.fund.residual_dust import (
        DUST_USDT_THRESHOLD,
        decimal as residual_decimal,
        proven_residual_for_position,
        validate_dust_conversion,
    )
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import _OperationLockGuard

    # Only a CLOSED row with a recorded buy-back order and a positive actual
    # repayment can prove that ``spot_buy_qty - repay_qty`` belongs to this
    # strategy.  Borrow-only/manual accounting rows are deliberately excluded.
    proven = sum(
        proven_residual_for_position(row)
        for row in matching_rows
    )

    lock_context = _request_operation_lock(request)
    if not lock_context or len(lock_context) != 2:
        raise HTTPException(status_code=503, detail="账户操作锁不可用，未执行残留兑换")
    lock_redis, lock_token = lock_context
    guard = _OperationLockGuard(
        lock_redis,
        data.sub_account_id,
        symbol,
        lock_token,
        ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
    )

    base_asset = symbol.replace("USDT", "")
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        margin = await client.get_margin_account()
        asset_info = next(
            (a for a in margin.get("userAssets", []) if a.get("asset") == base_asset),
            None,
        )
        if not asset_info:
            raise HTTPException(status_code=404, detail=f"未找到 {base_asset} 杠杆账户余额")
        borrowed = residual_decimal(asset_info.get("borrowed")) + residual_decimal(
            asset_info.get("interest")
        )
        if borrowed > Decimal("0.00000001"):
            raise HTTPException(status_code=409, detail=f"{base_asset} 仍有未清偿债务，先还币")
        free_margin = residual_decimal(asset_info.get("free"))

        spot = await client.get_spot_account()
        spot_info = next(
            (a for a in spot.get("balances", []) if a.get("asset") == base_asset),
            None,
        ) or {}
        try:
            price = await client.ws_spot_price(symbol, "bid")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="无法取得实时价格，未执行残留兑换") from exc
        allowed, reason = validate_dust_conversion(
            free_margin=free_margin,
            proven_quantity=proven,
            spot_free=spot_info.get("free"),
            spot_locked=spot_info.get("locked"),
            price=price,
            min_notional=DUST_USDT_THRESHOLD,
        )
        if not allowed:
            raise HTTPException(status_code=409, detail=reason)

        from engine.fund.residual_conversion import (
            ResidualConversionError,
            convert_margin_residual_to_bnb,
        )

        quantity = free_margin
        try:
            converted = await convert_margin_residual_to_bnb(
                client, base_asset, quantity, pre_submit_guard=guard,
            )
        except ResidualConversionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        dust_result = converted["dust"]
        conversion = converted["conversion"]
        transfer_rows = conversion.get("transferResult") if isinstance(conversion, dict) else None
        first_transfer = transfer_rows[0] if isinstance(transfer_rows, list) and transfer_rows else {}
        logger.info(
            "Residual BNB conversion account_id=%s asset=%s amount=%s bnb=%s transaction=%s",
            data.sub_account_id, base_asset, quantity,
            first_transfer.get("transferedAmount") or conversion.get("totalTransfered"),
            first_transfer.get("tranId") or conversion.get("tranId") or conversion.get("transId"),
        )

        # The holdings modal is driven by the Redis balance stream.  Ask the
        # pusher for a tenant-scoped immediate read so a confirmed conversion
        # is reflected without waiting for the normal ten-second cycle.  A
        # telemetry refresh failure must never turn a successful Binance
        # conversion into an API error.
        try:
            _redis().publish("balance:refresh", str(user_id))
        except Exception:
            logger.warning("Residual dust conversion succeeded but balance refresh publish failed", exc_info=True)

    return {
        "message": f"{base_asset} 已按可证明残留兑换 BNB",
        "asset": base_asset,
        "quantity": str(quantity),
        "tranId": first_transfer.get("tranId") or conversion.get("tranId") or conversion.get("transId"),
        "dust": dust_result,
    }


@router.delete("/repay-hold/{symbol}")
def clear_repay_hold(symbol: str, request: Request):
    """解除「还币暂停」:立即恢复该币自动借币(状态列点击/用户显式操作)。
    等价再武装动作:重存该币规则、重新推送。幂等。"""
    user_id = get_current_user_id(request)
    sym = _normalize_usdt_symbol(symbol)
    try:
        _redis().delete(f"engine:{user_id}:repayhold:{sym}")
    except Exception:
        pass
    return {"message": f"{sym} 已恢复自动借币"}


@router.post("/partial-repay")
@_serialize_account_operation
async def partial_repay(data: PartialRepayRequest, request: Request, db: Session = Depends(get_db)):
    """部分/全额还币(杠杆账户)。复用引擎 execute_repay 逻辑:先查实时债务+free,free 不足按 free 封顶(防 -3041),最终失败给可读 400。"""
    user_id = get_current_user_id(request)
    symbol = _normalize_usdt_symbol(data.symbol)
    account = db.query(SubAccount).filter(
        SubAccount.id == data.sub_account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    # The endpoint decorator owns the same account/asset lease as Worker
    # operations.  Carry its compare-and-renew guard into every financial POST
    # below; entering the decorator alone is not sufficient if the lease is
    # replaced while exchange reads or transfer preparation are in flight.
    lock_context = _request_operation_lock(request)
    operation_guard = None
    if lock_context:
        from engine.trading.order_executor import _OperationLockGuard

        operation_guard = _OperationLockGuard(
            lock_context[0],
            data.sub_account_id,
            symbol,
            lock_context[1],
        )

    # A previous process can die after the hedge has already been closed by
    # the exchange but before the OPEN row is updated.  Reconcile only rows
    # that pass the strict flat/zero-debt read-only proof; a live or indebted
    # OPEN row remains blocked below.
    stale_open_recovered = await _recover_stale_open_positions(
        db,
        user_id=user_id,
        account=account,
        symbol=symbol,
    )

    # ``execute_repay`` claims PENDING_REPAY as REPAYING before exchange I/O.
    # A process/deploy interruption can strand that claim.  Recover only while
    # this endpoint owns the account lock, and only after a stale-age plus
    # DB/exchange flatness proof.
    await _recover_stale_repaying_positions(
        db,
        user_id=user_id,
        account=account,
        symbol=symbol,
    )

    # A full repayment may explicitly include the risk-reducing close phase.
    # Partial requests and legacy callers remain blocked by the guard below.
    auto_closed = 0
    auto_close_errors: list[str] = []
    if data.auto_close:
        if not data.repay_all:
            raise HTTPException(
                status_code=400,
                detail="auto_close 仅允许与全额还币(repay_all)一起使用",
            )
        try:
            auto_closed, auto_close_errors = await _auto_close_open_positions_for_repay(
                db,
                user_id=user_id,
                account=account,
                symbol=symbol,
            )
        except HTTPException:
            raise
        except Exception as exc:
            # No exchange mutation is reported as complete when the close
            # client could not be created or the route could not be checked.
            auto_close_errors = [f"自动平仓未执行: {str(exc)[:160]}"]

    # ── 还币闸:对冲在场(现货已卖出/合约腿已开)禁止手动还币 ──
    # 借来的币已卖出时 free≈0,此端点会自动市价买回再还 = 强拆空头腿;而合约腿无人平,
    # 直接制造主账户孤儿合约仓(FIL 0.1 残留事故根因)。必须先平仓(强制平仓/等引擎平),
    # 对冲全平(PENDING_REPAY)或币还在手(BORROWED_IDLE)才允许还币。
    # 注意守卫只按本子账户本币查:其他子账户的对冲结构独立记账,不受本账户还币影响,
    # 查全用户会把「A 号已平想还币、B 号还开着」的正常操作也误拦。
    blocked = db.query(Position).filter(
        Position.sub_account_id == data.sub_account_id,
        Position.symbol == symbol,
        Position.status.notin_(("CLOSED", "FAILED", *REPAY_SAFE_STATUSES)),
    ).count()
    if blocked:
        suffix = f"（自动平仓结果: {auto_close_errors[0]}）" if auto_close_errors else ""
        raise HTTPException(
            status_code=409,
            detail=f"{symbol} 在该账户有 {blocked} 笔开仓/执行中的对冲持仓,禁止还币。"
                   f"请先平仓(右键→强制平仓),对冲全部平完后再还币。{suffix}",
        )
    if auto_close_errors:
        raise HTTPException(
            status_code=409,
            detail=f"{symbol} 自动平仓未完成，未发起还币: {auto_close_errors[0]}",
        )

    safe_positions = db.query(Position).filter(
        Position.sub_account_id == data.sub_account_id,
        Position.symbol == symbol,
        Position.status.in_(list(REPAY_SAFE_STATUSES)),
    ).all()
    if stale_open_recovered and not safe_positions:
        # The exchange proof already confirmed zero debt and no live hedge.
        # There is nothing left for this endpoint to submit; report the
        # idempotent reconciliation as success instead of requiring a second
        # manual click (or treating an omitted zero-balance asset as an error).
        if data.pause_borrow:
            _set_repay_hold(user_id, data.symbol, REPAY_RECONCILE_HOLD_SEC)
        return {
            "message": f"{symbol} 交易所已平仓且债务为 0，陈旧持仓记录已自动收口",
            "repaid": 0.0,
            "debt_before": 0.0,
            "debt_after": 0.0,
            "fully_repaid": True,
            "reconciled": True,
            "auto_closed": auto_closed,
        }
    borrowed_idle_positions = [
        position for position in safe_positions
        if position.status == "BORROWED_IDLE"
    ]
    if (
        not data.repay_all
        and borrowed_idle_positions
        and len(safe_positions) != 1
    ):
        # Binance debt is account/asset scoped. With more than one live row we
        # cannot prove which position owns the post-repay principal, so do not
        # mutate either the exchange or DB on a partial request.
        raise HTTPException(
            status_code=409,
            detail=(
                f"{symbol} 在该账户有多笔待处理持仓，无法安全分配部分还币后的剩余本金；"
                "请先逐笔收口，或选择全部还币。"
            ),
        )

    base_asset = symbol.replace("USDT", "")
    from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError

    try:
        async with BinanceTradingClient(account.api_key, account.api_secret) as client:
            # 1) 读实时债务与现货余额
            margin = await client.get_margin_account()
            asset_info = next((a for a in margin.get("userAssets", []) if a.get("asset") == base_asset), None)
            usdt_info = next((a for a in margin.get("userAssets", []) if a.get("asset") == "USDT"), None)
            if not asset_info:
                # Binance omits assets whose free and debt are both zero.  If
                # an explicit auto-close just confirmed all rows CLOSED, this
                # is an idempotent success rather than a missing-account error.
                if data.repay_all and auto_closed > 0:
                    if data.pause_borrow:
                        _set_repay_hold(user_id, data.symbol, REPAY_RECONCILE_HOLD_SEC)
                    try:
                        _redis().publish("balance:refresh", str(user_id))
                    except Exception:
                        pass
                    return {
                        "message": f"{account.note} {base_asset} 已平仓且 Binance 债务为 0",
                        "repaid": 0.0,
                        "debt_before": 0.0,
                        "debt_after": 0.0,
                        "fully_repaid": True,
                        "auto_closed": auto_closed,
                    }
                raise HTTPException(status_code=400, detail=f"账户无 {base_asset} 杠杆资产")
            borrowed_decimal = Decimal(str(asset_info.get("borrowed", "0") or 0))
            interest_decimal = Decimal(str(asset_info.get("interest", "0") or 0))
            borrowed = float(borrowed_decimal)
            interest = float(interest_decimal)
            free = float(asset_info.get("free", "0") or 0)
            free_before = free
            usdt_free = float(usdt_info.get("free", "0") or 0) if usdt_info else 0.0
            total_debt = borrowed + interest
            tracked_idle_principal: Decimal | None = None
            if borrowed_idle_positions and not data.repay_all:
                tracked_idle_principal = Decimal(str(
                    borrowed_idle_positions[0].borrow_qty or 0
                ))
                if borrowed_decimal > tracked_idle_principal + REPAY_DEBT_EPSILON:
                    # A position can own at most its recorded principal. Any
                    # excess Binance principal is untracked/external debt and
                    # cannot be assigned to this row without risking a later
                    # oversell. Full repayment remains the safe recovery path.
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"{symbol} Binance 本金 {borrowed_decimal} 高于持仓已跟踪本金 "
                            f"{tracked_idle_principal}，检测到未归属债务；未发起部分还币，请选择全部还币或先对账"
                        ),
                    )
            if total_debt < 1e-8:
                # 债务已为 0(可能此前已还/外部还清):仍收口卡住的 position(置 CLOSED),
                # 修复"已还币但状态仍待对冲"的孤儿。
                reconciled = _reconcile_positions_after_repay(
                    db,
                    user_id,
                    data.sub_account_id,
                    symbol,
                    Decimal("0"),
                )
                if not reconciled:
                    _set_repay_hold(
                        user_id,
                        data.symbol,
                        REPAY_RECONCILE_HOLD_SEC,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"{symbol} Binance 债务已归零，但持仓状态收口失败；"
                            "已暂停自动借币，请人工复核"
                        ),
                    )
                if data.pause_borrow:
                    _set_repay_hold(
                        user_id,
                        data.symbol,
                        REPAY_RECONCILE_HOLD_SEC,
                    )
                if data.sell_residual and free > 1e-8:
                    # Account-level ``free`` may include user-owned assets.
                    # Only the quantity proven by CLOSED buy-back rows may be
                    # sold or sent to the margin dust route.
                    from engine.fund.reconcile_checker import _proven_terminal_residual
                    proven = await asyncio.to_thread(
                        _proven_terminal_residual, data.sub_account_id, symbol,
                    )
                    cleanup_qty = min(Decimal(str(free)), proven)
                    if cleanup_qty <= Decimal("0.00000001"):
                        raise HTTPException(
                            status_code=409,
                            detail=f"{base_asset} 无法证明残留完全来自已结束仓位，未执行资产级清理",
                        )
                    # 显式卖回：零债务残留按已证明数量处理；名义 ≥ 5U
                    # 走市价卖回，低于最小名义时走 provenance-gated dust→BNB。
                    sold, note = await _sell_residual_spot(client, symbol, base_asset, float(cleanup_qty))
                    if sold <= 0:
                        dust_ok, dust_note = await _dust_residual_to_bnb(
                            client, base_asset, float(cleanup_qty),
                            pre_submit_guard=operation_guard,
                        )
                        try:
                            _redis().publish("balance:refresh", str(user_id))
                        except Exception:
                            pass
                        if dust_ok:
                            return {"message": f"{account.note} {dust_note}", "dusted": True}
                        raise HTTPException(status_code=400, detail=f"{base_asset} 残留无法清理: {note};{dust_note}")
                    try:
                        _redis().publish("balance:refresh", str(user_id))
                    except Exception:
                        pass
                    return {"message": f"{account.note} {base_asset} 无债务,{note}", "sold": sold}
                return {
                    "message": f"{account.note} {base_asset} 无需还币(债务为0),已同步持仓状态",
                    "repaid": 0.0,
                    "debt_before": 0.0,
                    "debt_after": 0.0,
                    "fully_repaid": True,
                    "auto_closed": auto_closed,
                }

            # 在途静默窗:还币操作(可能含买回/划转,数秒~数十秒)期间引擎不抢跑借币,
            # 防"边还边借"账目打架。秒级窗口对囤券策略无感;成功后按 pause_borrow 决定去留。
            _set_repay_hold(user_id, data.symbol, 10)

            # data.amount 是 Decimal(pydantic),而 free/total_debt/usdt_free 全为 float(来自币安字符串)。
            # 归一为 float,避免下游 `repay_amount - free`(shortfall)/`*= 0.999`(重试)触发 Decimal-float
            # 类型崩溃;margin_repay 出口统一 8 位量化,float 入参安全。
            req_qty = total_debt if data.repay_all else float(data.amount)
            if not data.repay_all and req_qty <= 0 and data.amount_usdt is not None and float(data.amount_usdt) > 0:
                # 金额(USDT)还币:按 Rust Binance WS 现价换算成币数量。
                cv_price = 0.0
                try:
                    cv_price = float(await client.ws_spot_price(symbol, "bid"))
                except Exception:
                    cv_price = 0.0
                if cv_price <= 0:
                    raise HTTPException(status_code=400, detail=f"无法获取 {base_asset} 现价,按金额还币暂不可用,请稍后重试或改用数量")
                req_qty = float(data.amount_usdt) / cv_price
            if req_qty <= 0:
                raise HTTPException(status_code=400, detail="还币数量或还币金额需大于 0")
            repay_target = min(req_qty, total_debt)
            repay_amount = repay_target
            bought_excess_qty = 0.0

            # 2) free 不足时:用 USDT 市价买入差额(常见于已平仓残留利息零头)。
            #    币安 MARKET BUY 受 NOTIONAL.minNotional(常 5 USDT)+ LOT_SIZE.stepSize 约束,
            #    故买入量须向上对齐到 minNotional;若子账户 USDT 不够,且全局开了 hedge_via_master,
            #    自动从主账户 universal_transfer 划 USDT 进子账户杠杆户,再买入还债。
            shortfall = repay_amount - free
            if shortfall > 1e-8:
                # 取交易对过滤器(stepSize / minNotional)+ 现价
                try:
                    info = await client._request("GET", "https://api.binance.com/api/v3/exchangeInfo",
                                                 {"symbol": symbol}, signed=False)
                    sp = info.get("symbols", [{}])[0]
                    flt = {f["filterType"]: f for f in sp.get("filters", [])}
                    step = float(flt.get("LOT_SIZE", {}).get("stepSize", "0.01") or "0.01")
                    min_notional = float(flt.get("NOTIONAL", {}).get("minNotional", "5") or "5")
                    price = float(await client.ws_spot_price(symbol, "ask"))
                except Exception:
                    step, min_notional, price = 0.01, 5.0, 0.0

                if price <= 0:
                    raise HTTPException(status_code=400, detail=f"无法获取 {base_asset} 价格,稍后重试")

                # 需买入量:满足 minNotional(币安用5分钟均价校验,现价可能偏低)→ 留 +20% 缓冲;
                # 再向上对齐 stepSize 并多加一档,确保名义价值稳过 NOTIONAL 过滤。
                import math
                target_notional = max(min_notional * 1.2, shortfall * price)
                need_qty = target_notional / price
                buy_qty = (math.ceil(need_qty / step) + 1) * step  # 向上对齐 stepSize + 多一档
                buy_cost = buy_qty * price * 1.01           # +1% 余量(滑点/手续费)

                # 子账户 USDT 不够买入 → 主账户按 transfer_order 顺序多源(合约/现货/全仓)累计划转补足
                if usdt_free < buy_cost:
                    deficit = buy_cost - usdt_free
                    from app.db.models import GlobalRules, FundRules
                    grules = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
                    hedge_via_master = bool(getattr(grules, "hedge_via_master", False)) if grules else False
                    master = _load_master_account(db, user_id)
                    if not hedge_via_master:
                        raise HTTPException(status_code=400, detail=f"子账户 USDT 不足(需 {buy_cost:.2f} 缺 {deficit:.2f}),且未开启「主账户自动划转(hedge_via_master)」,无法自动补足。请手动划入 USDT 或开启该功能。")
                    if not master or not master.api_key or not account.email:
                        raise HTTPException(status_code=400, detail=f"子账户 USDT 不足且主账户未配置(或子账户无 email),无法自动划转还币。")
                    # 按 FundRules.transfer_order 顺序从主账户各钱包归集 USDT 到主现货,再万向划转到子账户。
                    # 注:币安不允许从主账户合约/全仓【直接】跨账户划给子账户(-9000),须先内部归集到主现货。
                    fr = db.query(FundRules).filter(FundRules.user_id == user_id).first()
                    order_str = (fr.transfer_order if fr and fr.transfer_order else "futures,spot,margin")
                    sources = [s.strip() for s in order_str.split(",") if s.strip() in ("spot", "futures", "margin")]
                    xfer_amt = round(deficit + 1.0, 2)  # 多划 1 USDT 余量
                    # 内部归集 type 映射(各钱包 → 主现货 MAIN)
                    _INTERNAL = {"futures": "UMFUTURE_MAIN", "margin": "MARGIN_MAIN"}
                    try:
                        from engine.fund.margin_balancer import _master_source_usdt
                        async with BinanceTradingClient(master.api_key, master.api_secret) as mc:
                            bal = await _master_source_usdt(mc, sources)
                            spot_have = float(bal.get("spot", 0))
                            need_collect = max(0.0, xfer_amt - spot_have)
                            # 按 transfer_order 从非现货源归集到主现货
                            for src in sources:
                                if need_collect <= 0:
                                    break
                                if src == "spot":
                                    continue
                                avail = float(bal.get(src, 0))
                                take = round(min(need_collect, avail), 2)
                                if take <= 0:
                                    continue
                                try:
                                    await mc.transfer(
                                        _INTERNAL[src],
                                        "USDT",
                                        Decimal(str(take)),
                                        pre_submit_guard=operation_guard,
                                    )
                                    need_collect -= take
                                except Exception:
                                    continue
                            if need_collect > 0.01:
                                raise HTTPException(status_code=400, detail=f"主账户各钱包({order_str})USDT 合计不足,无法归集 {xfer_amt} USDT 还币。")
                            # 主现货 → 子账户 MARGIN(子账户万向划转,SPOT 起源)
                            await mc.universal_transfer(
                                asset="USDT", amount=Decimal(str(xfer_amt)),
                                from_account_type="SPOT", to_account_type="MARGIN",
                                from_email=None, to_email=account.email,
                                pre_submit_guard=operation_guard,
                            )
                        usdt_free += xfer_amt
                        logger.info(f"partial_repay: 主账户按序({order_str})归集+划转 {xfer_amt} USDT → 子账户 {account.note} 还币零头")
                    except HTTPException:
                        raise
                    except Exception as xe:
                        raise HTTPException(status_code=400, detail=f"主账户自动划转 USDT 失败: {str(xe)[:120]}")

                # 市价买入 base_asset(NO_SIDE_EFFECT=只用现有 USDT,不借币)
                try:
                    buy_result = await client._request(
                        "POST", "https://api.binance.com/sapi/v1/margin/order",
                        {
                            "symbol": symbol,
                            "side": "BUY",
                            "type": "MARKET",
                            "quantity": f"{buy_qty:.8f}",
                            "sideEffectType": "NO_SIDE_EFFECT",
                            "isIsolated": "FALSE",
                        },
                        pre_submit_guard=operation_guard,
                    )
                    executed = float(buy_result.get("executedQty", buy_qty) or buy_qty)
                    free += executed
                    # Only repay the caller's requested target.  A MARKET BUY
                    # may be rounded up to minNotional, but that must never turn
                    # a partial repayment into an implicit full repayment.
                    repay_amount = min(repay_target, free)
                    bought_excess_qty = max(0.0, executed - shortfall)
                except Exception as buy_err:
                    raise HTTPException(status_code=400, detail=f"买入 {base_asset} 还币失败: {str(buy_err)[:100]}")

            if repay_amount < 1e-8:
                raise HTTPException(status_code=400, detail=f"可还数量为 0(free={free:.6f}),无法还币")

            # 3) 还币,带重试。返回 Binance 实际接受的请求量；-3041 降量后不能再把
            # 原请求值当作“已全还”。
            async def _submit_repay(amount: float) -> float:
                submitted = amount
                for attempt in range(3):
                    try:
                        await client.margin_repay(
                            base_asset,
                            submitted,
                            pre_submit_guard=operation_guard,
                        )
                        return submitted
                    except BinanceAPIError as e:
                        if e.api_code == -3041 and attempt < 2:
                            submitted *= 0.999
                            continue
                        raise
                return 0.0

            # A BORROWED_IDLE row is hedgeable. Persist a non-hedgeable state
            # immediately before the first debt mutation so a crash cannot
            # later sell spot using the stale pre-repayment quantity. Price,
            # transfer, or top-up-buy failures above leave the state untouched.
            if borrowed_idle_positions and not _stage_borrowed_idle_positions_for_repay(
                db,
                borrowed_idle_positions,
                user_id,
                data.sub_account_id,
                symbol,
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{symbol} 持仓状态已变化，未向 Binance 发起还币；"
                        "请刷新后重试"
                    ),
                )

            total_repaid = await _submit_repay(repay_amount)

            # 3.1) 以 Binance 还后快照作为唯一收口依据。“全部还”若因结算延迟被降量，
            # 在账户仍有可用币时最多补还三轮；读不到还后债务时保守地不关闭 Position。
            debt_after: float | None = None
            principal_after: Decimal | None = None
            interest_after: Decimal | None = None
            partial_snapshot_reflected = False
            free_after = max(0.0, free - total_repaid)
            for verify_round in range(4):
                await asyncio.sleep(0.25)
                try:
                    margin_after = await client.get_margin_account()
                    asset_after = next(
                        (a for a in margin_after.get("userAssets", []) if a.get("asset") == base_asset),
                        None,
                    )
                    if asset_after is None:
                        principal_after = Decimal("0")
                        interest_after = Decimal("0")
                        debt_after = 0.0
                        free_after = 0.0
                    else:
                        principal_after = Decimal(str(asset_after.get("borrowed", "0") or 0))
                        interest_after = Decimal(str(asset_after.get("interest", "0") or 0))
                        debt_after = float(principal_after + interest_after)
                        free_after = float(asset_after.get("free", "0") or 0)
                except Exception as verify_error:
                    logger.warning(
                        "partial_repay post-check failed (%s acct %s): %s",
                        symbol, data.sub_account_id, verify_error,
                    )
                    break

                if debt_after <= float(REPAY_DEBT_EPSILON):
                    partial_snapshot_reflected = True
                    break
                if not data.repay_all:
                    # A successful HTTP response can precede the margin-account
                    # snapshot update. Do not restore BORROWED_IDLE from that
                    # stale pre-repay value; poll until Binance shows a real
                    # debt reduction or leave the row safely PENDING_REPAY.
                    debt_before_decimal = borrowed_decimal + interest_decimal
                    if (
                        principal_after is not None
                        and interest_after is not None
                        and principal_after + interest_after
                        < debt_before_decimal - REPAY_DEBT_EPSILON
                        and (
                            tracked_idle_principal is None
                            or principal_after <= min(
                                tracked_idle_principal, borrowed_decimal,
                            ) + REPAY_DEBT_EPSILON
                        )
                    ):
                        partial_snapshot_reflected = True
                        break
                    continue
                if verify_round >= 3 or free_after <= float(REPAY_DEBT_EPSILON):
                    break
                followup = min(debt_after, free_after)
                accepted = await _submit_repay(followup)
                if accepted <= 0:
                    break
                total_repaid += accepted

            fully_repaid = debt_after is not None and debt_after <= float(REPAY_DEBT_EPSILON)

            # 3.5) By default only sell the provable excess from this request's
            # rounded-up minNotional buy. ``free_after`` can contain a user
            # deposit, so an ordinary/automatic repay must never consume all of
            # it. The holdings modal may set sell_residual=True as explicit
            # operator consent; even then cleanup starts only after Binance has
            # confirmed zero debt and every DB position has passed the guard
            # above. Sub-minNotional remainders remain visible in margin because
            # Binance's asset-wide dust route cannot isolate this request's qty.
            cleanup_result: dict[str, object] = {}
            cleanup_message: str | None = None
            cleanup_warning: str | None = None
            try:
                explicit_cleanup = bool(
                    data.repay_all and data.sell_residual and fully_repaid
                )
                cleanup_qty = (
                    free_after
                    if explicit_cleanup
                    else min(free_after, bought_excess_qty)
                )
                if data.repay_all and fully_repaid and cleanup_qty > 1e-8:
                    sold, sell_note = await _sell_residual_spot(
                        client, symbol, base_asset, cleanup_qty
                    )
                    if sold > 0:
                        cleanup_result["sold"] = float(sold)
                        cleanup_message = sell_note
                        logger.info(
                            "partial_repay: sold leftover %s %s back to USDT (acct %s)",
                            sold, base_asset, data.sub_account_id,
                        )

                    # LOT_SIZE rounding can leave a sub-step remainder even
                    # after a successful sale. The dust helper is deliberately
                    # fail-closed until an exact-quantity conversion route is
                    # available; its warning never changes a successful repay
                    # into a 4xx response.
                    dust_qty = max(0.0, cleanup_qty - float(sold or 0))
                    if explicit_cleanup and dust_qty > 1e-8:
                        dust_ok, dust_note = await _dust_residual_to_bnb(
                            client, base_asset, dust_qty,
                            pre_submit_guard=operation_guard,
                        )
                        if dust_ok:
                            cleanup_result["dusted"] = True
                            cleanup_message = (
                                f"{cleanup_message}; {dust_note}"
                                if cleanup_message else dust_note
                            )
                        else:
                            cleanup_warning = (
                                f"债务已归零，但 {base_asset} 残留未自动清理："
                                f"{sell_note}; {dust_note}"
                            )
            except Exception as se:
                logger.warning(f"partial_repay 卖回零头残留失败(还币已成功): {se}")
                if data.repay_all and data.sell_residual and fully_repaid:
                    cleanup_warning = f"债务已归零，但 {base_asset} 残留清理失败：{str(se)[:100]}"

            # 4) 回写 position:手动还币绕过引擎对冲/还币流程,不回写则 BORROWED_IDLE 等未终态
            #    position 会永久卡在「待对冲」(状态孤儿)。债已清 → 收口该币 position(见 helper)。
            if fully_repaid:
                reconciled = _reconcile_positions_after_repay(
                    db,
                    user_id,
                    data.sub_account_id,
                    symbol,
                    Decimal(str(total_repaid)),
                    Decimal(str(debt_after)),
                )
                if not reconciled:
                    _set_repay_hold(
                        user_id,
                        data.symbol,
                        REPAY_RECONCILE_HOLD_SEC,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"{symbol} Binance 债务已归零，但持仓状态收口失败；"
                            "已暂停自动借币，请人工复核"
                        ),
                    )
            elif borrowed_idle_positions and not data.repay_all:
                position = borrowed_idle_positions[0]
                reconciled = (
                    partial_snapshot_reflected
                    and principal_after is not None
                    and interest_after is not None
                    and _reconcile_borrowed_idle_after_partial_repay(
                        db,
                        user_id,
                        data.sub_account_id,
                        symbol,
                        position.id,
                        principal_after,
                        interest_after,
                    )
                )
                if not reconciled:
                    _set_repay_hold(
                        user_id,
                        data.symbol,
                        REPAY_RECONCILE_HOLD_SEC,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"{symbol} 还币请求已提交，但 Binance 剩余本金尚未完成安全对账；"
                            "持仓已转为待还币，禁止按旧数量对冲，系统将继续收口债务"
                        ),
                    )

            # Only a confirmed zero debt plus a committed Position close may
            # immediately re-arm borrowing. Unknown verification or residual
            # debt retains a short fence so the next cycle cannot race the
            # just-submitted repayment.
            _hk = f"engine:{user_id}:repayhold:{symbol}"
            if data.pause_borrow:
                _set_repay_hold(
                    user_id,
                    data.symbol,
                    REPAY_RECONCILE_HOLD_SEC,
                )
            elif not fully_repaid:
                _set_repay_hold(user_id, data.symbol, REPAY_RETRY_HOLD_SEC)
            else:
                try:
                    _redis().delete(_hk)
                except Exception:
                    # Leaving a stale hold is conservative; the explicit
                    # resume endpoint can clear it after Redis recovers.
                    logger.warning("Unable to clear repay hold %s", _hk, exc_info=True)

            # 写后即时刷新:手动部分/全额还币 → 请求 BalancePusher 立刻重推该用户余额(不等 10s 轮询,问题4)
            try:
                _redis().publish("balance:refresh", str(user_id))
            except Exception:
                pass

            if data.repay_all and not fully_repaid:
                remaining = "未知" if debt_after is None else f"{debt_after:.8f}"
                message = f"已还 {total_repaid:.6f} {base_asset}，仍有债务 {remaining}，未执行持仓收口"
            else:
                message = f"已还 {total_repaid:.6f} {base_asset} (账户 {account.note})"
                if cleanup_message:
                    message += f"，{cleanup_message}"
            return {
                "message": message,
                "repaid": float(total_repaid),
                "debt_before": total_debt,
                "debt_after": debt_after,
                "free_before": free_before,
                "fully_repaid": fully_repaid,
                "cleanup_warning": cleanup_warning,
                "auto_closed": auto_closed,
                **cleanup_result,
            }
    except BinanceAPIError as e:
        raise HTTPException(status_code=400, detail=f"还币失败(币安 {e.api_code}): {e.message}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"还币失败: {str(e)}")


# ─── Manual Open / Close (executed API-side, works regardless of engine state) ───


def _build_spread_snapshot(symbol: str):
    """Build a SpreadSnapshot from the Redis spreads hash for manual execution."""
    from engine.spread_feed import SpreadSnapshot
    symbol = str(symbol or "").strip().upper().replace("-", "").replace("_", "")
    raw = _redis().hget("spreads", symbol)
    if not raw:
        return None
    p = json.loads(raw)
    return SpreadSnapshot(
        symbol=str(p.get("symbol") or symbol).strip().upper(),
        spot_bid=Decimal(str(p["spot_bid"])),
        spot_ask=Decimal(str(p["spot_ask"])),
        fut_bid=Decimal(str(p["fut_bid"])),
        fut_ask=Decimal(str(p["fut_ask"])),
        spread_long=Decimal(str(p["spread_long"])),
        spread_short=Decimal(str(p["spread_short"])),
        ts=int(p.get("ts", 0) or 0),
        # ``ts`` is Binance's exchange event time and is not a liveness
        # signal.  Manual execution must carry the Rust-local receive times
        # through to the same freshness gate used by workers.
        spot_recv_ts_ms=int(p.get("spot_recv_ts_ms", 0) or 0),
        fut_recv_ts_ms=int(p.get("fut_recv_ts_ms", 0) or 0),
    )

def _load_global_rules_snapshot(db: Session, user_id: int):
    from app.db.models import GlobalRules
    from engine.config_loader import GlobalRulesSnapshot, DEFAULT_GLOBAL
    # Never fall back to another user's row when a tenant has not created a
    # rule row yet.  The NULL-owner row is the only host-wide default, matching
    # ConfigLoader's user-scoped lookup semantics.
    rules = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
    if rules is None:
        rules = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).order_by(GlobalRules.id).first()
    if not rules:
        return DEFAULT_GLOBAL
    # Keep API-side/manual execution on the same rule surface as ConfigLoader.
    # The previous constructor only copied the original spread fields, so
    # manual open/hedge/close silently used dataclass defaults for newer safety
    # controls (borrow mode, collateral, freshness/glitch gates, net gate,
    # fees, and the maker/emergency exit mode).
    snapshot = GlobalRulesSnapshot(
        auto_push_spread=rules.auto_push_spread,
        remove_spread=rules.remove_spread,
        open_spread=rules.open_spread,
        close_spread=rules.close_spread,
        order_amount=rules.order_amount,
        open_order_amount=getattr(rules, "open_order_amount", None),
        close_funding_ratio=rules.close_funding_ratio,
        repay_funding_ratio=rules.repay_funding_ratio,
        borrow_delay_sec=rules.borrow_delay_sec,
        confirm_delay_sec=rules.confirm_delay_sec,
        confirm_skip_spread=rules.confirm_skip_spread,
        repay_ban_minutes=rules.repay_ban_minutes,
        interest_filter=rules.interest_filter,
        max_positions=rules.max_positions or 10,
        auto_start_on_boot=bool(rules.auto_start_on_boot),
        futures_liquidation_threshold=rules.futures_liquidation_threshold,
        repay_spread=rules.repay_spread,
        max_daily_interest_rate=rules.max_daily_interest_rate,
        slippage_pct=getattr(rules, "slippage_pct", None) or Decimal("0.1"),
        follow_type=getattr(rules, "follow_type", None) or "market",
        stabilize_sec=getattr(rules, "stabilize_sec", None) or Decimal("0"),
        tier_ratios=getattr(rules, "tier_ratios", None) or "",
        borrow_spread=getattr(rules, "borrow_spread", None) if getattr(rules, "borrow_spread", None) is not None else Decimal("0.5"),
        borrow_rate_per_sec=getattr(rules, "borrow_rate_per_sec", None) if getattr(rules, "borrow_rate_per_sec", None) is not None else Decimal("3.9"),
        inventory_probe_rate_per_sec=(
            getattr(rules, "inventory_probe_rate_per_sec", None)
            if getattr(rules, "inventory_probe_rate_per_sec", None) is not None
            else Decimal("2.0")
        ),
        borrow_via_otoco=bool(getattr(rules, "borrow_via_otoco", False)),
        # Preserve a legacy NULL until the system row has been overlaid.  Both
        # fields are system-controlled, so deriving here from the tenant row
        # can freeze the wrong mode before the authoritative bool is applied.
        borrow_mode=(getattr(rules, "borrow_mode", None) or ""),
        otoco_legs=int(getattr(rules, "otoco_legs", 2) or 2),
        multi_max_accounts_per_symbol=int(getattr(rules, "multi_max_accounts_per_symbol", 5) or 5),
        hedge_via_master=bool(getattr(rules, "hedge_via_master", False)),
        max_spread_pct=getattr(rules, "max_spread_pct", None) if getattr(rules, "max_spread_pct", None) is not None else Decimal("3"),
        min_volume_24h=getattr(rules, "min_volume_24h", None) if getattr(rules, "min_volume_24h", None) is not None else Decimal("0"),
        min_volume_24h_futures=getattr(rules, "min_volume_24h_futures", None) if getattr(rules, "min_volume_24h_futures", None) is not None else Decimal("0"),
        block_risky_open=bool(getattr(rules, "block_risky_open", False)),
        filter_duration_ms=int(getattr(rules, "filter_duration_ms", 0) or 0),
        min_borrow_usdt=getattr(rules, "min_borrow_usdt", None) if getattr(rules, "min_borrow_usdt", None) is not None else Decimal("0"),
        collateral_ratio=getattr(rules, "collateral_ratio", None) if getattr(rules, "collateral_ratio", None) is not None else Decimal("1"),
        taker_fee_spot=getattr(rules, "taker_fee_spot", None) if getattr(rules, "taker_fee_spot", None) is not None else Decimal("0.00075"),
        taker_fee_futures=getattr(rules, "taker_fee_futures", None) if getattr(rules, "taker_fee_futures", None) is not None else Decimal("0.00075"),
        bnb_burn_enabled=bool(getattr(rules, "bnb_burn_enabled", False)),
        removed_cooldown_minutes=int(getattr(rules, "removed_cooldown_minutes", 0) or 0),
        open_spread_buffer=getattr(rules, "open_spread_buffer", None) if getattr(rules, "open_spread_buffer", None) is not None else Decimal("0"),
        max_loss_per_position=getattr(rules, "max_loss_per_position", None),
        net_gate_mode=(getattr(rules, "net_gate_mode", None) or "shadow"),
        hedge_auto_converge=bool(getattr(rules, "hedge_auto_converge", False)),
        spot_order_mode=(getattr(rules, "spot_order_mode", None) or "market"),
    )

    # ConfigLoader applies the NULL-owner system row over a tenant row for
    # system-controlled fields (order mode, borrow mode, safety gates, etc.).
    # Manual open/hedge/close runs in this API process and must use the same
    # effective values; otherwise a user can see one policy in the dashboard
    # while the direct operation silently uses stale per-user defaults.
    if rules.user_id is not None:
        from engine.config_loader import _SYSTEM_FIELDS, _SYS_BOOL, _SYS_INT, _SYS_STR

        system_rules = db.query(GlobalRules).filter(
            GlobalRules.user_id.is_(None)
        ).order_by(GlobalRules.id).first()
        if system_rules is not None:
            overrides = {}
            for field in _SYSTEM_FIELDS:
                value = getattr(system_rules, field, None)
                if value is None:
                    continue
                if field in _SYS_BOOL:
                    value = bool(value)
                elif field in _SYS_INT:
                    value = int(value)
                elif field in _SYS_STR:
                    value = str(value)
                overrides[field] = value
            if overrides:
                snapshot = replace(snapshot, **overrides)

    # A NULL borrow_mode is a legacy row that derives from the effective
    # borrow_via_otoco flag. Derive only after system overrides are applied.
    if not snapshot.borrow_mode:
        snapshot = replace(
            snapshot,
            borrow_mode="otoco" if snapshot.borrow_via_otoco else "repay",
        )
    return snapshot


def _load_master_account(db: Session, user_id: int):
    """Return only the master account owned by this user."""
    return db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()


async def _assert_master_one_way(fc):
    """主账户必须单向持仓 —— 下单不带 positionSide,双向模式会先卖现货再 -4061 回滚。
    引擎进程的 master_client 注册表在创建时断言;API 进程直建 client 须同样校验。"""
    if await fc.get_position_mode():
        raise ValueError("主账户处于双向持仓模式,请先在币安合约设置切回单向持仓")


class ManualOpenRequest(BaseModel):
    sub_account_id: int
    symbol: str
    order_amount: Decimal | None = None  # override global order_amount for this open


@router.post("/manual-open")
@_serialize_account_operation
async def manual_open(data: ManualOpenRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == data.sub_account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    if not account.is_enabled:
        raise HTTPException(status_code=400, detail="账户已禁用，无法开仓")

    symbol = _normalize_usdt_symbol(data.symbol)
    if _new_action_is_paused(user_id, symbol):
        raise HTTPException(status_code=409, detail=f"{symbol} 挂单已暂停，请先恢复挂单")
    spread = _build_spread_snapshot(symbol)
    if not spread:
        raise HTTPException(status_code=400, detail=f"无 {symbol} 行情数据，无法开仓")

    # 进行中锁:同账户同币的开仓在途时拒绝并发提交。开仓同步执行 20~40s(借币延迟+对冲),
    # 客户端超时重发/连点会重复借币开仓(端点无幂等),Redis NX 锁挡住第二发。
    _open_lock_key = f"manual_open_lock:{data.sub_account_id}:{symbol}"
    _rl = _redis()
    if not _rl.set(_open_lock_key, "1", nx=True, ex=90):
        raise HTTPException(status_code=429, detail=f"{symbol} 该账户已有开仓请求执行中,请等待其完成(勿重复提交)")

    import dataclasses
    rules = _load_global_rules_snapshot(db, user_id)
    if data.order_amount and data.order_amount > 0:
        rules = dataclasses.replace(
            rules,
            order_amount=data.order_amount,
            open_order_amount=data.order_amount,
        )

    master = None
    if getattr(rules, "hedge_via_master", False):
        master = _load_master_account(db, user_id)
        if not master:
            raise HTTPException(status_code=400, detail="已开启主账户对冲,但主账户未配置")

    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_open
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(BinanceTradingClient(
                account.api_key, account.api_secret, sub_account_id=account.id))
            fc = None
            if master:
                fc = await stack.enter_async_context(BinanceTradingClient(
                    master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
                await _assert_master_one_way(fc)
            # spread_feed=None → skip the post-delay re-confirm; manual open forces
            # at the current spread (interest-rate filter still applies).
            lock_context = _request_operation_lock(request)
            await execute_open(
                account.id, symbol, spread, rules, client, notifier, account.note,
                spread_feed=None, futures_client=fc, user_id=user_id,
                new_action_guard=lambda: not _new_action_is_paused(
                    user_id, symbol
                ),
                operation_lock_redis=(
                    lock_context[0]
                    if lock_context
                    else None
                ),
                operation_lock_token=(
                    lock_context[1]
                    if lock_context
                    else None
                ),
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"开仓失败: {e}")
    finally:
        try:
            _rl.delete(_open_lock_key)
        except Exception:
            pass

    latest = db.query(Position).filter(
        Position.sub_account_id == account.id, Position.symbol == symbol,
    ).order_by(Position.id.desc()).first()
    if latest and latest.status == "OPEN":
        return {"message": f"开仓成功 {symbol} @ {account.note}", "position_id": latest.id, "status": "OPEN"}
    detail = latest.error_message if latest else "未知错误"
    return {"message": f"开仓未完成 {symbol}: {detail}", "status": latest.status if latest else "FAILED"}


class ManualCloseRequest(BaseModel):
    position_id: int


@router.post("/manual-close")
@_serialize_position_operation
async def manual_close(data: ManualCloseRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    position = db.query(Position).filter(
        Position.id == data.position_id, Position.user_id == user_id,
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "OPEN":
        raise HTTPException(status_code=400, detail=f"持仓状态为 {position.status}，无法平仓")

    account = db.query(SubAccount).filter(
        SubAccount.id == position.sub_account_id,
        SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    spread = _build_spread_snapshot(position.symbol)
    if not spread:
        # Close still works without live spread; use zeros only for the recorded close_spread.
        from engine.spread_feed import SpreadSnapshot
        spread = SpreadSnapshot(position.symbol, Decimal("0"), Decimal("0"),
                                Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), 0)

    master = None
    if getattr(position, "hedge_account", None) == "master":
        master = _load_master_account(db, user_id)
        if not master:
            raise HTTPException(status_code=400, detail="该持仓合约腿在主账户,但主账户未配置")

    # Keep the configured spot exit mode while retaining the explicit
    # risk-reducing emergency-close behavior below.
    rules = _load_global_rules_snapshot(db, user_id)

    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_close
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(BinanceTradingClient(
                account.api_key, account.api_secret, sub_account_id=account.id))
            fc = None
            if master:
                fc = await stack.enter_async_context(BinanceTradingClient(
                    master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
                await _assert_master_one_way(fc)
            lock_context = _request_operation_lock(request)
            completed = await execute_close(
                position,
                spread,
                client,
                notifier,
                account.note,
                futures_client=fc,
                spot_order_mode=(getattr(rules, "spot_order_mode", None) or "market"),
                allow_emergency_close=True,
                user_id=user_id,
                operation_lock_redis=(lock_context[0] if lock_context else None),
                operation_lock_token=(lock_context[1] if lock_context else None),
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"平仓失败: {e}")

    db.refresh(position)
    if not completed or position.status != "CLOSED":
        detail = position.error_message or (
            "行情未满足平仓安全条件，或还币仍在等待中；持仓保持未平，请稍后重试"
        )
        raise HTTPException(status_code=409, detail=f"平仓未完成: {detail}")
    return {"message": f"平仓完成 {position.symbol}", "status": position.status,
            "realized_pnl": str(position.realized_pnl or 0)}


class ManualPositionRequest(BaseModel):
    position_id: int


@router.post("/manual-hedge")
@_serialize_position_operation
async def manual_hedge(data: ManualPositionRequest, request: Request, db: Session = Depends(get_db)):
    """手动对冲：把 BORROWED_IDLE 持仓卖现货+合约跟多 → OPEN。"""
    user_id = get_current_user_id(request)
    position = db.query(Position).filter(
        Position.id == data.position_id, Position.user_id == user_id,
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "BORROWED_IDLE":
        raise HTTPException(status_code=400, detail=f"持仓状态为 {position.status}，无法对冲")
    account = db.query(SubAccount).filter(
        SubAccount.id == position.sub_account_id,
        SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    spread = _build_spread_snapshot(position.symbol)
    if not spread:
        raise HTTPException(status_code=400, detail=f"无 {position.symbol} 行情数据，无法对冲")
    rules = _load_global_rules_snapshot(db, user_id)
    master = None
    if getattr(rules, "hedge_via_master", False):
        master = _load_master_account(db, user_id)
        if not master:
            raise HTTPException(status_code=400, detail="已开启主账户对冲,但主账户未配置")

    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_hedge
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(BinanceTradingClient(
                account.api_key, account.api_secret, sub_account_id=account.id))
            fc = None
            if master:
                fc = await stack.enter_async_context(BinanceTradingClient(
                    master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
                await _assert_master_one_way(fc)
            lock_context = _request_operation_lock(request)
            await execute_hedge(position, spread, rules, client, notifier, account.note,
                                futures_client=fc, user_id=user_id,
                                operation_lock_redis=(
                                    lock_context[0] if lock_context else None
                                ),
                                operation_lock_token=(
                                    lock_context[1] if lock_context else None
                                ))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"对冲失败: {e}")
    db.refresh(position)
    return {"message": f"对冲完成 {position.symbol}", "status": position.status}


@router.post("/manual-repay")
@_serialize_position_operation
async def manual_repay(data: ManualPositionRequest, request: Request, db: Session = Depends(get_db)):
    """手动还币：把 PENDING_REPAY 持仓的杠杆负债还清 → CLOSED。"""
    user_id = get_current_user_id(request)
    position = db.query(Position).filter(
        Position.id == data.position_id, Position.user_id == user_id,
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    account = db.query(SubAccount).filter(
        SubAccount.id == position.sub_account_id,
        SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    # A process can die after execute_repay claims REPAYING.  Let this
    # position-scoped entry point use the same stale-age and exchange-flat
    # recovery as /partial-repay while the decorator-owned account lock is held.
    # It also closes a stale OPEN row only when Binance proves all legs and
    # margin debt are already flat; no exchange mutation is performed there.
    if position.status == "OPEN":
        await _recover_stale_open_positions(
            db,
            user_id=user_id,
            account=account,
            symbol=position.symbol,
        )
        db.refresh(position)
    if position.status == "REPAYING":
        await _recover_stale_repaying_positions(
            db,
            user_id=user_id,
            account=account,
            symbol=position.symbol,
        )
        db.refresh(position)
    if position.status == "CLOSED":
        return {
            "message": f"还币完成 {position.symbol}（交易所已平仓且债务为 0，记录已对账收口）",
            "status": "CLOSED",
            "reconciled": True,
            "realized_pnl": str(position.realized_pnl or 0),
        }
    if position.status != "PENDING_REPAY":
        code = 409 if position.status == "REPAYING" else 400
        raise HTTPException(
            status_code=code,
            detail=(
                f"持仓状态为 {position.status}，无法还币"
                if code == 400
                else "还币任务仍在交易所核对中，暂未确认对冲已平，请稍后重试"
            ),
        )
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_repay
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with BinanceTradingClient(account.api_key, account.api_secret,
                                        sub_account_id=account.id) as client:
            lock_context = _request_operation_lock(request)
            completed = await execute_repay(
                position,
                client,
                notifier,
                account.note,
                operation_lock_redis=(lock_context[0] if lock_context else None),
                operation_lock_token=(lock_context[1] if lock_context else None),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"还币失败: {e}")
    db.refresh(position)
    if not completed or position.status != "CLOSED":
        detail = position.error_message or "Binance 尚未确认债务归零，持仓保持待还币"
        raise HTTPException(status_code=409, detail=f"还币未完成: {detail}")
    return {"message": f"还币完成 {position.symbol}", "status": position.status,
            "realized_pnl": str(position.realized_pnl or 0)}


# ─── Engine Start/Stop Control ───


@router.post("/workers/start")
def start_engine(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    r = _redis()
    if not _command_consumer_alive(r):
        # Do not leave a durable STARTING row (or a misleading success toast)
        # when the separate cex-worker host process is stopped.  The operator
        # must bring that service up first; once its heartbeat is present the
        # same button can safely enqueue the tenant start command.
        raise HTTPException(
            status_code=503,
            detail="cex-worker.service 未运行或命令消费者无心跳，请先启动 Worker 服务",
        )
    state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    current_status = str(getattr(state, "status", "STOPPED") or "STOPPED").strip().upper()
    live_transition = _fresh_engine_transition(state)
    if current_status == "RUNNING":
        # Starting an already-running tenant is idempotent.  Returning the
        # terminal state keeps repeated clicks/tabs from adding commands.
        return {
            "message": "Engine already running",
            "engine_status": "RUNNING",
            "command_consumer": True,
            "idempotent": True,
        }
    if live_transition == "STARTING":
        # The original command is still owned by the Worker.  Do not enqueue
        # a second start; the UI can continue polling this same transition.
        return {
            "message": "Engine start already pending",
            "engine_status": "STARTING",
            "command_consumer": True,
            "idempotent": True,
        }
    if live_transition == "STOPPING":
        raise HTTPException(
            status_code=409,
            detail="引擎正在停止，请等待停止完成后再启动",
        )
    # Commit the intent before publishing the command.  The previous order
    # published first and then wrote STARTING; a fast consumer could process
    # the command and persist RUNNING, after which this request overwrote it
    # with STARTING.  The dashboard then stayed in a transition forever.  A
    # short-lived STARTING row is still recoverable if the process dies between
    # the DB commit and Redis enqueue (the Worker already fences stale intents).
    previous_status = state.status if state else "STOPPED"
    if not state:
        state = EngineState(scope="global", user_id=user_id, status="STARTING")
        db.add(state)
    else:
        state.status = "STARTING"
    db.commit()
    try:
        r.rpush(f"engine:{user_id}:commands", json.dumps({"action": "start"}))
        r.expire(f"engine:{user_id}:commands", 120)
    except Exception as exc:
        # Do not leave a durable transition when the command could not be
        # handed to Redis.  Restore the prior state when possible; otherwise
        # expose ERROR so the UI offers a retry instead of a false success.
        try:
            state.status = previous_status or "ERROR"
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"Worker 启动命令入队失败: {exc}",
        ) from exc
    return {
        "message": "Engine start signal sent",
        "engine_status": "STARTING",
        "command_consumer": True,
    }


@router.post("/workers/stop")
def stop_engine(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    r = _redis()
    if not _command_consumer_alive(r):
        raise HTTPException(
            status_code=503,
            detail="cex-worker.service 未运行或命令消费者无心跳，无法确认停止状态",
        )
    state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    current_status = str(getattr(state, "status", "STOPPED") or "STOPPED").strip().upper()
    live_transition = _fresh_engine_transition(state)
    # A missing global row is not the same as a durable STOPPED state.  Keep
    # the command path alive so the Worker can acknowledge the stop and leave
    # a recoverable state row for subsequent dashboard reads.
    if state is not None and current_status == "STOPPED":
        return {
            "message": "Engine already stopped",
            "engine_status": "STOPPED",
            "command_consumer": True,
            "idempotent": True,
        }
    if live_transition == "STOPPING":
        return {
            "message": "Engine stop already pending",
            "engine_status": "STOPPING",
            "command_consumer": True,
            "idempotent": True,
        }
    if live_transition == "STARTING":
        raise HTTPException(
            status_code=409,
            detail="引擎正在启动，请等待启动完成后再停止",
        )
    # Mirror start_engine: persist STOPPING before enqueueing so a fast
    # command consumer cannot write STOPPED and then be overwritten by this
    # request's late transition update.
    previous_status = state.status if state else "STOPPED"
    if not state:
        # Keep stop idempotent but durable.  Without a global row the command
        # consumer had no state to acknowledge, so a successful stop could
        # leave the UI showing the transient response forever after a restart.
        state = EngineState(scope="global", user_id=user_id, status="STOPPING")
        db.add(state)
    else:
        state.status = "STOPPING"
    db.commit()
    try:
        r.rpush(f"engine:{user_id}:commands", json.dumps({"action": "stop"}))
        r.expire(f"engine:{user_id}:commands", 120)
    except Exception as exc:
        try:
            state.status = previous_status or "STOPPED"
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"Worker 停止命令入队失败: {exc}",
        ) from exc
    return {
        "message": "Engine stop signal sent",
        "engine_status": "STOPPING",
        "command_consumer": True,
    }


def _owned_sub(db: Session, user_id: int, account_id: int) -> SubAccount:
    acc = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return acc


@router.post("/workers/{account_id}/restart")
def restart_one_worker(account_id: int, request: Request, db: Session = Depends(get_db)):
    """单独重启某子账户的 worker(卡死/心跳超时时无需整体停启)。经 Redis 命令 →
    orchestrator.restart_worker 取消并重建该 task,其余 worker 不动。"""
    user_id = get_current_user_id(request)
    acc = _owned_sub(db, user_id, account_id)
    r = _redis()
    r.rpush(f"engine:{user_id}:commands", json.dumps({"action": "restart_worker", "account_id": account_id}))
    r.expire(f"engine:{user_id}:commands", 120)
    return {"message": f"worker {(acc.note or '未命名子账户')} 重启信号已发送"}


@router.post("/workers/{account_id}/stop")
def stop_one_worker(account_id: int, request: Request, db: Session = Depends(get_db)):
    """停用单个 worker = 禁用该子账户(is_enabled=False);orchestrator 下轮对账停其 worker。
    注:若该账户尚有在场持仓,worker 会被保留以管理平仓/还币(不会孤儿化),属预期安全行为。"""
    user_id = get_current_user_id(request)
    acc = _owned_sub(db, user_id, account_id)
    acc.is_enabled = False
    db.commit()
    return {"message": f"worker {(acc.note or '未命名子账户')} 已停用(约10s内生效;有在场持仓则保留至平仓)"}


@router.post("/workers/{account_id}/start")
def start_one_worker(account_id: int, request: Request, db: Session = Depends(get_db)):
    """启用单个 worker = 启用该子账户(is_enabled=True);orchestrator 下轮对账拉起。"""
    user_id = get_current_user_id(request)
    acc = _owned_sub(db, user_id, account_id)
    acc.is_enabled = True
    db.commit()
    return {"message": f"worker {(acc.note or '未命名子账户')} 已启用(约10s内拉起)"}


def _live_worker_scopes(db: Session, user_id: int) -> list[str]:
    """当前仍存在【且已启用】的子账户对应的 worker scope。用于过滤掉:
    ① 已删除子账户残留的 engine_state(sub:N)僵尸行;
    ② 已停用(is_enabled=false)子账户的 worker —— 它们 status=STOPPED、心跳永久过期,
       不该被算作「超时」(超时仅指 RUNNING 却心跳卡死的 worker)。"""
    sub_ids = [r.id for r in db.query(SubAccount.id).filter(
        SubAccount.user_id == user_id, SubAccount.is_enabled == True,
    ).all()]
    return [f"sub:{i}" for i in sub_ids]


@router.get("/workers/status")
def workers_status(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    global_state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    alive = False
    try:
        alive = _command_consumer_alive(_redis())
    except Exception:
        pass
    scopes = _live_worker_scopes(db, user_id)
    if not scopes:
        # Keep the global transition visible even before the orchestrator has
        # spawned its first account task (normally a few seconds after start).
        return {
            "workers": [],
            "engine_status": _display_engine_status(
                global_state,
                command_consumer=alive,
            ),
            "command_consumer": alive,
        }
    workers = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope.in_(scopes),
    ).all()
    return {
        "workers": [_worker_payload(w, db, user_id) for w in workers],
        "engine_status": _display_engine_status(
            global_state,
            command_consumer=alive,
        ),
        "command_consumer": alive,
    }

STUCK_STATUSES = {
    "PENDING_BORROW", "BORROW_SUBMITTING", "BORROW_OUTCOME_UNKNOWN",
    "BORROWED", "SPOT_SOLD",
    "CLOSING_FUTURES", "FUTURES_CLOSED", "CLOSING_SPOT", "SPOT_BOUGHT", "REPAYING",
}
HEARTBEAT_STALE_SEC = 120


def _valid_inventory_probe_rate(value, fallback: float = 2.0) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return fallback
    return rate if 0 < rate <= 10 else fallback


def _inventory_probe_health_config(
    db: Session,
    user_id: int,
) -> tuple[float, float, dict[str, float]]:
    """Return tenant-scoped configured available-inventory GET rates."""
    from app.db.models import GlobalRules

    system_rules = db.query(GlobalRules).filter(
        GlobalRules.user_id.is_(None)
    ).order_by(GlobalRules.id).first()
    user_rules = db.query(GlobalRules).filter(
        GlobalRules.user_id == user_id
    ).first()
    system_value = getattr(system_rules, "inventory_probe_rate_per_sec", None)
    user_value = getattr(user_rules, "inventory_probe_rate_per_sec", None)
    # ConfigLoader runs each tenant's Worker from that tenant's GlobalRules
    # row.  Health must use the same precedence or the dashboard can advertise
    # the system default while the Worker polls at a different cadence.
    configured_default = _valid_inventory_probe_rate(
        user_value if user_value is not None else system_value
    )
    accounts = db.query(SubAccount).filter(
        SubAccount.user_id == user_id,
        SubAccount.is_enabled == True,
    ).all()
    account_rates = _inventory_probe_rates_by_account(accounts, configured_default)
    aggregate_rate = round(sum(account_rates.values()), 2)
    return round(configured_default, 2), aggregate_rate, account_rates


def _inventory_candidate_health(
    redis_client,
    user_id: int,
    account_ids,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Read only Worker-published, tenant/account-scoped candidate snapshots."""
    counts: dict[str, int] = {}
    members: dict[str, list[str]] = {}
    for raw_account_id in account_ids:
        try:
            account_id = int(raw_account_id)
            raw = redis_client.get(
                f"engine:{int(user_id)}:inventory_candidates:{account_id}"
            )
            parsed = json.loads(raw) if raw is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, list):
            continue
        normalized = sorted({
            str(symbol).strip().upper()
            for symbol in parsed
            if isinstance(symbol, str)
            and str(symbol).strip().upper().endswith("USDT")
            and str(symbol).strip().upper() != "USDT"
            and str(symbol).strip().upper().isalnum()
        })
        key = str(account_id)
        counts[key] = len(normalized)
        members[key] = normalized
    return counts, members


def _inventory_rate_per_candidate(
    account_rates: dict[str, float],
    candidate_counts: dict[str, int],
) -> float:
    """Return the tenant's candidate-aware inventory GET allocation.

    A pushed-list count is only an opportunity-set size and can include
    symbols that fail an account's executable gates.  Health consumers that
    still read the legacy ``throttle_rate`` field must use the same Worker
    candidate snapshots as the explicit inventory fields, otherwise a push or
    removal leaves a stale/incorrect denominator until the old list changes.
    """
    total_candidates = 0
    total_rate = 0.0
    for account_id, raw_count in candidate_counts.items():
        try:
            count = max(0, int(raw_count))
            raw_rate = account_rates.get(str(account_id), account_rates.get(account_id, 0.0))
            rate = float(raw_rate)
        except (TypeError, ValueError, OverflowError):
            continue
        if count <= 0 or not math.isfinite(rate) or rate <= 0:
            continue
        total_candidates += count
        total_rate += rate
    if total_candidates <= 0:
        return 0.0
    return round(total_rate / total_candidates, 3)


def _fresh_inventory_worker_accounts(worker_rows, now, *, max_age: float = HEARTBEAT_STALE_SEC) -> set[str]:
    """Return accounts whose Worker can currently own a candidate snapshot.

    Candidate keys are deliberately short-lived, but a crashed Worker can
    leave its last key visible until TTL expiry.  Health must not treat that
    telemetry as an executable opportunity set while the persisted Worker
    heartbeat is stopped or stale.
    """
    fresh: set[str] = set()
    for worker in worker_rows or ():
        if getattr(worker, "status", None) != "RUNNING":
            continue
        heartbeat = getattr(worker, "last_heartbeat", None)
        if heartbeat is None:
            continue
        try:
            # SQLite and a few legacy drivers return timezone-naive values
            # even for a timezone-aware column; production heartbeats are UTC.
            if getattr(heartbeat, "tzinfo", None) is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            age = (now - heartbeat).total_seconds()
        except (AttributeError, TypeError, ValueError):
            continue
        if age < 0 or age > max_age:
            continue
        account_id = _worker_account_id(getattr(worker, "scope", ""))
        if account_id is not None:
            fresh.add(str(account_id))
    return fresh


def _scoped_uid_weight_snapshot(
    snapshot: object,
    account_ids: set[str] | list[str] | tuple[str, ...],
    *,
    now_ts: float | None = None,
) -> tuple[int, int]:
    """Return the freshest-account UID weight without cross-tenant leakage."""
    owned = {str(value) for value in account_ids}
    if not owned or not isinstance(snapshot, dict):
        return 0, 0
    current = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    rows: list[tuple[int, int]] = []
    for account_id in owned:
        item = snapshot.get(account_id)
        if not isinstance(item, dict):
            continue
        try:
            stamp = float(item.get("uid_weight_time", 0) or 0)
            age = current - stamp if stamp > 0 else float("inf")
            if age > 60:
                continue
            rows.append((
                max(0, int(item.get("used_uid_weight_1m", 0) or 0)),
                max(0, int(item.get("uid_limit", 180000) or 180000)),
            ))
        except (TypeError, ValueError, OverflowError):
            continue
    return max(rows, key=lambda row: row[0]) if rows else (0, 0)


@router.get("/health", response_model=HealthResponse)
def engine_health(request: Request, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    from engine.metrics import all_metrics_snapshot
    from app.services.spread_reader import spread_reader

    user_id = get_current_user_id(request)

    global_state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    now = datetime.now(timezone.utc)
    scopes = _live_worker_scopes(db, user_id)
    worker_rows = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope.in_(scopes),
    ).all() if scopes else []

    workers = []
    any_stale = False
    for w in worker_rows:
        stale = False
        # 仅 RUNNING 的 worker 才判「超时」:STOPPED 是主动停用,本就不更新心跳,标超时是误报
        if w.status == "RUNNING" and w.last_heartbeat:
            delta = (now - w.last_heartbeat).total_seconds()
            stale = delta > HEARTBEAT_STALE_SEC
        if stale:
            any_stale = True
        account_id = _worker_account_id(w.scope)
        account = db.query(SubAccount).filter(
            SubAccount.id == account_id,
            SubAccount.user_id == user_id,
        ).first() if account_id is not None else None
        workers.append(WorkerHealth(
            account_id=account_id or 0,
            account_note=account.note if account and account.note else ("未命名子账户" if account_id is not None else w.scope),
            scope=w.scope,
            status=w.status,
            last_heartbeat=w.last_heartbeat,
            heartbeat_stale=stale,
            active_positions=w.active_positions or 0,
            total_cycles=w.total_cycles or 0,
            error_message=w.error_message,
        ))

    stuck = []
    stuck_rows = db.query(Position).filter(
        Position.user_id == user_id,
        Position.status.in_(STUCK_STATUSES),
    ).all()
    from engine.fund.health_monitor import position_is_stuck, position_stuck_minutes
    for p in stuck_rows:
        if not position_is_stuck(p, now):
            continue
        mins = position_stuck_minutes(p, now)
        stuck.append(StuckPosition(
            id=p.id,
            symbol=p.symbol,
            sub_account_id=p.sub_account_id,
            status=p.status,
            stuck_minutes=mins,
            error_message=p.error_message,
        ))

    total_open = db.query(Position).filter(
        Position.user_id == user_id, Position.status == "OPEN",
    ).count()

    raw_metrics = all_metrics_snapshot()
    api_metrics = {k: APIMetricsResponse(**v) for k, v in raw_metrics.items()}

    spread_health = spread_reader.health()
    spread_count = spread_health.get("active_symbols", 0)

    # Host-level command consumer liveness is separate from tenant Worker
    # rows.  The API can remain healthy while cex-worker.service is stopped;
    # expose that distinction so the dashboard does not report a queued
    # STARTING command as a live engine.
    command_consumer = False
    try:
        command_consumer = _command_consumer_alive(_redis())
    except Exception:
        command_consumer = False
    engine_status = _display_engine_status(
        global_state,
        command_consumer=command_consumer,
        now=now,
    )

    overall = "HEALTHY"
    if engine_status in ("STOPPED", "ERROR"):
        overall = "UNHEALTHY"
    elif engine_status in ("STARTING", "STOPPING") and not command_consumer:
        overall = "UNHEALTHY"
    elif any_stale or len(stuck) > 0:
        overall = "DEGRADED"

    # uptime from global engine state
    uptime_sec = None
    if global_state and global_state.started_at and engine_status == "RUNNING":
        uptime_sec = int((now - global_state.started_at).total_seconds())

    # IP-wide used weight (published to Redis by engine workers + balance_pusher)
    used_weight, weight_limit, weight_age = 0, 6000, None
    uid_used, uid_limit = 0, 180000   # Binance signed API UID rolling weight; defined even when Redis is unavailable
    owned_account_ids = {
        str(row.id) for row in db.query(SubAccount.id).filter(
            SubAccount.user_id == user_id,
        ).all()
    }
    uid_scope_available = bool(owned_account_ids)
    if not uid_scope_available:
        # UID weight is per Binance account. Never expose the process-wide
        # busiest UID to a tenant that has no bound account.
        uid_limit = 0
    throttle_rate = 0.0
    configured_default_rate = 3.9
    borrow_route_ceiling = 2.0
    inventory_probe_rate = 2.0
    aggregate_inventory_probe_rate = 0.0
    account_inventory_probe_rates: dict[str, float] = {}
    account_inventory_candidate_counts: dict[str, int] = {}
    account_inventory_candidate_symbols: dict[str, list[str]] = {}
    try:
        (
            inventory_probe_rate,
            aggregate_inventory_probe_rate,
            account_inventory_probe_rates,
        ) = _inventory_probe_health_config(db, user_id)
    except Exception:
        logger.exception("Failed to resolve inventory probe health configuration")
    try:
        from app.db.models import GlobalRules
        from engine.trading.binance_trading import borrow_route_rate_ceiling

        user_rate_rules = db.query(GlobalRules).filter(
            GlobalRules.user_id == user_id
        ).first()
        system_rate_rules = db.query(GlobalRules).filter(
            GlobalRules.user_id.is_(None)
        ).order_by(GlobalRules.id).first()
        route_rules = system_rate_rules or user_rate_rules
        configured_default_rate = float(
            getattr(route_rules, "borrow_rate_per_sec", None)
            or getattr(user_rate_rules, "borrow_rate_per_sec", None)
            or 3.9
        )
        route_mode = getattr(route_rules, "borrow_mode", None)
        if not route_mode:
            route_mode = (
                "otoco"
                if bool(getattr(route_rules, "borrow_via_otoco", False))
                else "repay"
            )
        borrow_route_ceiling = borrow_route_rate_ceiling(
            route_mode, int(getattr(route_rules, "otoco_legs", 2) or 2)
        )
    except Exception:
        # Unknown configuration must retain the direct borrow-repay ceiling.
        pass
    try:
        r = _redis()
        # A candidate snapshot is owned by a live Worker, not merely by an
        # enabled DB account.  Exclude stopped/stale workers from the member
        # set so a crash cannot advertise old candidates until key TTL expiry.
        candidate_account_ids = _fresh_inventory_worker_accounts(worker_rows, now)
        (
            account_inventory_candidate_counts,
            account_inventory_candidate_symbols,
        ) = _inventory_candidate_health(
            r,
            user_id,
            candidate_account_ids,
        )
        raw = r.get("engine:weight:latest")
        if raw:
            wd = json.loads(raw)
            used_weight = int(wd.get("used_weight_1m", 0))
            weight_limit = int(wd.get("limit", 6000))
            if wd.get("weight_time"):
                weight_age = int(datetime.now(timezone.utc).timestamp() - float(wd["weight_time"]))
        # UID weight is per Binance account. The legacy ``latest`` key is a
        # process-wide max and must never be used for tenant health. Filter
        # the account-keyed snapshot strictly to this user's bound accounts.
        pa_raw = r.get("engine:uid_weight:by_account")
        pa = json.loads(pa_raw) if pa_raw else {}
        uid_used, scoped_limit = _scoped_uid_weight_snapshot(
            pa, owned_account_ids,
        )
        if uid_scope_available:
            uid_limit = scoped_limit or 180000
        # ``throttle_rate`` is retained for older clients, but its denominator
        # must follow the Worker-published executable candidate set.  Using the
        # raw pushed-list length made the value lag after a push/removal and
        # counted symbols that this account could not actually probe.
        throttle_rate = _inventory_rate_per_candidate(
            account_inventory_probe_rates,
            account_inventory_candidate_counts,
        )
    except Exception:
        pass

    # Aggregate borrow rate for the dashboard — folds in the two real ceilings so the
    # number reflects what can actually be sustained, not an inflated paper sum:
    #   (1) Route cap: direct borrow-repay is 2/s; supported MARGIN_BUY routes
    #       are order-count governed and can target 3.9/s.
    #   (2) Shared IP budget: the borrow call is 0 IP weight, but each borrow cycle drags
    #       read calls (interest/lot/book) off the host-wide IP budget. That shared budget
    #       caps the whole host's borrow cadence no matter how many UIDs are added.
    # Conservative IP weight charged by the reads around one borrow cycle; calibrate from
    # the per-cycle X-SAPI-USED-IP-WEIGHT-1M delta if it needs tightening.
    IP_WEIGHT_PER_BORROW_CYCLE = 10
    agg_borrow_rate = 0.0
    single_borrow_rate = 0.0
    actual_borrow_rate = 0.0
    try:
        default_rate = configured_default_rate
        subs = db.query(SubAccount).filter(
            SubAccount.user_id == user_id, SubAccount.is_enabled == True,
        ).all()
        uid_capped_sum = sum(
            min(float(s.borrow_rate_per_sec) if s.borrow_rate_per_sec else default_rate, borrow_route_ceiling)
            for s in subs
        )
        # host-shared IP ceiling (steady-state from the published IP weight limit)
        ip_host_ceiling = (weight_limit / IP_WEIGHT_PER_BORROW_CYCLE / 60) if weight_limit else float("inf")
        agg_borrow_rate = round(min(uid_capped_sum, ip_host_ceiling), 2)
        # 单UID建仓速率: 实时实际速率 = 最近60s内最忙子账户成功借币(TradeLog action=BORROW)次数 / 60。
        # 反映引擎此刻真正的单账户建仓节奏(非理论上限);无近期借币则为 0。
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        rows = (db.query(TradeLog.sub_account_id, func.count(TradeLog.id))
                .filter(TradeLog.user_id == user_id,
                        TradeLog.action == "BORROW",
                        TradeLog.status == "SUCCESS",
                        TradeLog.created_at >= cutoff)
                .group_by(TradeLog.sub_account_id).all())
        max_cnt = max((c for _, c in rows), default=0)
        single_borrow_rate = round(max_cnt / 60.0, 2)
        actual_borrow_rate = round(sum(int(c) for _, c in rows) / 60.0, 2)
    except Exception:
        pass

    # 逐子账户可借速率:direct 路径按 UID 余量；order 路径按订单路由硬顶。
    account_borrow_rates: dict[str, float] = {}
    try:
        default_rate2 = configured_default_rate
        now_ts = datetime.now(timezone.utc).timestamp()
        pa_raw = r.get("engine:uid_weight:by_account")
        pa = json.loads(pa_raw) if pa_raw else {}
        subs2 = db.query(SubAccount).filter(
            SubAccount.user_id == user_id, SubAccount.is_enabled == True,
        ).all()
        for s in subs2:
            cfg = float(s.borrow_rate_per_sec) if s.borrow_rate_per_sec else default_rate2
            d = pa.get(str(s.id))
            used = 0
            lim = 180000
            if d:
                wt = float(d.get("uid_weight_time", 0) or 0)
                age = now_ts - wt if wt > 0 else 1e9
                used = int(d.get("used_uid_weight_1m", 0)) if age <= 60 else 0
                lim = int(d.get("uid_limit", 180000) or 180000)
            ceiling = (
                max(0.0, (lim - used)) / 1500 / 60
                if borrow_route_ceiling <= 2.0
                else borrow_route_ceiling
            )
            account_borrow_rates[str(s.id)] = round(min(ceiling, cfg), 2)
    except Exception:
        pass

    return HealthResponse(
        status=overall,
        engine_status=engine_status,
        command_consumer=command_consumer,
        workers=workers,
        stuck_positions=stuck,
        open_positions=total_open,
        api_metrics=api_metrics,
        spread_count=spread_count,
        uptime_sec=uptime_sec,
        used_weight_1m=used_weight,
        weight_limit=weight_limit,
        weight_age_sec=weight_age,
        uid_used_1m=uid_used,
        uid_limit=uid_limit,
        throttle_rate=throttle_rate,
        agg_borrow_rate=agg_borrow_rate,
        single_borrow_rate=single_borrow_rate,
        actual_borrow_rate=actual_borrow_rate,
        uid_scope_available=uid_scope_available,
        account_borrow_rates=account_borrow_rates,
        inventory_probe_rate=inventory_probe_rate,
        aggregate_inventory_probe_rate=aggregate_inventory_probe_rate,
        account_inventory_probe_rates=account_inventory_probe_rates,
        account_inventory_candidate_counts=account_inventory_candidate_counts,
        account_inventory_candidate_symbols=account_inventory_candidate_symbols,
    )
