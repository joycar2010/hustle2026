"""
MT5 Bridge Microservice  v2.0
Windows Server 2025 专用 — 支持多终端实例、完整14端点
端口: 8001（系统主账户）| 8002（用户账户，可选）

端点清单 (对应 Go mt5/handler.go 12条路由 + 额外交易端点):
  GET  /health
  GET  /mt5/connection/status
  POST /mt5/connection/reconnect
  GET  /mt5/positions
  GET  /mt5/account/balance
  GET  /mt5/account/info
  GET  /mt5/symbols
  GET  /mt5/tick/{symbol}
  GET  /mt5/history/deals
  GET  /mt5/history/orders
  POST /mt5/order
  POST /mt5/position/close
  POST /mt5/position/close-all
  POST /mt5/cancel-all
"""

import asyncio
import contextvars
import hashlib
import json
import os
import time
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Optional, List, Dict, Any

import MetaTrader5 as mt5
from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from .runtime import (
    DurableExecutionCoordinator,
    ExecutionBusy,
    ExecutionOutcome,
    IntentConflict,
    ProcessIsolatedExecutionCoordinator,
    PrioritizedSingleThreadExecutor,
    PositionSnapshotCache,
    TradeAdmissionGate,
    mark_execution_dispatching,
)

load_dotenv()

# ─── 日志 ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mt5-bridge")

# ─── 配置（从 .env 读取）────────────────────────────────────────────────────
API_KEY        = os.getenv("API_KEY",           "<REDACTED_API_KEY>")
MT5_LOGIN      = int(os.getenv("MT5_LOGIN",     "0"))
MT5_PASSWORD   = os.getenv("MT5_PASSWORD",      "")
MT5_SERVER     = os.getenv("MT5_SERVER",        "Bybit-Live-2")
MT5_PATH       = os.getenv("MT5_PATH",          r"C:\Program Files\MetaTrader 5\terminal64.exe")
SERVICE_PORT   = int(os.getenv("SERVICE_PORT",  "8001"))
INSTANCE_NAME  = os.getenv("INSTANCE_NAME",     "system")   # 'system' | 'cq987'
BRIDGE_BUILD_ID = os.getenv(
    "MT5_BRIDGE_BUILD_ID", "mt5-trade-wake-priority-20260817.4"
)
POSITIONS_CACHE_TTL_MS = max(0, int(os.getenv("POSITIONS_CACHE_TTL_MS", "150")))
POSITIONS_STALE_MAX_MS = max(POSITIONS_CACHE_TTL_MS, int(os.getenv("POSITIONS_STALE_MAX_MS", "2000")))
# A positions poll must never hold the FastAPI event loop behind an active
# trade burst.  After this bounded wait the snapshot cache serves its last
# known value (within POSITIONS_STALE_MAX_MS), or the caller gets a clear 503
# when no authoritative snapshot exists yet.
POSITIONS_READ_GATE_WAIT_MS = max(
    0, min(250, int(os.getenv("POSITIONS_READ_GATE_WAIT_MS", "25")))
)
# Keep the small gaps between multi-slot commands inside one trade burst.
# The native priority queue already keeps admitted trades ahead of ordinary
# reads, so a long quiet window only delays the first broker-fresh UI snapshot
# after the final fill. 75 ms still coalesces adjacent clicks while keeping the
# post-fill refresh inside the 0.5 s application budget whenever broker ACK is
# itself subsecond.
POSITIONS_TRADE_QUIET_MS = max(
    0,
    min(
        POSITIONS_STALE_MAX_MS,
        int(os.getenv("POSITIONS_TRADE_QUIET_MS", "75")),
    ),
)
# Public quote polling must not repeatedly enter the account-scoped native
# owner. A short request cache coalesces UI/sampler reads, while trade bursts
# may use the last snapshot regardless of this fresh-cache TTL.
PUBLIC_TICK_CACHE_TTL_MS = max(
    0, int(os.getenv("MT5_PUBLIC_TICK_CACHE_TTL_MS", "250"))
)
# Symbol contract metadata changes infrequently, while a burst of orders can
# otherwise pay one native ``symbol_info`` round trip per request. Keep this
# short so broker-side precision/filling changes are picked up regularly.
SYMBOL_INFO_CACHE_TTL_MS = max(0, int(os.getenv("SYMBOL_INFO_CACHE_TTL_MS", "1000")))
POST_TRADE_SNAPSHOT_GRACE_MS = max(
    0, min(500, int(os.getenv("POST_TRADE_SNAPSHOT_GRACE_MS", "50")))
)
ACCOUNT_SNAPSHOT_TTL_MS = max(100, int(os.getenv("ACCOUNT_SNAPSHOT_TTL_MS", "1000")))
ACCOUNT_SNAPSHOT_STALE_MAX_MS = max(
    ACCOUNT_SNAPSHOT_TTL_MS,
    int(os.getenv("ACCOUNT_SNAPSHOT_STALE_MAX_MS", "15000")),
)
ACCOUNT_IDLE_REFRESH_SEC = max(
    1.0, float(os.getenv("ACCOUNT_IDLE_REFRESH_SEC", "5"))
)
ACCOUNT_HISTORY_REFRESH_SEC = max(
    ACCOUNT_IDLE_REFRESH_SEC,
    float(os.getenv("ACCOUNT_HISTORY_REFRESH_SEC", "60")),
)
EXEC_SYNC_WAIT_SEC = max(0.05, float(os.getenv("EXEC_SYNC_WAIT_SEC", "0.85")))
REQUOTE_RETRIES = min(2, max(0, int(os.getenv("MT5_REQUOTE_RETRIES", "1"))))
IDEMPOTENCY_DB = os.getenv("IDEMPOTENCY_DB", os.path.join(os.getcwd(), "idempotency.db"))
EXECUTION_PROCESS_ISOLATION = str(os.getenv(
    "MT5_EXECUTION_PROCESS_ISOLATION", "0"
)).strip().lower() in ("1", "true", "yes", "on")
_EXECUTION_CHILD = str(os.getenv("MT5_EXECUTION_CHILD", "0")).strip() == "1"
EXECUTION_FENCE_KEY = os.getenv(
    "MT5_EXECUTION_FENCE_KEY",
    "%s|%s" % (str(MT5_SERVER).strip().lower(), MT5_LOGIN),
)
PARENT_NATIVE_READ_GATE_WAIT_MS = max(100, int(os.getenv(
    "MT5_PARENT_READ_GATE_WAIT_MS", "5000"
)))
SHUTDOWN_STEP_SEC = max(0.1, float(os.getenv("MT5_SHUTDOWN_STEP_SEC", "2")))
EXECUTION_SHUTDOWN_SEC = max(
    SHUTDOWN_STEP_SEC,
    float(os.getenv("MT5_EXECUTION_SHUTDOWN_BUDGET_SEC", "22")),
)

# ─── FastAPI ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title=f"MT5 Bridge [{INSTANCE_NAME}]",
    version="3.0.0",
    description="Hustle2026 MT5 Windows Microservice",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 安全 ─────────────────────────────────────────────────────────────────────
def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

# ────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ────────────────────────────────────────────────────────────────────────────
class OrderRequest(BaseModel):
    symbol: str
    volume: float
    order_type: str          # "buy" | "sell" | "buy_limit" | "sell_limit"
    price: Optional[float]   = None
    sl:    Optional[float]   = None
    tp:    Optional[float]   = None
    deviation: int           = 10
    comment:   str           = ""
    position_ticket: Optional[int] = None  # 用于平仓
    request_id: Optional[str] = None  # M2幂等键(V1.1 §9.2): 同键重放只返回原结果
    ack_only: bool = False

class ClosePositionRequest(BaseModel):
    symbol: Optional[str] = None
    side: Optional[str] = None
    volume: Optional[float] = None
    ticket: Optional[int]   = None
    request_id: Optional[str] = None
    ack_only: bool = False

class CloseAllRequest(BaseModel):
    symbol: Optional[str] = None   # None = 全部品种
    request_id: Optional[str] = None
    ack_only: bool = False

class CancelAllRequest(BaseModel):
    symbol: Optional[str] = None
    request_id: Optional[str] = None
    ack_only: bool = False


# MetaTrader5's C extension is account/terminal scoped and must remain on one
# native thread.  Trade calls use the urgent lane; high-frequency positions
# reads use the background lane and cannot build a FIFO ahead of a trade.
MT5_API_PRIORITY_TRADE = 0
MT5_API_PRIORITY_NORMAL = 10
MT5_API_PRIORITY_POSITIONS = 50
_MT5_CALL_PRIORITY = contextvars.ContextVar("mt5_call_priority", default=None)
_MT5_NATIVE_TRACE = contextvars.ContextVar("mt5_native_trace", default=None)
_MT5_READ_GATE_HELD = contextvars.ContextVar("mt5_read_gate_held", default=False)
_MT5_API_EXECUTOR = PrioritizedSingleThreadExecutor(thread_name_prefix="mt5-api")
# Keep durable order-status reads out of asyncio's default executor. Native
# account reads can legitimately wait behind a trade burst; status must not.
_ORDER_STATUS_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="mt5-order-status"
)
# FastAPI's default asyncio executor is also used by unrelated application
# tasks. Keep bridge control reads (health, account, quotes, positions) in a
# bounded pool so a burst of status polling cannot delay the next refresh.
_CONTROL_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(4, min(16, int(os.getenv("MT5_CONTROL_WORKERS", "8")))),
    thread_name_prefix="mt5-control",
)
_MT5_TRADE_GATE = TradeAdmissionGate()
_SYMBOL_INFO_CACHE_LOCK = threading.RLock()
_SYMBOL_INFO_CACHE = {}
_TICK_SNAPSHOT_LOCK = threading.RLock()
_TICK_SNAPSHOTS = {}
_TICK_REFRESH_LOCKS = {}
_TICK_SNAPSHOT_GENERATION = 0
_CONNECTION_ACCOUNT_CACHE_LOCK = threading.RLock()
_ACCOUNT_SNAPSHOT_REFRESH_LOCK = threading.Lock()
_ACCOUNT_SNAPSHOT_REFRESH_TASK = None
_ACCOUNT_CACHE_UNSET = object()
_CONTROL_READ_DEFERRED = object()
_CONNECTION_ACCOUNT_CACHE = {
    "payload": None,
    "complete": False,
    "balance": None,
    "equity": None,
    "updated_at": 0.0,
    "refreshed_at": 0.0,
    "snapshot_ts_ms": 0,
    "history_refreshed_at": 0.0,
    "history_snapshot_ts_ms": 0,
}
_TERMINAL_INFO_CACHE_LOCK = threading.RLock()
_TERMINAL_INFO_CACHE = {
    "trade_allowed": None,
    "refreshed_at": 0.0,
    "snapshot_ts_ms": 0,
}


_ACCOUNT_INFO_FIELDS = (
    "login", "balance", "equity", "margin", "margin_free", "margin_level",
    "margin_so_call", "margin_so_so", "margin_so_mode", "profit", "currency",
    "leverage", "server", "name", "company",
)


def _serialize_account_info(info):
    return {
        field: getattr(info, field, None)
        for field in _ACCOUNT_INFO_FIELDS
    }


def _cache_connection_account(info, total_swap=_ACCOUNT_CACHE_UNSET):
    if info is None:
        return
    now_mono = time.monotonic()
    now_wall = time.time()
    now_ms = time.time_ns() // 1_000_000
    fields = _serialize_account_info(info)
    with _CONNECTION_ACCOUNT_CACHE_LOCK:
        payload = dict(_CONNECTION_ACCOUNT_CACHE.get("payload") or {})
        payload.update(fields)
        if total_swap is not _ACCOUNT_CACHE_UNSET:
            payload["swap"] = round(float(total_swap or 0.0), 2)
            _CONNECTION_ACCOUNT_CACHE.update({
                "complete": True,
                "history_refreshed_at": now_mono,
                "history_snapshot_ts_ms": now_ms,
            })
        else:
            payload.setdefault("swap", None)
        _CONNECTION_ACCOUNT_CACHE.update(payload)
        _CONNECTION_ACCOUNT_CACHE.update({
            "payload": payload,
            "updated_at": now_wall,
            "refreshed_at": now_mono,
            "snapshot_ts_ms": now_ms,
        })


