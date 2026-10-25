"""Runtime gate for the notification-centre website maintenance switch.

The admin API stores a compact JSON snapshot at ``notification:maintenance``.
Workers read that snapshot before admission of any new borrow/open/top-up
action.  Exit paths (unhedge, close, repay and debt reconciliation) do not
consult this gate, so maintenance cannot strand an existing position.
"""

from __future__ import annotations

import json
import inspect
import logging
import time
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAINTENANCE_REDIS_KEY = "notification:maintenance"
_DB_FALLBACK_CACHE_TTL_SEC = 10.0
_db_fallback_cache: tuple[float, bool] | None = None


def _active(payload: dict) -> bool:
    if not bool(payload.get("active", payload.get("enabled", False))):
        return False
    until = payload.get("until_at")
    if not until:
        return True
    try:
        parsed = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed >= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        # An invalid expiry is treated as active until an administrator fixes
        # it; malformed maintenance data must not silently reopen trading.
        return True


def maintenance_blocks_new(payload: object) -> bool:
    """Return whether a decoded snapshot blocks admission of new actions.

    The value comes from a safety-critical Redis key.  A missing state field,
    unexpected JSON type, or non-boolean control value is not evidence that
    maintenance is disabled; treating it as normal would reopen borrowing
    after a truncated/corrupt publish.  Legacy snapshots containing only
    ``enabled`` remain supported.
    """
    if not isinstance(payload, dict):
        return True
    state_keys = {"active", "enabled"}
    if not state_keys.intersection(payload):
        return True
    for key in state_keys.intersection(payload):
        if not isinstance(payload.get(key), bool):
            return True
    if not _active(payload):
        return False
    return bool(payload.get("stop_strategy", True) or payload.get("block_trading", True))


def _maintenance_blocks_new_from_db() -> bool:
    """Recover the durable switch when Redis lost its snapshot.

    Redis is the hot-path transport, but a restart/expiry must not silently
    reopen new borrowing while the admin row is still in maintenance mode.
    A short cache prevents a missing key from turning every Worker loop into a
    database query.  Any schema/connection error blocks new actions.
    """
    global _db_fallback_cache
    now = time.monotonic()
    cached = _db_fallback_cache
    if cached is not None and now - cached[0] < _DB_FALLBACK_CACHE_TTL_SEC:
        return cached[1]
    try:
        from app.db.session import SessionLocal
        from app.db.models_notify import NotificationMaintenance

        db = SessionLocal()
        try:
            row = db.query(NotificationMaintenance).filter(
                NotificationMaintenance.id == 1,
            ).first()
            if row is None:
                result = False
            else:
                until = getattr(row, "until_at", None)
                if until is not None:
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=timezone.utc)
                    else:
                        until = until.astimezone(timezone.utc)
                result = maintenance_blocks_new({
                    "active": bool(getattr(row, "enabled", False)) and not (
                        until is not None and until < datetime.now(timezone.utc)
                    ),
                    "stop_strategy": bool(getattr(row, "stop_strategy", True)),
                    "block_trading": bool(getattr(row, "block_trading", True)),
                    "until_at": until.isoformat() if until else None,
                })
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("maintenance DB fallback failed; blocking new actions: %s", exc)
        result = True
    _db_fallback_cache = (now, result)
    return result


def maintenance_blocks_new_sync(redis_client=None) -> bool:
    """Read the gate with a fail-closed policy on Redis errors.

    The final Binance request callback is synchronous while the Worker keeps
    a long-lived ``redis.asyncio`` client.  Callers may therefore omit the
    client and let this helper create a short-timeout synchronous connection.
    Passing an async client is rejected rather than coercing its coroutine to
    a truthy value (which would incorrectly reject every request).
    """
    client = redis_client
    owns_client = client is None
    if client is None:
        try:
            import redis
            from app.config import settings

            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("maintenance gate client unavailable; blocking new actions: %s", exc)
            return True
    try:
        raw = client.get(MAINTENANCE_REDIS_KEY)
        if inspect.isawaitable(raw):
            close = getattr(raw, "close", None)
            if callable(close):
                close()
            raise TypeError("maintenance gate requires a synchronous Redis client")
        if not raw:
            return _maintenance_blocks_new_from_db()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return maintenance_blocks_new(json.loads(raw))
    except Exception as exc:  # noqa: BLE001
        logger.error("maintenance gate read failed; blocking new actions: %s", exc)
        return True
    finally:
        if owns_client and client is not None:
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except Exception:
                logger.debug("maintenance gate sync Redis close failed", exc_info=True)


async def maintenance_blocks_new_async(redis_client) -> bool:
    """Async equivalent used by Worker hot loops."""
    if redis_client is None:
        return False
    try:
        raw = await redis_client.get(MAINTENANCE_REDIS_KEY)
        if not raw:
            # The DB query runs off the event loop because this gate is called
            # from the Worker's hot cycle.  Missing Redis state is rare, but
            # must remain fail-closed with respect to the durable switch.
            return await asyncio.to_thread(_maintenance_blocks_new_from_db)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return maintenance_blocks_new(json.loads(raw))
    except Exception as exc:  # noqa: BLE001
        logger.error("async maintenance gate read failed; blocking new actions: %s", exc)
        return True


__all__ = [
    "MAINTENANCE_REDIS_KEY",
    "maintenance_blocks_new",
    "maintenance_blocks_new_sync",
    "maintenance_blocks_new_async",
]
