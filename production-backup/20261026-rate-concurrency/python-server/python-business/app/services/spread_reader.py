import asyncio
import json
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from engine.freshness import configured_spread_max_age_ms
from app.db.schemas import SpreadData

FULL_REFRESH_INTERVAL_SEC = 2
DEFAULT_SPREAD_MAX_AGE_MS = configured_spread_max_age_ms()


def is_spread_fresh(
    data: SpreadData | None,
    *,
    now_ms: int | None = None,
    max_age_ms: int = DEFAULT_SPREAD_MAX_AGE_MS,
) -> bool:
    """Require both Rust WS legs to have a recent local receive timestamp."""
    if data is None:
        return False
    try:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        limit = max(1, int(max_age_ms))
        for received in (
            int(data.spot_recv_ts_ms or 0),
            int(data.fut_recv_ts_ms or 0),
        ):
            age = now - received
            if received <= 0 or age > limit or age < -60_000:
                return False
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _latest_receive_ts(data: SpreadData) -> int:
    spot = int(data.spot_recv_ts_ms or 0)
    fut = int(data.fut_recv_ts_ms or 0)
    return min(spot, fut) if spot > 0 and fut > 0 else 0


class SpreadReader:
    def __init__(self):
        self._cache: dict[str, SpreadData] = {}
        self._last_update_ts: int = 0
        self._redis: Optional[aioredis.Redis] = None
        self._subscriber_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None

    @staticmethod
    def _live_ts(parsed: dict) -> int:
        """Return the oldest local receipt timestamp from a raw snapshot."""
        try:
            spot = int(parsed.get("spot_recv_ts_ms", 0) or 0)
            futures = int(parsed.get("fut_recv_ts_ms", 0) or 0)
            return min(spot, futures) if spot > 0 and futures > 0 else 0
        except (AttributeError, TypeError, ValueError, OverflowError):
            return 0

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await self._load_all()
        self._subscriber_task = asyncio.create_task(self._subscribe_loop())
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def stop(self):
        for task in (self._subscriber_task, self._refresh_task):
            if task:
                task.cancel()
        for task in (self._subscriber_task, self._refresh_task):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def _load_all(self):
        if not self._redis:
            return
        payloads = await self._redis.hgetall("spreads")
        for symbol, raw in payloads.items():
            try:
                parsed = json.loads(raw)
                data = SpreadData(**parsed)
                self._cache[str(symbol).upper()] = data
                self._last_update_ts = max(self._last_update_ts, _latest_receive_ts(data))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    async def _refresh_loop(self):
        while True:
            await asyncio.sleep(FULL_REFRESH_INTERVAL_SEC)
            try:
                await self._load_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def _subscribe_loop(self):
        while True:
            pubsub = None
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe("spread:updates")
                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue
                    symbol = str(msg["data"]).upper()
                    raw = await self._redis.hget("spreads", symbol)
                    if raw:
                        parsed = json.loads(raw)
                        data = SpreadData(**parsed)
                        self._cache[symbol] = data
                        self._last_update_ts = max(self._last_update_ts, _latest_receive_ts(data))
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await self._load_all()
                except Exception:
                    pass
                await asyncio.sleep(1)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass

    def get_all(self) -> list[SpreadData]:
        """Keep stale rows visible; execution paths still fail closed."""
        return list(self._cache.values())

    def get_symbol(self, symbol: str) -> Optional[SpreadData]:
        return self._cache.get(symbol.upper())

    def get_top(self, limit: int = 20) -> list[SpreadData]:
        items = sorted(
            self._cache.values(),
            key=lambda x: max(abs(x.spread_long), abs(x.spread_short)),
            reverse=True,
        )
        return items[:limit]

    def health(self) -> dict:
        now_ms = int(time.time() * 1000)
        age = now_ms - self._last_update_ts if self._last_update_ts > 0 else None
        return {
            "status": "ok" if self._cache and age is not None and age <= DEFAULT_SPREAD_MAX_AGE_MS else "stale",
            "redis_connected": self._redis is not None,
            "active_symbols": len(self._cache),
            "last_update_age_ms": age,
        }


spread_reader = SpreadReader()