def _cached_connection_account():
    with _CONNECTION_ACCOUNT_CACHE_LOCK:
        return dict(_CONNECTION_ACCOUNT_CACHE)


def _cached_connection_identity():
    """Return the last broker-proved login without performing native I/O."""
    cached = _cached_connection_account()
    payload = cached.get("payload")
    refreshed_at = float(cached.get("refreshed_at") or 0.0)
    age_ms = (
        max(0.0, (time.monotonic() - refreshed_at) * 1000.0)
        if refreshed_at else None
    )
    actual_login = None
    if isinstance(payload, dict):
        try:
            actual_login = int(payload.get("login"))
        except (TypeError, ValueError):
            actual_login = None
    fresh = bool(
        actual_login is not None
        and age_ms is not None
        and age_ms <= ACCOUNT_SNAPSHOT_STALE_MAX_MS
    )
    return {
        "actual_login": actual_login,
        "expected_login": MT5_LOGIN,
        "verified": bool(fresh and actual_login == MT5_LOGIN),
        "fresh": fresh,
        "age_ms": round(age_ms, 3) if age_ms is not None else None,
        "snapshot_ts_ms": int(cached.get("snapshot_ts_ms") or 0),
    }


def _invalidate_account_snapshot():
    with _CONNECTION_ACCOUNT_CACHE_LOCK:
        # Drop flattened account fields as well as the canonical payload. A
        # reconnect must never expose values from the previous MT5 session.
        _CONNECTION_ACCOUNT_CACHE.clear()
        _CONNECTION_ACCOUNT_CACHE.update({
            "payload": None,
            "complete": False,
            "balance": None,
            "equity": None,
            "updated_at": 0.0,
            "refreshed_at": 0.0,
            "snapshot_ts_ms": 0,
            "history_refreshed_at": 0.0,
            "history_snapshot_ts_ms": 0,
        })


def _account_snapshot_view(source="cache", trade_activity=False,
                           require_complete=True):
    with _CONNECTION_ACCOUNT_CACHE_LOCK:
        cached = dict(_CONNECTION_ACCOUNT_CACHE)
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        if require_complete and not cached.get("complete"):
            return None
        refreshed_at = float(cached.get("refreshed_at") or 0.0)
        if not refreshed_at:
            return None
        age_ms = max(0.0, (time.monotonic() - refreshed_at) * 1000)
        if age_ms > ACCOUNT_SNAPSHOT_STALE_MAX_MS:
            return None
        history_refreshed_at = float(cached.get("history_refreshed_at") or 0.0)
        history_age_ms = (max(0.0, (time.monotonic() - history_refreshed_at) * 1000)
                          if history_refreshed_at else None)
        response = dict(payload)
        response.update({
            "account_snapshot_ts_ms": int(cached.get("snapshot_ts_ms") or 0),
            "account_snapshot_age_ms": round(age_ms, 3),
            "account_snapshot_source": str(source),
            # Trading responses are deliberately cache-only even when the
            # snapshot is only a few milliseconds old. Mark that explicitly
            # so callers do not mistake it for a request-time broker read.
            "account_snapshot_stale": (
                bool(trade_activity) or age_ms >= ACCOUNT_SNAPSHOT_TTL_MS
            ),
            "account_snapshot_trade_activity": bool(trade_activity),
            "account_snapshot_complete": bool(cached.get("complete")),
            "account_history_ts_ms": int(cached.get("history_snapshot_ts_ms") or 0),
            "account_history_age_ms": (round(history_age_ms, 3)
                                       if history_age_ms is not None else None),
        })
        return response


def _history_refresh_due():
    with _CONNECTION_ACCOUNT_CACHE_LOCK:
        refreshed_at = float(_CONNECTION_ACCOUNT_CACHE.get("history_refreshed_at") or 0.0)
        complete = bool(_CONNECTION_ACCOUNT_CACHE.get("complete"))
    return (not complete or not refreshed_at or
            time.monotonic() - refreshed_at >= ACCOUNT_HISTORY_REFRESH_SEC)


def _periodic_history_refresh_due():
    # Process isolation uses the startup prewarm as the one 30-day history
    # load. Runtime refreshes keep core account fields fresh without putting a
    # long history RPC in front of newly admitted broker commands.
    return bool(not EXECUTION_PROCESS_ISOLATION and _history_refresh_due())


def _cache_terminal_info(info):
    if info is None:
        return
    value = getattr(info, "trade_allowed", None)
    with _TERMINAL_INFO_CACHE_LOCK:
        _TERMINAL_INFO_CACHE.update({
            "trade_allowed": (bool(value) if value is not None else None),
            "refreshed_at": time.monotonic(),
            "snapshot_ts_ms": time.time_ns() // 1_000_000,
        })


def _cached_terminal_info():
    with _TERMINAL_INFO_CACHE_LOCK:
        cached = dict(_TERMINAL_INFO_CACHE)
    refreshed_at = float(cached.get("refreshed_at") or 0.0)
    cached["age_ms"] = (
        round(max(0.0, (time.monotonic() - refreshed_at) * 1000), 3)
        if refreshed_at else None
    )
    return cached


def _invalidate_terminal_info_cache():
    with _TERMINAL_INFO_CACHE_LOCK:
        _TERMINAL_INFO_CACHE.update({
            "trade_allowed": None,
            "refreshed_at": 0.0,
            "snapshot_ts_ms": 0,
        })


def _clear_symbol_info_cache():
    with _SYMBOL_INFO_CACHE_LOCK:
        _SYMBOL_INFO_CACHE.clear()


def _tick_key(symbol):
    return str(symbol or "").strip()


def _tick_refresh_lock(symbol):
    key = _tick_key(symbol)
    with _TICK_SNAPSHOT_LOCK:
        lock = _TICK_REFRESH_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _TICK_REFRESH_LOCKS[key] = lock
        return lock


def _clear_tick_snapshots():
    # Keep the per-symbol asyncio locks: an in-flight request may still hold
    # one while a reconnect invalidates its snapshot.
    global _TICK_SNAPSHOT_GENERATION
    with _TICK_SNAPSHOT_LOCK:
        _TICK_SNAPSHOTS.clear()
        _TICK_SNAPSHOT_GENERATION += 1


def _tick_snapshot_generation():
    with _TICK_SNAPSHOT_LOCK:
        return _TICK_SNAPSHOT_GENERATION


def _tick_payload(symbol, tick):
    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "last": tick.last,
        "volume": tick.volume,
        "time": tick.time,
        "time_msc": tick.time_msc,
    }


def _store_tick_snapshot(symbol, tick, generation=None):
    key = _tick_key(symbol)
    payload = _tick_payload(key, tick)
    with _TICK_SNAPSHOT_LOCK:
        if (generation is not None and
                int(generation) != _TICK_SNAPSHOT_GENERATION):
            return None
        _TICK_SNAPSHOTS[key] = {
            "payload": payload,
            "refreshed_at": time.monotonic(),
        }
    response = dict(payload)
    response.update({
        "from_cache": False,
        "age_ms": 0.0,
        "snapshot_source": "broker",
    })
    return response


def _tick_snapshot_view(symbol, source, allow_stale=False):
    key = _tick_key(symbol)
    with _TICK_SNAPSHOT_LOCK:
        snapshot = _TICK_SNAPSHOTS.get(key)
        if snapshot is None:
            return None
        payload = dict(snapshot["payload"])
        refreshed_at = float(snapshot["refreshed_at"])
    age_ms = max(0.0, (time.monotonic() - refreshed_at) * 1000.0)
    if not allow_stale and age_ms > PUBLIC_TICK_CACHE_TTL_MS:
        return None
    payload.update({
        "from_cache": True,
        "age_ms": round(age_ms, 3),
        "snapshot_source": str(source),
    })
    return payload


def _is_native_trade_callable(func):
    """MetaTrader5._core trade calls need a positional request inside the worker.

    The extension rejects a direct positional argument submitted through
    ``executor.submit(func, request)`` (``-2``), while a keyword request is
    silently converted to an empty request.  A closure keeps the call on the
    dedicated MT5 thread without changing the extension's native signature.
    """
    return (
        getattr(func, "__module__", "") == "MetaTrader5._core"
        and getattr(func, "__name__", "") in {"order_send", "order_check"}
    )


def _default_mt5_priority(func):
    name = getattr(func, "__name__", "")
    if name in {"order_send", "order_check"}:
        return MT5_API_PRIORITY_TRADE
    if name == "positions_get":
        return MT5_API_PRIORITY_POSITIONS
    return MT5_API_PRIORITY_NORMAL


def _mt5_call(func, *args, _priority=None, _metric_name=None, **kwargs):
    # A v3 execution already represents a broker command.  Its symbol/tick/
    # position discovery calls inherit the urgent lane so a positions poll
    # cannot delay the command between preflight and order_send.
    priority = _priority
    if priority is None:
        priority = _MT5_CALL_PRIORITY.get()
    if priority is None:
        priority = _default_mt5_priority(func)
    is_isolated_parent_read = (
        EXECUTION_PROCESS_ISOLATION
        and not _EXECUTION_CHILD
        and not _MT5_READ_GATE_HELD.get()
        and not _is_native_trade_callable(func)
    )
    is_background_position_read = (
        not is_isolated_parent_read
        and getattr(func, "__name__", "") == "positions_get"
        and priority > MT5_API_PRIORITY_TRADE
        and not _MT5_READ_GATE_HELD.get()
    )
    if is_background_position_read:
        _MT5_TRADE_GATE.begin_read(
            timeout=POSITIONS_READ_GATE_WAIT_MS / 1000.0,
            quiet_seconds=POSITIONS_TRADE_QUIET_MS / 1000.0,
        )
    try:
        if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD:
            coordinator = globals().get("_EXECUTION")
            if coordinator is None:
                raise RuntimeError("native MT5 owner is not initialized")

            def _native_owner_call():
                if is_isolated_parent_read:
                    _MT5_TRADE_GATE.begin_read(
                        timeout=PARENT_NATIVE_READ_GATE_WAIT_MS / 1000.0,
                        quiet_seconds=POSITIONS_TRADE_QUIET_MS / 1000.0,
                    )
                try:
                    return coordinator.native_call(
                        getattr(func, "__name__", ""), args=args, kwargs=kwargs,
                    )
                finally:
                    if is_isolated_parent_read:
                        _MT5_TRADE_GATE.end_read()

            native_future = _MT5_API_EXECUTOR.submit(
                _native_owner_call, priority=priority,
                metric_name=(_metric_name or getattr(func, "__name__", None)),
            )
        elif _is_native_trade_callable(func):
            def _native_trade_call():
                mark_execution_dispatching()
                if not args and set(kwargs) == {"request"}:
                    return func(kwargs["request"])
                return func(*args, **kwargs)
            native_future = _MT5_API_EXECUTOR.submit(
                _native_trade_call, priority=priority,
                metric_name=(_metric_name or getattr(func, "__name__", None)),
            )
        else:
            native_future = _MT5_API_EXECUTOR.submit(
                func, *args, priority=priority,
                metric_name=(_metric_name or getattr(func, "__name__", None)),
                **kwargs,
            )
        try:
            return native_future.result()
        finally:
            trace = _MT5_NATIVE_TRACE.get()
            timing = getattr(native_future, "native_timing", None)
            if isinstance(trace, list) and isinstance(timing, dict):
                trace.append(dict(timing))
    finally:
        if is_background_position_read:
            _MT5_TRADE_GATE.end_read()


