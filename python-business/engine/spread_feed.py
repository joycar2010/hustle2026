import asyncio
import json
import logging
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SpreadSnapshot:
    symbol: str
    spot_bid: Decimal
    spot_ask: Decimal
    fut_bid: Decimal
    fut_ask: Decimal
    spread_long: Decimal
    spread_short: Decimal
    ts: int


class SpreadFeed:
    def __init__(self):
        self._cache: dict[str, SpreadSnapshot] = {}
        self._redis: Optional[aioredis.Redis] = None
        self._running = False

    async def start(self):
        self._running = True
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await self._load_all()
        asyncio.create_task(self._subscribe_loop())
        logger.info(f"SpreadFeed started: {len(self._cache)} symbols loaded")

    async def stop(self):
        self._running = False
        if self._redis:
            await self._redis.aclose()

    async def _load_all(self):
        data = await self._redis.hgetall("spreads")
        for symbol, raw in data.items():
            try:
                parsed = json.loads(raw)
                self._cache[symbol] = SpreadSnapshot(
                    symbol=parsed["symbol"],
                    spot_bid=Decimal(str(parsed["spot_bid"])),
                    spot_ask=Decimal(str(parsed["spot_ask"])),
                    fut_bid=Decimal(str(parsed["fut_bid"])),
                    fut_ask=Decimal(str(parsed["fut_ask"])),
                    spread_long=Decimal(str(parsed["spread_long"])),
                    spread_short=Decimal(str(parsed["spread_short"])),
                    ts=parsed["ts"],
                )
            except Exception:
                continue

    async def _subscribe_loop(self):
        while self._running:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe("spread:updates")
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg["type"] != "message":
                        continue
                    symbol = msg["data"]
                    raw = await self._redis.hget("spreads", symbol)
                    if raw:
                        parsed = json.loads(raw)
                        self._cache[symbol] = SpreadSnapshot(
                            symbol=parsed["symbol"],
                            spot_bid=Decimal(str(parsed["spot_bid"])),
                            spot_ask=Decimal(str(parsed["spot_ask"])),
                            fut_bid=Decimal(str(parsed["fut_bid"])),
                            fut_ask=Decimal(str(parsed["fut_ask"])),
                            spread_long=Decimal(str(parsed["spread_long"])),
                            spread_short=Decimal(str(parsed["spread_short"])),
                            ts=parsed["ts"],
                        )
            except Exception as e:
                if self._running:
                    logger.warning(f"SpreadFeed subscribe error: {e}")
                    await asyncio.sleep(1)

    def get_symbol(self, symbol: str) -> Optional[SpreadSnapshot]:
        return self._cache.get(symbol.upper())

    def get_all(self) -> dict[str, SpreadSnapshot]:
        return self._cache

    @property
    def count(self) -> int:
        return len(self._cache)
