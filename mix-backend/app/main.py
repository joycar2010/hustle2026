"""
HustleCoin Mix 后端 —— 从 contracts/openapi.yaml 展开的路由骨架。
后端同学：逐个 router 把 TODO 换成真实实现，前端不动（VITE_MIX_API 指向本服务即可）。
启动：uvicorn app.main:app --host 127.0.0.1 --port 8200
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .routers import positions, strategies, rules, accounts, misc, me, auth, history, ops, notify_center, credentials

app = FastAPI(title="HustleCoin Mix API", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def _validation_400(request: Request, exc: RequestValidationError):
    """契约铁律：口径参数缺失/非法一律 400（不是 FastAPI 默认 422）。"""
    return JSONResponse(status_code=400, content={"error": "口径参数缺失或非法（必须显式）", "detail": exc.errors()})

# 双域同机同后端：nginx 按 Host 收口；本服务对两域一视同仁。
# 生产建议用 nginx 白名单 Origin，联调期放开。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
for r in (positions.router, strategies.router, rules.router, accounts.router, misc.router, me.router,
          auth.router, history.router, ops.router, notify_center.router, credentials.router):
    app.include_router(r, prefix=API)

# WS 已剥离为独立 hub（Rust mix-ws-hub@8201，qh-ws-hub 模式；Python app.ws_main 为回滚备胎）。
# 本 API 进程不持长连接，只负责把 position:updates 预打包帧发布到 mix:ws:frames（hub 纯中继）。
import asyncio  # noqa: E402
from . import ws as _ws  # noqa: E402


@app.on_event("startup")
async def _start_frames_publisher():
    asyncio.get_event_loop().create_task(_ws.position_frames_publisher())
    asyncio.get_event_loop().create_task(history.history_sync_loop())  # 交易历史落 mix 库(300s)


@app.get(f"{API}/health")
async def health():
    from . import datasources as ds
    return {"ok": True, **ds.degraded()}