async def _mt5_call_async(func, *args, _priority=None, _metric_name=None, **kwargs):
    """Run a blocking MT5 wrapper without pinning FastAPI's event loop."""
    return await _control_call_async(
        _mt5_call, func, *args, _priority=_priority,
        _metric_name=_metric_name, **kwargs
    )


async def _control_call_async(func, *args, **kwargs):
    """Run a non-trade bridge read outside asyncio's shared thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _CONTROL_EXECUTOR, partial(func, *args, **kwargs)
    )


async def _ensure_mt5_async():
    """Keep connection checks off the event loop during a broker burst."""
    if not await _control_call_async(mgr.ensure):
        raise HTTPException(503, "MT5 not connected")


def _try_control_native_read(func, *args, _priority=MT5_API_PRIORITY_NORMAL,
                             _metric_name=None, _quiet_seconds=0.0, **kwargs):
    """Run one background MT5 read only when no trade is reserved.

    Every native call owns its own lease. A trade can still arrive after the
    final reservation check, but it then waits for at most this one already
    admitted call instead of an account-info/positions/history bundle.
    """
    if _MT5_TRADE_GATE.pending_trades() > 0:
        return _CONTROL_READ_DEFERRED
    try:
        _MT5_TRADE_GATE.begin_read(
            timeout=0.0, quiet_seconds=max(0.0, float(_quiet_seconds or 0.0)),
        )
    except TimeoutError:
        return _CONTROL_READ_DEFERRED
    read_token = _MT5_READ_GATE_HELD.set(True)
    try:
        # reserve_trade() is deliberately non-blocking and may win between
        # the optimistic check and begin_read(). Yield before native RPC.
        if _MT5_TRADE_GATE.pending_trades() > 0:
            return _CONTROL_READ_DEFERRED
        return _mt5_call(
            func, *args, _priority=_priority, _metric_name=_metric_name,
            **kwargs
        )
    finally:
        _MT5_READ_GATE_HELD.reset(read_token)
        _MT5_TRADE_GATE.end_read()


def _refresh_account_snapshot_sync(include_history=False, wait_for_lock=False):
    """Refresh account truth without allowing a request-time history scan."""
    acquired = _ACCOUNT_SNAPSHOT_REFRESH_LOCK.acquire(blocking=bool(wait_for_lock))
    if not acquired:
        return None
    try:
        info = _try_control_native_read(
            mt5.account_info,
            _priority=MT5_API_PRIORITY_NORMAL,
            _metric_name="account_info",
        )
        if info is _CONTROL_READ_DEFERRED:
            return None
        if info is None:
            raise RuntimeError("mt5.account_info() returned no snapshot")
        try:
            actual_login = int(getattr(info, "login", 0) or 0)
        except (TypeError, ValueError):
            actual_login = 0
        if actual_login != MT5_LOGIN:
            mgr.connected = False
            mgr.failures += 1
            _invalidate_account_snapshot()
            raise RuntimeError(
                "MT5 account identity mismatch: expected=%s actual=%s"
                % (MT5_LOGIN, actual_login or "missing")
            )
        _cache_connection_account(info)
        mgr.ping()

        if not include_history:
            return _account_snapshot_view("broker", require_complete=False)

        positions = _try_control_native_read(
            mt5.positions_get,
            _priority=MT5_API_PRIORITY_NORMAL,
            _metric_name="account_positions",
        )
        if positions is _CONTROL_READ_DEFERRED:
            return _account_snapshot_view("broker", require_complete=False)
        if positions is None:
            raise RuntimeError("positions_get returned no account snapshot")

        from_date = datetime.utcnow() - timedelta(days=30)
        deals = _try_control_native_read(
            mt5.history_deals_get,
            from_date,
            datetime.utcnow() + timedelta(hours=6),
            _priority=MT5_API_PRIORITY_NORMAL,
            _metric_name="history_deals_30d",
        )
        if deals is _CONTROL_READ_DEFERRED:
            return _account_snapshot_view("broker", require_complete=False)
        if deals is None:
            raise RuntimeError("history_deals_get returned no account snapshot")
        total_swap = sum(float(getattr(position, "swap", 0.0) or 0.0)
                         for position in positions)
        total_swap += sum(float(getattr(deal, "swap", 0.0) or 0.0)
                          for deal in deals)
        _cache_connection_account(info, total_swap=total_swap)
        return _account_snapshot_view("broker", require_complete=True)
    finally:
        _ACCOUNT_SNAPSHOT_REFRESH_LOCK.release()


async def _account_snapshot_for_endpoint(require_complete=True):
    trade_activity = _MT5_TRADE_GATE.pending_trades() > 0
    cached = _account_snapshot_view(
        "cache", trade_activity=trade_activity,
        require_complete=require_complete,
    )
    if trade_activity:
        if cached is None:
            raise HTTPException(503, "MT5 account snapshot unavailable or expired")
        return cached
    if cached is not None and not cached["account_snapshot_stale"]:
        return cached

    try:
        await _ensure_mt5_async()
        refresh_result = await _control_call_async(
            _refresh_account_snapshot_sync, False, False,
        )
        if refresh_result is not None:
            refreshed = _account_snapshot_view(
                "broker", require_complete=require_complete,
            )
            if refreshed is not None:
                return refreshed
    except HTTPException:
        pass
    except Exception as exc:
        logger.debug("account snapshot refresh deferred: %s", exc)

    trade_activity = _MT5_TRADE_GATE.pending_trades() > 0
    cached = _account_snapshot_view(
        "cache", trade_activity=trade_activity,
        require_complete=require_complete,
    )
    if cached is None:
        raise HTTPException(503, "MT5 account snapshot unavailable or expired")
    return cached


async def _account_snapshot_refresh_loop():
    while True:
        await asyncio.sleep(ACCOUNT_IDLE_REFRESH_SEC)
        if _MT5_TRADE_GATE.pending_trades() > 0 or not mgr.connected:
            continue
        try:
            await _control_call_async(
                _refresh_account_snapshot_sync,
                _periodic_history_refresh_due(),
                False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("idle account snapshot refresh deferred: %s", exc)


def _wait_for_account_snapshot_refresh():
    with _ACCOUNT_SNAPSHOT_REFRESH_LOCK:
        return None

# ────────────────────────────────────────────────────────────────────────────
# MT5 连接管理
# ────────────────────────────────────────────────────────────────────────────
class MT5Manager:
    def __init__(self):
        self.connected   = False
        self.failures    = 0
        self.last_ok_at: Optional[datetime] = None
        self.last_attempt: Optional[datetime] = None
        self.STALE_SEC   = 30   # 超过30s无请求算陈旧
        self.MAX_DELAY   = 60

    # ── 内部连接 ──────────────────────────────────────────────────────────
    def _do_connect(self) -> bool:
        self.last_attempt = datetime.utcnow()
        _invalidate_terminal_info_cache()
        _clear_tick_snapshots()
        try:
            if not _mt5_call(mt5.initialize, path=MT5_PATH, login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER, timeout=120000):
                logger.error(f"mt5.initialize failed: {_mt5_call(mt5.last_error)}")
                self.failures += 1
                return False

            # 已登录正确账户则跳过 login()
            info = _mt5_call(mt5.account_info)
            if info and info.login == MT5_LOGIN:
                logger.info(f"MT5 already connected: {MT5_LOGIN}@{MT5_SERVER}")
                self._on_success()
                self._activate_symbols()
                return True

            if not _mt5_call(mt5.login, MT5_LOGIN, password=MT5_PASSWORD,
                             server=MT5_SERVER, timeout=10000):
                logger.error(f"mt5.login failed: {_mt5_call(mt5.last_error)}")
                _mt5_call(mt5.shutdown)
                self.failures += 1
                return False

            self._on_success()
            self._activate_symbols()
            logger.info(f"MT5 connected: {MT5_LOGIN}@{MT5_SERVER}")
            return True

        except Exception as e:
            logger.error(f"MT5 connect exception: {e}")
            self.failures += 1
            return False

    def _on_success(self):
        self.connected  = True
        self.failures   = 0
        self.last_ok_at = datetime.utcnow()

    def _activate_symbols(self):
        for sym in ["XAUUSD+", "XAUUSD.S", "XAUUSD"]:
            try:
                info = _mt5_call(mt5.symbol_info, sym)
                if info and not info.visible:
                    _mt5_call(mt5.symbol_select, sym, True)
                    logger.info(f"Activated symbol: {sym}")
            except Exception:
                pass

    # ── 健康检测 ─────────────────────────────────────────────────────────
    def is_healthy(self) -> bool:
        if not self.connected:
            return False
        if self.last_ok_at is None:
            return False
        stale = (datetime.utcnow() - self.last_ok_at).total_seconds() > self.STALE_SEC
        return not stale

    # ── 对外接口：确保已连接 ─────────────────────────────────────────────
    def ensure(self) -> bool:
        if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD:
            coordinator = globals().get("_EXECUTION")
            if coordinator is None:
                self.connected = False
                return False
            try:
                if not coordinator.metrics().get("coordinator_healthy"):
                    self.connected = False
                    return False
                if self.is_healthy():
                    return True
                info = _mt5_call(mt5.account_info)
                if info is None or int(getattr(info, "login", 0) or 0) != MT5_LOGIN:
                    self.connected = False
                    self.failures += 1
                    return False
                self._on_success()
                _cache_connection_account(info)
                return True
            except Exception as exc:
                logger.error("MT5 owner health check failed: %s", exc)
                self.connected = False
                self.failures += 1
                return False
        if self.is_healthy():
            return True
        # 验证连接是否真实有效
        try:
            if self.connected and _mt5_call(mt5.account_info) is not None:
                self.last_ok_at = datetime.utcnow()
                return True
        except Exception:
            pass
        self.connected = False
        return self._do_connect()

    def ping(self):
        """刷新 last_ok_at，防止误判陈旧"""
        self.last_ok_at = datetime.utcnow()

    def disconnect(self):
        _invalidate_terminal_info_cache()
        _clear_tick_snapshots()
        if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD:
            # Coordinator teardown asks the child owner to close MT5. The
            # HTTP process has no terminal session of its own.
            self.connected = False
            return
        try:
            _mt5_call(mt5.shutdown)
        except Exception:
            pass
        self.connected = False

    def reconnect(self) -> bool:
        _invalidate_terminal_info_cache()
        _clear_tick_snapshots()
        if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD:
            coordinator = globals().get("_EXECUTION")
            try:
                # Reconnect is a native control operation too. It must never
                # enter the sole MT5 owner after a trade has been admitted.
                _MT5_TRADE_GATE.begin_read(timeout=135.0)
                try:
                    connected = bool(coordinator and coordinator.native_call(
                        "__bridge_reconnect__", timeout=135.0,
                    ))
                finally:
                    _MT5_TRADE_GATE.end_read()
            except Exception as exc:
                logger.error("MT5 owner reconnect failed: %s", exc)
                connected = False
            self.connected = connected
            if connected:
                self._on_success()
                _clear_symbol_info_cache()
                _POSITION_CACHE.invalidate()
            else:
                self.failures += 1
            return connected
        self.disconnect()
        return self._do_connect()

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected":  self.connected,
            "healthy":    self.is_healthy(),
            "failures":   self.failures,
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "account":    MT5_LOGIN,
            "server":     MT5_SERVER,
            "instance":   INSTANCE_NAME,
        }


mgr = MT5Manager()


def _bounded_shutdown_call(label, callback, timeout):
    """Run one blocking cleanup step without making service stop unbounded."""
    failure = []

    def _run():
        try:
            callback()
        except Exception as exc:
            failure.append(exc)

    worker = threading.Thread(
        target=_run, name="shutdown-" + str(label).replace(" ", "-"), daemon=True,
    )
    worker.start()
    worker.join(max(0.0, float(timeout)))
    if worker.is_alive():
        logger.error("Shutdown step timed out | step=%s timeout=%ss", label, timeout)
        return False
    if failure:
        logger.error("Shutdown step failed | step=%s error=%s", label, failure[0])
        return False
    return True

# ─── 生命周期 ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    global _ACCOUNT_SNAPSHOT_REFRESH_TASK
    logger.info(f"Starting MT5 Bridge [{INSTANCE_NAME}] port={SERVICE_PORT}")
    if EXECUTION_PROCESS_ISOLATION and _EXECUTION is not None:
        ready = await _control_call_async(
            _EXECUTION.wait_ready,
            float(os.getenv("MT5_EXECUTION_READY_SEC", "55")),
        )
        if not ready:
            raise RuntimeError("MT5 isolated execution worker is not ready")
    if mgr.ensure():
        try:
            await _control_call_async(
                _refresh_account_snapshot_sync, True, True,
            )
        except Exception as exc:
            logger.warning("initial account snapshot unavailable: %s", exc)
    _ACCOUNT_SNAPSHOT_REFRESH_TASK = asyncio.create_task(
        _account_snapshot_refresh_loop()
    )

@app.on_event("shutdown")
async def on_shutdown():
    global _ACCOUNT_SNAPSHOT_REFRESH_TASK
    refresh_task = _ACCOUNT_SNAPSHOT_REFRESH_TASK
    _ACCOUNT_SNAPSHOT_REFRESH_TASK = None
    if refresh_task is not None:
        refresh_task.cancel()
        await asyncio.wait({refresh_task}, timeout=SHUTDOWN_STEP_SEC)
        _bounded_shutdown_call(
            "account snapshot", _wait_for_account_snapshot_refresh,
            SHUTDOWN_STEP_SEC,
        )
    with _POSITION_REFRESH_TIMER_LOCK:
        refresh_timer = _POSITION_REFRESH_TIMER
        if refresh_timer is not None:
            refresh_timer.cancel()
    execution = globals().get("_EXECUTION")
    if execution is not None:
        _bounded_shutdown_call(
            "execution coordinator", execution.shutdown, EXECUTION_SHUTDOWN_SEC,
        )
    _bounded_shutdown_call("MT5 disconnect", mgr.disconnect, SHUTDOWN_STEP_SEC)
    _MT5_API_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    _ORDER_STATUS_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    _CONTROL_EXECUTOR.shutdown(wait=False, cancel_futures=True)

# ────────────────────────────────────────────────────────────────────────────
# 辅助：标准化量和价格
# ────────────────────────────────────────────────────────────────────────────
def _pick_filling(sym_info):
    """按 symbol 支持的 filling 位掩码选模式: IOC 优先(IC 现行为, 零回归) -> FOK -> RETURN。
    修 Exness-MT5Trial5 XAUUSD 不支持 IOC 时硬编码致 retcode=10030 拒单。"""
    fm = getattr(sym_info, "filling_mode", 0) or 0
    if fm & 2:   # SYMBOL_FILLING_IOC
        return mt5.ORDER_FILLING_IOC
    if fm & 1:   # SYMBOL_FILLING_FOK
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN

def _normalize_volume(volume: float, sym_info) -> float:
    step = sym_info.volume_step
    vmin = sym_info.volume_min
    vmax = sym_info.volume_max
    v = round(round(volume / step) * step, 8)
    v = max(v, vmin)
    if v > vmax:
        logger.warning(f"Volume {v} > volume_max {vmax}, capping")
        v = vmax
    return v

def _normalize_price(price: float, digits: int) -> float:
    return round(price, digits)

ORDER_TYPE_MAP = {
    "buy":        mt5.ORDER_TYPE_BUY,
    "sell":       mt5.ORDER_TYPE_SELL,
    "buy_limit":  mt5.ORDER_TYPE_BUY_LIMIT,
    "sell_limit": mt5.ORDER_TYPE_SELL_LIMIT,
    "buy_stop":   mt5.ORDER_TYPE_BUY_STOP,
    "sell_stop":  mt5.ORDER_TYPE_SELL_STOP,
}


def _serialize_position(position):
    return {
        "ticket": position.ticket,
        "symbol": position.symbol,
        "type": position.type,
        "volume": position.volume,
        "price_open": position.price_open,
        "price_current": position.price_current,
        "profit": position.profit,
        "swap": position.swap,
        "sl": position.sl,
        "tp": position.tp,
        "margin": getattr(position, "margin", 0.0),
        "price_liquidation": getattr(position, "price_liquidation", 0.0),
        "time": position.time,
        "comment": getattr(position, "comment", ""),
    }


_POSITION_CACHE = PositionSnapshotCache(
    fetcher=lambda: _mt5_call(mt5.positions_get),
    serializer=_serialize_position,
    ttl_ms=POSITIONS_CACHE_TTL_MS,
    stale_max_ms=POSITIONS_STALE_MAX_MS,
)


def _fetch_authoritative_positions():
    """Wait out a trade burst, then perform one broker positions read."""
    _MT5_TRADE_GATE.begin_read(
        timeout=None,
        quiet_seconds=POSITIONS_TRADE_QUIET_MS / 1000.0,
    )
    read_token = _MT5_READ_GATE_HELD.set(True)
    try:
        return _mt5_call(
            mt5.positions_get,
            _priority=MT5_API_PRIORITY_POSITIONS,
            _metric_name="positions_get",
        )
    finally:
        _MT5_READ_GATE_HELD.reset(read_token)
        _MT5_TRADE_GATE.end_read()

# Coalesce the broker read after a trade burst. This follows the MT4
# command-first scheduler: trading stays contiguous, then one authoritative
# positions snapshot is published for the whole burst.
_POSITION_REFRESH_TIMER_LOCK = threading.Lock()
_POSITION_REFRESH_TIMER = None


def _run_post_trade_snapshot_refresh():
    global _POSITION_REFRESH_TIMER
    with _POSITION_REFRESH_TIMER_LOCK:
        _POSITION_REFRESH_TIMER = None
    if _MT5_TRADE_GATE.pending_trades() > 0:
        # The command that is currently completing (or the next queued
        # command) schedules its own coalesced refresh. Spinning a new Timer
        # every 10 ms here only adds thread churn and can never outrun the
        # account-scoped native worker.
        logger.debug("post-trade positions refresh deferred while trade burst is active")
        return
    quiet_remaining = _MT5_TRADE_GATE.quiet_remaining(
        POSITIONS_TRADE_QUIET_MS / 1000.0
    )
    if quiet_remaining > 0:
        _schedule_post_trade_snapshot(
            delay_ms=max(1, int(quiet_remaining * 1000) + 1)
        )
        return
    try:
        _POSITION_CACHE.get()
    except Exception as exc:
        logger.debug("post-trade positions refresh deferred: %s", exc)
    if _MT5_TRADE_GATE.pending_trades() > 0:
        return
    try:
        _refresh_account_snapshot_sync(include_history=False, wait_for_lock=False)
    except Exception as exc:
        logger.debug("post-trade account refresh deferred: %s", exc)


def _schedule_post_trade_snapshot(delay_ms=None):
    global _POSITION_REFRESH_TIMER
    delay_ms = POST_TRADE_SNAPSHOT_GRACE_MS if delay_ms is None else max(0, int(delay_ms))
    timer = threading.Timer(delay_ms / 1000.0, _run_post_trade_snapshot_refresh)
    timer.daemon = True
    with _POSITION_REFRESH_TIMER_LOCK:
        previous = _POSITION_REFRESH_TIMER
        _POSITION_REFRESH_TIMER = timer
        if previous is not None:
            previous.cancel()
        timer.start()


def _trade_snapshot_metadata():
    """Attach non-blocking snapshot state to a terminal trade result."""
    try:
        return _POSITION_CACHE.metadata()
    except Exception:
        return {"snapshot_pending": True}

# ────────────────────────────────────────────────────────────────────────────
# 端点实现
# ────────────────────────────────────────────────────────────────────────────

# ── 1. Health ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    queue_metrics = _EXECUTION.metrics() if "_EXECUTION" in globals() else {}
    execution_healthy = bool(
        not EXECUTION_PROCESS_ISOLATION
        or queue_metrics.get("coordinator_healthy") is True
    )
    pending_trades = _MT5_TRADE_GATE.pending_trades()
    terminal_cache = _cached_terminal_info()
    ta = terminal_cache.get("trade_allowed")
    ta_source = "cache" if terminal_cache.get("refreshed_at") else "unavailable"
    if not pending_trades and execution_healthy:
        try:
            terminal_info = await _control_call_async(
                _try_control_native_read,
                mt5.terminal_info,
                _priority=MT5_API_PRIORITY_NORMAL,
                _metric_name="terminal_info_health",
            )
            if terminal_info is not _CONTROL_READ_DEFERRED and terminal_info is not None:
                _cache_terminal_info(terminal_info)
                terminal_cache = _cached_terminal_info()
                ta = terminal_cache.get("trade_allowed")
                ta_source = "broker"
        except Exception:
            terminal_cache = _cached_terminal_info()
            ta = terminal_cache.get("trade_allowed")
            ta_source = (
                "cache" if terminal_cache.get("refreshed_at") else "unavailable"
            )
    return {
        "status":   "ok" if execution_healthy else "degraded",
        "service":  "mt5-bridge",
        "build_id": BRIDGE_BUILD_ID,
        "instance": INSTANCE_NAME,
        "mt5":      mgr.connected,
        "trade_allowed": ta,
        "trade_allowed_source": ta_source,
        "trade_allowed_cache_age_ms": terminal_cache.get("age_ms"),
        "trade_activity": bool(pending_trades),
        "execution_process_isolation": EXECUTION_PROCESS_ISOLATION,
        "execution_healthy": execution_healthy,
        "execution_queue": queue_metrics,
        "mt5_api_queue": _MT5_API_EXECUTOR.metrics(),
        "mt5_trade_gate": _MT5_TRADE_GATE.metrics(),
    }

# ── 2. Connection Status ──────────────────────────────────────────────────
@app.get("/mt5/connection/status", dependencies=[Depends(verify_api_key)])
async def connection_status(execution_probe: bool = False):
    if execution_probe:
        identity = _cached_connection_identity()
        queue_metrics = _EXECUTION.metrics() if "_EXECUTION" in globals() else {}
        coordinator_healthy = bool(
            not EXECUTION_PROCESS_ISOLATION
            or queue_metrics.get("coordinator_healthy") is True
        )
        connected = bool(
            mgr.connected
            and mgr.is_healthy()
            and coordinator_healthy
            and identity["verified"]
        )
        status = mgr.get_status()
        status.update({
            "connected": connected,
            "healthy": connected,
            "account": identity["actual_login"],
            "expected_account": identity["expected_login"],
            "account_identity_verified": identity["verified"],
            "account_snapshot_ts_ms": identity["snapshot_ts_ms"],
            "account_snapshot_age_ms": identity["age_ms"],
            "account_snapshot_source": "memory",
            "account_snapshot_stale": not identity["fresh"],
            "execution_probe": True,
            "execution_healthy": coordinator_healthy,
            "trade_activity": bool(_MT5_TRADE_GATE.pending_trades()),
        })
        return status
    status = mgr.get_status()
    pending_trades = _MT5_TRADE_GATE.pending_trades()
    snapshot = _account_snapshot_view(
        "cache", trade_activity=bool(pending_trades), require_complete=False,
    )
    if snapshot is not None:
        status.update({
            "balance": snapshot.get("balance"),
            "equity": snapshot.get("equity"),
            "account_snapshot_ts_ms": snapshot["account_snapshot_ts_ms"],
            "account_snapshot_age_ms": snapshot["account_snapshot_age_ms"],
            "account_snapshot_source": snapshot["account_snapshot_source"],
            "account_snapshot_stale": snapshot["account_snapshot_stale"],
        })
    if pending_trades:
        # Admission already proved connectivity. Do not put another account
        # read on the native worker while queued trades are being drained.
        status.update({
            "trade_activity": True,
            "pending_trades": pending_trades,
        })
        return status
    if mgr.connected:
        try:
            snapshot = await _account_snapshot_for_endpoint(require_complete=False)
            status.update({
                "balance": snapshot.get("balance"),
                "equity": snapshot.get("equity"),
                "account_snapshot_ts_ms": snapshot["account_snapshot_ts_ms"],
                "account_snapshot_age_ms": snapshot["account_snapshot_age_ms"],
                "account_snapshot_source": snapshot["account_snapshot_source"],
                "account_snapshot_stale": snapshot["account_snapshot_stale"],
            })
        except HTTPException:
            status["account_snapshot_stale"] = True
    return status

# ── 3. Reconnect ──────────────────────────────────────────────────────────
@app.post("/mt5/connection/reconnect", dependencies=[Depends(verify_api_key)])
async def reconnect():
    ok = await _control_call_async(mgr.reconnect)
    _clear_symbol_info_cache()
    _POSITION_CACHE.invalidate()
    _invalidate_account_snapshot()
    return {"success": ok, "instance": INSTANCE_NAME}

# ── 4. Positions ──────────────────────────────────────────────────────────
@app.get("/mt5/positions", dependencies=[Depends(verify_api_key)])
async def get_positions(symbol: Optional[str] = None, authoritative: bool = False):
    quiet_seconds = POSITIONS_TRADE_QUIET_MS / 1000.0
    if authoritative:
        await _ensure_mt5_async()
        try:
            snapshot = await _control_call_async(
                _POSITION_CACHE.get,
                authoritative=True,
                fetcher=_fetch_authoritative_positions,
            )
        except Exception as exc:
            raise HTTPException(
                503,
                "MT5 authoritative positions snapshot unavailable: %s" % exc,
            )
        if snapshot["snapshot_stale"] or snapshot["snapshot_source"] != "broker":
            raise HTTPException(
                503,
                "MT5 authoritative positions snapshot was not broker-fresh",
            )
    else:
        trade_activity = _MT5_TRADE_GATE.trade_activity(quiet_seconds)
        if trade_activity:
            snapshot = _POSITION_CACHE.get_cached()
            if snapshot is None:
                raise HTTPException(
                    503,
                    "MT5 bounded positions snapshot unavailable during trade activity",
                )
        else:
            await _ensure_mt5_async()
            # A command can be admitted while the connection check completes.
            # Re-check before allowing the cache to schedule native broker I/O.
            trade_activity = _MT5_TRADE_GATE.trade_activity(quiet_seconds)
            if trade_activity:
                snapshot = _POSITION_CACHE.get_cached()
                if snapshot is None:
                    raise HTTPException(
                        503,
                        "MT5 bounded positions snapshot unavailable during trade activity",
                    )
            else:
                try:
                    snapshot = await _control_call_async(_POSITION_CACHE.get)
                except Exception as exc:
                    raise HTTPException(503, "MT5 positions snapshot unavailable: %s" % exc)
    mgr.ping()
    snapshot = dict(snapshot)
    snapshot["snapshot_authoritative"] = bool(authoritative)
    snapshot["snapshot_trade_activity"] = _MT5_TRADE_GATE.trade_activity(
        quiet_seconds
    )
    if symbol:
        snapshot["positions"] = [
            position for position in snapshot["positions"]
            if position.get("symbol") == symbol
        ]
    return snapshot

# ── 5. Account Balance ────────────────────────────────────────────────────
@app.get("/mt5/account/balance", dependencies=[Depends(verify_api_key)])
async def account_balance():
    snapshot = await _account_snapshot_for_endpoint(require_complete=False)
    fields = ("balance", "equity", "margin", "margin_free", "margin_level", "profit")
    response = {field: snapshot.get(field) for field in fields}
    response.update({
        key: value for key, value in snapshot.items()
        if key.startswith("account_snapshot_")
    })
    return response

# ── 6. Account Info（含历史换算 Swap）────────────────────────────────────
@app.get("/mt5/account/info", dependencies=[Depends(verify_api_key)])
async def account_info():
    return await _account_snapshot_for_endpoint(require_complete=True)

# ── 7. Symbols ────────────────────────────────────────────────────────────
@app.get("/mt5/symbols", dependencies=[Depends(verify_api_key)])
async def get_symbols():
    await _ensure_mt5_async()
    syms = await _mt5_call_async(mt5.symbols_get) or []
    mgr.ping()
    return {
        "symbols": [
            {
                "name":         s.name,
                "description":  s.description,
                "digits":       s.digits,
                "volume_min":   s.volume_min,
                "volume_max":   s.volume_max,
                "volume_step":  s.volume_step,
                "visible":      s.visible,
            }
            for s in syms
            if s.visible
        ]
    }

# ── 8. Tick ───────────────────────────────────────────────────────────────
@app.get("/mt5/symbol_info/{symbol}", dependencies=[Depends(verify_api_key)])
async def get_symbol_info(symbol: str):
    """
    Return full MT5 symbol_info including swap_long/swap_short for overnight fee display.

    Critical for the StrategyPanel "Bybit 过夜费 多/空" widget — these values come from
    the broker's MT5 terminal symbol properties (NOT from any REST funding-rate API).
    """
    await _ensure_mt5_async()
    info = await _mt5_call_async(mt5.symbol_info, symbol)
    if info is None:
        error = await _mt5_call_async(mt5.last_error)
        raise HTTPException(404, f"Symbol {symbol} not found: {error}")
    mgr.ping()
    return {
        "symbol":              info.name,
        "description":         info.description,
        "digits":              info.digits,
        "point":               info.point,
        "volume_min":          info.volume_min,
        "volume_max":          info.volume_max,
        "volume_step":         info.volume_step,
        "trade_contract_size": info.trade_contract_size,
        "swap_long":           info.swap_long,
        "swap_short":          info.swap_short,
        "swap_mode":           info.swap_mode,
        "swap_rollover3days":  info.swap_rollover3days,
        "currency_base":       info.currency_base,
        "currency_profit":     info.currency_profit,
        "currency_margin":     info.currency_margin,
        "visible":             info.visible,
        # Trade-engine status: only TRADE_FULL (4) accepts both open+close.
        # Exposed for backend's first-trade-after-MT5-reopen preflight check.
        # MT5 ENUM_SYMBOL_TRADE_MODE: 0=DISABLED 1=LONGONLY 2=SHORTONLY 3=CLOSEONLY 4=FULL
        "trade_mode":          int(info.trade_mode),
        "trade_allowed":       int(info.trade_mode) == 4,
    }


@app.get("/mt5/tick/{symbol}", dependencies=[Depends(verify_api_key)])
async def get_tick(symbol: str):
    key = _tick_key(symbol)
    quiet_seconds = POSITIONS_TRADE_QUIET_MS / 1000.0
    trade_activity = _MT5_TRADE_GATE.trade_activity(quiet_seconds)
    cached = _tick_snapshot_view(
        key,
        "trade_cache" if trade_activity else "request_cache",
        allow_stale=trade_activity,
    )
    if cached is not None:
        return cached
    if trade_activity:
        raise HTTPException(
            503, "MT5 tick snapshot unavailable during trade activity"
        )

    # Coalesce simultaneous UI and spread-sampler misses for one symbol. The
    # second waiter rechecks both the cache and trade gate before native I/O.
    async with _tick_refresh_lock(key):
        trade_activity = _MT5_TRADE_GATE.trade_activity(quiet_seconds)
        cached = _tick_snapshot_view(
            key,
            "trade_cache" if trade_activity else "request_cache",
            allow_stale=trade_activity,
        )
        if cached is not None:
            return cached
        if trade_activity:
            raise HTTPException(
                503, "MT5 tick snapshot unavailable during trade activity"
            )

        await _ensure_mt5_async()

        # Connection validation can overlap a newly admitted command. Never
        # enqueue symbol_info_tick after that command has reserved the owner.
        trade_activity = _MT5_TRADE_GATE.trade_activity(quiet_seconds)
        if trade_activity:
            cached = _tick_snapshot_view(
                key, "trade_cache", allow_stale=True,
            )
            if cached is not None:
                return cached
            raise HTTPException(
                503, "MT5 tick snapshot unavailable during trade activity"
            )

        snapshot_generation = _tick_snapshot_generation()
        tick = await _control_call_async(
            _try_control_native_read,
            mt5.symbol_info_tick,
            key,
            _priority=MT5_API_PRIORITY_NORMAL,
            _metric_name="symbol_info_tick",
            _quiet_seconds=quiet_seconds,
        )
        if tick is _CONTROL_READ_DEFERRED:
            cached = _tick_snapshot_view(
                key, "trade_cache", allow_stale=True,
            )
            if cached is not None:
                return cached
            raise HTTPException(
                503, "MT5 tick snapshot unavailable during trade activity"
            )
        if tick is None:
            raise HTTPException(404, f"No tick for symbol {key}")
        response = _store_tick_snapshot(
            key, tick, generation=snapshot_generation,
        )
        if response is None:
            raise HTTPException(503, "MT5 tick snapshot invalidated by reconnect")
        mgr.ping()
        return response

# ── 9. History Deals ──────────────────────────────────────────────────────
@app.get("/mt5/history/deals", dependencies=[Depends(verify_api_key)])
async def history_deals(
    days:   int           = Query(7),
    symbol: Optional[str] = Query(None),
):
    await _ensure_mt5_async()
    from_date = datetime.utcnow() - timedelta(days=days)
    deals = await _mt5_call_async(
        mt5.history_deals_get, from_date, datetime.utcnow() + timedelta(hours=6)
    ) or []
    mgr.ping()
    result = []
    for d in deals:
        if symbol and d.symbol != symbol:
            continue
        result.append({
            "ticket":     d.ticket,
            "order":      d.order,
            "symbol":     d.symbol,
            "type":       d.type,
            "entry":      d.entry,
            "volume":     d.volume,
            "price":      d.price,
            "profit":     d.profit,
            "swap":       getattr(d, "swap", 0.0),
            "commission": d.commission,
            "comment":    d.comment,
            "time":       d.time,
        })
    return {"deals": result}

# ── 10. History Orders ────────────────────────────────────────────────────
@app.get("/mt5/history/orders", dependencies=[Depends(verify_api_key)])
async def history_orders(
    days:   int           = Query(7),
    symbol: Optional[str] = Query(None),
):
    await _ensure_mt5_async()
    from_date = datetime.utcnow() - timedelta(days=days)
    orders = await _mt5_call_async(
        mt5.history_orders_get, from_date, datetime.utcnow()
    ) or []
    mgr.ping()
    result = []
    for o in orders:
        if symbol and o.symbol != symbol:
            continue
        result.append({
            "ticket":      o.ticket,
            "symbol":      o.symbol,
            "type":        o.type,
            "volume_initial": o.volume_initial,
            "volume_current": o.volume_current,
            "price_open":  o.price_open,
            "price_current": o.price_current,
            "state":       o.state,
            "comment":     o.comment,
            "time_setup":  o.time_setup,
            "time_done":   o.time_done,
        })
    return {"orders": result}

# ── 11. Place Order ───────────────────────────────────────────────────────
# ── M2 幂等层(V1.1 §9.2): request_id → 结果, 本地SQLite(WAL) ────────────────
# 同一 request_id 重放只返回原结果, 绝不二次 order_send; SENDING=已进入
# order_send但结果未知(崩溃/超时中), 拒绝重发交由后端查询/人工对账。
import sqlite3 as _sq3
import threading as _thr
import json as _json_idem
_IDEM_LOCK = _thr.Lock()
_IDEM_CONN = None


def _idem_conn():
    global _IDEM_CONN
    if _IDEM_CONN is None:
        _IDEM_CONN = _sq3.connect("idempotency.db", check_same_thread=False)
        _IDEM_CONN.execute("PRAGMA journal_mode=WAL")
        _IDEM_CONN.execute(
            "CREATE TABLE IF NOT EXISTS order_requests ("
            "request_id TEXT PRIMARY KEY, state TEXT, result TEXT,"
            "created_at REAL, updated_at REAL)")
        _IDEM_CONN.commit()
    return _IDEM_CONN


def _idem_get(request_id):
    if not request_id:
        return None
    with _IDEM_LOCK:
        return _idem_conn().execute(
            "SELECT state, result FROM order_requests WHERE request_id=?",
            (request_id,)).fetchone()


def _idem_put(request_id, state, result=None):
    if not request_id:
        return
    import time as _t_idem
    _now = _t_idem.time()
    with _IDEM_LOCK:
        c = _idem_conn()
        c.execute(
            "INSERT INTO order_requests (request_id, state, result, created_at, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,"
            " result=excluded.result, updated_at=excluded.updated_at",
            (request_id, state,
             _json_idem.dumps(result) if result is not None else None, _now, _now))
        c.commit()


# Legacy v2 handler retained for source audit only; v3 route is registered below.
async def place_order(req: OrderRequest):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")

    # ── M2 幂等重放检查(V1.1 §9.2) ──
    if req.request_id:
        _prev = _idem_get(req.request_id)
        if _prev:
            _pstate, _pres = _prev
            if _pstate == "DONE" and _pres:
                _r = _json_idem.loads(_pres)
                _r["idempotency_hit"] = True
                return _r
            if _pstate == "FAILED":
                raise HTTPException(400, "idempotent-replay: previous attempt FAILED terminally")
            return {"success": False, "unknown": True, "state": _pstate,
                    "request_id": req.request_id, "idempotency_hit": True,
                    "error": "previous attempt outcome unknown (SENDING), refuse to resend"}
        _idem_put(req.request_id, "SENDING")

    ot_key = req.order_type.lower()
    if ot_key not in ORDER_TYPE_MAP:
        raise HTTPException(400, f"Invalid order_type: {req.order_type}")
    order_type = ORDER_TYPE_MAP[ot_key]

    # 获取品种信息
    sym_info = mt5.symbol_info(req.symbol)
    if sym_info is None:
        raise HTTPException(400, f"Symbol not found: {req.symbol} [{mt5.last_error()}]")
    if not sym_info.visible:
        mt5.symbol_select(req.symbol, True)
        sym_info = mt5.symbol_info(req.symbol)

    digits = sym_info.digits
    volume = _normalize_volume(req.volume, sym_info)

    # 确定 trade_action 和 filling
    pending_types = {
        mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
        mt5.ORDER_TYPE_BUY_STOP,  mt5.ORDER_TYPE_SELL_STOP,
    }
    if order_type in pending_types:
        trade_action = mt5.TRADE_ACTION_PENDING
        type_filling = mt5.ORDER_FILLING_RETURN
    else:
        trade_action = mt5.TRADE_ACTION_DEAL
        type_filling = _pick_filling(sym_info)

    request = {
        "action":       trade_action,
        "symbol":       req.symbol,
        "volume":       volume,
        "type":         order_type,
        "deviation":    req.deviation,
        "magic":        MT5_LOGIN,
        "comment":      req.comment[:255],
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": type_filling,
    }
    if req.price is not None:
        request["price"] = _normalize_price(req.price, digits)
    if req.sl is not None:
        request["sl"] = _normalize_price(req.sl, digits)
    if req.tp is not None:
        request["tp"] = _normalize_price(req.tp, digits)
    if req.position_ticket is not None:
        request["position"] = req.position_ticket

    MAX_RETRY = 2
    for attempt in range(MAX_RETRY):
        result = mt5.order_send(request)
        if result is None:
            raise HTTPException(500, f"order_send returned None: {mt5.last_error()}")
        # 20260716 实际成交口径(V1.1 §7.1): 同时接受 DONE 和 DONE_PARTIAL(10010)。
        # 旧行为把部分成交抛400 → 后端当整单失败按全量重试, 已成交部分成双重敞口。
        # volume 字段语义升级为"实际成交量"(DONE时=请求量, 向后兼容), 并补
        # requested/normalized/filled/remaining 四量与 partial 标志。
        if result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            mgr.ping()
            _filled = float(result.volume or 0.0)
            _partial = (result.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL)
            logger.info(f"Order OK{' (PARTIAL)' if _partial else ''} | sym={req.symbol} side={req.order_type} "
                        f"req_vol={volume} filled={_filled} price={result.price} order={result.order}")
            _resp = {
                "success":  True,
                "retcode":  result.retcode,
                "order":    result.order,
                "deal":     result.deal,
                "volume":   _filled,
                "price":    result.price,
                "comment":  result.comment,
                "requested_volume": req.volume,
                "normalized_volume": volume,
                "filled_volume": _filled,
                "remaining_volume": max(0.0, round(volume - _filled, 8)),
                "partial": _partial,
                "request_id": req.request_id,
            }
            _idem_put(req.request_id, "DONE", _resp)
            return _resp
        # 可重试错误（重新报价/流动性不足）
        if result.retcode in (10030, 10018) and attempt < MAX_RETRY - 1:
            logger.warning(f"Retrying order, retcode={result.retcode}")
            continue
        _idem_put(req.request_id, "FAILED", {"error": f"retcode={result.retcode} comment={result.comment}"})
        raise HTTPException(400, f"Order failed retcode={result.retcode} comment={result.comment}")

# ── 12. Close Specific Position ───────────────────────────────────────────
async def close_position(req: ClosePositionRequest):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")

    if req.ticket:
        positions = mt5.positions_get(ticket=req.ticket)
        if not positions:
            raise HTTPException(404, f"Position ticket {req.ticket} not found")
        pos = positions[0]
    else:
        # 按 symbol + side 找仓位
        all_pos = mt5.positions_get(symbol=req.symbol) if req.symbol else mt5.positions_get()
        if not all_pos:
            raise HTTPException(404, "No matching positions found")
        # side="sell" → 平多(type=0)，side="buy" → 平空(type=1)
        target_type = 0 if req.side.lower() == "sell" else 1
        matching = [p for p in all_pos if p.type == target_type]
        if not matching:
            raise HTTPException(404, f"No {req.side} positions for {req.symbol}")
        # 选最接近 req.volume 的仓位
        if req.volume:
            matching.sort(key=lambda p: abs(p.volume - req.volume))
        pos = matching[0]

    sym_info = mt5.symbol_info(pos.symbol)
    if sym_info is None:
        raise HTTPException(400, f"Symbol info not found for {pos.symbol}")

    close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
    close_vol  = _normalize_volume(req.volume or pos.volume, sym_info)

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       pos.symbol,
        "volume":       close_vol,
        "type":         close_type,
        "position":     pos.ticket,
        "deviation":    10,
        "magic":        MT5_LOGIN,
        "comment":      "",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling(sym_info),
    }
    result = mt5.order_send(request)
    if result is None:
        raise HTTPException(500, f"Close failed: {mt5.last_error()}")
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise HTTPException(400, f"Close failed retcode={result.retcode}")
    mgr.ping()
    return {
        "success": True,
        "retcode": result.retcode,
        "order":   result.order,
        "volume":  result.volume,
        "price":   result.price,
        "comment": result.comment,
    }

# ── 13. Close All Positions ───────────────────────────────────────────────
async def close_all_positions(req: CloseAllRequest):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")

    positions = mt5.positions_get(symbol=req.symbol) if req.symbol else mt5.positions_get()
    if not positions:
        return {"closed": 0, "failed": 0, "results": []}

    results = []
    closed  = 0
    failed  = 0

    for pos in positions:
        sym_info = mt5.symbol_info(pos.symbol)
        if sym_info is None:
            failed += 1
            results.append({"ticket": pos.ticket, "success": False, "reason": "no sym_info"})
            continue
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        vol = _normalize_volume(pos.volume, sym_info)
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       vol,
            "type":         close_type,
            "position":     pos.ticket,
            "deviation":    10,
            "magic":        MT5_LOGIN,
            "comment":      "",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": _pick_filling(sym_info),
        }
        res = mt5.order_send(request)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
            results.append({"ticket": pos.ticket, "success": True, "order": res.order})
        else:
            failed += 1
            rc = res.retcode if res else -1
            results.append({"ticket": pos.ticket, "success": False, "retcode": rc})

    mgr.ping()
    return {"closed": closed, "failed": failed, "results": results}

# ── 14. Cancel All Pending Orders ─────────────────────────────────────────
async def cancel_all(req: CancelAllRequest):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")

    orders = mt5.orders_get(symbol=req.symbol) if req.symbol else mt5.orders_get()
    if not orders:
        return {"cancelled": 0, "failed": 0}

    cancelled = 0
    failed    = 0

    for order in orders:
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order":  order.ticket,
        }
        res = mt5.order_send(request)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            cancelled += 1
        else:
            failed += 1

    mgr.ping()
    return {"cancelled": cancelled, "failed": failed}


# ────────────────────────────────────────────────────────────────────────────
# ── M2: 幂等状态查询(V1.1 §9.1) — 后端HTTP超时后按request_id查询, 禁止盲重发 ──
async def order_status(request_id: str):
    loop = asyncio.get_running_loop()
    row = await loop.run_in_executor(
        _ORDER_STATUS_EXECUTOR, partial(_idem_get, request_id)
    )
    if not row:
        raise HTTPException(404, "unknown request_id")
    _state, _result = row
    out = {"request_id": request_id, "state": _state,
           "terminal": _state in ("DONE", "FAILED")}
    if _result:
        try:
            out["result"] = _json_idem.loads(_result)
        except Exception:
            pass
    return out


# v3 execution path: one durable writer per MT5 account.
def _model_payload(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _intent_hash(op, payload):
    stable = {
        key: value for key, value in payload.items()
        if key not in ("request_id", "ack_only")
    }
    encoded = json.dumps(
        {"op": op, "payload": stable},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _failure(request_id, error, **extra):
    result = {"success": False, "request_id": request_id, "error": str(error)}
    result.update(extra)
    return ExecutionOutcome("FAILED", result)


def _unknown(request_id, error, **extra):
    result = {
        "success": False,
        "unknown": True,
        "state": "UNKNOWN",
        "request_id": request_id,
        "error": str(error),
    }
    result.update(extra)
    return ExecutionOutcome("UNKNOWN", result)


def _success_codes():
    return {
        getattr(mt5, "TRADE_RETCODE_DONE", 10009),
        getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010),
    }


def _requote_codes():
    return {
        getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004),
        getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
        getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10021),
    }


def _refresh_deal_price(request, sym_info=None):
    tick = _mt5_call(mt5.symbol_info_tick, request["symbol"])
    if tick is None:
        return False
    buy_types = {
        getattr(mt5, "ORDER_TYPE_BUY", 0),
        getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2),
        getattr(mt5, "ORDER_TYPE_BUY_STOP", 4),
        getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", 6),
    }
    price = tick.ask if request["type"] in buy_types else tick.bid
    if price is None or float(price) <= 0:
        return False
    # The caller already resolved symbol_info to build volume/filling. Reuse
    # it here instead of issuing a second native IPC call on every deal.
    info = sym_info or _mt5_call(mt5.symbol_info, request["symbol"])
    digits = int(getattr(info, "digits", 0) or 0)
    request["price"] = _normalize_price(float(price), digits)
    return True


def _refresh_deal_price_native(request, sym_info):
    """Refresh a market request while the native worker remains owned."""
    tick = mt5.symbol_info_tick(request["symbol"])
    if tick is None:
        return False
    buy_types = {
        getattr(mt5, "ORDER_TYPE_BUY", 0),
        getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2),
        getattr(mt5, "ORDER_TYPE_BUY_STOP", 4),
        getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", 6),
    }
    price = tick.ask if request["type"] in buy_types else tick.bid
    if price is None or float(price) <= 0:
        return False
    digits = int(getattr(sym_info, "digits", 0) or 0)
    request["price"] = _normalize_price(float(price), digits)
    return True


def _send_with_requote(request, sym_info=None):
    is_deal = request.get("action") == getattr(mt5, "TRADE_ACTION_DEAL", 1)
    # Keep quote refresh, bounded requote retry and order_send in one native
    # worker task. A burst cannot interleave another account read between
    # quote refresh and the broker command.
    def _native_send():
        retries = 0
        quote_refresh_ns = 0
        broker_send_ns = 0
        attempts = 0

        def _timed_quote_refresh():
            nonlocal quote_refresh_ns
            started_ns = time.perf_counter_ns()
            try:
                return _refresh_deal_price_native(request, sym_info)
            finally:
                quote_refresh_ns += time.perf_counter_ns() - started_ns

        def _result(value):
            return value, retries, {
                "quote_refresh_ms": round(quote_refresh_ns / 1_000_000, 3),
                "broker_order_send_ms": round(broker_send_ns / 1_000_000, 3),
                "order_attempts": attempts,
            }

        while True:
            if is_deal:
                _timed_quote_refresh()
            # MetaTrader5's C extension accepts the trade request as its
            # positional argument.  Passing ``request=...`` looks equivalent
            # in Python, but the extension silently builds an empty native
            # request and returns retcode=10013 (INVALID_REQUEST).
            send_started_ns = time.perf_counter_ns()
            try:
                # Persist the point of no return before entering the native
                # extension. A crash in symbol/tick preflight remains safely
                # replayable as CLAIMED; only this boundary becomes SENDING.
                mark_execution_dispatching()
                result = mt5.order_send(dict(request))
            finally:
                broker_send_ns += time.perf_counter_ns() - send_started_ns
                attempts += 1
            if result is None:
                return _result(None)
            if result.retcode not in _requote_codes() or retries >= REQUOTE_RETRIES or not is_deal:
                return _result(result)
            if not _timed_quote_refresh():
                return _result(result)
            retries += 1
            logger.warning(
                "Refreshing quote and retrying once | instance=%s symbol=%s retcode=%s retry=%s",
                INSTANCE_NAME, request.get("symbol"), result.retcode, retries,
            )

    result, retries, order_timing = _mt5_call(
        _native_send,
        _priority=MT5_API_PRIORITY_TRADE,
        _metric_name="order_send",
    )
    trace = _MT5_NATIVE_TRACE.get()
    if isinstance(trace, list):
        for timing in reversed(trace):
            if timing.get("name") == "order_send":
                timing.update(order_timing)
                break
    return result, retries


def _symbol_info(symbol):
    key = str(symbol)
    now = time.monotonic()
    ttl_sec = SYMBOL_INFO_CACHE_TTL_MS / 1000.0
    if ttl_sec > 0:
        with _SYMBOL_INFO_CACHE_LOCK:
            cached = _SYMBOL_INFO_CACHE.get(key)
            if cached is not None and now - cached[0] < ttl_sec:
                return cached[1]
    info = _mt5_call(mt5.symbol_info, key)
    if info is not None and not info.visible:
        _mt5_call(mt5.symbol_select, key, True)
        info = _mt5_call(mt5.symbol_info, key)
    if info is not None and ttl_sec > 0:
        with _SYMBOL_INFO_CACHE_LOCK:
            _SYMBOL_INFO_CACHE[key] = (time.monotonic(), info)
    return info


def _execute_order(payload):
    request_id = payload["request_id"]
    order_key = str(payload.get("order_type") or "").lower()
    if order_key not in ORDER_TYPE_MAP:
        return _failure(request_id, "Invalid order_type: %s" % payload.get("order_type"))
    info = _symbol_info(payload["symbol"])
    if info is None:
        return _failure(request_id, "Symbol not found: %s" % payload["symbol"])
    order_type = ORDER_TYPE_MAP[order_key]
    pending_types = {
        mt5.ORDER_TYPE_BUY_LIMIT,
        mt5.ORDER_TYPE_SELL_LIMIT,
        mt5.ORDER_TYPE_BUY_STOP,
        mt5.ORDER_TYPE_SELL_STOP,
    }
    request = {
        "action": mt5.TRADE_ACTION_PENDING if order_type in pending_types else mt5.TRADE_ACTION_DEAL,
        "symbol": payload["symbol"],
        "volume": _normalize_volume(float(payload["volume"]), info),
        "type": order_type,
        "deviation": int(payload.get("deviation") or 10),
        "magic": MT5_LOGIN,
        "comment": str(payload.get("comment") or "")[:255],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN if order_type in pending_types else _pick_filling(info),
    }
    digits = int(info.digits)
    for field in ("price", "sl", "tp"):
        value = payload.get(field)
        if value is not None:
            request[field] = _normalize_price(float(value), digits)
    if payload.get("position_ticket") is not None:
        request["position"] = int(payload["position_ticket"])

    result, retries = _send_with_requote(request, sym_info=info)
    if result is None:
        return _unknown(
            request_id,
            "order_send returned None: %s" % (_mt5_call(mt5.last_error),),
            requote_retries=retries,
        )
    if result.retcode not in _success_codes():
        return _failure(
            request_id,
            "Order failed retcode=%s comment=%s" % (result.retcode, result.comment),
            retcode=result.retcode,
            comment=result.comment,
            requote_retries=retries,
        )
    filled = float(getattr(result, "volume", 0.0) or 0.0)
    normalized = float(request["volume"])
    partial = result.retcode == getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
    response = {
        "success": True,
        "retcode": result.retcode,
        "order": result.order,
        "deal": result.deal,
        "volume": filled,
        "price": result.price,
        "comment": result.comment,
        "requested_volume": float(payload["volume"]),
        "normalized_volume": normalized,
        "filled_volume": filled,
        "remaining_volume": max(0.0, round(normalized - filled, 8)),
        "partial": partial,
        "requote_retries": retries,
        "request_id": request_id,
    }
    _POSITION_CACHE.invalidate()
    response.update(_trade_snapshot_metadata())
    _schedule_post_trade_snapshot()
    mgr.ping()
    return ExecutionOutcome("DONE", response)


def _select_close_position(payload):
    ticket = payload.get("ticket")
    if ticket is not None:
        # QH closes exact tickets and normally has just published the same
        # snapshot used to render the slot. Reuse that bounded snapshot so a
        # multi-slot close burst does not pay one native positions_get call
        # before every order_send. The ticket remains in the MT5 request, and
        # a missing/expired snapshot falls back to an authoritative lookup.
        cached = _POSITION_CACHE.peek_ticket(ticket)
        if cached is not None:
            return SimpleNamespace(**cached)
        positions = _mt5_call(mt5.positions_get, ticket=int(ticket))
        return positions[0] if positions else None
    symbol = payload.get("symbol")
    side = str(payload.get("side") or "").lower()
    if not symbol or side not in ("buy", "sell"):
        return None
    positions = _mt5_call(mt5.positions_get, symbol=symbol)
    target_type = 0 if side == "buy" else 1
    matching = [position for position in (positions or []) if position.type == target_type]
    if payload.get("volume") is not None:
        requested = float(payload["volume"])
        matching.sort(key=lambda position: abs(float(position.volume) - requested))
    return matching[0] if matching else None


def _close_one(position, requested_volume=None):
    info = _symbol_info(position.symbol)
    if info is None:
        return None, 0, "Symbol info not found for %s" % position.symbol, 0.0
    raw_volume = min(float(requested_volume), float(position.volume)) if requested_volume is not None else float(position.volume)
    volume = _normalize_volume(raw_volume, info)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_SELL if position.type == 0 else mt5.ORDER_TYPE_BUY,
        "position": position.ticket,
        "deviation": 10,
        "magic": MT5_LOGIN,
        "comment": "",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling(info),
    }
    result, retries = _send_with_requote(request, sym_info=info)
    return result, retries, None, volume


def _execute_close(payload):
    request_id = payload["request_id"]
    position = _select_close_position(payload)
    if position is None:
        label = "ticket %s" % payload.get("ticket") if payload.get("ticket") else "matching position"
        return _failure(request_id, "Position %s not found" % label)
    result, retries, error, requested = _close_one(position, payload.get("volume"))
    if error:
        return _failure(request_id, error)
    if result is None:
        return _unknown(
            request_id,
            "close order_send returned None: %s" % (_mt5_call(mt5.last_error),),
            ticket=position.ticket,
            requote_retries=retries,
        )
    if result.retcode not in _success_codes():
        return _failure(
            request_id,
            "Close failed retcode=%s comment=%s" % (result.retcode, result.comment),
            ticket=position.ticket,
            retcode=result.retcode,
            requote_retries=retries,
        )
    filled = float(getattr(result, "volume", 0.0) or 0.0)
    partial = result.retcode == getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
    _POSITION_CACHE.invalidate()
    snapshot_metadata = _trade_snapshot_metadata()
    _schedule_post_trade_snapshot()
    mgr.ping()
    if partial and filled + 1e-9 < requested:
        return _unknown(
            request_id,
            "Close partially filled; reconcile the exact ticket before retrying",
            ticket=position.ticket,
            retcode=result.retcode,
            filled_volume=filled,
            remaining_volume=max(0.0, round(requested - filled, 8)),
            partial=True,
            requote_retries=retries,
        )
    response = {
        "success": True,
        "retcode": result.retcode,
        "order": result.order,
        "deal": getattr(result, "deal", None),
        "ticket": position.ticket,
        "volume": filled,
        "price": result.price,
        "comment": result.comment,
        "partial": partial,
        "requote_retries": retries,
        "request_id": request_id,
    }
    response.update(snapshot_metadata)
    return ExecutionOutcome("DONE", response)


def _execute_close_all(payload):
    request_id = payload["request_id"]
    symbol = payload.get("symbol")
    positions = _mt5_call(mt5.positions_get, symbol=symbol) if symbol else _mt5_call(mt5.positions_get)
    if positions is None:
        return _unknown(request_id, "positions_get returned None before close-all")
    results = []
    closed = failed = retries_total = 0
    has_unknown = False
    for position in positions:
        result, retries, error, requested = _close_one(position)
        retries_total += retries
        if error:
            failed += 1
            results.append({"ticket": position.ticket, "success": False, "reason": error})
        elif result is None:
            failed += 1
            has_unknown = True
            results.append({"ticket": position.ticket, "success": False, "unknown": True})
        elif result.retcode == getattr(mt5, "TRADE_RETCODE_DONE", 10009):
            closed += 1
            results.append({"ticket": position.ticket, "success": True, "order": result.order})
        else:
            failed += 1
            results.append({"ticket": position.ticket, "success": False, "retcode": result.retcode})
    if positions:
        _POSITION_CACHE.invalidate()
        _schedule_post_trade_snapshot()
    mgr.ping()
    response = {
        "success": failed == 0,
        "closed": closed,
        "failed": failed,
        "results": results,
        "requote_retries": retries_total,
        "request_id": request_id,
    }
    if has_unknown:
        response.update({"unknown": True, "state": "UNKNOWN"})
        return ExecutionOutcome("UNKNOWN", response)
    return ExecutionOutcome("DONE", response)


def _execute_cancel_all(payload):
    request_id = payload["request_id"]
    symbol = payload.get("symbol")
    orders = _mt5_call(mt5.orders_get, symbol=symbol) if symbol else _mt5_call(mt5.orders_get)
    if orders is None:
        return _unknown(request_id, "orders_get returned None before cancel-all")
    cancelled = failed = 0
    unknown = False
    for order in orders:
        result = _mt5_call(
            mt5.order_send,
            request={"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket},
        )
        if result is None:
            failed += 1
            unknown = True
        elif result.retcode == getattr(mt5, "TRADE_RETCODE_DONE", 10009):
            cancelled += 1
        else:
            failed += 1
    response = {
        "success": failed == 0,
        "cancelled": cancelled,
        "failed": failed,
        "request_id": request_id,
    }
    if unknown:
        response.update({"unknown": True, "state": "UNKNOWN"})
        return ExecutionOutcome("UNKNOWN", response)
    return ExecutionOutcome("DONE", response)


def _execute_v3(op, payload):
    execution_started_at_ns = time.time_ns()
    execution_started_mono_ns = time.perf_counter_ns()
    native_trace = []
    priority_token = _MT5_CALL_PRIORITY.set(MT5_API_PRIORITY_TRADE)
    trace_token = _MT5_NATIVE_TRACE.set(native_trace)
    try:
        if not mgr.ensure():
            outcome = _failure(payload["request_id"], "MT5 not connected")
        else:
            handlers = {
                "order": _execute_order,
                "close": _execute_close,
                "close_all": _execute_close_all,
                "cancel_all": _execute_cancel_all,
            }
            outcome = handlers[op](payload)
    except Exception as exc:
        # Preserve the coordinator's existing UNKNOWN semantics, but keep the
        # native timing trace that explains where an exceptional call failed.
        outcome = ExecutionOutcome("UNKNOWN", {
            "success": False,
            "unknown": True,
            "request_id": payload["request_id"],
            "error": "execution exception: %s" % exc,
        })
    finally:
        _MT5_NATIVE_TRACE.reset(trace_token)
        _MT5_CALL_PRIORITY.reset(priority_token)

    execution_completed_at_ns = time.time_ns()
    execution_ms = max(
        0.0,
        (time.perf_counter_ns() - execution_started_mono_ns) / 1_000_000,
    )
    compact_calls = []
    for call in native_trace:
        compact = {
            key: call[key]
            for key in (
                "name", "priority", "queue_depth_at_submit", "queue_ms",
                "run_ms", "total_ms", "success", "quote_refresh_ms",
                "broker_order_send_ms", "order_attempts",
            )
            if key in call
        }
        compact_calls.append(compact)
    order_calls = [
        call for call in native_trace if call.get("name") == "order_send"
    ]
    timing = {
        "execution_started_at_ns": execution_started_at_ns,
        "execution_completed_at_ns": execution_completed_at_ns,
        "execution_ms": round(execution_ms, 3),
        "native_queue_ms": round(sum(
            float(call.get("queue_ms") or 0.0) for call in native_trace
        ), 3),
        "native_run_ms": round(sum(
            float(call.get("run_ms") or 0.0) for call in native_trace
        ), 3),
        "order_native_ms": round(sum(
            float(call.get("run_ms") or 0.0) for call in order_calls
        ), 3),
        "broker_order_send_ms": round(sum(
            float(call.get("broker_order_send_ms") or 0.0)
            for call in order_calls
        ), 3),
        "quote_refresh_ms": round(sum(
            float(call.get("quote_refresh_ms") or 0.0)
            for call in order_calls
        ), 3),
        "order_attempts": sum(
            int(call.get("order_attempts") or 0) for call in order_calls
        ),
        "native_calls": compact_calls,
    }
    result = dict(outcome.result)
    result["execution_timing"] = timing
    return ExecutionOutcome(outcome.state, result)


def _on_trade_admitted(_request_id, _op):
    _MT5_TRADE_GATE.reserve_trade()


def _on_trade_completed(_request_id, _op):
    _MT5_TRADE_GATE.release_trade()
    _POSITION_CACHE.invalidate()
    _schedule_post_trade_snapshot()


_EXECUTION_WORKER_NATIVE_METHODS = frozenset({
    "account_info",
    "history_deals_get",
    "history_orders_get",
    "initialize",
    "last_error",
    "login",
    "orders_get",
    "positions_get",
    "shutdown",
    "symbol_info",
    "symbol_info_tick",
    "symbol_select",
    "symbols_get",
    "terminal_info",
})


def _execution_worker_native_call(method, args, kwargs):
    """Serve parent reads without creating a second terminal IPC session."""
    method = str(method or "")
    if method == "__bridge_reconnect__":
        return mgr.reconnect()
    if method not in _EXECUTION_WORKER_NATIVE_METHODS:
        raise RuntimeError("native RPC method is not allowed: %s" % method)
    function = getattr(mt5, method, None)
    if not callable(function):
        raise RuntimeError("MetaTrader5 method is unavailable: %s" % method)
    result = _mt5_call(function, *(args or ()), **(kwargs or {}))
    if method == "account_info" and result is not None:
        try:
            actual_login = int(getattr(result, "login", 0) or 0)
        except (TypeError, ValueError):
            actual_login = 0
        if actual_login == MT5_LOGIN:
            mgr._on_success()
            _cache_connection_account(result)
        else:
            mgr.connected = False
            mgr.failures += 1
            _invalidate_account_snapshot()
    return result


def _execution_worker_startup():
    timeout = max(
        1.0, float(os.getenv("MT5_EXECUTION_CONNECT_SEC", "45"))
    )
    retry_delay = max(
        0.01,
        float(os.getenv("MT5_EXECUTION_CONNECT_RETRY_MS", "750")) / 1000.0,
    )
    deadline = time.monotonic() + timeout
    attempts = 0
    while True:
        attempts += 1
        if mgr.ensure():
            if attempts > 1:
                logger.info(
                    "MT5 execution worker connected after %s attempts", attempts
                )
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "MT5 execution worker could not connect after %s attempts"
                % attempts
            )
        # A failed initialize can leave a transient IPC handle behind. Close
        # it before retrying, as the long-running HTTP bridge already does on
        # later health probes.
        try:
            mgr.disconnect()
        except Exception:
            pass
        logger.warning(
            "MT5 execution worker IPC connect deferred | attempt=%s", attempts
        )
        time.sleep(min(retry_delay, max(0.0, deadline - time.monotonic())))


def _execution_worker_shutdown():
    mgr.disconnect()
    _MT5_API_EXECUTOR.shutdown(wait=True, cancel_futures=False)


if _EXECUTION_CHILD:
    _EXECUTION = None
elif EXECUTION_PROCESS_ISOLATION:
    _EXECUTION = ProcessIsolatedExecutionCoordinator(
        IDEMPOTENCY_DB,
        "app.main:_execute_v3",
        on_admit=_on_trade_admitted,
        on_complete=_on_trade_completed,
        admission_gate=_MT5_TRADE_GATE,
        owner_fence_key=EXECUTION_FENCE_KEY,
    )
else:
    _EXECUTION = DurableExecutionCoordinator(
        IDEMPOTENCY_DB,
        _execute_v3,
        on_admit=_on_trade_admitted,
        on_complete=_on_trade_completed,
    )


def _pending_response_v3(request_id, state="PENDING", trace=None):
    return JSONResponse(status_code=202, content={
        "success": False,
        "accepted": True,
        "pending": True,
        "unknown": False,
        "state": state,
        "request_id": request_id,
        "status_url": "/mt5/order-status/%s" % request_id,
        "trace": dict(trace or {}),
    })


def _record_trace(record):
    trace = dict(record.get("trace") or {})
    trace.setdefault("agent_wal_durable_ns", int(record.get("admitted_at_ns") or 0))
    trace.setdefault("agent_worker_claimed_ns", int(record.get("claimed_at_ns") or 0))
    trace.setdefault("agent_execution_started_ns", int(record.get("started_at_ns") or 0))
    trace.setdefault("agent_execution_completed_ns", int(record.get("completed_at_ns") or 0))
    trace.setdefault("agent_worker_pid", int(record.get("worker_pid") or 0))
    return trace


def _render_record(record, replay=False):
    state = record["state"]
    result = dict(record.get("result") or {})
    request_id = record["request_id"]
    trace = _record_trace(record)
    if any(trace.values()):
        result_trace = dict(result.get("trace") or {})
        result_trace.update({key: value for key, value in trace.items() if value})
        result["trace"] = result_trace
    if state == "DONE":
        result.setdefault("success", True)
        result.setdefault("request_id", request_id)
        if replay:
            result["idempotency_hit"] = True
        return result
    if state == "FAILED":
        raise HTTPException(400, result.get("error") or "execution failed")
    if state == "UNKNOWN":
        result.setdefault("success", False)
        result.setdefault("unknown", True)
        result.setdefault("state", "UNKNOWN")
        result.setdefault("request_id", request_id)
        if replay:
            result["idempotency_hit"] = True
        return JSONResponse(status_code=202, content=result)
    if state == "ABSENT":
        result.setdefault("success", False)
        result.setdefault("failed", True)
        result.setdefault("not_sent", True)
        result.setdefault("dispatch_durable", False)
        result.setdefault("request_id", request_id)
        return JSONResponse(status_code=409, content=result)
    return _pending_response_v3(request_id, state=state, trace=trace)


def _render_current_submission(request_id, admission_trace):
    """Return the WAL's real phase; never promote ADMITTED to SENDING in UI."""
    record = _EXECUTION.get(request_id)
    if record is None:
        return _pending_response_v3(request_id, trace=admission_trace)
    state = str(record.get("state") or "PENDING")
    if state in ("DONE", "FAILED", "UNKNOWN", "ABSENT"):
        return _render_record(record)
    trace = dict(admission_trace or {})
    trace.update({key: value for key, value in _record_trace(record).items() if value})
    return _pending_response_v3(request_id, state=state, trace=trace)


