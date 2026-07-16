# -*- coding: utf-8 -*-
"""Fake MT5 Bridge — V1.1 §18.2 测试床组件 (2026-07-16)。

模拟桥 HTTP 契约(含 20260716 实际成交口径升级后的四量字段), 行为可编排:
    POST /ctl/behavior {"mode": "done|partial|reject|hang", "filled_ratio": 0.6,
                        "retcode": 10004, "hang_seconds": 30}
    POST /mt5/order    → 按当前行为返回
    GET  /health       → 恒 ok
    GET  /ctl/orders   → 已收到的下单请求流水(断言用)

独立跑: venv/bin/python tests/testbed/fake_bridge.py --port 18999
测试内嵌: run_scenarios.py 经 httpx ASGITransport 直连 app, 无需端口。
"""
import asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="fake-mt5-bridge")

STATE = {
    "mode": "done",          # done | partial | reject | hang
    "filled_ratio": 0.5,      # partial 模式的成交比例
    "retcode_fail": 10004,    # reject 模式返回的 retcode
    "hang_seconds": 30.0,     # hang 模式挂起秒数(模拟HTTP超时→UNKNOWN)
    "orders": [],             # 收到的下单请求流水
    "next_ticket": 90000001,
}


class OrderReq(BaseModel):
    symbol: str
    volume: float
    order_type: str
    price: Optional[float] = None
    deviation: int = 20
    comment: str = ""
    position_ticket: Optional[int] = None


class Behavior(BaseModel):
    mode: Optional[str] = None
    filled_ratio: Optional[float] = None
    retcode_fail: Optional[int] = None
    hang_seconds: Optional[float] = None


@app.get("/health")
async def health():
    return {"status": "ok", "service": "fake-mt5-bridge", "instance": "testbed", "mt5": True}


@app.post("/ctl/behavior")
async def set_behavior(b: Behavior):
    for k, v in b.model_dump(exclude_none=True).items():
        STATE[k] = v
    return {"ok": True, "state": {k: STATE[k] for k in ("mode", "filled_ratio", "retcode_fail", "hang_seconds")}}


@app.get("/ctl/orders")
async def list_orders():
    return {"orders": STATE["orders"]}


@app.post("/ctl/reset")
async def reset():
    STATE["orders"] = []
    STATE["mode"] = "done"
    return {"ok": True}


@app.post("/mt5/order")
async def place_order(req: OrderReq):
    STATE["orders"].append(req.model_dump())
    mode = STATE["mode"]
    if mode == "hang":
        await asyncio.sleep(float(STATE["hang_seconds"]))
    ticket = STATE["next_ticket"]
    STATE["next_ticket"] += 1
    normalized = round(req.volume, 2)
    if mode == "reject":
        from fastapi import HTTPException
        raise HTTPException(400, f"Order failed retcode={STATE['retcode_fail']} comment=fake-reject")
    if mode == "partial":
        filled = round(normalized * float(STATE["filled_ratio"]), 2)
        retcode, partial = 10010, True
    else:  # done (hang 睡醒后也按 done 返回 — 模拟"已成交但响应迟到")
        filled = normalized
        retcode, partial = 10009, False
    return {
        "success": True,
        "retcode": retcode,
        "order": ticket,
        "deal": ticket + 5000000,
        "volume": filled,
        "price": 2400.5,
        "comment": "Request executed",
        "requested_volume": req.volume,
        "normalized_volume": normalized,
        "filled_volume": filled,
        "remaining_volume": max(0.0, round(normalized - filled, 8)),
        "partial": partial,
    }


if __name__ == "__main__":
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18999)
    a = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=a.port)
