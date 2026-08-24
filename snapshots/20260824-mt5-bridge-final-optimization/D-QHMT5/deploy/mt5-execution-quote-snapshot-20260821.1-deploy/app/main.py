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
  POST /mt5/position/close-batch
  POST /mt5/position/close-all
  POST /mt5/cancel-all
"""

import asyncio
import contextvars
import hashlib
import json
import math
import os
import time
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Optional, List, Dict, Any, Union

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

try:
    # Optional on older candidate runtimes.  The batch remains safe because
    # its outer request WAL is still the idempotency boundary; newer isolated
    # workers additionally expose per-ticket progress during SENDING.
    from .runtime import record_execution_progress
except ImportError:  # pragma: no cover - exercised by legacy runtime deploys
    def record_execution_progress(_progress):
        return False

load_dotenv()

# ─── 日志 ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mt5-bridge")

# ─── 配置（从 .env 读取）────────────────────────────────────────────────────
API_KEY        = os.getenv("API_KEY",           "OQ6bUimHZDmXEZzJKE")
MT5_LOGIN      = int(os.getenv("MT5_LOGIN",     "0"))
MT5_PASSWORD   = os.getenv("MT5_PASSWORD",      "")
MT5_SERVER     = os.getenv("MT5_SERVER",        "Bybit-Live-2")
MT5_PATH       = os.getenv("MT5_PATH",          r"C:\Program Files\MetaTrader 5\terminal64.exe")
SERVICE_PORT   = int(os.getenv("SERVICE_PORT",  "8001"))
INSTANCE_NAME  = os.getenv("INSTANCE_NAME",     "system")   # 'system' | 'cq987'
BRIDGE_BUILD_ID = os.getenv(
    "MT5_BRIDGE_BUILD_ID", "mt5-execution-probe-memory-20260819.6"
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
# A trade must not pay a native ``symbol_info_tick`` round trip when the
# terminal already returned a recent quote.  This cache is deliberately local
# to each native owner process; it is never used as a durable broker snapshot.
NATIVE_TICK_CACHE_TTL_MS = max(
    0, int(os.getenv("MT5_NATIVE_TICK_CACHE_TTL_MS", "300"))
)
# ``lazy`` sends a market request as-is and only obtains a quote when MT5
# explicitly reports a quote/price request error. ``always`` is a rollback
# switch for brokers that require a client-side price on every market deal.
TRADE_QUOTE_MODE = str(os.getenv("MT5_TRADE_QUOTE_MODE", "lazy") or "lazy").strip().lower()
if TRADE_QUOTE_MODE not in {"lazy", "always"}:
    TRADE_QUOTE_MODE = "lazy"
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
HISTORY_CACHE_TTL_SEC = max(
    1.0, float(os.getenv("MT5_HISTORY_CACHE_TTL_SEC", "30"))
)
HISTORY_CACHE_STALE_MAX_SEC = max(
    HISTORY_CACHE_TTL_SEC,
    float(os.getenv("MT5_HISTORY_CACHE_STALE_MAX_SEC", "900")),
)
EXEC_SYNC_WAIT_SEC = max(0.05, float(os.getenv("EXEC_SYNC_WAIT_SEC", "0.85")))
REQUOTE_RETRIES = min(2, max(0, int(os.getenv("MT5_REQUOTE_RETRIES", "1"))))
CLOSE_BATCH_MAX_TICKETS = max(
    1, min(64, int(os.getenv("MT5_CLOSE_BATCH_MAX_TICKETS", "32")))
)
IDEMPOTENCY_DB = os.getenv("IDEMPOTENCY_DB", os.path.join(os.getcwd(), "idempotency.db"))
EXECUTION_PROCESS_ISOLATION = str(os.getenv(
    "MT5_EXECUTION_PROCESS_ISOLATION", "0"
)).strip().lower() in ("1", "true", "yes", "on")
_EXECUTION_CHILD = str(os.getenv("MT5_EXECUTION_CHILD", "0")).strip() == "1"
# In isolated mode the parent stamps admission hints with the current native
# worker generation.  The child receives the same value from runtime.py before
# importing this module; a restart therefore fences all pre-restart hints.
EXECUTION_WORKER_GENERATION = str(
    os.getenv("MT5_EXECUTION_WORKER_GENERATION", "") or ""
).strip()
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
# Admission position hints are an optimization only.  Keep their trust
# window shorter than the general stale projection window so a queued close
# falls back to an exact broker ticket read rather than using an old volume or
# side.  A zero/negative value disables hint reuse entirely.
CLOSE_SNAPSHOT_MAX_AGE_MS = max(
    0,
    min(
        POSITIONS_STALE_MAX_MS,
        int(os.getenv("MT5_CLOSE_SNAPSHOT_MAX_AGE_MS", "500")),
    ),
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


class CloseBatchTicketRequest(BaseModel):
    ticket: int
    symbol: Optional[str] = None
    side: Optional[str] = None
    volume: Optional[float] = None


class CloseBatchRequest(BaseModel):
    tickets: List[Union[CloseBatchTicketRequest, int]]
    # Optional caller-level identity.  When omitted, request_id remains the
    # durable batch identity for backwards compatibility.
    batch_id: Optional[str] = None
    request_id: Optional[str] = None
    ack_only: bool = False


class CloseAllRequest(BaseModel):
    symbol: Optional[str] = None   # None = 全部品种
    # Optional exact-ticket scope.  The bridge fixes this list at admission
    # and never discovers a different position set halfway through a batch.
    tickets: Optional[List[int]] = None
    batch_id: Optional[str] = None
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
_HISTORY_CACHE_LOCK = threading.RLock()
_HISTORY_CACHE = {}
_HISTORY_REFRESHING = set()
_MT5_TRADE_GATE = TradeAdmissionGate()
_SYMBOL_INFO_CACHE_LOCK = threading.RLock()
_SYMBOL_INFO_CACHE = {}
_TICK_SNAPSHOT_LOCK = threading.RLock()
_TICK_SNAPSHOTS = {}
# Native-owner quote cache.  Unlike ``_TICK_SNAPSHOTS`` this cache is filled
# by both public tick reads and the execution worker itself, so process
# isolation does not leave the order hot path without a usable recent quote.
_NATIVE_TICK_CACHE_LOCK = threading.RLock()
_NATIVE_TICK_CACHE = {}
_TICK_REFRESH_LOCKS = {}
_TICK_SNAPSHOT_GENERATION = 0
_CONNECTION_ACCOUNT_CACHE_LOCK = threading.RLock()
_ACCOUNT_SNAPSHOT_REFRESH_LOCK = threading.Lock()
_ACCOUNT_SNAPSHOT_REFRESH_TASK = None
_ACCOUNT_CACHE_UNSET = object()
_CONTROL_READ_DEFERRED = object()
_SNAPSHOT_UNSET = object()
_READ_GATE_DISABLED = object()
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
    with _NATIVE_TICK_CACHE_LOCK:
        _NATIVE_TICK_CACHE.clear()


def _tick_snapshot_generation():
    with _TICK_SNAPSHOT_LOCK:
        return _TICK_SNAPSHOT_GENERATION


def _native_tick_price(tick, request_type):
    """Return the side-specific quote only when it is finite and positive."""
    buy_types = {
        getattr(mt5, "ORDER_TYPE_BUY", 0),
        getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2),
        getattr(mt5, "ORDER_TYPE_BUY_STOP", 4),
        getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", 6),
    }
    field = "ask" if request_type in buy_types else "bid"
    try:
        price = float(getattr(tick, field))
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return price


def _store_native_tick_snapshot(symbol, tick):
    """Store a small process-local quote record for the next market deal."""
    key = _tick_key(symbol)
    if not key or tick is None:
        return None
    # Validate both sides at write time.  A one-sided quote is not useful for
    # an opposite-leg close and should force the bounded native refresh path.
    try:
        bid = float(getattr(tick, "bid"))
        ask = float(getattr(tick, "ask"))
    except (AttributeError, TypeError, ValueError):
        return None
    if (not math.isfinite(bid) or not math.isfinite(ask)
            or bid <= 0 or ask <= 0):
        return None
    payload = {
        "bid": bid,
        "ask": ask,
        "last": getattr(tick, "last", None),
        "volume": getattr(tick, "volume", None),
        "time": getattr(tick, "time", None),
        "time_msc": getattr(tick, "time_msc", None),
        "refreshed_at": time.monotonic(),
    }
    with _NATIVE_TICK_CACHE_LOCK:
        _NATIVE_TICK_CACHE[key] = payload
    return payload


def _native_tick_snapshot_view(symbol):
    """Return a bounded recent native quote, or ``None`` when unavailable."""
    if NATIVE_TICK_CACHE_TTL_MS <= 0:
        return None
    key = _tick_key(symbol)
    with _NATIVE_TICK_CACHE_LOCK:
        cached = dict(_NATIVE_TICK_CACHE.get(key) or {})
    refreshed_at = float(cached.get("refreshed_at") or 0.0)
    if not refreshed_at:
        return None
    age_ms = max(0.0, (time.monotonic() - refreshed_at) * 1000.0)
    if age_ms > NATIVE_TICK_CACHE_TTL_MS:
        return None
    cached["age_ms"] = round(age_ms, 3)
    return cached


def _apply_native_tick_price(request, sym_info, cached):
    """Apply a cached/native quote and return its normalized price."""
    if not cached:
        return None
    price = _native_tick_price(
        SimpleNamespace(**cached), request.get("type")
    )
    if price is None:
        return None
    digits = int(getattr(sym_info, "digits", 0) or 0)
    request["price"] = _normalize_price(price, digits)
    return price


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


def _mt5_call(func, *args, _priority=None, _metric_name=None,
              _read_gate_timeout=_READ_GATE_DISABLED,
              _read_gate_quiet_seconds=0.0, **kwargs):
    """Submit exactly one native call to the account-scoped owner.

    A read gate is acquired *inside* the single native worker, immediately
    before the call starts.  Acquiring it in the HTTP/control thread makes a
    queue of not-yet-running reads look active to the trade promoter and was
    the source of multi-second bursts during health/positions polling.
    ``_CONTROL_READ_DEFERRED`` is returned when a queued read reaches the
    worker after a trade has reserved the account.
    """
    priority = _priority
    if priority is None:
        priority = _MT5_CALL_PRIORITY.get()
    if priority is None:
        priority = _default_mt5_priority(func)
    explicit_gate = _read_gate_timeout is not _READ_GATE_DISABLED
    # Preserve the low-level helper's historical safety for callers that use
    # _mt5_call directly, while moving acquisition into the worker. Public
    # request paths use _try_control_native_read and receive the explicit
    # deferred sentinel instead of holding a queued lease.
    implicit_gate = (
        not explicit_gate
        and not _MT5_READ_GATE_HELD.get()
        and not _is_native_trade_callable(func)
        and priority > MT5_API_PRIORITY_TRADE
        and (
            (EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD)
            or getattr(func, "__name__", "") == "positions_get"
        )
    )
    gate_read = explicit_gate or implicit_gate
    gate_timeout = (
        _read_gate_timeout if explicit_gate else
        (0.0
         if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD
         else POSITIONS_READ_GATE_WAIT_MS / 1000.0)
    )
    gate_quiet = max(0.0, float(_read_gate_quiet_seconds or 0.0))
    if implicit_gate and not gate_quiet:
        gate_quiet = POSITIONS_TRADE_QUIET_MS / 1000.0

    def _run_with_gate(call):
        token = None
        if gate_read and not _MT5_READ_GATE_HELD.get():
            try:
                _MT5_TRADE_GATE.begin_read(
                    timeout=gate_timeout,
                    quiet_seconds=gate_quiet,
                )
            except TimeoutError:
                if explicit_gate:
                    return _CONTROL_READ_DEFERRED
                raise
            token = _MT5_READ_GATE_HELD.set(True)
            # A trade can be reserved by another thread immediately after
            # the gate opens. Recheck before the native call so a read that
            # merely reached the worker does not sneak ahead of the durable
            # writer.
            if explicit_gate and _MT5_TRADE_GATE.pending_trades() > 0:
                _MT5_READ_GATE_HELD.reset(token)
                _MT5_TRADE_GATE.end_read()
                token = None
                return _CONTROL_READ_DEFERRED
        try:
            return call()
        finally:
            if token is not None:
                _MT5_READ_GATE_HELD.reset(token)
                _MT5_TRADE_GATE.end_read()

    if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD:
        coordinator = globals().get("_EXECUTION")
        if coordinator is None:
            raise RuntimeError("native MT5 owner is not initialized")

        def _native_owner_call():
            return _run_with_gate(lambda: coordinator.native_call(
                getattr(func, "__name__", ""), args=args, kwargs=kwargs,
            ))

        native_future = _MT5_API_EXECUTOR.submit(
            _native_owner_call, priority=priority,
            metric_name=(_metric_name or getattr(func, "__name__", None)),
        )
    elif _is_native_trade_callable(func):
        def _native_trade_call():
            def _call():
                mark_execution_dispatching()
                if not args and set(kwargs) == {"request"}:
                    return func(kwargs["request"])
                return func(*args, **kwargs)
            return _run_with_gate(_call)
        native_future = _MT5_API_EXECUTOR.submit(
            _native_trade_call, priority=priority,
            metric_name=(_metric_name or getattr(func, "__name__", None)),
        )
    else:
        native_future = _MT5_API_EXECUTOR.submit(
            lambda: _run_with_gate(lambda: func(*args, **kwargs)),
            priority=priority,
            metric_name=(_metric_name or getattr(func, "__name__", None)),
        )
    try:
        result = native_future.result()
        if getattr(func, "__name__", "") == "symbol_info_tick" and args:
            # Keep the owner-local cache warm in both the HTTP process and an
            # isolated execution child.  The latter cannot see the parent's
            # Python snapshot dictionary over the RPC boundary.
            _store_native_tick_snapshot(args[0], result)
        return result
    finally:
        trace = _MT5_NATIVE_TRACE.get()
        timing = getattr(native_future, "native_timing", None)
        if isinstance(trace, list) and isinstance(timing, dict):
            trace.append(dict(timing))


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
    # In process-isolated mode the HTTP process is not the native terminal
    # owner. Calling mgr.ensure() here would enqueue an account_info RPC for
    # every UI read. Admission/worker health and the cached verified identity
    # are sufficient for a request path; reconnect/order failures remain the
    # authoritative signal for a lost terminal session.
    if EXECUTION_PROCESS_ISOLATION and not _EXECUTION_CHILD:
        identity = _cached_connection_identity()
        try:
            probe = _EXECUTION.execution_probe_health()
        except Exception:
            probe = {"coordinator_healthy": False}
        if (mgr.connected and identity.get("verified") and
                probe.get("coordinator_healthy") is True):
            return True
        raise HTTPException(503, "MT5 native owner is not ready")
    if not await _control_call_async(mgr.ensure):
        raise HTTPException(503, "MT5 not connected")


def _try_control_native_read(func, *args, _priority=MT5_API_PRIORITY_NORMAL,
                             _metric_name=None, _quiet_seconds=0.0, **kwargs):
    """Run one bounded control read without reserving a queued lease."""
    if _MT5_TRADE_GATE.pending_trades() > 0:
        return _CONTROL_READ_DEFERRED
    # The lease is acquired by the native worker after any already-running
    # call completes. A read that was merely queued when a trade arrived is
    # rejected in O(1) and never delays promotion of the trade.
    return _mt5_call(
        func, *args, _priority=_priority, _metric_name=_metric_name,
        _read_gate_timeout=0.0,
        _read_gate_quiet_seconds=_quiet_seconds,
        **kwargs
    )


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
        # A successful initialize/login can attach this process to a new
        # terminal session (or even a different account after a bad restart).
        # Never let the old session's position projection survive that
        # boundary; close selection will then perform an exact broker read.
        position_cache = globals().get("_POSITION_CACHE")
        if position_cache is not None:
            position_cache.invalidate()
        _invalidate_account_snapshot()
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
                probe_fn = getattr(coordinator, "execution_probe_health", None)
                probe = (probe_fn() if callable(probe_fn)
                         else coordinator.metrics())
                if not probe.get("coordinator_healthy"):
                    self.connected = False
                    return False
                # The parent has no terminal session. A cached verified
                # connection plus a healthy native owner is the admission
                # check; never enqueue account_info on every trade/HTTP read.
                if self.connected:
                    return True
                identity = _cached_connection_identity()
                if identity.get("verified"):
                    self._on_success()
                    return True
                # A disconnected owner needs one explicit identity probe to
                # bootstrap the cache. This path is reached only when the
                # cached connection is absent/invalid, never on the hot trade
                # path after startup.
                info = _mt5_call(mt5.account_info)
                if (info is None or
                        int(getattr(info, "login", 0) or 0) != MT5_LOGIN):
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
        if EXECUTION_PROCESS_ISOLATION and _EXECUTION_CHILD and self.connected:
            # Startup verified the child terminal. Let the broker result (or
            # an explicit reconnect) detect a lost session instead of adding
            # a cold account_info RPC before the first order after 30 seconds.
            self._on_success()
            return True
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
        position_cache = globals().get("_POSITION_CACHE")
        if position_cache is not None:
            position_cache.invalidate()
        _invalidate_account_snapshot()
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


def _fetch_bounded_positions():
    value = _mt5_call(
        mt5.positions_get,
        _priority=MT5_API_PRIORITY_POSITIONS,
        _metric_name="positions_get",
        _read_gate_timeout=POSITIONS_READ_GATE_WAIT_MS / 1000.0,
        _read_gate_quiet_seconds=POSITIONS_TRADE_QUIET_MS / 1000.0,
    )
    return None if value is _CONTROL_READ_DEFERRED else value


_POSITION_CACHE = PositionSnapshotCache(
    fetcher=_fetch_bounded_positions,
    serializer=_serialize_position,
    ttl_ms=POSITIONS_CACHE_TTL_MS,
    stale_max_ms=POSITIONS_STALE_MAX_MS,
)


def _fetch_authoritative_positions():
    """Wait out a trade burst, then perform one broker positions read."""
    return _mt5_call(
        mt5.positions_get,
        _priority=MT5_API_PRIORITY_POSITIONS,
        _metric_name="positions_get_authoritative",
        _read_gate_timeout=None,
        _read_gate_quiet_seconds=POSITIONS_TRADE_QUIET_MS / 1000.0,
    )

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


def _mark_trade_snapshot_pending():
    """Invalidate/project positions only from the owning HTTP process.

    In isolation the child has its own Python cache and its 50 ms refresh
    timer cannot observe the parent's durable trade admission gate. Letting
    that timer call positions_get re-introduces a nested read queue directly
    in front of the next order. The parent completion callback owns the single
    post-burst projection instead.
    """
    if EXECUTION_PROCESS_ISOLATION and _EXECUTION_CHILD:
        return {"snapshot_pending": True, "snapshot_owner": "parent"}
    _POSITION_CACHE.invalidate()
    metadata = _trade_snapshot_metadata()
    _schedule_post_trade_snapshot()
    return metadata

# ────────────────────────────────────────────────────────────────────────────
# 端点实现
# ────────────────────────────────────────────────────────────────────────────

# ── 1. Health ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health(deep: bool = False):
    # Health probes are high-frequency reads. The default response is purely
    # in-memory; an operator can opt into SQLite/native diagnostics with
    # ``?deep=true`` without making normal probes compete with trades.
    if deep and "_EXECUTION" in globals():
        queue_metrics = _EXECUTION.metrics()
    elif "_EXECUTION" in globals():
        try:
            queue_metrics = _EXECUTION.execution_probe_health()
        except Exception:
            queue_metrics = {}
        queue_metrics = dict(queue_metrics or {})
        queue_metrics.update({
            "source": "memory",
            "single_thread": True,
            "owner_serial": True,
            "native_owner_concurrency": 1,
        })
    else:
        queue_metrics = {"source": "memory", "single_thread": True}
    execution_healthy = bool(
        not EXECUTION_PROCESS_ISOLATION
        or queue_metrics.get("coordinator_healthy") is True
    )
    pending_trades = _MT5_TRADE_GATE.pending_trades()
    terminal_cache = _cached_terminal_info()
    ta = terminal_cache.get("trade_allowed")
    ta_source = "cache" if terminal_cache.get("refreshed_at") else "unavailable"
    if deep and not pending_trades and execution_healthy:
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
        "mt5_api_queue": dict(_MT5_API_EXECUTOR.metrics(),
                               scope="parent_control_rpc"),
        "mt5_trade_gate": _MT5_TRADE_GATE.metrics(),
        "deep": bool(deep),
    }

# ── 2. Connection Status ──────────────────────────────────────────────────
@app.get("/mt5/connection/status", dependencies=[Depends(verify_api_key)])
async def connection_status(execution_probe: bool = False):
    if execution_probe:
        identity = _cached_connection_identity()
        execution_health = {
            "coordinator_healthy": not EXECUTION_PROCESS_ISOLATION,
            "source": "memory",
        }
        if EXECUTION_PROCESS_ISOLATION:
            try:
                execution_health = _EXECUTION.execution_probe_health()
            except Exception:
                execution_health = {
                    "coordinator_healthy": False,
                    "source": "memory",
                }
        coordinator_healthy = bool(
            execution_health.get("coordinator_healthy") is True
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
            "execution_health_source": "memory",
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
    syms = await _control_call_async(
        _try_control_native_read, mt5.symbols_get,
        _priority=MT5_API_PRIORITY_NORMAL, _metric_name="symbols_get",
    )
    if syms is _CONTROL_READ_DEFERRED:
        raise HTTPException(503, "MT5 symbols snapshot deferred during trade activity")
    syms = syms or []
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
    info = await _control_call_async(
        _try_control_native_read, mt5.symbol_info, symbol,
        _priority=MT5_API_PRIORITY_NORMAL, _metric_name="symbol_info",
    )
    if info is _CONTROL_READ_DEFERRED:
        raise HTTPException(503, "MT5 symbol snapshot deferred during trade activity")
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
_HISTORY_CACHE_LOCK = globals().get("_HISTORY_CACHE_LOCK", threading.RLock())
_HISTORY_CACHE = globals().get("_HISTORY_CACHE", {})
_HISTORY_REFRESHING = globals().get("_HISTORY_REFRESHING", set())


def _history_cache_key(kind, days):
    return str(kind), max(1, min(90, int(days or 7)))


def _history_cache_view(kind, days):
    key = _history_cache_key(kind, days)
    with _HISTORY_CACHE_LOCK:
        entry = dict(_HISTORY_CACHE.get(key) or {})
        # Read the refresh marker under the same lock as the cache entry. A
        # request must not report a stale snapshot as settled in the small
        # window where the background worker has already claimed the key.
        pending = key in _HISTORY_REFRESHING
    if not entry:
        return None
    age = max(0.0, time.monotonic() - float(entry.get("updated_at") or 0.0))
    if age > HISTORY_CACHE_STALE_MAX_SEC:
        return None
    return {
        "records": list(entry.get("records") or []),
        "age_ms": round(age * 1000.0, 3),
        "stale": age >= HISTORY_CACHE_TTL_SEC,
        "pending": pending,
    }


def _serialize_history_record(kind, row):
    fields = (("ticket", "order", "symbol", "type", "entry", "volume",
               "price", "profit", "swap", "commission", "comment", "time")
              if kind == "deals" else
              ("ticket", "symbol", "type", "volume_initial", "volume_current",
               "price_open", "price_current", "state", "comment", "time_setup",
               "time_done"))
    return {field: getattr(row, field, None) for field in fields}


def _refresh_history_cache(kind, days):
    key = _history_cache_key(kind, days)
    try:
        if _MT5_TRADE_GATE.trade_activity(POSITIONS_TRADE_QUIET_MS / 1000.0):
            return
        from_date = datetime.utcnow() - timedelta(days=key[1])
        method = (mt5.history_deals_get if kind == "deals"
                  else mt5.history_orders_get)
        rows = _try_control_native_read(
            method, from_date, datetime.utcnow() + timedelta(hours=6),
            _priority=MT5_API_PRIORITY_NORMAL,
            _metric_name="history_%s_cache" % kind,
            _quiet_seconds=POSITIONS_TRADE_QUIET_MS / 1000.0,
        )
        if rows is _CONTROL_READ_DEFERRED or rows is None:
            return
        with _HISTORY_CACHE_LOCK:
            _HISTORY_CACHE[key] = {
                "records": [_serialize_history_record(kind, row) for row in rows],
                "updated_at": time.monotonic(),
            }
    except Exception as exc:
        logger.debug("history cache refresh deferred (%s): %s", kind, exc)
    finally:
        with _HISTORY_CACHE_LOCK:
            _HISTORY_REFRESHING.discard(key)


def _schedule_history_refresh(kind, days):
    key = _history_cache_key(kind, days)
    with _HISTORY_CACHE_LOCK:
        if key in _HISTORY_REFRESHING:
            return False
        _HISTORY_REFRESHING.add(key)
    try:
        _CONTROL_EXECUTOR.submit(_refresh_history_cache, key[0], key[1])
    except Exception:
        with _HISTORY_CACHE_LOCK:
            _HISTORY_REFRESHING.discard(key)
        return False
    return True


def _history_response(kind, days, symbol):
    view = _history_cache_view(kind, days)
    if view is None:
        _schedule_history_refresh(kind, days)
        return JSONResponse(status_code=202, content={
            kind: [], "snapshot_pending": True,
            "snapshot_source": "background_refresh", "retry_after_ms": 250,
        })
    if view["stale"]:
        _schedule_history_refresh(kind, days)
    records = view["records"]
    if symbol:
        records = [row for row in records if row.get("symbol") == symbol]
    return {
        kind: records,
        "snapshot_pending": bool(view["pending"] or view["stale"]),
        "snapshot_source": "cache", "snapshot_age_ms": view["age_ms"],
    }


@app.get("/mt5/history/deals", dependencies=[Depends(verify_api_key)])
async def history_deals(
    days:   int           = Query(7),
    symbol: Optional[str] = Query(None),
):
    await _ensure_mt5_async()
    return _history_response("deals", days, symbol)

# ── 10. History Orders ────────────────────────────────────────────────────
@app.get("/mt5/history/orders", dependencies=[Depends(verify_api_key)])
async def history_orders(
    days:   int           = Query(7),
    symbol: Optional[str] = Query(None),
):
    await _ensure_mt5_async()
    return _history_response("orders", days, symbol)

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
    # Keep the legacy status endpoint aligned with the v3 durable coordinator:
    # UNKNOWN is terminal for dispatch/idempotency (reconciliation may still be
    # required), while ABSENT is the explicit not-admitted tombstone.
    out = {"request_id": request_id, "state": _state,
           "terminal": _state in ("DONE", "FAILED", "UNKNOWN", "ABSENT")}
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


def _close_batch_child_request_id(batch_request_id, ticket):
    """Derive an immutable per-ticket id without exposing user input in it."""
    material = "qh-close-batch-v1:%s:%s" % (
        str(batch_request_id or ""), int(ticket),
    )
    return "cb" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:30]


def _normalize_close_batch_payload(payload, batch_request_id=None):
    """Validate/canonicalize an exact-ticket batch before it enters the WAL.

    The bridge never discovers tickets on behalf of this operation.  A caller
    may provide only an integer ticket, or an object with optional symbol,
    side, and volume hints.  The broker snapshot remains authoritative for
    the position identity and current volume.
    """
    payload = dict(payload or {})
    raw_tickets = payload.get("tickets")
    if not isinstance(raw_tickets, (list, tuple)):
        raise HTTPException(400, "tickets must be a list")
    if not raw_tickets:
        raise HTTPException(400, "tickets must not be empty")
    if len(raw_tickets) > CLOSE_BATCH_MAX_TICKETS:
        raise HTTPException(
            400,
            "too many tickets (max %s)" % CLOSE_BATCH_MAX_TICKETS,
        )
    batch_id = str(batch_request_id or payload.get("request_id") or "")
    if not batch_id:
        raise HTTPException(400, "close batch request_id is required")

    normalized = []
    seen = set()
    for index, raw in enumerate(raw_tickets):
        if isinstance(raw, dict):
            item = raw
        elif isinstance(raw, int) and not isinstance(raw, bool):
            item = {"ticket": raw}
        else:
            raise HTTPException(400, "invalid ticket item at index %s" % index)
        try:
            ticket = int(item.get("ticket"))
        except (TypeError, ValueError):
            raise HTTPException(400, "invalid ticket at index %s" % index)
        if ticket <= 0:
            raise HTTPException(400, "ticket must be positive")
        if ticket in seen:
            raise HTTPException(409, "duplicate ticket %s" % ticket)
        seen.add(ticket)

        symbol = item.get("symbol")
        symbol = str(symbol).strip() if symbol not in (None, "") else None
        side = item.get("side")
        side = str(side).strip().lower() if side not in (None, "") else None
        if side not in (None, "buy", "sell"):
            raise HTTPException(400, "invalid side for ticket %s" % ticket)
        volume = item.get("volume")
        if volume in (None, ""):
            volume = None
        else:
            try:
                volume = float(volume)
            except (TypeError, ValueError):
                raise HTTPException(400, "invalid volume for ticket %s" % ticket)
            if volume <= 0 or not math.isfinite(volume):
                raise HTTPException(400, "volume must be positive for ticket %s" % ticket)
        normalized.append({
            "ticket": ticket,
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "child_request_id": _close_batch_child_request_id(batch_id, ticket),
        })

    # Canonical order makes retries idempotent even if a client reorders its
    # selected slots.  The child id intentionally depends on ticket, not index.
    normalized.sort(key=lambda item: item["ticket"])
    payload["tickets"] = normalized
    # Canonicalize the compatibility alias before intent hashing.  A replay
    # using ``batch_id`` versus the legacy ``request_id`` must address the
    # same durable parent, rather than differing only by an omitted/None field.
    payload["batch_id"] = batch_id
    payload["batch_request_id"] = batch_id
    return payload


def _active_worker_generation():
    """Return the native-owner generation visible to this process.

    The HTTP parent reads the coordinator's current generation while the
    isolated child reads the value installed by ``runtime._isolated_worker``
    before importing this module.  Returning ``None`` deliberately disables
    admission hints when the owner is not ready yet.
    """
    if EXECUTION_PROCESS_ISOLATION:
        if _EXECUTION_CHILD:
            return EXECUTION_WORKER_GENERATION or None
        coordinator = globals().get("_EXECUTION")
        generation = getattr(coordinator, "_process_generation", None)
        return str(generation).strip() if generation else None
    # Non-isolated deployments have one Python/native owner.  The cache boot
    # is a process epoch and is enough to fence an in-process replay.
    cache = globals().get("_POSITION_CACHE")
    boot = getattr(cache, "boot", None)
    return ("local:%s" % int(boot)) if boot else None


def _snapshot_age_ms(snapshot):
    try:
        timestamp = int(snapshot.get("snapshot_ts_ms") or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    age = (time.time_ns() // 1_000_000) - timestamp
    # A clock jump into the future is not a reason to trust the row.  Allow a
    # small NTP skew, but reject a materially future timestamp as malformed.
    if age < -2000:
        return None
    return max(0, age)


def _snapshot_metadata_trusted(snapshot, *, require_generation=True):
    """Validate the durable context around an admission-time snapshot."""
    if not isinstance(snapshot, dict):
        return False
    # Admission envelopes are produced only from the broker-authoritative
    # cache.  An omitted/legacy source marker is indistinguishable from a
    # hand-built or partially decoded row, so fail closed and let the caller
    # perform an exact native lookup.
    if snapshot.get("snapshot_source") != "broker":
        return False
    if bool(snapshot.get("snapshot_stale")):
        return False
    try:
        if int(snapshot.get("snapshot_boot") or 0) <= 0:
            return False
        if int(snapshot.get("snapshot_seq") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    age_ms = _snapshot_age_ms(snapshot)
    if age_ms is None or CLOSE_SNAPSHOT_MAX_AGE_MS <= 0:
        return False
    if age_ms > CLOSE_SNAPSHOT_MAX_AGE_MS:
        return False

    # Legacy non-isolated test/development bridges did not persist context
    # fields.  Keep those deployments compatible, but require every field in
    # the production process-isolated path.
    if not EXECUTION_PROCESS_ISOLATION:
        return True
    try:
        login = int(snapshot.get("snapshot_login"))
    except (TypeError, ValueError):
        return False
    if login != MT5_LOGIN:
        return False
    if str(snapshot.get("snapshot_server") or "").strip().casefold() != str(
            MT5_SERVER or "").strip().casefold():
        return False
    if str(snapshot.get("snapshot_instance") or "").strip() != str(INSTANCE_NAME):
        return False
    if str(snapshot.get("snapshot_fence_key") or "") != str(EXECUTION_FENCE_KEY):
        return False
    expected_generation = _active_worker_generation()
    actual_generation = str(snapshot.get("snapshot_worker_generation") or "").strip()
    if require_generation and (not expected_generation or
                                actual_generation != expected_generation):
        return False
    return True


def _trusted_position_snapshot(snapshot, ticket=None):
    """Return a validated exact-ticket position hint, or ``None``."""
    if not _snapshot_metadata_trusted(snapshot):
        return None
    hinted = snapshot.get("position", snapshot)
    if not isinstance(hinted, dict):
        return None
    try:
        hinted_ticket = int(hinted.get("ticket"))
    except (TypeError, ValueError):
        return None
    if ticket is not None:
        try:
            if hinted_ticket != int(ticket):
                return None
        except (TypeError, ValueError):
            return None
    if (not hinted.get("symbol") or hinted.get("type") is None or
            hinted.get("volume") is None):
        return None
    try:
        volume = float(hinted.get("volume"))
        if volume <= 0 or not math.isfinite(volume):
            return None
    except (TypeError, ValueError):
        return None
    return dict(hinted)


def _trusted_positions_snapshot(snapshot, tickets):
    """Validate and select every exact ticket from an admission snapshot."""
    if not _snapshot_metadata_trusted(snapshot):
        return None
    rows = snapshot.get("positions")
    if not isinstance(rows, list):
        return None
    by_ticket = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            row_ticket = int(row.get("ticket"))
        except (TypeError, ValueError):
            continue
        # A duplicate ticket in a serialized snapshot is malformed.  Do not
        # let the last row silently win and change the side/volume used for a
        # close after the snapshot crossed a process boundary.
        if row_ticket in by_ticket:
            return None
        by_ticket[row_ticket] = dict(row)
    selected = []
    for raw_ticket in tickets or ():
        try:
            ticket = int(raw_ticket)
        except (TypeError, ValueError):
            return None
        row = by_ticket.get(ticket)
        if row is None:
            return None
        if (not row.get("symbol") or row.get("type") is None or
                row.get("volume") is None):
            return None
        try:
            volume = float(row.get("volume"))
            if volume <= 0 or not math.isfinite(volume):
                return None
        except (TypeError, ValueError):
            return None
        selected.append(SimpleNamespace(**row))
    return selected


def _fresh_admission_positions(tickets):
    """Return a versioned, broker-fresh cache subset without native I/O.

    The parent HTTP process owns the admission snapshot in isolated mode,
    while the child owns the terminal.  Passing this immutable subset through
    the durable payload removes a redundant ``positions_get`` immediately
    before a close.  Any stale, incomplete, or invalidated snapshot falls
    back to the child's authoritative lookup.
    """
    wanted = []
    seen = set()
    for raw in tickets or ():
        try:
            ticket = int(raw)
        except (TypeError, ValueError):
            return None
        if ticket <= 0 or ticket in seen:
            return None
        seen.add(ticket)
        wanted.append(ticket)
    if not wanted:
        return None
    try:
        snapshot = _POSITION_CACHE.get_cached()
    except Exception:
        return None
    if not isinstance(snapshot, dict):
        return None
    # Only a non-stale broker generation can supply the request-building
    # fields.  ``get_cached`` already enforces STALE_MAX and marks invalidated
    # generations as stale.
    if snapshot.get("snapshot_stale") or snapshot.get("snapshot_source") != "broker":
        return None
    worker_generation = _active_worker_generation()
    if EXECUTION_PROCESS_ISOLATION and not worker_generation:
        return None
    try:
        snapshot_ts_ms = int(snapshot.get("snapshot_ts_ms") or 0)
        snapshot_boot = int(snapshot.get("snapshot_boot") or 0)
        snapshot_seq = int(snapshot.get("snapshot_seq") or 0)
    except (TypeError, ValueError):
        # A corrupted in-memory projection must only disable the optimization
        # and force the child to perform its exact broker read.
        return None
    if not _snapshot_metadata_trusted(dict(snapshot, **{
            "snapshot_login": MT5_LOGIN,
            "snapshot_server": MT5_SERVER,
            "snapshot_instance": INSTANCE_NAME,
            "snapshot_fence_key": EXECUTION_FENCE_KEY,
            "snapshot_worker_generation": worker_generation,
        }), require_generation=False):
        return None
    positions = snapshot.get("positions")
    if not isinstance(positions, list):
        return None
    by_ticket = {}
    for position in positions:
        if not isinstance(position, dict):
            continue
        try:
            position_ticket = int(position.get("ticket"))
        except (TypeError, ValueError):
            continue
        if position_ticket in by_ticket:
            return None
        by_ticket[position_ticket] = dict(position)
    selected = []
    for ticket in wanted:
        item = by_ticket.get(ticket)
        if not item:
            return None
        # These fields are required to construct an exact close request.  A
        # partial cache row must never be mistaken for broker truth.
        if (not item.get("symbol") or item.get("type") is None
                or item.get("volume") is None):
            return None
        try:
            volume = float(item.get("volume"))
            if volume <= 0 or not math.isfinite(volume):
                return None
        except (TypeError, ValueError):
            return None
        selected.append(item)
    return {
        "positions": selected,
        "snapshot_boot": snapshot_boot,
        "snapshot_seq": snapshot_seq,
        "snapshot_ts_ms": snapshot_ts_ms,
        "snapshot_source": "broker",
        "snapshot_stale": False,
        "snapshot_login": MT5_LOGIN,
        "snapshot_server": MT5_SERVER,
        "snapshot_instance": INSTANCE_NAME,
        "snapshot_fence_key": EXECUTION_FENCE_KEY,
        "snapshot_worker_generation": worker_generation,
    }


def _attach_admission_position_snapshot(op, payload):
    """Attach only a fresh exact-ticket hint before durable admission."""
    if op == "close":
        ticket = payload.get("ticket")
        snapshot = _fresh_admission_positions([ticket]) if ticket is not None else None
        if snapshot:
            payload["_position_snapshot"] = {
                "position": snapshot["positions"][0],
                "snapshot_boot": snapshot["snapshot_boot"],
                "snapshot_seq": snapshot["snapshot_seq"],
                "snapshot_ts_ms": snapshot["snapshot_ts_ms"],
                "snapshot_source": snapshot.get("snapshot_source"),
                "snapshot_stale": snapshot.get("snapshot_stale", False),
                "snapshot_login": snapshot.get("snapshot_login"),
                "snapshot_server": snapshot.get("snapshot_server"),
                "snapshot_instance": snapshot.get("snapshot_instance"),
                "snapshot_fence_key": snapshot.get("snapshot_fence_key"),
                "snapshot_worker_generation": snapshot.get(
                    "snapshot_worker_generation"
                ),
            }
            payload["_position_snapshot_version"] = (
                snapshot["snapshot_boot"], snapshot["snapshot_seq"]
            )
    elif op in ("close_batch", "close_all"):
        raw_tickets = payload.get("tickets") or []
        # close-batch tickets may be objects; close-all tickets are integers.
        tickets = [
            item.get("ticket") if isinstance(item, dict) else item
            for item in raw_tickets
        ]
        snapshot = _fresh_admission_positions(tickets)
        if snapshot:
            payload["_positions_snapshot"] = snapshot
            payload["_position_snapshot_version"] = (
                snapshot["snapshot_boot"], snapshot["snapshot_seq"]
            )
    return payload


def _intent_hash(op, payload):
    stable = {
        key: value for key, value in payload.items()
        if key not in (
            "request_id", "ack_only", "_position_snapshot",
            "_positions_snapshot", "_position_snapshot_version",
        )
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
    """Refresh a market request while the native worker remains owned.

    This is deliberately the slow/authoritative path.  The normal market
    order path first uses a recent owner-local quote (when available), or
    lets MT5 resolve the current market price.  A native quote read happens
    only after a quote-related retcode, keeping the two calls contiguous in
    the same native worker task.
    """
    tick = mt5.symbol_info_tick(request["symbol"])
    if tick is None:
        return {"ok": False, "source": "native", "age_ms": None}
    cached = _store_native_tick_snapshot(request["symbol"], tick)
    price = _apply_native_tick_price(request, sym_info, cached)
    if price is None:
        return {"ok": False, "source": "native", "age_ms": None}
    return {"ok": True, "source": "native", "age_ms": 0.0}


def _send_with_requote(request, sym_info=None, on_dispatch=None):
    is_deal = request.get("action") == getattr(mt5, "TRADE_ACTION_DEAL", 1)
    # Keep quote refresh, bounded requote retry and order_send in one native
    # worker task. A burst cannot interleave another account read between
    # quote refresh and the broker command.
    def _native_send():
        retries = 0
        quote_refresh_ns = 0
        broker_send_ns = 0
        attempts = 0
        quote_source = "request" if "price" in request else "omitted"
        quote_age_ms = None

        def _timed_quote_refresh():
            nonlocal quote_refresh_ns, quote_source, quote_age_ms
            started_ns = time.perf_counter_ns()
            try:
                details = _refresh_deal_price_native(request, sym_info)
                if details.get("ok"):
                    quote_source = details.get("source", "native")
                    quote_age_ms = details.get("age_ms")
                return details
            finally:
                quote_refresh_ns += time.perf_counter_ns() - started_ns

        def _use_cached_quote():
            nonlocal quote_source, quote_age_ms
            cached = _native_tick_snapshot_view(request.get("symbol"))
            if not cached:
                return False
            if _apply_native_tick_price(request, sym_info, cached) is None:
                return False
            quote_source = "cache"
            quote_age_ms = cached.get("age_ms")
            return True

        def _result(value):
            return value, retries, {
                "quote_refresh_ms": round(quote_refresh_ns / 1_000_000, 3),
                "broker_order_send_ms": round(broker_send_ns / 1_000_000, 3),
                "order_attempts": attempts,
                "quote_source": quote_source,
                "quote_age_ms": quote_age_ms,
            }

        while True:
            if is_deal and attempts == 0:
                if TRADE_QUOTE_MODE == "always":
                    # Compatibility mode for a broker that rejects market
                    # requests without a client-side price.
                    _timed_quote_refresh()
                elif "price" not in request:
                    # A recent tick is free; an old/missing tick must not
                    # become a hidden one-second read before order_send.
                    _use_cached_quote()
            # MetaTrader5's C extension accepts the trade request as its
            # positional argument.  Passing ``request=...`` looks equivalent
            # in Python, but the extension silently builds an empty native
            # request and returns retcode=10013 (INVALID_REQUEST).
            sent_without_price = bool(is_deal and "price" not in request)
            send_started_ns = time.perf_counter_ns()
            try:
                # Persist the point of no return before entering the native
                # extension. A crash in symbol/tick preflight remains safely
                # replayable as CLAIMED; only this boundary becomes SENDING.
                if callable(on_dispatch):
                    try:
                        on_dispatch(attempts + 1)
                    except Exception:
                        logger.exception("close-batch progress checkpoint failed")
                mark_execution_dispatching()
                result = mt5.order_send(dict(request))
            finally:
                broker_send_ns += time.perf_counter_ns() - send_started_ns
                attempts += 1
            if result is None:
                return _result(None)
            retcode = int(getattr(result, "retcode", 0) or 0)
            requote = retcode in _requote_codes()
            invalid_price = retcode in {
                getattr(mt5, "TRADE_RETCODE_INVALID_PRICE", 10015),
                getattr(mt5, "TRADE_RETCODE_INVALID_REQUEST", 10013),
            }
            # INVALID_REQUEST/INVALID_PRICE is eligible for one quote retry
            # only when the initial market request omitted price.  An
            # explicitly supplied price is caller intent and must not be
            # silently overwritten. Requote/price-off remains retryable for
            # either form because MT5 explicitly says the quote moved.
            # Only an INVALID_REQUEST/INVALID_PRICE from a request that was
            # actually sent without a price is eligible for the lazy quote
            # recovery.  A cache hit or ``always`` preflight adds a price
            # before dispatch; an unrelated 10013/10015 must remain terminal
            # instead of causing an extra broker round trip.
            quote_retry = requote or (sent_without_price and invalid_price)
            if (not quote_retry or retries >= REQUOTE_RETRIES or not is_deal):
                return _result(result)
            refreshed = _timed_quote_refresh()
            if not refreshed.get("ok"):
                return _result(result)
            retries += 1
            logger.warning(
                "Refreshing quote and retrying once | instance=%s symbol=%s retcode=%s retry=%s",
                INSTANCE_NAME, request.get("symbol"), retcode, retries,
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
    response.update(_mark_trade_snapshot_pending())
    mgr.ping()
    return ExecutionOutcome("DONE", response)


def _select_close_position(payload):
    ticket = payload.get("ticket")
    if ticket is not None:
        # The admission layer may have attached a broker-fresh serialized
        # position. In process isolation this avoids a parent-to-child native
        # positions_get(ticket=...) round trip. The exact ticket remains
        # in the eventual MT5 request, so a changed/closed position fails
        # safely at the broker rather than closing a different ticket.
        snapshot = payload.get("_position_snapshot")
        if isinstance(snapshot, dict):
            hinted = _trusted_position_snapshot(snapshot, ticket)
            if hinted is not None:
                return SimpleNamespace(**hinted)
        # QH closes exact tickets and normally has just published the same
        # snapshot used to render the slot. Reuse that bounded snapshot so a
        # multi-slot close burst does not pay one native positions_get call
        # before every order_send. The ticket remains in the MT5 request, and
        # a missing/expired snapshot falls back to an authoritative lookup.
        # Never fall back to the legacy ``peek_ticket`` API.  It predates
        # invalidation/generation fencing and can return a stale-max row from
        # a previous broker generation.  The current runtime always exposes
        # ``peek_fresh_ticket``; an older runtime must pay the authoritative
        # exact-ticket read instead.
        fresh_peek = getattr(_POSITION_CACHE, "peek_fresh_ticket", None)
        cached = fresh_peek(ticket) if callable(fresh_peek) else None
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


def _close_one(position, requested_volume=None, sym_info=None,
               on_dispatch=None):
    # Batch closes resolve symbol metadata once per symbol and pass it down;
    # the legacy single-ticket path keeps its existing lookup behavior.
    info = sym_info or _symbol_info(position.symbol)
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
    result, retries = _send_with_requote(
        request, sym_info=info, on_dispatch=on_dispatch,
    )
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
    snapshot_metadata = _mark_trade_snapshot_pending()
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


def _execute_close_batch(payload):
    """Close an immutable ticket manifest with one broker position snapshot.

    This function runs inside the existing process-isolated execution worker.
    It deliberately keeps the loop synchronous: MetaTrader5 has one native
    owner per terminal, so parallel Python calls would only add ambiguity.
    """
    request_id = str(payload["request_id"])
    positions_override = payload.get("_positions_snapshot", _SNAPSHOT_UNSET)
    payload = _normalize_close_batch_payload(
        payload, batch_request_id=str(
            payload.get("batch_request_id") or payload.get("batch_id") or request_id
        ),
    )
    tickets = payload["tickets"]
    batch_id = str(payload.get("batch_request_id") or request_id)
    if positions_override is _SNAPSHOT_UNSET:
        positions = _mt5_call(
            mt5.positions_get,
            _priority=MT5_API_PRIORITY_TRADE,
            _metric_name="close_batch_positions_get",
        )
    elif isinstance(positions_override, dict):
        # A dictionary is an admission-time snapshot carried through the WAL.
        # It is trusted only while its account/worker generation and age still
        # match this native owner.  Invalid hints deliberately pay one
        # authoritative positions read; they must never silently become a
        # stale volume/side input.
        positions = _trusted_positions_snapshot(
            positions_override, [item["ticket"] for item in tickets]
        )
        if positions is None:
            positions = _mt5_call(
                mt5.positions_get,
                _priority=MT5_API_PRIORITY_TRADE,
                _metric_name="close_batch_positions_get_fallback",
            )
    else:
        # close-all supplies the list it just obtained inside this same native
        # worker.  It is authoritative local state, not a durable admission
        # hint, so no cross-process metadata validation is needed.
        positions = positions_override

    progress = {
        "schema_version": 2,
        "batch_id": batch_id,
        "request_id": request_id,
        "tickets": {
            str(item["ticket"]): {
                "ticket": item["ticket"],
                "child_request_id": item["child_request_id"],
                "state": "PENDING",
            }
            for item in tickets
        },
    }

    _last_checkpoint_ns = [0]
    _checkpoint_count = [0]
    _dispatch_checkpoint_seen = [False]

    def checkpoint(force=False):
        # The outer WAL is the idempotency boundary.  Keep the initial,
        # broker-dispatch, and terminal snapshots durable, while coalescing
        # intermediate per-ticket progress so a 20-ticket close does not turn
        # SQLite FULL commits into another serial execution queue.
        now_ns = time.time_ns()
        _checkpoint_count[0] += 1
        if (not force and _last_checkpoint_ns[0] and
                now_ns - _last_checkpoint_ns[0] < 25_000_000 and
                _checkpoint_count[0] % 4):
            return
        record_execution_progress(progress)
        _last_checkpoint_ns[0] = now_ns

    checkpoint(force=True)

    def base_result(item):
        return {
            "ticket": item["ticket"],
            "request_id": item["child_request_id"],
            "child_request_id": item["child_request_id"],
            "batch_request_id": batch_id,
            "op": "close",
        }

    def unknown_result(item, error, **extra):
        result = base_result(item)
        result.update({
            "success": False,
            "unknown": True,
            "state": "UNKNOWN",
            "certainty": "UNKNOWN",
            "retry_prohibited": True,
            "error": str(error),
        })
        result.update(extra)
        return result

    def failed_result(item, error, **extra):
        result = base_result(item)
        result.update({
            "success": False,
            "failed": True,
            "state": "FAILED",
            "error": str(error),
        })
        result.update(extra)
        return result

    if positions is None:
        results = []
        for item in tickets:
            progress["tickets"][str(item["ticket"])].update({
                "state": "UNKNOWN", "unknown": True,
                "retry_prohibited": True,
                "error": "positions_get returned None before exact-ticket batch",
            })
            results.append(unknown_result(
                item,
                "positions_get returned None before exact-ticket batch",
                dispatch_started=False,
            ))
        checkpoint(force=True)
        return ExecutionOutcome("UNKNOWN", {
            "success": False,
            "unknown": True,
            "state": "UNKNOWN",
            "closed": 0,
            "failed": 0,
            "unknown_count": len(results),
            "attempted": 0,
            "total": len(results),
            "results": results,
            "request_id": request_id,
            "batch_request_id": batch_id,
            "batch_progress": progress,
        })

    positions_by_ticket = {}
    for position in positions:
        try:
            ticket = int(position.ticket)
        except (AttributeError, TypeError, ValueError):
            continue
        positions_by_ticket.setdefault(ticket, []).append(position)

    results = []
    symbol_info_by_symbol = {}
    closed = failed = unknown_count = attempted = retries_total = 0
    for item in tickets:
        ticket = item["ticket"]
        matches = positions_by_ticket.get(ticket) or []
        if len(matches) != 1:
            unknown_count += 1
            reason = (
                "exact ticket is absent from the single broker snapshot"
                if not matches
                else "broker snapshot contains duplicate ticket identity"
            )
            progress["tickets"][str(ticket)].update({
                "state": "UNKNOWN", "unknown": True,
                "retry_prohibited": True,
                "snapshot_matches": len(matches), "error": reason,
            })
            results.append(unknown_result(
                item, reason, dispatch_started=False,
                snapshot_matches=len(matches),
            ))
            checkpoint()
            continue
        position = matches[0]
        actual_symbol = str(getattr(position, "symbol", "") or "")
        if not actual_symbol:
            failed += 1
            progress["tickets"][str(ticket)].update({
                "state": "FAILED", "error": "position symbol is missing",
                "not_sent": True, "not_filled": True,
            })
            results.append(failed_result(
                item, "position symbol is missing", not_sent=True,
                not_filled=True, dispatch_durable=False,
            ))
            checkpoint()
            continue
        if item.get("symbol") and item["symbol"] != actual_symbol:
            failed += 1
            progress["tickets"][str(ticket)].update({
                "state": "FAILED", "symbol": actual_symbol,
                "error": "position symbol does not match exact-ticket intent",
                "not_sent": True, "not_filled": True,
            })
            results.append(failed_result(
                item, "position symbol does not match exact-ticket intent",
                symbol=actual_symbol, expected_symbol=item["symbol"],
                not_sent=True, not_filled=True, dispatch_durable=False,
            ))
            checkpoint()
            continue
        try:
            position_type = int(position.type)
        except (AttributeError, TypeError, ValueError):
            position_type = -1
        actual_side = "buy" if position_type == 0 else "sell" if position_type == 1 else None
        if actual_side is None:
            failed += 1
            progress["tickets"][str(ticket)].update({
                "state": "FAILED", "symbol": actual_symbol,
                "error": "unsupported position type",
                "not_sent": True, "not_filled": True,
            })
            results.append(failed_result(
                item, "unsupported position type", symbol=actual_symbol,
                not_sent=True, not_filled=True, dispatch_durable=False,
            ))
            checkpoint()
            continue
        if item.get("side") and item["side"] != actual_side:
            failed += 1
            progress["tickets"][str(ticket)].update({
                "state": "FAILED", "symbol": actual_symbol,
                "side": actual_side,
                "error": "position side does not match exact-ticket intent",
                "not_sent": True, "not_filled": True,
            })
            results.append(failed_result(
                item, "position side does not match exact-ticket intent",
                symbol=actual_symbol, side=actual_side,
                expected_side=item["side"], not_sent=True,
                not_filled=True, dispatch_durable=False,
            ))
            checkpoint()
            continue

        entry = progress["tickets"][str(ticket)]
        entry.update({
            "symbol": actual_symbol,
            "side": actual_side,
            "volume": float(getattr(position, "volume", 0.0) or 0.0),
            "state": "PENDING",
        })
        checkpoint()

        if actual_symbol not in symbol_info_by_symbol:
            try:
                symbol_info_by_symbol[actual_symbol] = _symbol_info(actual_symbol)
            except Exception:
                symbol_info_by_symbol[actual_symbol] = None
        info = symbol_info_by_symbol[actual_symbol]
        if info is None:
            failed += 1
            entry.update({
                "state": "FAILED", "error": "symbol info is unavailable",
                "not_sent": True, "not_filled": True,
            })
            results.append(failed_result(
                item, "symbol info is unavailable", symbol=actual_symbol,
                side=actual_side, not_sent=True, not_filled=True,
                dispatch_durable=False,
            ))
            checkpoint()
            continue

        attempted += 1
        def on_dispatch(attempt, _entry=entry):
            _entry.update({"state": "SENDING", "attempt": int(attempt)})
            # The outer WAL is already fenced before the first broker write;
            # make that first per-ticket progress durable, then let later
            # tickets share the bounded checkpoint cadence.
            checkpoint(force=not _dispatch_checkpoint_seen[0])
            _dispatch_checkpoint_seen[0] = True
        try:
            result, retries, error, requested = _close_one(
                position, item.get("volume"), sym_info=info,
                on_dispatch=on_dispatch,
            )
        except Exception as exc:
            unknown_count += 1
            entry.update({
                "state": "UNKNOWN", "unknown": True,
                "retry_prohibited": True,
                "error": "close dispatch raised %s" % exc.__class__.__name__,
            })
            results.append(unknown_result(
                item,
                "close dispatch raised %s" % exc.__class__.__name__,
                symbol=actual_symbol,
                side=actual_side,
                dispatch_started=True,
            ))
            checkpoint()
            continue
        retries_total += retries
        if error:
            failed += 1
            entry.update({"state": "FAILED", "error": error,
                          "not_sent": True, "not_filled": True})
            results.append(failed_result(
                item, error, symbol=actual_symbol, side=actual_side,
                not_sent=True, not_filled=True, dispatch_durable=False,
            ))
            checkpoint()
            continue
        if result is None:
            unknown_count += 1
            entry.update({"state": "UNKNOWN", "unknown": True,
                          "retry_prohibited": True,
                          "error": "close order_send returned None",
                          "requote_retries": retries})
            results.append(unknown_result(
                item, "close order_send returned None",
                symbol=actual_symbol, side=actual_side,
                dispatch_started=True, requote_retries=retries,
            ))
            checkpoint()
            continue

        retcode = int(getattr(result, "retcode", 0) or 0)
        filled = float(getattr(result, "volume", 0.0) or 0.0)
        partial = retcode == getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
        if partial or (
            retcode == getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            and filled + 1e-9 < requested
        ):
            unknown_count += 1
            entry.update({
                "state": "UNKNOWN", "unknown": True,
                "retry_prohibited": True, "retcode": retcode,
                "partial": True, "filled_volume": filled,
                "remaining_volume": max(0.0, round(requested - filled, 8)),
                "requote_retries": retries,
            })
            results.append(unknown_result(
                item,
                "close partially filled; reconcile exact ticket before retrying",
                symbol=actual_symbol,
                side=actual_side,
                dispatch_started=True,
                retcode=retcode,
                partial=True,
                filled_volume=filled,
                remaining_volume=max(0.0, round(requested - filled, 8)),
                requote_retries=retries,
            ))
            checkpoint()
            continue
        if retcode != getattr(mt5, "TRADE_RETCODE_DONE", 10009):
            failed += 1
            entry.update({"state": "FAILED", "retcode": retcode,
                          "comment": getattr(result, "comment", ""),
                          "requote_retries": retries})
            results.append(failed_result(
                item,
                "Close failed retcode=%s comment=%s" % (
                    retcode, getattr(result, "comment", ""),
                ),
                symbol=actual_symbol,
                side=actual_side,
                retcode=retcode,
                requote_retries=retries,
            ))
            checkpoint()
            continue

        closed += 1
        entry.update({
            "state": "DONE", "success": True,
            "retcode": retcode,
            "order": getattr(result, "order", None),
            "deal": getattr(result, "deal", None),
            "filled_volume": filled,
            "price": getattr(result, "price", None),
            "comment": getattr(result, "comment", ""),
            "partial": False,
            "requote_retries": retries,
        })
        child = base_result(item)
        child.update({
            "success": True,
            "state": "DONE",
            "symbol": actual_symbol,
            "side": actual_side,
            "retcode": retcode,
            "order": getattr(result, "order", None),
            "deal": getattr(result, "deal", None),
            "volume": filled,
            "price": getattr(result, "price", None),
            "comment": getattr(result, "comment", ""),
            "partial": False,
            "requote_retries": retries,
        })
        results.append(child)
        checkpoint(force=True)

    # Persist the final per-ticket map even when the last item failed or was
    # UNKNOWN; this is the restart/reconciliation checkpoint for the batch.
    checkpoint(force=True)
    if attempted:
        snapshot_metadata = _mark_trade_snapshot_pending()
    else:
        snapshot_metadata = _trade_snapshot_metadata()
    mgr.ping()
    response = {
        "success": closed == len(tickets),
        "closed": closed,
        "failed": failed,
        "unknown_count": unknown_count,
        "attempted": attempted,
        "total": len(tickets),
        "results": results,
        "requote_retries": retries_total,
        "request_id": request_id,
        "batch_request_id": batch_id,
        "batch_progress": progress,
    }
    response.update(snapshot_metadata)
    if unknown_count:
        response.update({"unknown": True, "state": "UNKNOWN"})
        return ExecutionOutcome("UNKNOWN", response)
    response["state"] = "DONE"
    return ExecutionOutcome("DONE", response)


def _close_batch_child_id(batch_id, ticket):
    """Compatibility alias: all close endpoints share one child ID scheme."""
    return _close_batch_child_request_id(batch_id, ticket)


def _execute_close_all(payload):
    """Adapt close-all to the canonical exact-ticket batch executor.

    Discovery is performed once here, then passed into ``_execute_close_batch``
    so close-all and explicit close-batch cannot drift in queue or retry
    semantics.  The native owner still sends one order at a time.
    """
    request_id = str(payload["request_id"])
    batch_id = str(payload.get("batch_id") or request_id)
    symbol = payload.get("symbol")
    requested_tickets = []
    for raw in (payload.get("tickets") or []):
        try:
            ticket = int(raw)
        except (TypeError, ValueError):
            continue
        if ticket > 0 and ticket not in requested_tickets:
            requested_tickets.append(ticket)
    positions_override = payload.get("_positions_snapshot", _SNAPSHOT_UNSET)
    snapshot_override = None
    if positions_override is _SNAPSHOT_UNSET:
        positions = _mt5_call(
            mt5.positions_get,
            **({"symbol": symbol} if symbol else {}),
            _priority=MT5_API_PRIORITY_TRADE,
            _metric_name="close_all_positions_get",
        )
    else:
        # Keep an admission snapshot as a dictionary until the canonical
        # batch executor validates its account/worker generation and age.  A
        # previous implementation converted it to a list here, bypassing the
        # validator and allowing an old worker snapshot to drive close-all.
        snapshot_override = positions_override if isinstance(
            positions_override, dict
        ) else None
        if snapshot_override is not None:
            if not _snapshot_metadata_trusted(snapshot_override):
                positions = _mt5_call(
                    mt5.positions_get,
                    **({"symbol": symbol} if symbol else {}),
                    _priority=MT5_API_PRIORITY_TRADE,
                    _metric_name="close_all_positions_get_fallback",
                )
                # The fallback is now an authoritative local list.  Do not
                # hand the rejected envelope to _execute_close_batch or it
                # would perform the same positions_get a second time.
                snapshot_override = None
            else:
                raw_positions = snapshot_override.get("positions")
                positions = [
                    SimpleNamespace(**item) if isinstance(item, dict) else item
                    for item in (raw_positions or [])
                ] if isinstance(raw_positions, list) else None
                if positions is not None and symbol:
                    positions = [
                        position for position in positions
                        if str(getattr(position, "symbol", "") or "") == str(symbol)
                    ]
        else:
            # A list produced by this same native worker is authoritative
            # local state (used by the non-admission close-all path).
            positions = positions_override
    if positions is not None and not positions and not requested_tickets:
        return ExecutionOutcome("DONE", {
            "success": True, "state": "DONE", "batch_id": batch_id,
            "closed": 0, "failed": 0, "unknown": 0, "partial": 0,
            "tickets": [], "results": [], "results_by_ticket": {},
            "request_id": request_id,
        })
    if positions is None and not requested_tickets:
        return ExecutionOutcome("UNKNOWN", {
            "success": False, "unknown": True, "state": "UNKNOWN",
            "batch_id": batch_id, "closed": 0, "failed": 0,
            "unknown": 0, "partial": 0, "tickets": [], "results": [],
            "results_by_ticket": {}, "request_id": request_id,
            "error": "positions_get returned None before close-all",
        })
    fixed_tickets = list(requested_tickets)
    if not fixed_tickets:
        seen = set()
        for position in positions or ():
            try:
                ticket = int(position.ticket)
            except (TypeError, ValueError, AttributeError):
                continue
            if ticket > 0 and ticket not in seen:
                seen.add(ticket)
                fixed_tickets.append(ticket)
    if not fixed_tickets:
        return ExecutionOutcome("DONE", {
            "success": True, "state": "DONE", "batch_id": batch_id,
            "closed": 0, "failed": 0, "unknown": 0, "partial": 0,
            "tickets": [], "results": [], "results_by_ticket": {},
            "request_id": request_id,
        })
    if len(fixed_tickets) > CLOSE_BATCH_MAX_TICKETS:
        return _failure(
            request_id,
            "too many close-all tickets (max %s)" % CLOSE_BATCH_MAX_TICKETS,
            batch_id=batch_id,
        )
    manifest = [
        {"ticket": ticket, **({"symbol": symbol} if symbol else {})}
        for ticket in fixed_tickets
    ]
    outcome = _execute_close_batch({
        "request_id": request_id,
        "batch_request_id": batch_id,
        "tickets": manifest,
        # Preserve the metadata envelope when it came from admission.  The
        # batch executor will validate it again in the child immediately
        # before constructing any order request.  Local native lists remain
        # authoritative and avoid a redundant positions_get call.
        "_positions_snapshot": (
            snapshot_override if snapshot_override is not None else positions
        ),
    })
    response = dict(outcome.result or {})
    response.update({
        "batch_id": batch_id,
        "tickets": fixed_tickets,
        "results_by_ticket": {
            str(item.get("ticket")): item
            for item in response.get("results") or ()
            if isinstance(item, dict) and item.get("ticket") is not None
        },
    })
    if "unknown_count" in response:
        response["unknown"] = int(response.get("unknown_count") or 0)
    return ExecutionOutcome(outcome.state, response)


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
            effective_op = (
                "close_batch"
                if op == "close" and payload.get("_close_batch") is True
                else op
            )
            handlers = {
                "order": _execute_order,
                "close": _execute_close,
                "close_batch": _execute_close_batch,
                "close_all": _execute_close_all,
                "cancel_all": _execute_cancel_all,
            }
            outcome = handlers[effective_op](payload)
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
                "broker_order_send_ms", "order_attempts", "quote_source",
                "quote_age_ms",
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
    if not (EXECUTION_PROCESS_ISOLATION and _EXECUTION_CHILD):
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
    # A close-batch has two identities in the public schema: ``batch_id`` is
    # the caller's cohort identity and ``request_id`` is the backwards
    # compatible field used by older clients.  Once a batch id is supplied it
    # must be the durable parent and the root for every deterministic child
    # ticket id.  Choosing a random/request id first would make the response,
    # WAL row, and child ids refer to three different batches.
    if op == "close_batch":
        request_id = (
            str(payload.get("batch_id") or "").strip()
            or str(payload.get("request_id") or "").strip()
            or uuid.uuid4().hex
        )
    else:
        request_id = payload.get("request_id") or uuid.uuid4().hex
    payload["request_id"] = request_id
    if op == "close_batch":
        # Canonicalize before hashing/admission so the durable row contains
        # the exact ticket manifest and deterministic child identities.
        payload = _normalize_close_batch_payload(
            payload, batch_request_id=request_id,
        )
        payload["_close_batch"] = True
    payload = _attach_admission_position_snapshot(op, payload)
    intent_hash = _intent_hash(op, payload)
    # runtime.execution_priority intentionally knows only the stable public
    # close operation.  Keep batch work in that urgent lane without changing
    # the shared runtime contract; the payload marker selects the batch
    # handler inside this module.
    execution_op = "close" if op == "close_batch" else op
    try:
        submission = _EXECUTION.submit(request_id, execution_op, intent_hash, payload)
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


@app.post("/mt5/position/close-batch", dependencies=[Depends(verify_api_key)])
async def close_batch_positions_v3(req: CloseBatchRequest):
    return await _submit_v3("close_batch", req)


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
