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
import uuid
from datetime import datetime, timedelta
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
    PrioritizedSingleThreadExecutor,
    PositionSnapshotCache,
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
POSITIONS_CACHE_TTL_MS = max(0, int(os.getenv("POSITIONS_CACHE_TTL_MS", "150")))
POSITIONS_STALE_MAX_MS = max(POSITIONS_CACHE_TTL_MS, int(os.getenv("POSITIONS_STALE_MAX_MS", "2000")))
EXEC_SYNC_WAIT_SEC = max(0.05, float(os.getenv("EXEC_SYNC_WAIT_SEC", "0.85")))
REQUOTE_RETRIES = min(2, max(0, int(os.getenv("MT5_REQUOTE_RETRIES", "1"))))
IDEMPOTENCY_DB = os.getenv("IDEMPOTENCY_DB", os.path.join(os.getcwd(), "idempotency.db"))

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
_MT5_API_EXECUTOR = PrioritizedSingleThreadExecutor(thread_name_prefix="mt5-api")


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


def _mt5_call(func, *args, _priority=None, **kwargs):
    # A v3 execution already represents a broker command.  Its symbol/tick/
    # position discovery calls inherit the urgent lane so a positions poll
    # cannot delay the command between preflight and order_send.
    priority = _priority
    if priority is None:
        priority = _MT5_CALL_PRIORITY.get()
    if priority is None:
        priority = _default_mt5_priority(func)
    if _is_native_trade_callable(func) and not args and set(kwargs) == {"request"}:
        request = kwargs["request"]
        return _MT5_API_EXECUTOR.submit(
            lambda: func(request), priority=priority,
        ).result()
    return _MT5_API_EXECUTOR.submit(
        func, *args, priority=priority, **kwargs,
    ).result()

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
        try:
            _mt5_call(mt5.shutdown)
        except Exception:
            pass
        self.connected = False

    def reconnect(self) -> bool:
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

# ─── 生命周期 ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    logger.info(f"Starting MT5 Bridge [{INSTANCE_NAME}] port={SERVICE_PORT}")
    mgr.ensure()

@app.on_event("shutdown")
async def on_shutdown():
    execution = globals().get("_EXECUTION")
    if execution is not None:
        await asyncio.to_thread(execution.shutdown)
    mgr.disconnect()
    _MT5_API_EXECUTOR.shutdown(wait=True, cancel_futures=False)

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

# ────────────────────────────────────────────────────────────────────────────
# 端点实现
# ────────────────────────────────────────────────────────────────────────────

# ── 1. Health ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    ta = None
    try:
        _ti = _mt5_call(mt5.terminal_info)
        ta = bool(_ti.trade_allowed) if _ti else None
    except Exception:
        ta = None
    queue_metrics = _EXECUTION.metrics() if "_EXECUTION" in globals() else {}
    return {
        "status":   "ok",
        "service":  "mt5-bridge",
        "instance": INSTANCE_NAME,
        "mt5":      mgr.connected,
        "trade_allowed": ta,
        "execution_queue": queue_metrics,
        "mt5_api_queue": _MT5_API_EXECUTOR.metrics(),
    }

# ── 2. Connection Status ──────────────────────────────────────────────────
@app.get("/mt5/connection/status", dependencies=[Depends(verify_api_key)])
async def connection_status():
    status = mgr.get_status()
    if mgr.connected:
        info = _mt5_call(mt5.account_info)
        if info:
            mgr.ping()
            status.update({
                "balance": info.balance,
                "equity":  info.equity,
            })
    return status

# ── 3. Reconnect ──────────────────────────────────────────────────────────
@app.post("/mt5/connection/reconnect", dependencies=[Depends(verify_api_key)])
async def reconnect():
    ok = mgr.reconnect()
    _POSITION_CACHE.invalidate()
    return {"success": ok, "instance": INSTANCE_NAME}

# ── 4. Positions ──────────────────────────────────────────────────────────
@app.get("/mt5/positions", dependencies=[Depends(verify_api_key)])
async def get_positions(symbol: Optional[str] = Query(None)):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    try:
        snapshot = _POSITION_CACHE.get()
    except Exception as exc:
        raise HTTPException(503, "MT5 positions snapshot unavailable: %s" % exc)
    mgr.ping()
    if symbol:
        snapshot = dict(snapshot)
        snapshot["positions"] = [
            position for position in snapshot["positions"]
            if position.get("symbol") == symbol
        ]
    return snapshot

# ── 5. Account Balance ────────────────────────────────────────────────────
@app.get("/mt5/account/balance", dependencies=[Depends(verify_api_key)])
async def account_balance():
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    info = _mt5_call(mt5.account_info)
    if info is None:
        raise HTTPException(500, f"mt5.account_info() failed: {_mt5_call(mt5.last_error)}")
    mgr.ping()
    return {
        "balance":       info.balance,
        "equity":        info.equity,
        "margin":        info.margin,
        "margin_free":   info.margin_free,
        "margin_level":  info.margin_level,
        "profit":        info.profit,
    }

