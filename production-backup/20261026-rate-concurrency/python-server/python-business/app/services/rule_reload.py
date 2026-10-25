import logging
from collections.abc import Iterable

from app.config import settings
from engine.trading.borrow_coordination import (
    borrow_failure_key,
    legacy_borrow_failure_key,
)


logger = logging.getLogger(__name__)


def clear_account_borrow_failure(
    client,
    *,
    user_id: int,
    sub_account_id: int,
    symbol: str,
    owned_account_ids: Iterable[int],
) -> None:
    """Re-arm one account without dropping a legacy user-wide cooldown.

    During a rolling upgrade, a live cooldown may still use the old
    ``engine:{user}:borrowfail:{symbol}`` key. Before deleting that ambiguous
    key, copy its value and remaining TTL to every owned sibling account. The
    selected account can then be cleared precisely without making sibling
    workers forget a still-active failure.
    """
    target_id = int(sub_account_id)
    legacy_key = legacy_borrow_failure_key(user_id, symbol)
    legacy_value = client.get(legacy_key)
    if legacy_value is not None:
        ttl = int(client.ttl(legacy_key))
        if ttl != -2:
            sibling_ids = {
                int(account_id)
                for account_id in owned_account_ids
                if int(account_id) != target_id
            }
            for account_id in sibling_ids:
                key = borrow_failure_key(user_id, account_id, symbol)
                current_value = client.get(key)
                if current_value is None:
                    if ttl > 0:
                        client.set(key, legacy_value, ex=ttl)
                    elif ttl == -1:
                        client.set(key, legacy_value)
                    continue

                current_ttl = int(client.ttl(key))
                if ttl == -1 and current_ttl != -1:
                    client.persist(key)
                elif (
                    ttl > 0
                    and current_ttl != -1
                    and current_ttl < ttl
                ):
                    client.expire(key, ttl)
            # Delete only after every sibling copy succeeds. An exception
            # leaves the legacy key in place, which fails closed.
            client.delete(legacy_key)

    client.delete(borrow_failure_key(user_id, target_id, symbol))


def clear_user_borrow_failures(
    client,
    *,
    user_id: int,
    symbol: str,
    owned_account_ids: Iterable[int],
) -> None:
    """Re-arm one user-symbol rule across only that user's accounts."""
    keys = [legacy_borrow_failure_key(user_id, symbol)]
    keys.extend(
        borrow_failure_key(user_id, int(account_id), symbol)
        for account_id in set(owned_account_ids)
    )
    client.delete(*keys)


def publish_rules_reload(user_id: int, reason: str = "rules-updated") -> bool:
    """Notify only the owning user's workers after a committed rule change."""
    client = None
    try:
        import redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.publish(f"rules:reload:{int(user_id)}", reason)
        return True
    except Exception:
        # The worker's periodic DB reload remains the fallback. A Redis outage
        # must not turn an already committed settings update into an API error.
        logger.warning("Unable to publish rules reload for user %s", user_id, exc_info=True)
        return False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
