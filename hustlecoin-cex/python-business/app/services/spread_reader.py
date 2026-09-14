import asyncio
import json
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.db.schemas import SpreadData


class SpreadReader:
    def __init__(self):
        self._cache: dict[str, SpreadData] = {}
        self._last_update_ts: int = 0
        self._redis: Optional[aioredis.Redis] = None

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await self._load_all()
        asyncio.create_task(self._subscribe_loop())

    async def _load_all(self):
        data = await self._redis.hgetall("spreads")
        for symbol, raw in data.items():
            try:
                parsed = json.loads(raw)
                self._cache[symbol] = SpreadData(**parsed)
                self._last_update_ts = max(self._last_update_ts, parsed.get("ts", 0))
            except (json.JSONDecodeError, Exception):
                continue

    async def _subscribe_loop(self):
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe("spread:updates")
                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue
                    symbol = msg["data"]
                    raw = await self._redis.hget("spreads", symbol)
                    if raw:
                        parsed = json.loads(raw)
                        self._cache[symbol] = SpreadData(**parsed)
                        self._last_update_ts = parsed.get("ts", 0)
            except Exception:
                await asyncio.sleep(1)

    def get_all(self) -> list[SpreadData]:
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
            "status": "ok" if age is not None and age < 5000 else "stale",
            "redis_connected": self._redis is not None,
            "active_symbols": len(self._cache),
            "last_update_age_ms": age,
        }


spread_reader = SpreadReader()
