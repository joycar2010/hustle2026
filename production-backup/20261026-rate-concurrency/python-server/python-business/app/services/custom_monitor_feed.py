"""Read-only Binance WS feed for tenant-owned asymmetric symbol mappings."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Literal

import redis.asyncio as aioredis
from websockets.asyncio.client import connect as websocket_connect

from app.config import settings
from app.db.models import CustomMonitorSymbol, GlobalRules
from app.db.schemas.spread import SpreadData
from app.db.session import SessionLocal
from app.services.custom_monitor_push import custom_monitor_block_reason
from app.services.pushed_symbols import (
    custom_monitor_candidate_key,
    custom_monitor_source_key,
    is_custom_monitor_candidate,
    mutate_pushed_symbols_async,
)
from engine.thresholds import upward_reached

logger = logging.getLogger(__name__)

SPOT_WS_URL = "wss://stream.binance.com:9443/ws"
FUTURES_WS_URL = "wss://fstream.binance.com/ws"
MAPPING_REFRESH_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 15.0
SNAPSHOT_MAX_AGE_MS = 300_000
CACHE_TTL_SECONDS = 360
SUBSCRIPTION_CHUNK_SIZE = 200
CUSTOM_AUTO_PUSH_INTERVAL_SECONDS = 1.0
DEFAULT_AUTO_PUSH_SPREAD = Decimal("0.8")


def _valid_user_id(user_id: int) -> int:
    value = int(user_id)
    if value <= 0:
        raise ValueError("user_id must be a positive integer")
    return value


def custom_spread_key(user_id: int) -> str:
    return f"custom:spreads:{_valid_user_id(user_id)}"


def custom_spread_channel(user_id: int) -> str:
    return f"custom:spread:updates:{_valid_user_id(user_id)}"


@dataclass(frozen=True, slots=True)
class MonitorMapping:
    monitor_id: int
    user_id: int
    spot_symbol: str
    futures_symbol: str
    display_symbol: str

    @property
    def key(self) -> tuple[int, int]:
        return self.user_id, self.monitor_id


@dataclass(frozen=True, slots=True)
class BookQuote:
    bid: Decimal
    ask: Decimal
    ts: int
    recv_ts_ms: int


def calculate_custom_spread(
    mapping: MonitorMapping,
    spot: BookQuote,
    futures: BookQuote,
) -> SpreadData:
    """Use the same executable bid/ask formula as the Rust spread engine."""

    if min(spot.bid, spot.ask, futures.bid, futures.ask) <= 0:
        raise ValueError("book prices must be positive")
    hundred = Decimal("100")
    return SpreadData(
        symbol=mapping.display_symbol,
        spot_bid=spot.bid,
        spot_ask=spot.ask,
        fut_bid=futures.bid,
        fut_ask=futures.ask,
        spread_long=(futures.bid - spot.ask) / spot.ask * hundred,
        spread_short=(spot.bid - futures.ask) / futures.ask * hundred,
        # A pair is only as fresh as its older leg.
        ts=min(spot.ts, futures.ts),
        spot_recv_ts_ms=spot.recv_ts_ms,
        fut_recv_ts_ms=futures.recv_ts_ms,
        spot_symbol=mapping.spot_symbol,
        futures_symbol=mapping.futures_symbol,
        custom_monitor_id=mapping.monitor_id,
        is_custom=True,
        data_status="LIVE",
        execution_eligible=False,
    )


def parse_book_ticker(raw: str | bytes | dict) -> tuple[str, BookQuote] | None:
    """Parse raw or combined Binance bookTicker messages; ignore control acks."""

    try:
        payload = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
        if not isinstance(payload, dict):
            return None
        data = payload.get("data", payload)
        if not isinstance(data, dict) or not data.get("s"):
            return None
        bid = Decimal(str(data.get("b", "0")))
        ask = Decimal(str(data.get("a", "0")))
        if bid <= 0 or ask <= 0:
            return None
        now_ms = time.time_ns() // 1_000_000
        ts = int(data.get("E") or data.get("T") or now_ms)
        return str(data["s"]).upper(), BookQuote(
            bid=bid,
            ask=ask,
            ts=ts,
            recv_ts_ms=now_ms,
        )
    except (json.JSONDecodeError, InvalidOperation, TypeError, ValueError, KeyError):
        return None


def decode_tenant_update(raw: str | bytes, expected_user_id: int) -> dict | None:
    """Validate tenant metadata before forwarding a Redis event."""

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        if int(payload.pop("user_id")) != _valid_user_id(expected_user_id):
            return None
        monitor_id = int(payload.get("custom_monitor_id"))
        if monitor_id <= 0:
            return None
        payload["custom_monitor_id"] = monitor_id
        payload["is_custom"] = True
        payload["execution_eligible"] = False
        validated = SpreadData.model_validate(payload)
        return validated.model_dump(mode="json")
    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
        return None


def _snapshot_freshness_ts(snapshot: SpreadData) -> int:
    received = [
        int(value)
        for value in (snapshot.spot_recv_ts_ms, snapshot.fut_recv_ts_ms)
        if int(value or 0) > 0
    ]
    return min(received) if received else int(snapshot.ts)


def custom_snapshot_is_fresh(
    snapshot: SpreadData | None,
    *,
    now_ms: int | None = None,
) -> bool:
    """Apply the same bounded local-receive freshness fence as the feed."""
    if snapshot is None:
        return False
    try:
        now = time.time_ns() // 1_000_000 if now_ms is None else int(now_ms)
        received = _snapshot_freshness_ts(snapshot)
        age = now - int(received)
        return received > 0 and age >= -60_000 and age <= SNAPSHOT_MAX_AGE_MS
    except (TypeError, ValueError, OverflowError):
        return False


async def load_user_snapshots(redis_client, user_id: int | None) -> dict[int, SpreadData]:
    """Load validated, tenant-scoped custom snapshots from Redis.

    The Worker runs in a separate process from ``CustomMonitorFeed``.  Reading
    this short-lived hash gives auto-push the same source data without joining
    the public execution feed or asking Binance for any private state.
    """
    if redis_client is None or user_id is None:
        return {}
    try:
        uid = _valid_user_id(user_id)
        stored = await redis_client.hgetall(custom_spread_key(uid))
    except Exception:
        return {}
    snapshots: dict[int, SpreadData] = {}
    for field, raw in (stored or {}).items():
        try:
            monitor_id = int(field)
        except (TypeError, ValueError):
            continue
        decoded = decode_tenant_update(raw, uid)
        if decoded is None:
            continue
        try:
            snapshot = SpreadData.model_validate(decoded)
        except (TypeError, ValueError):
            continue
        if (
            snapshot.custom_monitor_id != monitor_id
            or not snapshot.is_custom
            or snapshot.execution_eligible is not False
            or not custom_snapshot_is_fresh(snapshot)
        ):
            continue
        snapshots[monitor_id] = snapshot
    return snapshots


def _load_active_mappings() -> list[MonitorMapping]:
    db = SessionLocal()
    try:
        rows = db.query(CustomMonitorSymbol).filter(
            CustomMonitorSymbol.is_active.is_(True),
            CustomMonitorSymbol.is_removed.is_(False),
        ).all()
        return [
            MonitorMapping(
                monitor_id=int(row.id),
                user_id=_valid_user_id(row.user_id),
                spot_symbol=str(row.spot_symbol).upper(),
                futures_symbol=str(row.futures_symbol).upper(),
                display_symbol=str(
                    row.display_symbol
                    or str(row.spot_symbol).upper().removesuffix("USDT")
                ).upper(),
            )
            for row in rows
        ]
    finally:
        db.close()


def _load_custom_auto_push_state(
    user_ids: set[int],
) -> dict[int, tuple[Decimal, frozenset[int]]]:
    """Load tenant thresholds and safe custom-monitor ids for auto-push.

    This is deliberately independent of ``SubAccount``/Worker state.  The
    public custom-monitor feed is also the source of the dashboard's
    candidate rows, so a user with no enabled workers must still receive a
    qualifying candidate.  The DB read is kept in a short-lived thread-safe
    session and applies the same blacklist/delisting gates as the Worker.
    """
    normalized_ids = {int(value) for value in user_ids if int(value) > 0}
    if not normalized_ids:
        return {}

    db = SessionLocal()
    try:
        rows = db.query(CustomMonitorSymbol).filter(
            CustomMonitorSymbol.user_id.in_(normalized_ids),
            CustomMonitorSymbol.is_active.is_(True),
            CustomMonitorSymbol.is_removed.is_(False),
        ).all()
        rules = {
            int(row.user_id): row
            for row in db.query(GlobalRules).filter(
                GlobalRules.user_id.in_(normalized_ids)
            ).all()
            if row.user_id is not None
        }
        result: dict[int, tuple[Decimal, frozenset[int]]] = {}
        allowed_by_user: dict[int, set[int]] = {}
        for row in rows:
            user_id = int(row.user_id)
            # A blocked mapping remains visible in the custom monitor tab,
            # but must never be inserted into the executable opportunity list.
            if custom_monitor_block_reason(db, user_id, row):
                continue
            allowed_by_user.setdefault(user_id, set()).add(int(row.id))

        for user_id, monitor_ids in allowed_by_user.items():
            row = rules.get(user_id)
            raw_threshold = getattr(row, "auto_push_spread", None)
            try:
                threshold = Decimal(
                    str(
                        DEFAULT_AUTO_PUSH_SPREAD
                        if raw_threshold is None
                        else raw_threshold
                    )
                )
            except (TypeError, ValueError, ArithmeticError):
                threshold = DEFAULT_AUTO_PUSH_SPREAD
            if not threshold.is_finite() or threshold <= 0:
                # Worker._update_state uses the same disabled-when-nonpositive
                # contract for automatic discovery.
                continue
            result[user_id] = (threshold, frozenset(monitor_ids))
        return result
    except Exception:
        # A transient control-plane/database outage must not stop the public
        # WS feed or cause a tight retry/log loop.  Worker discovery remains
        # the compatibility fallback once its own DB snapshot recovers.
        logger.warning(
            "Unable to load custom-monitor auto-push state",
            exc_info=True,
        )
        return {}
    finally:
        db.close()


class CustomMonitorFeed:
    """Maintain targeted public WS subscriptions outside execution data."""

    def __init__(
        self,
        mapping_loader: Callable[[], list[MonitorMapping]] | None = None,
        redis_factory: Callable[..., object] | None = None,
        connect_factory: Callable[..., object] | None = None,
        refresh_seconds: float = MAPPING_REFRESH_SECONDS,
        reconnect_initial_seconds: float = 1.0,
        auto_push_interval_seconds: float = CUSTOM_AUTO_PUSH_INTERVAL_SECONDS,
    ):
        self._mapping_loader = mapping_loader or _load_active_mappings
        self._redis_factory = redis_factory or aioredis.from_url
        self._connect_factory = connect_factory or websocket_connect
        self._refresh_seconds = refresh_seconds
        self._reconnect_initial_seconds = reconnect_initial_seconds
        self._auto_push_interval_seconds = max(
            0.1, float(auto_push_interval_seconds)
        )
        self._redis = None
        self._running = False
        self._tasks: set[asyncio.Task] = set()
        self._mappings: dict[tuple[int, int], MonitorMapping] = {}
        self._by_spot: dict[str, set[tuple[int, int]]] = {}
        self._by_futures: dict[str, set[tuple[int, int]]] = {}
        self._desired_spot: set[str] = set()
        self._desired_futures: set[str] = set()
        self._spot_quotes: dict[str, BookQuote] = {}
        self._futures_quotes: dict[str, BookQuote] = {}
        self._snapshots: dict[tuple[int, int], SpreadData] = {}
        self._snapshot_lock = threading.Lock()
        self._publish_lock = asyncio.Lock()
        self._request_id = 0
        self._last_redis_warning = 0.0

    async def start(self) -> None:
        if self._running:
            return
        self._redis = self._redis_factory(settings.redis_url, decode_responses=True)
        self._running = True
        try:
            await self._refresh_mappings()
        except Exception as exc:
            logger.warning("Custom monitor initial mapping load failed: %s", exc)
        self._tasks = {
            asyncio.create_task(self._mapping_loop(), name="custom-monitor-config"),
            asyncio.create_task(self._stream_loop("spot"), name="custom-monitor-spot-ws"),
            asyncio.create_task(self._stream_loop("futures"), name="custom-monitor-futures-ws"),
            asyncio.create_task(
                self._custom_auto_push_loop(),
                name="custom-monitor-auto-push",
            ),
        }
        logger.info("CustomMonitorFeed started with %d mapping(s)", len(self._mappings))

    async def stop(self) -> None:
        self._running = False
        tasks, self._tasks = self._tasks, set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._redis is not None:
            try:
                close_result = self._redis.aclose()
                if inspect.isawaitable(close_result):
                    await close_result
            except Exception as exc:
                logger.warning("Custom monitor Redis close failed: %s", exc)
            self._redis = None
        logger.info("CustomMonitorFeed stopped")

    def get_user_snapshots(self, user_id: int | None) -> dict[int, SpreadData]:
        if user_id is None:
            return {}
        try:
            uid = _valid_user_id(user_id)
        except (TypeError, ValueError):
            return {}
        now_ms = time.time_ns() // 1_000_000
        with self._snapshot_lock:
            return {
                monitor_id: snapshot
                for (owner_id, monitor_id), snapshot in self._snapshots.items()
                if owner_id == uid
                and now_ms - _snapshot_freshness_ts(snapshot) <= SNAPSHOT_MAX_AGE_MS
            }

    def get_snapshot(self, user_id: int | None, monitor_id: int) -> SpreadData | None:
        try:
            key = (_valid_user_id(user_id), int(monitor_id))
        except (TypeError, ValueError):
            return None
        now_ms = time.time_ns() // 1_000_000
        with self._snapshot_lock:
            snapshot = self._snapshots.get(key)
            if (
                snapshot is None
                or now_ms - _snapshot_freshness_ts(snapshot) > SNAPSHOT_MAX_AGE_MS
            ):
                return None
            return snapshot

    async def _mapping_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._refresh_seconds)
                await self._refresh_mappings()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Custom monitor mapping refresh failed: %s", exc)

    async def _custom_auto_push_loop(self) -> None:
        """Mirror qualifying custom snapshots without requiring a Worker.

        Custom mappings are display-only and never enter an exchange command
        queue.  Keeping this loop beside the public WS feed means an idle or
        intentionally stopped tenant Worker cannot make the dashboard's
        custom candidate list silently stop updating.  Worker-side discovery
        remains as a rolling-upgrade fallback; Redis membership mutation is
        atomic and therefore idempotent across both paths.
        """
        while self._running:
            try:
                await self._auto_push_custom_snapshots_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Custom monitor auto-push evaluation failed",
                    exc_info=True,
                )
            try:
                await asyncio.sleep(self._auto_push_interval_seconds)
            except asyncio.CancelledError:
                raise

    def _live_custom_snapshots(self) -> dict[int, dict[int, SpreadData]]:
        """Copy current tenant snapshots while holding the feed lock."""
        now_ms = time.time_ns() // 1_000_000
        grouped: dict[int, dict[int, SpreadData]] = {}
        with self._snapshot_lock:
            for (user_id, monitor_id), snapshot in self._snapshots.items():
                mapping = self._mappings.get((user_id, monitor_id))
                if mapping is None or not custom_snapshot_is_fresh(
                    snapshot, now_ms=now_ms
                ):
                    continue
                if (
                    snapshot.custom_monitor_id != monitor_id
                    or snapshot.spot_symbol != mapping.spot_symbol
                    or snapshot.futures_symbol != mapping.futures_symbol
                    or str(snapshot.data_status or "").upper() != "LIVE"
                ):
                    continue
                grouped.setdefault(user_id, {})[monitor_id] = snapshot
        return grouped

    async def _auto_push_custom_snapshots_once(self) -> None:
        """Add fresh threshold-matching custom candidates to each user list."""
        if self._redis is None:
            return
        grouped = self._live_custom_snapshots()
        if not grouped:
            return
        state = await asyncio.to_thread(
            _load_custom_auto_push_state,
            set(grouped),
        )
        for user_id, snapshots in grouped.items():
            rule = state.get(user_id)
            if rule is None:
                continue
            threshold, allowed_ids = rule
            candidates: set[str] = set()
            for monitor_id, snapshot in snapshots.items():
                if monitor_id not in allowed_ids:
                    continue
                if upward_reached(snapshot.spread_short, threshold):
                    candidates.add(custom_monitor_candidate_key(monitor_id))
            if not candidates:
                continue

            key = f"engine:{int(user_id)}:pushed_symbols"
            current, changed = await mutate_pushed_symbols_async(
                self._redis,
                key,
                add={
                    candidate
                    for candidate in candidates
                    if is_custom_monitor_candidate(candidate)
                },
            )
            if not changed:
                continue
            try:
                source_key = custom_monitor_source_key(user_id)
                await self._redis.hset(
                    source_key,
                    mapping={
                        candidate: str(
                            int(candidate.split(":", 1)[1])
                        )
                        for candidate in candidates
                    },
                )
            except Exception:
                # Source metadata is advisory; list membership is already
                # atomically committed and remains tenant-scoped.
                logger.warning(
                    "Unable to persist custom monitor source metadata for user %s",
                    user_id,
                    exc_info=True,
                )
            try:
                await self._redis.publish(
                    "pushed:updates",
                    json.dumps(
                        {
                            "user_id": int(user_id),
                            "pushed_symbols": current,
                            "source": "custom_monitor",
                        }
                    ),
                )
            except Exception:
                logger.warning(
                    "Unable to publish custom monitor push update for user %s",
                    user_id,
                    exc_info=True,
                )

    async def _refresh_mappings(self) -> None:
        rows = await asyncio.to_thread(self._mapping_loader)
        fresh = {row.key: row for row in rows}
        async with self._publish_lock:
            await self._apply_mappings(fresh)

    async def _apply_mappings(
        self,
        fresh: dict[tuple[int, int], MonitorMapping],
    ) -> None:
        old = self._mappings
        changed_or_removed = {
            key for key, value in old.items() if key not in fresh or fresh[key] != value
        }
        now_ms = time.time_ns() // 1_000_000
        with self._snapshot_lock:
            expired = {
                key for key, snapshot in self._snapshots.items()
                if now_ms - _snapshot_freshness_ts(snapshot) > SNAPSHOT_MAX_AGE_MS
            }

        self._mappings = fresh
        self._rebuild_indexes()
        with self._snapshot_lock:
            for key in changed_or_removed | expired:
                self._snapshots.pop(key, None)

        if self._redis is None:
            return
        for user_id, monitor_id in changed_or_removed:
            await self._redis.hdel(custom_spread_key(user_id), str(monitor_id))

        await self._hydrate_from_redis(fresh)

        added_or_changed = {
            key for key, value in fresh.items() if key not in old or old[key] != value
        }
        for key in added_or_changed:
            mapping = fresh[key]
            if (
                mapping.spot_symbol in self._spot_quotes
                and mapping.futures_symbol in self._futures_quotes
            ):
                await self._publish_current(mapping)

    def _rebuild_indexes(self) -> None:
        by_spot: dict[str, set[tuple[int, int]]] = {}
        by_futures: dict[str, set[tuple[int, int]]] = {}
        for key, mapping in self._mappings.items():
            by_spot.setdefault(mapping.spot_symbol, set()).add(key)
            by_futures.setdefault(mapping.futures_symbol, set()).add(key)
        self._by_spot = by_spot
        self._by_futures = by_futures
        self._desired_spot = set(by_spot)
        self._desired_futures = set(by_futures)
        self._spot_quotes = {
            symbol: quote for symbol, quote in self._spot_quotes.items()
            if symbol in self._desired_spot
        }
        self._futures_quotes = {
            symbol: quote for symbol, quote in self._futures_quotes.items()
            if symbol in self._desired_futures
        }

    async def _hydrate_from_redis(
        self,
        mappings: dict[tuple[int, int], MonitorMapping],
    ) -> None:
        if self._redis is None:
            return
        by_user: dict[int, dict[int, MonitorMapping]] = {}
        for mapping in mappings.values():
            by_user.setdefault(mapping.user_id, {})[mapping.monitor_id] = mapping
        hydrated: dict[tuple[int, int], SpreadData] = {}
        now_ms = time.time_ns() // 1_000_000
        for user_id, user_mappings in by_user.items():
            stored = await self._redis.hgetall(custom_spread_key(user_id))
            for field, raw in stored.items():
                try:
                    monitor_id = int(field)
                except (TypeError, ValueError):
                    continue
                mapping = user_mappings.get(monitor_id)
                decoded = decode_tenant_update(raw, user_id)
                if mapping is None or decoded is None:
                    continue
                snapshot = SpreadData.model_validate(decoded)
                if (
                    decoded.get("spot_symbol") != mapping.spot_symbol
                    or decoded.get("futures_symbol") != mapping.futures_symbol
                    or now_ms - _snapshot_freshness_ts(snapshot) > SNAPSHOT_MAX_AGE_MS
                ):
                    continue
                hydrated[(user_id, monitor_id)] = snapshot
        if hydrated:
            with self._snapshot_lock:
                self._snapshots.update(hydrated)

    async def _stream_loop(self, market: Literal["spot", "futures"]) -> None:
        url = SPOT_WS_URL if market == "spot" else FUTURES_WS_URL
        backoff = self._reconnect_initial_seconds
        while self._running:
            desired = self._desired_spot if market == "spot" else self._desired_futures
            if not desired:
                await asyncio.sleep(0.5)
                continue
            try:
                async with self._connect_factory(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=1024,
                ) as socket:
                    subscribed: set[str] = set()
                    backoff = self._reconnect_initial_seconds
                    logger.info("Custom monitor %s WS connected", market)
                    while self._running:
                        desired = set(
                            self._desired_spot
                            if market == "spot"
                            else self._desired_futures
                        )
                        if not desired:
                            break
                        await self._sync_subscriptions(socket, subscribed, desired)
                        subscribed = desired
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=1.0)
                        except TimeoutError:
                            continue
                        parsed = parse_book_ticker(raw)
                        if parsed is None:
                            continue
                        symbol, quote = parsed
                        if symbol in desired:
                            await self._handle_quote(market, symbol, quote)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._running:
                    logger.warning("Custom monitor %s WS error: %s", market, exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, RECONNECT_MAX_SECONDS)

    async def _sync_subscriptions(self, socket, subscribed: set[str], desired: set[str]) -> None:
        await self._send_subscription(socket, "SUBSCRIBE", desired - subscribed)
        await self._send_subscription(socket, "UNSUBSCRIBE", subscribed - desired)

    async def _send_subscription(self, socket, method: str, symbols: set[str]) -> None:
        ordered = sorted(symbols)
        for offset in range(0, len(ordered), SUBSCRIPTION_CHUNK_SIZE):
            chunk = ordered[offset:offset + SUBSCRIPTION_CHUNK_SIZE]
            self._request_id += 1
            await socket.send(json.dumps({
                "method": method,
                "params": [f"{symbol.lower()}@bookTicker" for symbol in chunk],
                "id": self._request_id,
            }))
            if offset + SUBSCRIPTION_CHUNK_SIZE < len(ordered):
                await asyncio.sleep(0.25)

    async def _handle_quote(
        self,
        market: Literal["spot", "futures"],
        symbol: str,
        quote: BookQuote,
    ) -> None:
        if market == "spot":
            self._spot_quotes[symbol] = quote
            affected = set(self._by_spot.get(symbol, set()))
        else:
            self._futures_quotes[symbol] = quote
            affected = set(self._by_futures.get(symbol, set()))
        async with self._publish_lock:
            for key in affected:
                mapping = self._mappings.get(key)
                if mapping is not None:
                    await self._publish_current(mapping)

    async def _publish_current(self, mapping: MonitorMapping) -> None:
        spot = self._spot_quotes.get(mapping.spot_symbol)
        futures = self._futures_quotes.get(mapping.futures_symbol)
        if spot is None or futures is None:
            return
        now_ms = time.time_ns() // 1_000_000
        if now_ms - min(spot.recv_ts_ms, futures.recv_ts_ms) > SNAPSHOT_MAX_AGE_MS:
            return
        snapshot = calculate_custom_spread(mapping, spot, futures)
        with self._snapshot_lock:
            self._snapshots[mapping.key] = snapshot

        payload = snapshot.model_dump(mode="json")
        payload["user_id"] = mapping.user_id
        raw = json.dumps(payload, separators=(",", ":"))
        if self._redis is None:
            return
        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.hset(custom_spread_key(mapping.user_id), str(mapping.monitor_id), raw)
            pipe.expire(custom_spread_key(mapping.user_id), CACHE_TTL_SECONDS)
            pipe.publish(custom_spread_channel(mapping.user_id), raw)
            await pipe.execute()
        except Exception as exc:
            now = time.monotonic()
            if now - self._last_redis_warning >= 10:
                self._last_redis_warning = now
                logger.warning("Custom monitor Redis publish failed: %s", exc)


custom_monitor_feed = CustomMonitorFeed()
