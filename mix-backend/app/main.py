"""
HustleCoin Mix 后端 —— 从 contracts/openapi.yaml 展开的路由骨架。
后端同学：逐个 router 把 TODO 换成真实实现，前端不动（VITE_MIX_API 指向本服务即可）。
启动：uvicorn app.main:app --host 127.0.0.1 --port 8200
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .routers import aicoin, ledger, maintenance, proposal, positions, strategies, rules, accounts, misc, me, auth, history, ops, notify_center, credentials, ai, investor, risk, intents
from .routers import v6ops, portal, lab, webauthn_auth, training, research, fastlane, automation, playbooks, guidance

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
          auth.router, history.router, ops.router, notify_center.router, credentials.router, ai.router,
          investor.router, risk.router, aicoin.router, proposal.router, maintenance.router, ledger.router):
    app.include_router(r, prefix=API)

# V6 契约(方案 §4/§8/§9/§13):operator/portal/lab 三命名空间 + WebAuthn
API6 = "/api/v6"
for r in (v6ops.router, portal.router, lab.router, training.router, research.router, intents.router, fastlane.router, automation.router, playbooks.router, guidance.router):
    app.include_router(r, prefix=API6)
app.include_router(webauthn_auth.router, prefix=API)

# WS 已剥离为独立 hub（Rust mix-ws-hub@8201，qh-ws-hub 模式；Python app.ws_main 为回滚备胎）。
# 本 API 进程不持长连接，只负责把 position:updates 预打包帧发布到 mix:ws:frames（hub 纯中继）。
import asyncio  # noqa: E402
from . import ws as _ws  # noqa: E402


@app.on_event("startup")
async def _start_frames_publisher():
    asyncio.get_event_loop().create_task(_ws.position_frames_publisher())
    asyncio.get_event_loop().create_task(history.history_sync_loop())  # 交易历史落 mix 库(300s)
    from . import kernel_shadow  # noqa: E402
    asyncio.get_event_loop().create_task(kernel_shadow.kernel_shadow_loop())  # 执行内核影随(120s,shadow)
    from . import v6core  # noqa: E402
    asyncio.get_event_loop().create_task(v6core.control_snapshot_loop())  # V6 统一快照(3s,generation 单调)
    from . import v6lang  # noqa: E402
    asyncio.get_event_loop().create_task(v6lang.ensure_seed())  # V6.1 字典+能力注册表种子(幂等)
    from .routers import training as _tr  # noqa: E402
    asyncio.get_event_loop().create_task(_tr.ensure_seed())  # N4 训练认证祖父条款(现役全员预发)
    from . import risk_guard  # noqa: E402  PATCH-02 §8:③分位采样器+四层保护评估(shadow)
    asyncio.get_event_loop().create_task(risk_guard.spread_sampler_loop())
    asyncio.get_event_loop().create_task(risk_guard.risk_exit_loop())
    from .routers import ops as _ops  # noqa: E402  投资人门户实时投影(CORE_POOL 数据打通)
    asyncio.get_event_loop().create_task(_ops.investor_projection_loop())
    from .routers import investor as _inv  # noqa: E402  REV2 §4A 身份份额最小切分种子
    asyncio.get_event_loop().create_task(_inv.ensure_client_seed())
    asyncio.get_event_loop().create_task(v6ops.legacy_compare_daily_loop())  # §14.2 时钟发条(每UTC日保底一跑)
    asyncio.get_event_loop().create_task(risk.override_age_reminder_loop())  # 人工冻结>24h跑马灯提醒(防遗忘)
    from . import asset360 as _a360  # noqa: E402
    asyncio.get_event_loop().create_task(_a360.l1lite_mult_loop())  # l1lite 张→base乘数发布(gate/okx)


@app.get(f"{API}/health")
async def health():
    from . import datasources as ds
    return {"ok": True, **ds.degraded()}
