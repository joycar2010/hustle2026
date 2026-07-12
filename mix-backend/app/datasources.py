"""
数据源层 —— dcm_main 只读池(asyncpg) + A 机 Redis 总线 + 微型 TTL 缓存。
铁律：本层只读。任何异常降级为 None/[]，由适配层如实标注 degraded，绝不向上抛 500。
"""
import json
import time
import asyncio
import logging
from typing import Any, Optional

from . import config

log = logging.getLogger("mix.datasources")

_pg_pool = None
_pg_main_pool = None
_redis = None
_pg_lock = asyncio.Lock()


async def pg():
    """dcm_main 只读连接池（mix_ro 角色）。未配置/失败返回 None。"""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    if not config.PG_DSN:
        return None
    async with _pg_lock:
        if _pg_pool is not None:
            return _pg_pool
        try:
            import asyncpg
            _pg_pool = await asyncpg.create_pool(config.PG_DSN, min_size=1, max_size=4, command_timeout=8)
        except Exception as e:  # noqa: BLE001
            log.warning("pg pool unavailable: %s", e)
            return None
    return _pg_pool


async def pg_main():
    """mix_main 读写池（mix_app 角色）—— 用户体系/KMS 审批流自有库。"""
    global _pg_main_pool
    if _pg_main_pool is not None:
        return _pg_main_pool
    if not config.MAIN_DSN:
        return None
    async with _pg_lock:
        if _pg_main_pool is not None:
            return _pg_main_pool
        try:
            import asyncpg
            _pg_main_pool = await asyncpg.create_pool(config.MAIN_DSN, min_size=1, max_size=4, command_timeout=8)
        except Exception as e:  # noqa: BLE001
            log.warning("pg_main pool unavailable: %s", e)
            return None
    return _pg_main_pool


def rds():
    """Redis 客户端（懒加载）。未配置返回 None。"""
    global _redis
    if _redis is not None:
        return _redis
    if not config.REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(config.REDIS_URL, decode_responses=True,
                                   socket_timeout=5, socket_connect_timeout=5)
    except Exception as e:  # noqa: BLE001
        log.warning("redis unavailable: %s", e)
        return None
    return _redis


# ---------------- 微型 TTL 缓存（保护总线与 DB，前端 5s 轮询打不穿） ----------------
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < config.CACHE_TTL_SEC:
        return hit[1]
    return None


def _cache_put(key: str, val: Any):
    _cache[key] = (time.monotonic(), val)
    return val


async def get_json(key: str) -> Optional[dict]:
    """GET 一个 string 键并 json 解析（带 TTL 缓存）。"""
    ck = f"g:{key}"
    c = _cache_get(ck)
    if c is not None:
        return c
    r = rds()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        return _cache_put(ck, json.loads(raw) if raw else None)
    except Exception as e:  # noqa: BLE001
        log.warning("get_json(%s): %s", key, e)
        return None


async def hgetall_json(key: str) -> dict[str, dict]:
    """HGETALL 一个 hash 键，逐字段 json 解析（带 TTL 缓存）。"""
    ck = f"h:{key}"
    c = _cache_get(ck)
    if c is not None:
        return c
    r = rds()
    if r is None:
        return {}
    try:
        raw = await r.hgetall(key)
        out = {}
        for k, v in raw.items():
            try:
                out[k] = json.loads(v)
            except Exception:  # noqa: BLE001
                out[k] = {"raw": v}
        return _cache_put(ck, out)
    except Exception as e:  # noqa: BLE001
        log.warning("hgetall_json(%s): %s", key, e)
        return {}


async def keys_values(pattern: str) -> dict[str, Optional[dict]]:
    """按模式取一组 string 键（用于 dcm:hb:* / dcm:account:*）。"""
    ck = f"k:{pattern}"
    c = _cache_get(ck)
    if c is not None:
        return c
    r = rds()
    if r is None:
        return {}
    try:
        ks = sorted(await r.keys(pattern))
        out = {}
        for k in ks:
            raw = await r.get(k)
            try:
                out[k] = json.loads(raw) if raw else None
            except Exception:  # noqa: BLE001
                out[k] = None
        return _cache_put(ck, out)
    except Exception as e:  # noqa: BLE001
        log.warning("keys_values(%s): %s", pattern, e)
        return {}


async def fetch(sql: str, *args) -> list[dict]:
    """只读 SQL（带 TTL 缓存，键=SQL+参数）。失败返回 []。"""
    ck = f"q:{sql}:{args}"
    c = _cache_get(ck)
    if c is not None:
        return c
    pool = await pg()
    if pool is None:
        return []
    try:
        rows = await pool.fetch(sql, *args)
        return _cache_put(ck, [dict(r) for r in rows])
    except Exception as e:  # noqa: BLE001
        log.warning("fetch(%s): %s", sql[:60], e)
        return []


def degraded() -> dict:
    """数据源可用性快照（供 /health 与前端 degraded 标注）。"""
    return {
        "pg_configured": bool(config.PG_DSN),
        "redis_configured": bool(config.REDIS_URL),
    }
