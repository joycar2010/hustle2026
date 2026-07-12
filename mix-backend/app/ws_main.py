"""
独立 WS hub 进程（mix-ws.service @127.0.0.1:8201，nginx /ws/ → 此进程）。
与 API 进程（mix-backend @8200）故障域隔离：API 重启不断长连接，连接洪峰不拖 API 延迟。
协议与鉴权与内嵌版完全一致（ws.py 单一实现）——用户端量级再上台阶时，
把本进程换成 Rust hub（qh-ws-hub 模式）即可，前端与 API 零改动。
启动：uvicorn app.ws_main:app --host 127.0.0.1 --port 8201
"""
from fastapi import FastAPI

from . import ws as _ws
from . import datasources as ds

app = FastAPI(title="HustleCoin Mix WS hub", version="0.1.0")
app.add_api_websocket_route("/ws/stream", _ws.ws_stream)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "role": "ws-hub", **ds.degraded()}
