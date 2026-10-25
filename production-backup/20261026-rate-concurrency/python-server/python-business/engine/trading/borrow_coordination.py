"""Redis helpers used by the borrow coordination guards.

The no-inventory marker is intentionally kept at sub-account scope for the
balance read model.  The shorter coordination marker is scoped to the
application user so sibling workers cannot all retry the same Binance
``-3045`` condition.  Accounts without a resolved user id fall back to their
own scope; they must never share a marker with another account.
"""

import inspect
import re
import logging
import time
from contextlib import asynccontextmanager


logger = logging.getLogger(__name__)


ACCOUNT_OPERATION_LOCK_TTL_SEC = 180


class AccountOperationLockError(RuntimeError):
    """Base error for account/asset lifecycle lock failures."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


class AccountOperationLockBusy(AccountOperationLockError):
    """Another process currently owns the account/asset lifecycle."""


class AccountOperationLockUnavailable(AccountOperationLockError):
    """Redis could not safely coordinate the account/asset lifecycle."""


def normalize_asset(symbol: object) -> str:
    """Return a canonical base asset for a USDT pair."""
    raw = re.sub(r"[-_\s]+", "", str(symbol or "").strip().upper())
    return raw[:-4] if raw.endswith("USDT") else raw


def no_inventory_key(sub_account_id: int, symbol: object) -> str:
    """Return the account-scoped marker used by balance/UI reporting."""
    return f"engine:noinv:{int(sub_account_id)}:{normalize_asset(symbol)}USDT"


def borrow_capacity_key(
    user_id: int | None,
    sub_account_id: int,
    symbol: object,
) -> str:
    """Return the account-capacity marker, distinct from pool inventory."""
    tenant = (
        str(int(user_id))
        if user_id is not None
        else f"account-{int(sub_account_id)}"
    )
    return (
        f"engine:borrowcapacity:{tenant}:{int(sub_account_id)}:"
        f"{normalize_asset(symbol)}USDT"
    )


def borrow_failure_key(
    user_id: int | None,
    sub_account_id: int,
    symbol: object,
) -> str:
    """Return the account-scoped cooldown for a confirmed borrow failure."""
    tenant = str(int(user_id)) if user_id is not None else "None"
    return (
        f"engine:borrowfail:{tenant}:{int(sub_account_id)}:"
        f"{normalize_asset(symbol)}USDT"
    )


def legacy_borrow_failure_key(user_id: int | None, symbol: object) -> str:
    """Return the pre-account-scope key retained for rolling-upgrade reads."""
    tenant = str(int(user_id)) if user_id is not None else "None"
    return f"engine:{tenant}:borrowfail:{normalize_asset(symbol)}USDT"


def borrow_failure_read_keys(
    user_id: int | None,
    sub_account_id: int,
    symbol: object,
) -> tuple[str, str]:
    """Return the current key followed by its legacy compatibility key."""
    return (
        borrow_failure_key(user_id, sub_account_id, symbol),
        legacy_borrow_failure_key(user_id, symbol),
    )


def borrow_coordination_key(
    user_id: int | None,
    sub_account_id: int,
    symbol: object,
) -> str:
    """Return the short-lived retry-suppression marker.

    A known user gets one marker for all of its sub-accounts.  A missing user
    id falls back to an account marker rather than using a shared sentinel,
    which preserves tenant isolation while still preventing duplicate retries
    if a worker is restarted for the same account.
    """
    scope = f"{int(user_id)}" if user_id is not None else f"account:{int(sub_account_id)}"
    return f"engine:borrowcool:{scope}:{normalize_asset(symbol)}USDT"


def borrow_lock_key(user_id: int | None, sub_account_id: int, symbol: object) -> str:
    """Coordinate one account's borrow transition for an asset.

    Borrow admission is account scoped so independent sub-accounts can submit
    the same symbol concurrently.  The database active-position uniqueness
    constraint remains the final arbiter for duplicate attempts within one
    account/symbol; this key must never serialize sibling accounts through the
    tenant id alone.
    """
    return (
        f"engine:borrowlock:{int(sub_account_id)}:"
        f"{normalize_asset(symbol)}USDT"
    )


def account_operation_lock_key(sub_account_id: int, symbol: object) -> str:
    """Serialize balance-changing operations for one margin account and asset.

    This lock protects the actual account balance from a manual repay racing
    that account's borrow/hedge/repay lifecycle.  It is deliberately separate
    from the account-scoped borrow admission key so sibling accounts never
    block one another.
    """
    return f"engine:accountop:{int(sub_account_id)}:{normalize_asset(symbol)}USDT"


def master_symbol_lock_key(user_id: int | None, symbol: object) -> str:
    """Serialize independent sub-account commands on a shared master symbol.

    The account operation lock deliberately remains sub-account scoped so one
    account cannot block unrelated accounts.  A master futures position is
    shared by all of a tenant's sub-accounts, therefore opening/closing its
    increment needs this additional user+asset lease.
    """
    scope = str(int(user_id)) if user_id is not None else "None"
    return f"engine:masterop:{scope}:{normalize_asset(symbol)}USDT"


@asynccontextmanager
async def master_symbol_lock(
    redis_client,
    user_id: int | None,
    symbol: object,
    *,
    owner: str,
    ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Acquire an atomic user/symbol lease for a shared master hedge.

    Failure to expose Redis EVAL is fail-closed.  Release uses the same
    compare-and-delete primitive as account locks, so an expired caller can
    never delete a replacement owner's lease.
    """
    key = master_symbol_lock_key(user_id, symbol)
    token = f"{owner}:{time.time_ns()}"
    if not callable(getattr(redis_client, "eval", None)):
        raise AccountOperationLockUnavailable(
            key, f"atomic Redis EVAL unavailable for master symbol lock: {key}"
        )
    try:
        # A shared master position must not fall back to the short
        # 30-second borrow-transition lease. Callers may request a longer
        # delay, but never a shorter master coordination window.
        acquired = await _maybe_await(redis_client.set(
            key,
            token,
            nx=True,
            ex=max(ACCOUNT_OPERATION_LOCK_TTL_SEC, int(ttl_sec)),
        ))
    except Exception as exc:
        raise AccountOperationLockUnavailable(
            key, f"master symbol lock unavailable: {key}"
        ) from exc
    if not acquired:
        raise AccountOperationLockBusy(
            key, f"master symbol operation already in progress: {key}"
        )
    try:
        yield token
    finally:
        await release_account_operation_lock(redis_client, key, token)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def release_account_operation_lock(redis_client, key: str, token: str) -> None:
    """Release a lifecycle lock only when this caller still owns its token."""
    # GET followed by DEL is not an ownership check: the lease can be
    # replaced between the two commands and the stale owner would delete the
    # replacement.  Leave a lock in place until its TTL when the atomic Redis
    # primitive is unavailable or fails.  Callers therefore never trade lock
    # safety for eager cleanup.
    eval_fn = getattr(redis_client, "eval", None)
    if not callable(eval_fn):
        logger.warning(
            "Cannot release account operation lock %s without atomic EVAL; "
            "leaving it for TTL expiry",
            key,
        )
        return
    try:
        await _maybe_await(eval_fn(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1, key, token,
        ))
    except Exception:
        logger.warning(
            "Failed to atomically release account operation lock %s; "
            "leaving it for TTL expiry",
            key,
            exc_info=True,
        )


@asynccontextmanager
async def account_operation_lock(
    redis_client,
    sub_account_id: int,
    symbol: object,
    *,
    owner: str,
    ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Serialize every balance-changing action for one margin account/asset.

    Both synchronous Redis clients (API process) and ``redis.asyncio`` clients
    (Worker process) are supported so all entry points share one lock contract.
    Acquisition errors fail closed; callers can distinguish an occupied lock
    from an unavailable coordination service through the exception type.
    """
    key = account_operation_lock_key(sub_account_id, symbol)
    token = f"{owner}:{time.time_ns()}"
    if not callable(getattr(redis_client, "eval", None)):
        raise AccountOperationLockUnavailable(
            key,
            f"atomic Redis EVAL unavailable for account operation lock: {key}",
        )
    try:
        acquired = await _maybe_await(redis_client.set(
            key,
            token,
            nx=True,
            ex=max(1, int(ttl_sec)),
        ))
    except Exception as exc:
        raise AccountOperationLockUnavailable(
            key, f"account operation lock unavailable: {key}"
        ) from exc

    if not acquired:
        raise AccountOperationLockBusy(
            key, f"account operation already in progress: {key}"
        )

    try:
        yield token
    finally:
        await release_account_operation_lock(redis_client, key, token)