async def _submit_v3(op, model):
    agent_received_ns = time.time_ns()
    payload = _model_payload(model)
    request_id = payload.get("request_id") or uuid.uuid4().hex
    payload["request_id"] = request_id
    intent_hash = _intent_hash(op, payload)
    try:
        submission = _EXECUTION.submit(request_id, op, intent_hash, payload)
    except ExecutionBusy:
        raise HTTPException(
            429,
            "ACCOUNT_EXECUTION_BUSY: previous broker command is not terminal",
            headers={"Retry-After": "1"},
        )
    except IntentConflict as exc:
        raise HTTPException(409, str(exc))
    if submission.replayed:
        return _render_record(submission.record, replay=True)
    admission_trace = {
        "agent_received_ns": agent_received_ns,
        "agent_wal_durable_ns": int(submission.admitted_at_ns or time.time_ns()),
    }
    if payload.get("ack_only"):
        return _render_current_submission(request_id, admission_trace)
    try:
        wrapped = asyncio.wrap_future(submission.future)
        outcome = await asyncio.wait_for(asyncio.shield(wrapped), timeout=EXEC_SYNC_WAIT_SEC)
    except asyncio.TimeoutError:
        return _render_current_submission(request_id, admission_trace)
    record = _EXECUTION.get(request_id)
    if record is not None:
        return _render_record(record)
    return _render_record({"request_id": request_id, "state": outcome.state,
                           "result": outcome.result, "trace": admission_trace})


@app.post("/mt5/order", dependencies=[Depends(verify_api_key)])
async def place_order_v3(req: OrderRequest):
    return await _submit_v3("order", req)


@app.post("/mt5/position/close", dependencies=[Depends(verify_api_key)])
async def close_position_v3(req: ClosePositionRequest):
    if req.ticket is None:
        raise HTTPException(400, "EXACT_TICKET_REQUIRED")
    return await _submit_v3("close", req)


@app.post("/mt5/position/close-all", dependencies=[Depends(verify_api_key)])
async def close_all_positions_v3(req: CloseAllRequest):
    return await _submit_v3("close_all", req)


@app.post("/mt5/cancel-all", dependencies=[Depends(verify_api_key)])
async def cancel_all_v3(req: CancelAllRequest):
    return await _submit_v3("cancel_all", req)


@app.get("/mt5/order-status/{request_id}", dependencies=[Depends(verify_api_key)])
async def order_status_v3(request_id: str):
    loop = asyncio.get_running_loop()
    status = await loop.run_in_executor(
        _ORDER_STATUS_EXECUTOR, partial(_EXECUTION.status, request_id, True)
    )
    return status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
