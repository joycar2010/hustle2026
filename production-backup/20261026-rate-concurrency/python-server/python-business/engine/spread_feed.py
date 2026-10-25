import asyncio
import json
import logging
import time
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from engine.freshness import configured_spread_max_age_ms

logger = logging.getLogger(__name__)

# Pub/Sub is an edge-triggered transport. A reconnect can legitimately miss a
# quiet symbol's one update, so the Redis hash is periodically re-read as the
# authoritative snapshot.
FULL_REFRESH_INTERVAL_SEC = 2

# The Rust publisher and every Python consumer use this same local-receive
# freshness fence.  Resolve it once when the process starts, like other
# service configuration; changing it requires the service restart that also
# reloads the Rust environment.
DEFAULT_SPREAD_MAX_AGE_MS = configured_spread_max_age_ms()


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
    # Rust WS local receive times. Legacy snapshots have zero values and are
    # intentionally rejected by the trading freshness gate.
    spot_recv_ts_ms: int = 0
    fut_recv_ts_ms: int = 0


def is_spread_fresh(snapshot: SpreadSnapshot | None, *, now_ms: int | None = None,
                    max_age_ms: int = DEFAULT_SPREAD_MAX_AGE_MS) -> bool:
    """Require both legs to have been received locally within the live window.

    ``ts`` is Binance's event time and is intentionally not used as a liveness
    signal. Snapshots written before the receive-time fields existed fail
    closed until the Rust publisher replaces them.
    """
    if snapshot is None:
        return False
    try:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        limit = max(1, int(max_age_ms))
        for received in (int(snapshot.spot_recv_ts_ms or 0), int(snapshot.fut_recv_ts_ms or 0)):
            age = now - received
            if received <= 0 or age < -60_000 or age > limit:
                return False
        return True
    except (TypeError, ValueError, OverflowError):
        return False


class SpreadFeed:
    def __init__(self):
        self._cache: dict[str, SpreadSnapshot] = {}
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._subscriber_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None

    async def start(self):
        self._running = True
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await self._load_all()
        self._subscriber_task = asyncio.create_task(self._subscribe_loop())
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info(f"SpreadFeed started: {len(self._cache)} symbols loaded")

    async def stop(self):
        self._running = False
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

    async def _load_all(self):
        if not self._redis:
            return
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
                    ts=int(parsed.get("ts", 0) or 0),
                    spot_recv_ts_ms=int(parsed.get("spot_recv_ts_ms", 0) or 0),
                    fut_recv_ts_ms=int(parsed.get("fut_recv_ts_ms", 0) or 0),
                )
            except Exception:
                continue

    async def _refresh_loop(self):
        while self._running:
            await asyncio.sleep(FULL_REFRESH_INTERVAL_SEC)
            try:
                await self._load_all()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"SpreadFeed snapshot refresh failed: {e}")

    async def _subscribe_loop(self):
        while self._running:
            pubsub = None
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
                            ts=int(parsed.get("ts", 0) or 0),
                            spot_recv_ts_ms=int(parsed.get("spot_recv_ts_ms", 0) or 0),
                            fut_recv_ts_ms=int(parsed.get("fut_recv_ts_ms", 0) or 0),
                        )
            except Exception as e:
                if self._running:
                    logger.warning(f"SpreadFeed subscribe error: {e}")
                    # Do not wait for the next ticker event to repair a quiet
                    # symbol.  The previous implementation re-subscribed with
                    # its old in-memory cache, leaving ONTUSDT stale forever
                    # after a Redis connection reset.
                    try:
                        await self._load_all()
                    except Exception as refresh_error:
                        logger.warning(f"SpreadFeed reconnect refresh failed: {refresh_error}")
                    await asyncio.sleep(1)
            finally:
                # Pub/Sub owns a dedicated Redis connection.  Explicitly
                # close it on reconnect and cancellation so a flapping feed
                # cannot accumulate one connection per retry.
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass

    def get_symbol(self, symbol: str) -> Optional[SpreadSnapshot]:
        return self._cache.get(symbol.upper())

    def get_all(self) -> dict[str, SpreadSnapshot]:
        return self._cache

    @property
    def count(self) -> int:
        return len(self._cache)
