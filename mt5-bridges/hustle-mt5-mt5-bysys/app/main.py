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

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import MetaTrader5 as mt5
from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

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

# ─── FastAPI ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title=f"MT5 Bridge [{INSTANCE_NAME}]",
    version="2.0.0",
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
    comment:   str           = "hustle2026"
    position_ticket: Optional[int] = None  # 用于平仓

class ClosePositionRequest(BaseModel):
    symbol: str
    side:   str              # "buy"(平空) | "sell"(平多)
    volume: Optional[float] = None
    ticket: Optional[int]   = None

class CloseAllRequest(BaseModel):
    symbol: Optional[str] = None   # None = 全部品种

class CancelAllRequest(BaseModel):
    symbol: Optional[str] = None

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
            if not mt5.initialize(path=MT5_PATH):
                logger.error(f"mt5.initialize failed: {mt5.last_error()}")
                self.failures += 1
                return False

            # 已登录正确账户则跳过 login()
            info = mt5.account_info()
            if info and info.login == MT5_LOGIN:
                logger.info(f"MT5 already connected: {MT5_LOGIN}@{MT5_SERVER}")
                self._on_success()
                self._activate_symbols()
                return True

            if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD,
                             server=MT5_SERVER, timeout=10000):
                logger.error(f"mt5.login failed: {mt5.last_error()}")
                mt5.shutdown()
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
                info = mt5.symbol_info(sym)
                if info and not info.visible:
                    mt5.symbol_select(sym, True)
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
            if self.connected and mt5.account_info() is not None:
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
            mt5.shutdown()
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
    mgr.disconnect()

# ────────────────────────────────────────────────────────────────────────────
# 辅助：标准化量和价格
# ────────────────────────────────────────────────────────────────────────────
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

# ────────────────────────────────────────────────────────────────────────────
# 端点实现
# ────────────────────────────────────────────────────────────────────────────

# ── 1. Health ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status":   "ok",
        "service":  "mt5-bridge",
        "instance": INSTANCE_NAME,
        "mt5":      mgr.connected,
    }

# ── 2. Connection Status ──────────────────────────────────────────────────
@app.get("/mt5/connection/status", dependencies=[Depends(verify_api_key)])
async def connection_status():
    status = mgr.get_status()
    if mgr.connected:
        info = mt5.account_info()
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
    return {"success": ok, "instance": INSTANCE_NAME}

# ── 4. Positions ──────────────────────────────────────────────────────────
@app.get("/mt5/positions", dependencies=[Depends(verify_api_key)])
async def get_positions(symbol: Optional[str] = Query(None)):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    mgr.ping()
    if raw is None:
        return {"positions": []}
    positions = [
        {
            "ticket":          p.ticket,
            "symbol":          p.symbol,
            "type":            p.type,        # 0=BUY 1=SELL
            "volume":          p.volume,
            "price_open":      p.price_open,
            "price_current":   p.price_current,
            "profit":          p.profit,
            "swap":            p.swap,
            "sl":              p.sl,
            "tp":              p.tp,
            "margin":          getattr(p, "margin", 0.0),
            "price_liquidation": getattr(p, "price_liquidation", 0.0),
            "time":            p.time,
            "comment":         getattr(p, "comment", ""),
        }
        for p in raw
    ]
    return {"positions": positions}

# ── 5. Account Balance ────────────────────────────────────────────────────
@app.get("/mt5/account/balance", dependencies=[Depends(verify_api_key)])
async def account_balance():
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    info = mt5.account_info()
    if info is None:
        raise HTTPException(500, f"mt5.account_info() failed: {mt5.last_error()}")
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
    info = mt5.account_info()
    if info is None:
        raise HTTPException(500, f"mt5.account_info() failed: {mt5.last_error()}")
    mgr.ping()

    # 累计 swap = 持仓swap + 近30日历史deal swap
    total_swap = 0.0
    positions = mt5.positions_get() or []
    for p in positions:
        total_swap += p.swap

    from_date = datetime.utcnow() - timedelta(days=30)
    deals = mt5.history_deals_get(from_date, datetime.utcnow()) or []
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
    syms = mt5.symbols_get() or []
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
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(404, f"Symbol {symbol} not found: {mt5.last_error()}")
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
    }


@app.get("/mt5/tick/{symbol}", dependencies=[Depends(verify_api_key)])
async def get_tick(symbol: str):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise HTTPException(404, f"No tick for symbol {symbol}: {mt5.last_error()}")
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
    deals = mt5.history_deals_get(from_date, datetime.utcnow()) or []
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
    orders = mt5.history_orders_get(from_date, datetime.utcnow()) or []
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
@app.post("/mt5/order", dependencies=[Depends(verify_api_key)])
async def place_order(req: OrderRequest):
    if not mgr.ensure():
        raise HTTPException(503, "MT5 not connected")

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
        type_filling = mt5.ORDER_FILLING_IOC

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
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            mgr.ping()
            logger.info(f"Order OK | sym={req.symbol} side={req.order_type} vol={volume} "
                        f"price={request.get('price')} order={result.order}")
            return {
                "success":  True,
                "retcode":  result.retcode,
                "order":    result.order,
                "deal":     result.deal,
                "volume":   result.volume,
                "price":    result.price,
                "comment":  result.comment,
            }
        # 可重试错误（重新报价/流动性不足）
        if result.retcode in (10030, 10018) and attempt < MAX_RETRY - 1:
            logger.warning(f"Retrying order, retcode={result.retcode}")
            continue
        raise HTTPException(400, f"Order failed retcode={result.retcode} comment={result.comment}")

# ── 12. Close Specific Position ───────────────────────────────────────────
@app.post("/mt5/position/close", dependencies=[Depends(verify_api_key)])
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
        "comment":      "hustle2026-close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
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
@app.post("/mt5/position/close-all", dependencies=[Depends(verify_api_key)])
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
            "comment":      "hustle2026-close-all",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
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
@app.post("/mt5/cancel-all", dependencies=[Depends(verify_api_key)])
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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
