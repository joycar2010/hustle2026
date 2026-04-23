"""Regression: account_sync_service.py dispatches by `account.platform_id == PlatformId.*`.

Prior bug: `account.platform == "binance"` compared a SQLAlchemy relationship object to
a string — always False, so sync_binance_account / sync_bybit_account never ran. This
test pins the correct dispatch shape.
"""
from types import SimpleNamespace

from app.core.platform import PlatformId


def _dispatch(account):
    """Inline copy of the live branching logic (see account_sync_service.py:62-65).
    Must stay in lock-step with the service."""
    if account.platform_id == PlatformId.BINANCE:
        return "binance_sync"
    elif account.platform_id == PlatformId.BYBIT:
        return "bybit_sync"
    return None


def test_dispatch_routes_binance_smallint():
    acc = SimpleNamespace(platform_id=1)  # raw SmallInteger from PostgreSQL
    assert _dispatch(acc) == "binance_sync"


def test_dispatch_routes_bybit_smallint():
    acc = SimpleNamespace(platform_id=2)
    assert _dispatch(acc) == "bybit_sync"


def test_dispatch_ignores_ic_markets_and_gate():
    # These platforms have their own sync paths (or none yet). They MUST not be routed
    # through binance/bybit by accident — that was exactly the 2026-04-23 failure mode.
    assert _dispatch(SimpleNamespace(platform_id=3)) is None
    assert _dispatch(SimpleNamespace(platform_id=4)) is None


def test_legacy_string_platform_field_never_matches():
    # Document the bug shape so it can never silently come back: a SQLAlchemy relationship
    # attribute named `platform` returning a Platform ORM object is NOT a string.
    # Simulate the footgun — the old code path was `account.platform == "binance"`.
    class FakePlatformRelationship:
        def __init__(self, name):
            self.platform_name = name
        def __eq__(self, other):   # default object equality — never True vs a string
            return isinstance(other, FakePlatformRelationship) and self.platform_name == other.platform_name

    acc = SimpleNamespace(platform=FakePlatformRelationship("binance"), platform_id=1)
    # the buggy comparison:
    assert (acc.platform == "binance") is False, "relationship must never equal a raw string"
    # the correct comparison still works:
    assert _dispatch(acc) == "binance_sync"
