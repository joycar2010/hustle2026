"""Tenant-scoped admission gate for new borrow and top-up actions."""

from __future__ import annotations

import logging
import inspect

from app.config import settings

logger = logging.getLogger(__name__)


def paused_symbols_key(user_id: int) -> str:
    return f"engine:{int(user_id)}:paused_symbols"


def is_symbol_paused_sync(
    user_id: int | None,
    symbol: str,
    redis_client=None,
) -> bool:
    """Return whether admission is paused; an unknown gate fails closed."""
    if user_id is None:
        logger.error("pause gate unavailable: missing user id")
        return True
    client = redis_client
    owns_client = client is None
    try:
        if client is None:
            import redis

            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        result = client.sismember(
            paused_symbols_key(user_id),
            str(symbol or "").strip().upper(),
        )
        # A redis.asyncio client is a programming error at this synchronous
        # boundary.  Never coerce its coroutine to ``True``; fail closed and
        # close the coroutine to avoid an unawaited-coroutine warning.
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TypeError("pause gate requires a synchronous Redis client")
        return bool(result)
    except Exception as exc:
        logger.error(
            "pause gate read failed for user %s/symbol %s: %s",
            user_id,
            symbol,
            exc,
        )
        return True
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:
                pass


def load_paused_symbols_sync(
    user_id: int | None,
    redis_client=None,
) -> set[str] | None:
    """Return the tenant pause set, or ``None`` when it cannot be read."""
    if user_id is None:
        logger.error("pause gate unavailable: missing user id")
        return None
    client = redis_client
    owns_client = client is None
    try:
        if client is None:
            import redis

            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        values = client.smembers(paused_symbols_key(user_id)) or set()
        return {
            str(value).strip().upper()
            for value in values
            if str(value).strip()
        }
    except Exception as exc:
        logger.error("pause set read failed for user %s: %s", user_id, exc)
        return None
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:
                pass


async def is_symbol_paused_async(
    user_id: int | None,
    symbol: str,
    redis_client,
) -> bool:
    """Async equivalent for Worker checks immediately before admission."""
    if user_id is None or redis_client is None:
        logger.error("pause gate unavailable: missing user id or Redis client")
        return True
    try:
        return bool(
            await redis_client.sismember(
                paused_symbols_key(user_id),
                str(symbol or "").strip().upper(),
            )
        )
    except Exception as exc:
        logger.error(
            "async pause gate read failed for user %s/symbol %s: %s",
            user_id,
            symbol,
            exc,
        )
        return True


__all__ = [
    "is_symbol_paused_async",
    "is_symbol_paused_sync",
    "load_paused_symbols_sync",
    "paused_symbols_key",
]
