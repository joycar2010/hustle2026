"""DexCexMix gateway 骨架:/healthz /readyz + 总线心跳。

业务路由(auth/配置/路由表/通知模块)后续挂载;本骨架的职责是打通并验证
「仓库 → 部署 → systemd(slice) → HTTP → 跨机总线」整条链路。
"""
import asyncio
import logging
import os
import socket
import time
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from dcm_common.heartbeat import Heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("gateway")

SERVICE = "gateway"
VERSION = "0.1.0"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
TSDB_DSN = os.environ.get("DCM_TSDB_DSN", "")

_hb = Heartbeat(REDIS_URL, SERVICE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_hb.run_forever())
    logger.info(f"gateway up pid={os.getpid()} host={socket.gethostname()}")
    yield
    task.cancel()


app = FastAPI(title="DexCexMix Gateway", version=VERSION, lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"service": SERVICE, "version": VERSION, "pid": os.getpid(),
            "host": socket.gethostname(), "ts": int(time.time())}


@app.get("/readyz")
async def readyz():
    """依赖就绪探针:总线(A机Redis)+ 主库(C机PG)+ 时序库(A机PG),逐项报告。"""
    checks: dict[str, str] = {}
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        pong = await asyncio.wait_for(r.ping(), timeout=3)
        await r.aclose()
        checks["redis_bus"] = "ok" if pong else "no pong"
    except Exception as e:
        checks["redis_bus"] = f"error: {e}"
    for name, dsn in (("pg_main", PG_DSN), ("pg_tsdb", TSDB_DSN)):
        if not dsn:
            checks[name] = "unconfigured"
            continue
        try:
            conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5)
            await conn.execute("SELECT 1")
            await conn.close()
            checks[name] = "ok"
        except Exception as e:
            checks[name] = f"error: {e}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"service": SERVICE, "ready": ok, "checks": checks})
