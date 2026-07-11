"""decision v1 骨架:路由权威表(route_assignments)的唯一写入口。

定位:决策面输出「币 × 引擎 × 目标仓位」三元组。现在供人工/API 调用;将来 AI 顾问也
**只能**经同一 POST /routes 写入——schema 校验 → 硬校验钳位 → 乐观锁 → 全量审计 →
总线热发布(HSET dcm:route:assignments + PUBLISH dcm:route:updates,引擎 0 秒感知)。
AI 不碰订单;摘除 AI = 没人调这个 API,存量路由静止,天然退化为「只持有不新增」。

硬校验钳位(每条都有 coin/testgo 学费背书):
- engine/venue/market 白名单(CHECK 约束双保险);
- dualperp 必须双腿 perp 且异所;两腿必须真实存在于 feed 行情哈希(可交易性用实时行情证明,
  不信配置想当然);
- 单币名义钳位 + 全组合名义总额钳位(超限=钳到剩余额度并在响应里如实标注,不静默);
- 乐观锁:更新必须携带当前 version,错了 409(并发写保护);
- 一币一引擎:UNIQUE(symbol) 在 DB 层兜底路由互斥。
"""
import asyncio
import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dcm_common.heartbeat import Heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("decision")

SERVICE = "decision"
VERSION = "0.1.0"
PG_DSN = os.environ.get("DCM_PG_DSN", "")
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
MAX_NOTIONAL = Decimal(os.environ.get("DCM_ROUTE_MAX_NOTIONAL", "1000"))     # 单币上限(canary 期)
GLOBAL_MAX = Decimal(os.environ.get("DCM_ROUTE_GLOBAL_MAX", "5000"))         # 全组合上限

ENGINES = {"coin", "dualperp", "basis", "none"}
VENUES = {"binance", "okx", "bybit", "gate", "bitget", "hyperliquid"}  # HL=第六腿(2026-07-11 交易腿解锁)
MARKETS = {"spot", "perp"}

_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None
_hb = Heartbeat(REDIS_URL, SERVICE)


class RouteIn(BaseModel):
    symbol: str = Field(min_length=5, max_length=30, pattern=r"^[A-Z0-9]+$")
    engine: str
    venue_long: str = ""
    market_long: str = ""
    venue_short: str = ""
    market_short: str = ""
    target_notional_usdt: Decimal = Decimal("0")
    state: str = "proposed"
    reason: str = ""
    actor: str = "manual"
    version: int | None = None  # 更新时必带(乐观锁);新建省略


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _redis
    _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=5)
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    task = asyncio.create_task(_hb.run_forever())
    log.info(f"decision up pid={os.getpid()} max_notional={MAX_NOTIONAL} global_max={GLOBAL_MAX}")
    yield
    task.cancel()
    await _pool.close()


app = FastAPI(title="DexCexMix Decision", version=VERSION, lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"service": SERVICE, "version": VERSION, "pid": os.getpid(),
            "host": socket.gethostname(), "ts": int(time.time())}


