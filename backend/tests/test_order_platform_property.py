"""Regression: :prop:`OrderRecord.platform` derives the canonical key from the loaded
account's `platform_id` and is safe in async contexts (returns None for unloaded account
rather than triggering lazy-load)."""
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.platform import PlatformId
from app.models.account import Account
from app.models.order import Order


def _make_session():
    from sqlalchemy import create_engine
    # In-memory SQLite for model-level integration — no test DB required.
    engine = create_engine("sqlite+pysqlite:///:memory:", echo=False)
    # SmallInteger + UUID + JSONB + TIMESTAMP need the Postgres dialect — skip DDL and
    # operate purely in-memory: we never actually INSERT, we just assert attribute logic.
    return Session(bind=engine)


def test_platform_property_resolves_when_account_loaded():
    acc = Account(platform_id=PlatformId.BINANCE.value, account_name="t", api_key="k", api_secret="s", user_id=None)
    order = Order(account_id=None, symbol="XAUUSDT", order_side="buy", order_type="market",
                  price=1.0, qty=1.0, status="filled")
    # Attach the relationship in-memory (bypass DB). When SQLAlchemy's relationship slot
    # is populated, `state.unloaded` no longer contains 'account'.
    order.account = acc
    assert order.platform == PlatformId.BINANCE.key
    assert order.platform == "binance"


def test_platform_property_returns_none_when_account_unloaded():
    """Critical async-safety: the @property MUST NOT trigger lazy-load on an unloaded
    relationship (that raises MissingGreenlet in async sessions). It returns None instead
    and the caller is expected to eager-load via selectinload(Order.account)."""
    order = Order(account_id=None, symbol="XAUUSDT", order_side="buy", order_type="market",
                  price=1.0, qty=1.0, status="filled")
    # Do NOT set order.account — it's unloaded.
    assert order.platform is None


def test_platform_property_returns_none_for_unknown_platform_id():
    # Defensive: if somehow an account has a platform_id outside the enum (rare, but
    # could happen during a migration or data-import bug) we return None, not a stale
    # cached literal.
    acc = Account(platform_id=99, account_name="t", api_key="k", api_secret="s", user_id=None)
    order = Order(account_id=None, symbol="X", order_side="buy", order_type="market",
                  price=1.0, qty=1.0, status="filled")
    order.account = acc
    assert order.platform is None


def test_platform_property_for_each_known_platform():
    for pid in PlatformId:
        acc = Account(platform_id=pid.value, account_name="t", api_key="k", api_secret="s", user_id=None)
        order = Order(account_id=None, symbol="X", order_side="buy", order_type="market",
                      price=1.0, qty=1.0, status="filled")
        order.account = acc
        assert order.platform == pid.key, f"{pid.name} -> {pid.key}"
