"""
QHBridge MT4 Agent — 逐字节复刻 mt5-bridge 的 /mt5/* 协议(权威源:
D:\\QHMT5\\runtime\\releases\\v1\\ic\\app\\main.py),让 QH connector 零改即可切源。

架构:QH → 本 Agent(HTTP/X-API-Key)→ 文件桥 → QHBridge.mq4(EA,终端内)→ MT4 券商。
一账户一终端一 Agent 实例。读端点从 EA 导出的 state 文件读取;写端点(Phase D)投命令给 EA。

Phase A-C:实现 /health + 10 个读端点(SHADOW,零执行风险);写端点占位 501。
"""
import asyncio
import hashlib
import json
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from filebridge import FileBridge
from ledger import Ledger

# ─── 配置(env,.env 由 python-dotenv 或 uvicorn 环境注入)───
API_KEY       = os.getenv("API_KEY", "OQ6bUimHZDmXEZzJKE")   # 与 mt5-bridge 同默认(生产用 go 共享 key)
INSTANCE_NAME = os.getenv("INSTANCE_NAME", "qhmt4-unknown")
FILES_DIR     = os.getenv("TERMINAL_FILES_DIR", "")           # <terminal>\MQL4\Files\qhbridge
SERVICE_PORT  = int(os.getenv("SERVICE_PORT", "8041"))

if not FILES_DIR:
    raise RuntimeError("TERMINAL_FILES_DIR 未配置(应指向 <terminal>\\MQL4\\Files\\qhbridge)")

LEDGER_DB = os.getenv("LEDGER_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger_%s.db" % INSTANCE_NAME))
RESULT_WAIT_SEC = float(os.getenv("CMD_WAIT_SEC", "30"))
SYNC_WAIT_SEC = float(os.getenv("SYNC_WAIT_SEC", "0.55"))
MAX_PENDING_EXECUTIONS = max(1, int(os.getenv("MAX_PENDING_EXECUTIONS", "1")))

fb = FileBridge(FILES_DIR)
ledger = Ledger(LEDGER_DB)
app = FastAPI(title="QHBridge MT4 Agent", version="0.2")
_execution_queue = None
_execution_actor_task = None
_pending_futures = {}
_result_tasks = set()
_admission_lock = None


# ─── 请求模型(逐字节复刻 mt5-bridge)───
class OrderRequest(BaseModel):
    symbol: str
    volume: float
    order_type: str
    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    deviation: int = 10
    comment: str = ""
    position_ticket: Optional[int] = None
    request_id: Optional[str] = None
    # Ordered subsecond pairs use a durable Agent ACK as the inter-leg barrier.
    # The command still executes through the same single actor and WAL.
    ack_only: bool = False


class ClosePositionRequest(BaseModel):
    symbol: str
    side: str
    volume: Optional[float] = None
    ticket: Optional[int] = None
    request_id: Optional[str] = None


class CloseAllRequest(BaseModel):
    symbol: Optional[str] = None


class CancelAllRequest(BaseModel):
    symbol: Optional[str] = None


def _otoken(cmd_id: str) -> str:
    """MT4 OrderSend 用的 comment/对账 token(短,嵌 request_id 短哈希);
       EA 崩溃/超时后扫 orders/history 按 comment==otoken 认领,防重开。"""
    return "Q" + hashlib.sha1(cmd_id.encode()).hexdigest()[:9]


def _submit_and_wait(cmd_id: str, payload: dict):
    """投命令给 EA,等结果。返回 result dict 或 None(超时=UNKNOWN)。"""
    payload["otoken"] = _otoken(cmd_id)
    payload["ts"] = int(time.time())
    fb.submit_command(cmd_id, payload)
    return fb.wait_result(cmd_id, timeout=RESULT_WAIT_SEC, poll=0.01)