# ── 6. Account Info（含历史换算 Swap）────────────────────────────────────
@app.get("/mt5/account/info", dependencies=[Depends(verify_api_key)])
async def account_info():
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    info = _mt5_call(mt5.account_info)
    if info is None:
        raise HTTPException(500, f"mt5.account_info() failed: {_mt5_call(mt5.last_error)}")
    mgr.ping()

    # 累计 swap = 持仓swap + 近30日历史deal swap
    total_swap = 0.0
    positions = _mt5_call(mt5.positions_get) or []
    for p in positions:
        total_swap += p.swap

    from_date = datetime.utcnow() - timedelta(days=30)
    deals = _mt5_call(mt5.history_deals_get, from_date, datetime.utcnow() + timedelta(hours=6)) or []
    for d in deals:
        if hasattr(d, "swap") and d.swap != 0:
            total_swap += d.swap

    return {
        "login":         info.login,
        "balance":       info.balance,
        "equity":        info.equity,
        "margin":        info.margin,
        "margin_free":   info.margin_free,
        "margin_level":  info.margin_level,
        "margin_so_call": getattr(info, "margin_so_call", None),  # 保证金不足预警线(%)
        "margin_so_so":   getattr(info, "margin_so_so", None),    # 止损平仓线(stop-out %)
        "margin_so_mode": getattr(info, "margin_so_mode", None),  # 0=百分比 1=货币
        "profit":        info.profit,
        "swap":          round(total_swap, 2),
        "currency":      info.currency,
        "leverage":      info.leverage,
        "server":        info.server,
        "name":          info.name,
        "company":       info.company,
    }

# ── 7. Symbols ────────────────────────────────────────────────────────────
@app.get("/mt5/symbols", dependencies=[Depends(verify_api_key)])
async def get_symbols():
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    syms = _mt5_call(mt5.symbols_get) or []
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
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    info = _mt5_call(mt5.symbol_info, symbol)
    if info is None:
        raise HTTPException(404, f"Symbol {symbol} not found: {_mt5_call(mt5.last_error)}")
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
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    tick = _mt5_call(mt5.symbol_info_tick, symbol)
    if tick is None:
        raise HTTPException(404, f"No tick for symbol {symbol}: {_mt5_call(mt5.last_error)}")
    mgr.ping()
    return {
        "symbol": symbol,
        "bid":    tick.bid,
        "ask":    tick.ask,
        "last":   tick.last,
        "volume": tick.volume,
        "time":   tick.time,
        "time_msc": tick.time_msc,
    }

# ── 9. History Deals ──────────────────────────────────────────────────────
@app.get("/mt5/history/deals", dependencies=[Depends(verify_api_key)])
async def history_deals(
    days:   int           = Query(7),
    symbol: Optional[str] = Query(None),
):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    from_date = datetime.utcnow() - timedelta(days=days)
    deals = _mt5_call(mt5.history_deals_get, from_date, datetime.utcnow() + timedelta(hours=6)) or []
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
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    from_date = datetime.utcnow() - timedelta(days=days)
    orders = _mt5_call(mt5.history_orders_get, from_date, datetime.utcnow()) or []
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
    row = _idem_get(request_id)
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


def _send_with_requote(request, sym_info=None):
    retries = 0
    is_deal = request.get("action") == getattr(mt5, "TRADE_ACTION_DEAL", 1)
    if is_deal:
        _refresh_deal_price(request, sym_info=sym_info)
    while True:
        # MetaTrader5's C extension rejects a positional request when invoked
        # through the long-lived executor thread (error -2).  Keep the request
        # named so open and close use the same reliable call path.
        result = _mt5_call(mt5.order_send, request=dict(request))
        if result is None:
            return None, retries
        if result.retcode not in _requote_codes() or retries >= REQUOTE_RETRIES or not is_deal:
            return result, retries
        if not _refresh_deal_price(request, sym_info=sym_info):
            return result, retries
        retries += 1
        logger.warning(
            "Refreshing quote and retrying once | instance=%s symbol=%s retcode=%s retry=%s",
            INSTANCE_NAME, request.get("symbol"), result.retcode, retries,
        )


def _symbol_info(symbol):
    info = _mt5_call(mt5.symbol_info, symbol)
    if info is not None and not info.visible:
        _mt5_call(mt5.symbol_select, symbol, True)
        info = _mt5_call(mt5.symbol_info, symbol)
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
    mgr.ping()
    return ExecutionOutcome("DONE", response)


def _select_close_position(payload):
    ticket = payload.get("ticket")
    if ticket is not None:
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
    return ExecutionOutcome("DONE", {
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
    })


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
    token = _MT5_CALL_PRIORITY.set(MT5_API_PRIORITY_TRADE)
    try:
        if not mgr.ensure():
            return _failure(payload["request_id"], "MT5 not connected")
        handlers = {
            "order": _execute_order,
            "close": _execute_close,
            "close_all": _execute_close_all,
            "cancel_all": _execute_cancel_all,
        }
        return handlers[op](payload)
    finally:
        _MT5_CALL_PRIORITY.reset(token)


_EXECUTION = DurableExecutionCoordinator(IDEMPOTENCY_DB, _execute_v3)


def _pending_response_v3(request_id, state="PENDING"):
    return JSONResponse(status_code=202, content={
        "success": False,
        "accepted": True,
        "pending": True,
        "unknown": False,
        "state": state,
        "request_id": request_id,
        "status_url": "/mt5/order-status/%s" % request_id,
    })


def _render_record(record, replay=False):
    state = record["state"]
    result = dict(record.get("result") or {})
    request_id = record["request_id"]
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
    return _pending_response_v3(request_id, state=state)


async def _submit_v3(op, model):
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
    if payload.get("ack_only"):
        return _pending_response_v3(request_id)
    try:
        wrapped = asyncio.wrap_future(submission.future)
        outcome = await asyncio.wait_for(asyncio.shield(wrapped), timeout=EXEC_SYNC_WAIT_SEC)
    except asyncio.TimeoutError:
        return _pending_response_v3(request_id, state="SENDING")
    return _render_record({
        "request_id": request_id,
        "state": outcome.state,
        "result": outcome.result,
    })


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
    status = _EXECUTION.status(request_id)
    if status is None:
        raise HTTPException(404, "unknown request_id")
    return status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