def _row_dict(r: asyncpg.Record | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


async def _leg_exists_in_feed(venue: str, market: str, symbol: str) -> bool:
    try:
        return bool(await _redis.hexists(f"dcm:feed:{venue}:{market}", symbol))
    except Exception as e:
        log.warning(f"feed check failed {venue}:{market}:{symbol}: {e}")
        return False


async def _validate_and_clamp(body: RouteIn, conn: asyncpg.Connection) -> tuple[RouteIn, list[str]]:
    notes: list[str] = []
    if body.engine not in ENGINES:
        raise HTTPException(400, f"engine 必须是 {sorted(ENGINES)}")
    if body.state not in ("proposed", "active", "draining", "off"):
        raise HTTPException(400, "state 非法")

    if body.engine == "dualperp":
        for v, m, leg in ((body.venue_long, body.market_long, "long"),
                          (body.venue_short, body.market_short, "short")):
            if v not in VENUES or m != "perp":
                raise HTTPException(400, f"dualperp {leg} 腿必须是六所之一的 perp")
        if body.venue_long == body.venue_short:
            raise HTTPException(400, "dualperp 两腿必须异所")
        # 可交易性用实时行情证明:两腿都必须存在于 feed 哈希
        for v, m, leg in ((body.venue_long, body.market_long, "long"),
                          (body.venue_short, body.market_short, "short")):
            if not await _leg_exists_in_feed(v, m, body.symbol):
                raise HTTPException(400, f"{leg} 腿 {v}:{m}:{body.symbol} 不在 feed 行情中(不可交易或未纳入宇宙)")
    elif body.engine == "basis":
        body.venue_long, body.market_long = "binance", "spot"
        body.venue_short, body.market_short = "binance", "perp"
    else:  # coin / none:腿字段清空,防脏数据
        body.venue_long = body.market_long = body.venue_short = body.market_short = ""

    # 单币钳位
    if body.target_notional_usdt < 0:
        raise HTTPException(400, "target_notional_usdt 不能为负")
    if body.target_notional_usdt > MAX_NOTIONAL:
        notes.append(f"clamped: 单币上限 {MAX_NOTIONAL}(原请求 {body.target_notional_usdt})")
        body.target_notional_usdt = MAX_NOTIONAL

    # 全组合钳位(不含本币现有目标)
    row = await conn.fetchrow(
        "SELECT COALESCE(SUM(target_notional_usdt),0) AS s FROM route_assignments "
        "WHERE state IN ('proposed','active') AND symbol <> $1", body.symbol)
    remaining = GLOBAL_MAX - Decimal(row["s"])
    if body.target_notional_usdt > remaining:
        clamped = max(remaining, Decimal("0"))
        notes.append(f"clamped: 全组合上限 {GLOBAL_MAX},剩余额度 {remaining}(原请求 {body.target_notional_usdt})")
        body.target_notional_usdt = clamped
    return body, notes


async def _publish(symbol: str, row: dict | None):
    """总线热发布:引擎 HGETALL 起步 + 订阅增量,0 秒感知(coin rules:reload 同模式)。"""
    try:
        if row is None:
            await _redis.hdel("dcm:route:assignments", symbol)
        else:
            await _redis.hset("dcm:route:assignments", symbol, json.dumps(row, ensure_ascii=False))
        await _redis.publish("dcm:route:updates", symbol)
    except Exception as e:
        log.warning(f"route publish failed {symbol}: {e}")


@app.get("/routes")
async def list_routes():
    rows = await _pool.fetch("SELECT * FROM route_assignments ORDER BY symbol")
    return {"count": len(rows), "routes": [_row_dict(r) for r in rows]}


@app.post("/routes")
async def upsert_route(body: RouteIn):
    async with _pool.acquire() as conn:
        async with conn.transaction():
            old = await conn.fetchrow(
                "SELECT * FROM route_assignments WHERE symbol=$1 FOR UPDATE", body.symbol)
            body, notes = await _validate_and_clamp(body, conn)
            if old is not None:
                if body.version is None or body.version != old["version"]:
                    raise HTTPException(
                        409, f"version 冲突: 当前 {old['version']},请求 {body.version}(先 GET 再改)")
                new = await conn.fetchrow(
                    """UPDATE route_assignments SET engine=$2, venue_long=$3, market_long=$4,
                       venue_short=$5, market_short=$6, target_notional_usdt=$7, state=$8,
                       reason=$9, version=version+1, updated_by=$10, updated_at=now()
                       WHERE symbol=$1 RETURNING *""",
                    body.symbol, body.engine, body.venue_long, body.market_long,
                    body.venue_short, body.market_short, body.target_notional_usdt,
                    body.state, body.reason, body.actor)
            else:
                new = await conn.fetchrow(
                    """INSERT INTO route_assignments
                       (symbol, engine, venue_long, market_long, venue_short, market_short,
                        target_notional_usdt, state, reason, updated_by)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
                    body.symbol, body.engine, body.venue_long, body.market_long,
                    body.venue_short, body.market_short, body.target_notional_usdt,
                    body.state, body.reason, body.actor)
            await conn.execute(
                "INSERT INTO route_audit(symbol, actor, old_row, new_row, note) "
                "VALUES ($1,$2,$3,$4,$5)",
                body.symbol, body.actor,
                json.dumps(_row_dict(old), ensure_ascii=False) if old else None,
                json.dumps(_row_dict(new), ensure_ascii=False), "; ".join(notes))
    row = _row_dict(new)
    await _publish(body.symbol, row)
    log.info(f"route upsert {body.symbol} -> {body.engine} target={row['target_notional_usdt']} "
             f"by={body.actor} notes={notes}")
    return JSONResponse({"applied": row, "clamp_notes": notes})


@app.get("/readyz")
async def readyz():
    checks = {}
    try:
        await _pool.fetchval("SELECT 1")
        checks["pg"] = "ok"
    except Exception as e:
        checks["pg"] = f"error: {e}"
    try:
        checks["redis"] = "ok" if await _redis.ping() else "no pong"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"service": SERVICE, "ready": ok, "checks": checks})