def _intent_hash(op: str, payload: dict) -> str:
    stable = {k: v for k, v in payload.items() if k not in ("ts", "agent_received_ns", "agent_wal_durable_ns")}
    raw = json.dumps({"op": op, "payload": stable}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pending_response(cmd_id: str, state: str = "DISPATCHING", trace=None):
    content = {
        "success": False,
        "accepted": True,
        "pending": True,
        "unknown": False,
        "state": state,
        "request_id": cmd_id,
        "status_url": "/mt5/order-status/%s" % cmd_id,
    }
    if trace:
        content["trace"] = trace
    return JSONResponse(status_code=202, content=content)


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(401, "invalid api key")
    return x_api_key


def _require_connected():
    """EA 状态新鲜且 connected 才算在线,否则 503(与 mt5-bridge 未连接语义一致)。"""
    meta, age = fb.meta()
    if not meta or not fb.is_fresh(age) or not meta.get("connected"):
        raise HTTPException(503, "MT4 not connected")
    return meta


# ═══ 1. Health(免鉴权)═══
@app.get("/health")
async def health():
    meta, age = fb.meta()
    connected = bool(meta and fb.is_fresh(age) and meta.get("connected"))
    return {
        "status":   "ok",
        "service":  "mt4-bridge",
        "instance": INSTANCE_NAME,
        "mt5":      connected,   # 保留字段名 mt5 供 QH/go 健康检查兼容(含义=终端已连接)
        "mt4":      connected,
        "trade_allowed": (meta.get("trade_allowed") if meta else None),
    }


# ═══ 2. Connection Status ═══
@app.get("/mt5/connection/status", dependencies=[Depends(verify_api_key)])
async def connection_status():
    meta, age = fb.meta()
    connected = bool(meta and fb.is_fresh(age) and meta.get("connected"))
    out = {
        "connected":  connected,
        "healthy":    connected,
        "failures":   0 if connected else 1,
        "last_ok_at": (meta or {}).get("last_ok_at"),
        "account":    (meta or {}).get("account"),
        "server":     (meta or {}).get("server"),
        "instance":   INSTANCE_NAME,
    }
    if connected:
        acct, _ = fb.read_state("account")
        if acct:
            out["balance"] = acct.get("balance")
            out["equity"] = acct.get("equity")
    return out


# ═══ 3. Reconnect(写:Phase D)═══
@app.post("/mt5/connection/reconnect", dependencies=[Depends(verify_api_key)])
async def reconnect():
    # MT4 终端断线自愈,此处仅回执(EA 常驻,登录由终端维持)
    return {"success": True, "instance": INSTANCE_NAME}


# ═══ 4. Positions ═══
@app.get("/mt5/positions", dependencies=[Depends(verify_api_key)])
async def get_positions(symbol: Optional[str] = Query(None)):
    _require_connected()
    data, age = fb.read_state("positions")
    if not data or not fb.is_fresh_for(age, "positions"):
        raise HTTPException(503, "MT4 positions snapshot is stale")
    positions = data.get("positions", [])
    if symbol:
        positions = [p for p in positions if p.get("symbol") == symbol]
    return {
        "positions": positions,
        "snapshot_boot": data.get("snapshot_boot"),
        "snapshot_seq": data.get("snapshot_seq"),
        "snapshot_ts": data.get("snapshot_ts", data.get("ts")),
        "snapshot_age_ms": round(float(age or 0) * 1000, 3),
    }


# ═══ 5. Account Balance ═══
@app.get("/mt5/account/balance", dependencies=[Depends(verify_api_key)])
async def account_balance():
    _require_connected()
    acct, age = fb.read_state("account")
    if not acct or not fb.is_fresh(age):
        raise HTTPException(503, "MT4 not connected")
    return {
        "balance":      acct.get("balance"),
        "equity":       acct.get("equity"),
        "margin":       acct.get("margin"),
        "margin_free":  acct.get("margin_free"),
        "margin_level": acct.get("margin_level"),
        "profit":       acct.get("profit"),
    }


# ═══ 6. Account Info(EA 已算好累计 swap)═══
@app.get("/mt5/account/info", dependencies=[Depends(verify_api_key)])
async def account_info():
    _require_connected()
    acct, age = fb.read_state("account")
    if not acct or not fb.is_fresh(age):
        raise HTTPException(503, "MT4 not connected")
    # 逐字节复刻 mt5-bridge account_info 的 15 字段
    return {
        "login":          acct.get("login"),
        "balance":        acct.get("balance"),
        "equity":         acct.get("equity"),
        "margin":         acct.get("margin"),
        "margin_free":    acct.get("margin_free"),
        "margin_level":   acct.get("margin_level"),
        "margin_so_call": acct.get("margin_so_call"),
        "margin_so_so":   acct.get("margin_so_so"),
        "margin_so_mode": acct.get("margin_so_mode"),
        "profit":         acct.get("profit"),
        "swap":           acct.get("swap"),
        "currency":       acct.get("currency"),
        "leverage":       acct.get("leverage"),
        "server":         acct.get("server"),
        "name":           acct.get("name"),
        "company":        acct.get("company"),
    }


# ═══ 7. Symbols ═══
@app.get("/mt5/symbols", dependencies=[Depends(verify_api_key)])
async def get_symbols():
    _require_connected()
    data, _ = fb.read_state("symbols")
    syms = sorted((data or {}).get("symbols", {}).keys()) if data else []
    return {"symbols": syms, "count": len(syms)}


# ═══ 8. Symbol Info ═══
@app.get("/mt5/symbol_info/{symbol}", dependencies=[Depends(verify_api_key)])
async def get_symbol_info(symbol: str):
    _require_connected()
    fb.ensure_watch([symbol])
    # 等 EA 补导该符号(cycle ~100ms)
    deadline = time.time() + 0.8
    while time.time() < deadline:
        data, age = fb.read_state("symbols")
        info = (data or {}).get("symbols", {}).get(symbol) if data else None
        if info and fb.is_fresh(age):
            return {
                "symbol":              info.get("symbol", symbol),
                "description":         info.get("description", ""),
                "digits":              info.get("digits"),
                "point":               info.get("point"),
                "volume_min":          info.get("volume_min"),
                "volume_max":          info.get("volume_max"),
                "volume_step":         info.get("volume_step"),
                "trade_contract_size": info.get("trade_contract_size"),
                "swap_long":           info.get("swap_long"),
                "swap_short":          info.get("swap_short"),
                "swap_mode":           info.get("swap_mode"),
                "swap_rollover3days":  info.get("swap_rollover3days"),
                "currency_base":       info.get("currency_base"),
                "currency_profit":     info.get("currency_profit"),
                "currency_margin":     info.get("currency_margin"),
                "visible":             info.get("visible", True),
                "trade_mode":          info.get("trade_mode"),
                "trade_allowed":       info.get("trade_allowed"),
            }
        time.sleep(0.05)
    raise HTTPException(404, f"Symbol {symbol} not found or EA not exporting yet")


# ═══ 9. Tick ═══
@app.get("/mt5/tick/{symbol}", dependencies=[Depends(verify_api_key)])
async def get_tick(symbol: str):
    _require_connected()
    fb.ensure_watch([symbol])
    deadline = time.time() + 0.8
    while time.time() < deadline:
        data, age = fb.read_state("ticks")
        t = (data or {}).get("ticks", {}).get(symbol) if data else None
        if t and fb.is_fresh(age):
            tsec = int(t.get("time", 0))
            return {
                "symbol":   symbol,
                "bid":      t.get("bid"),
                "ask":      t.get("ask"),
                "last":     t.get("last", 0.0),
                "volume":   t.get("volume", 0),
                "time":     tsec,
                "time_msc": tsec * 1000,   # MT4 无 time_msc;合成。券商 GMT+3,消费端沿用 +10800000ms 校正
            }
        time.sleep(0.05)
    raise HTTPException(404, f"No tick for symbol {symbol}")


# ═══ 10. History Deals ═══
@app.get("/mt5/history/deals", dependencies=[Depends(verify_api_key)])
async def history_deals(days: int = 1):
    _require_connected()
    data, age = fb.read_state("history_deals")
    deals = (data or {}).get("deals", []) if data else []
    return {"deals": deals}


# ═══ 11. History Orders ═══
@app.get("/mt5/history/orders", dependencies=[Depends(verify_api_key)])
async def history_orders(days: int = 1):
    _require_connected()
    data, age = fb.read_state("history_orders")
    orders = (data or {}).get("orders", []) if data else []
    return {"orders": orders}


# ═══ 写端点(Phase D:命令账本 + 文件桥命令投递)═══

def _apply_order_result(rid, res):
    """把 EA 的 order 结果落账,返回 (ok, payload)。ok=False 时 payload={error:...}。
       映射为 mt5-bridge order 响应结构(success/retcode/order/deal/filled_volume 等)。"""
    if res.get("ok"):
        req_vol = res.get("requested_volume", res.get("volume"))
        filled = float(res.get("volume") or 0.0)
        resp = {
            "success": True,
            "retcode": res.get("retcode", 10009),
            "order": res.get("ticket"),
            "deal": res.get("ticket"),
            "volume": filled,
            "price": res.get("price"),
            "comment": res.get("comment", ""),
            "requested_volume": req_vol,
            "normalized_volume": res.get("normalized_volume", req_vol),
            "filled_volume": filled,
            "remaining_volume": max(0.0, round((req_vol or 0.0) - filled, 8)),
            "partial": bool(res.get("partial")),
            "requote_retries": int(res.get("requote_retries") or 0),
            "request_id": rid,
            "trace": {
                "ea_command_observed_us": res.get("ea_command_observed_us"),
                "broker_call_started_us": res.get("broker_call_started_us"),
                "broker_call_returned_us": res.get("broker_call_returned_us"),
                "broker_call_ms": res.get("broker_call_ms"),
            },
        }
        if rid:
            ledger.put(rid, "DONE", resp)
        return True, resp
    if res.get("unknown"):
        payload = {"success": False, "unknown": True, "state": "UNKNOWN",
                   "request_id": rid, "error": res.get("error") or "order outcome unknown"}
        ledger.put(rid, "UNKNOWN", payload, op="order")
        return False, payload
    err = res.get("error") or ("retcode=%s" % res.get("retcode"))
    fail = {"error": err}
    if rid:
        ledger.put(rid, "FAILED", fail)
    return False, fail


def _apply_close_result(rid, res):
    if res.get("ok"):
        resp = {
            "success": True,
            "retcode": res.get("retcode", 10009),
            "order": res.get("ticket"),
            "volume": res.get("volume"),
            "price": res.get("price"),
            "comment": res.get("comment", ""),
            "request_id": rid,
            "reconciled": bool(res.get("reconciled")),
            "requote_retries": int(res.get("requote_retries") or 0),
            "trace": {
                "ea_command_observed_us": res.get("ea_command_observed_us"),
                "broker_call_started_us": res.get("broker_call_started_us"),
                "broker_call_returned_us": res.get("broker_call_returned_us"),
                "broker_call_ms": res.get("broker_call_ms"),
            },
        }
        ledger.put(rid, "DONE", resp, op="close")
        return True, resp
    if res.get("unknown"):
        payload = {"success": False, "unknown": True, "state": "UNKNOWN",
                   "request_id": rid, "error": res.get("error") or "close outcome unknown"}
        ledger.put(rid, "UNKNOWN", payload, op="close")
        return False, payload
    fail = {"error": res.get("error") or ("retcode=%s" % res.get("retcode")),
            "request_id": rid}
    ledger.put(rid, "FAILED", fail, op="close")
    return False, fail


def _apply_execution_result(cmd_id, op, result):
    if result is None:
        payload = {"success": False, "unknown": True, "state": "UNKNOWN",
                   "request_id": cmd_id,
                   "error": "EA result deadline exceeded; query order-status and do not resend"}
        ledger.put(cmd_id, "UNKNOWN", payload, op=op)
        return False, payload
    if op == "close":
        return _apply_close_result(cmd_id, result)
    if op in ("close_all", "cancel_all"):
        if result.get("ok"):
            response = {"success": True, "request_id": cmd_id}
            fields = (("closed", "failed", "results", "requote_retries") if op == "close_all"
                      else ("cancelled", "failed"))
            for field in fields:
                if field in result:
                    response[field] = result[field]
            response.setdefault("failed", 0)
            if op == "close_all":
                response.setdefault("closed", 0)
                response.setdefault("results", [])
            else:
                response.setdefault("cancelled", 0)
            ledger.put(cmd_id, "DONE", response, op=op)
            return True, response
        if result.get("unknown"):
            payload = {"success": False, "unknown": True, "state": "UNKNOWN",
                       "request_id": cmd_id,
                       "error": result.get("error") or "%s outcome unknown" % op}
            ledger.put(cmd_id, "UNKNOWN", payload, op=op)
            return False, payload
        failure = {"request_id": cmd_id,
                   "error": result.get("error") or ("retcode=%s" % result.get("retcode"))}
        ledger.put(cmd_id, "FAILED", failure, op=op)
        return False, failure
    return _apply_order_result(cmd_id, result)


async def _complete_execution(cmd_id, op, future, write_trace):
    try:
        result = await asyncio.to_thread(
            fb.wait_result, cmd_id, RESULT_WAIT_SEC, 0.01)
        ok, response = await asyncio.to_thread(_apply_execution_result, cmd_id, op, result)
        if isinstance(response, dict):
            response.setdefault("trace", {})
            if isinstance(response["trace"], dict):
                response["trace"].update(write_trace)
        if not future.done():
            future.set_result((ok, response))
    except Exception as exc:
        payload = {"success": False, "unknown": True, "state": "UNKNOWN",
                   "request_id": cmd_id, "error": str(exc)}
        await asyncio.to_thread(ledger.put, cmd_id, "UNKNOWN", payload, op)
        if not future.done():
            future.set_result((False, payload))
    finally:
        _pending_futures.pop(cmd_id, None)


async def _execution_actor():
    while True:
        item = await _execution_queue.get()
        cmd_id, op, payload, future = item
        try:
            write_trace = await asyncio.to_thread(fb.submit_command, cmd_id, payload)
            task = asyncio.create_task(_complete_execution(cmd_id, op, future, write_trace))
            _result_tasks.add(task)
            task.add_done_callback(_result_tasks.discard)
            # Keep command-file FIFO deterministic: expose the next command only after
            # EA has durably claimed this one. Broker result waiting runs independently.
            await asyncio.to_thread(fb.wait_dispatch, cmd_id, RESULT_WAIT_SEC, 0.005)
        except Exception as exc:
            payload = {"success": False, "unknown": True, "state": "UNKNOWN",
                       "request_id": cmd_id, "error": str(exc)}
            await asyncio.to_thread(ledger.put, cmd_id, "UNKNOWN", payload, op)
            if not future.done():
                future.set_result((False, payload))
            _pending_futures.pop(cmd_id, None)
        finally:
            _execution_queue.task_done()


@app.on_event("startup")
async def _start_execution_actor():
    global _execution_queue, _execution_actor_task, _admission_lock
    _execution_queue = asyncio.Queue()
    _admission_lock = asyncio.Lock()
    _execution_actor_task = asyncio.create_task(_execution_actor())


@app.on_event("shutdown")
async def _stop_execution_actor():
    if _execution_actor_task:
        _execution_actor_task.cancel()
    for task in tuple(_result_tasks):
        task.cancel()
    if _result_tasks:
        await asyncio.gather(*tuple(_result_tasks), return_exceptions=True)


async def _submit_execution(cmd_id: str, op: str, payload: dict, ack_only: bool = False,
                            sync_wait: Optional[float] = None):
    intent_hash = _intent_hash(op, payload)
    existing = await asyncio.to_thread(ledger.get_details, cmd_id)
    if existing:
        if existing.get("intent_hash") and existing["intent_hash"] != intent_hash:
            raise HTTPException(409, "request_id reused with a different intent")
        result = await asyncio.to_thread(ledger.get_result, cmd_id)
        if existing["state"] == "DONE" and result is not None:
            result["idempotency_hit"] = True
            return result
        if existing["state"] == "FAILED":
            raise HTTPException(400, "idempotent-replay: previous attempt FAILED terminally")
        if existing["state"] == "UNKNOWN":
            return JSONResponse(status_code=202, content=result or {
                "success": False, "unknown": True, "state": "UNKNOWN",
                "request_id": cmd_id, "status_url": "/mt5/order-status/%s" % cmd_id})
        future = _pending_futures.get(cmd_id)
        if future is None:
            raw = await asyncio.to_thread(fb.read_result, cmd_id)
            if raw is not None:
                ok, response = _apply_execution_result(cmd_id, op, raw)
                if ok:
                    response["idempotency_hit"] = True
                    return response
                raise HTTPException(400, response.get("error", "%s failed" % op))
            return _pending_response(cmd_id)
        if ack_only:
            return _pending_response(cmd_id)
    else:
        async with _admission_lock:
            if len(_pending_futures) >= MAX_PENDING_EXECUTIONS:
                raise HTTPException(
                    429,
                    "ACCOUNT_EXECUTION_BUSY: previous broker command is not terminal",
                    headers={"Retry-After": "1"},
                )
            reserved = await asyncio.to_thread(ledger.reserve, cmd_id, op, intent_hash)
            if not reserved:
                return _pending_response(cmd_id)
            payload["agent_wal_durable_ns"] = time.time_ns()
            future = asyncio.get_running_loop().create_future()
            _pending_futures[cmd_id] = future
            await _execution_queue.put((cmd_id, op, payload, future))

    if ack_only:
        return _pending_response(cmd_id, trace={
            "agent_received_ns": payload.get("agent_received_ns"),
            "agent_wal_durable_ns": payload.get("agent_wal_durable_ns"),
        })

    try:
        wait_seconds = SYNC_WAIT_SEC if sync_wait is None else max(0.01, float(sync_wait))
        ok, response = await asyncio.wait_for(asyncio.shield(future), timeout=wait_seconds)
    except asyncio.TimeoutError:
        return _pending_response(cmd_id)
    if ok:
        return response
    if response.get("unknown"):
        return JSONResponse(status_code=202, content=response)
    raise HTTPException(400, "%s failed: %s" % (op, response.get("error")))


@app.post("/mt5/order", dependencies=[Depends(verify_api_key)])
async def place_order(req: OrderRequest):
    _require_connected()
    cmd_id = req.request_id or uuid.uuid4().hex
    payload = {"op": "order", "symbol": req.symbol, "order_type": req.order_type,
               "side": ("sell" if req.order_type.lower().startswith("sell") else "buy"),
               "volume": req.volume, "price": req.price, "sl": req.sl, "tp": req.tp,
               "deviation": req.deviation, "comment": req.comment,
               "agent_received_ns": time.time_ns()}
    payload["otoken"] = _otoken(cmd_id)
    return await _submit_execution(cmd_id, "order", payload, ack_only=req.ack_only)


@app.post("/mt5/position/close", dependencies=[Depends(verify_api_key)])
async def close_position(req: ClosePositionRequest):
    _require_connected()
    if not req.ticket:
        raise HTTPException(400, "EXACT_TICKET_REQUIRED")
    cmd_id = req.request_id or uuid.uuid4().hex
    payload = {"op": "close", "symbol": req.symbol, "side": req.side,
               "volume": req.volume, "ticket": req.ticket,
               "agent_received_ns": time.time_ns(), "otoken": _otoken(cmd_id)}
    return await _submit_execution(cmd_id, "close", payload)


@app.post("/mt5/position/close-all", dependencies=[Depends(verify_api_key)])
async def close_all(req: CloseAllRequest):
    _require_connected()
    cmd_id = uuid.uuid4().hex
    return await _submit_execution(
        cmd_id, "close_all", {"op": "close_all", "symbol": req.symbol},
        sync_wait=RESULT_WAIT_SEC,
    )


@app.post("/mt5/cancel-all", dependencies=[Depends(verify_api_key)])
async def cancel_all(req: CancelAllRequest):
    _require_connected()
    cmd_id = uuid.uuid4().hex
    return await _submit_execution(
        cmd_id, "cancel_all", {"op": "cancel_all", "symbol": req.symbol},
        sync_wait=RESULT_WAIT_SEC,
    )


@app.get("/mt5/order-status/{request_id}", dependencies=[Depends(verify_api_key)])
async def order_status(request_id: str):
    details = await asyncio.to_thread(ledger.get_details, request_id)
    if not details:
        raise HTTPException(404, "unknown request_id")
    state = details["state"]
    # SENDING 但结果文件已到 → 落账推进(UNKNOWN 解决,QH 超时后调此端点)
    if state in ("SENDING", "UNKNOWN"):
        res = await asyncio.to_thread(fb.read_result, request_id)
        if res is not None:
            ok, _ = await asyncio.to_thread(
                _apply_execution_result, request_id, details.get("op") or "order", res)
            updated = await asyncio.to_thread(ledger.get_details, request_id)
            state = (updated or {}).get("state", "DONE" if ok else "FAILED")
    out = {"request_id": request_id, "state": state,
           "pending": state == "SENDING",
           "unknown": state == "UNKNOWN",
           "terminal": state in ("DONE", "FAILED")}
    r = await asyncio.to_thread(ledger.get_result, request_id)
    if r is not None:
        out["result"] = r
    return out
