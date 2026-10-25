"""Database-only metrics for confirmed futures execution orders.

TradeLog is the execution audit trail.  Position's latest order-id fields are
deliberately not used: an opening position can have several limit/fallback
orders and a later close, while the position stores only the final leg.
"""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

FUTURES_EXECUTION_ACTIONS = frozenset({
    "FUTURES_LONG",
    "FUTURES_CLOSE",
    "FUTURES_LIMIT_FILL",
    "FUTURES_MARKET_FALLBACK",
    "ROLLBACK_FUTURES_CLOSE",
})


def _positive_quantity(value: Any) -> bool:
    try:
        amount = Decimal(str(value))
        return amount.is_finite() and amount > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _execution_key(row: Any) -> tuple[str, str, str] | None:
    """Return account/symbol/order identity, or None for an unconfirmed row."""
    order_id = str(getattr(row, "order_id", None) or "").strip()
    symbol = str(getattr(row, "symbol", None) or "").strip().upper()
    # The executor may use a summary placeholder (for example ``"limit"``)
    # when tranche logs already contain the real order. Binance IDs are
    # positive integer strings, so reject non-numeric placeholders.
    if not order_id or not order_id.isdigit() or int(order_id) <= 0 or not symbol:
        return None
    # A master hedge is shared by subaccounts: key it as master so the same
    # Binance order cannot be counted once per child strategy.  Sub-account
    # legs remain isolated even if an exchange order id is ever reused.
    hedge_account = str(getattr(row, "hedge_account", None) or "").strip().lower()
    if hedge_account == "master":
        account = "master"
    else:
        account = f"sub:{getattr(row, 'sub_account_id', '')}"
    return account, symbol, order_id


def dedupe_confirmed_futures_orders(rows: Iterable[Any]) -> int:
    """Count distinct confirmed exchange orders from already user-scoped rows.

    ``SUCCESS`` plus a positive executed quantity and a real order id are the
    persisted confirmation contract.  Rows are expected to expose the fields
    selected by :func:`count_confirmed_futures_orders`.
    """
    keys: set[tuple[str, str, str]] = set()
    for row in rows:
        if str(getattr(row, "action", "") or "").upper() not in FUTURES_EXECUTION_ACTIONS:
            continue
        if str(getattr(row, "status", "") or "").upper() != "SUCCESS":
            continue
        if not _positive_quantity(getattr(row, "quantity", None)):
            continue
        key = _execution_key(row)
        if key is not None:
            keys.add(key)
    return len(keys)


def count_confirmed_futures_orders(db, user_id: int) -> int:
    """Count confirmed futures orders for one UID without exchange calls.

    The query is intentionally user-scoped before materialising rows.  An
    outer join retains old logs whose Position row was removed; those rows are
    still attributable to their sub-account and cannot silently disappear.
    Database/query failures propagate to the caller so a stale value can be
    retained instead of publishing a false zero.
    """
    # Lazy imports avoid the app.db.models <-> engine.models compatibility
    # import cycle when this small pure helper is imported by tests/tools.
    from engine.models import Position, TradeLog

    rows = (
        db.query(
            TradeLog.action,
            TradeLog.status,
            TradeLog.quantity,
            TradeLog.order_id,
            TradeLog.symbol,
            TradeLog.sub_account_id,
            Position.hedge_account,
        )
        .outerjoin(Position, Position.id == TradeLog.position_id)
        .filter(TradeLog.user_id == user_id)
        .filter(TradeLog.action.in_(tuple(FUTURES_EXECUTION_ACTIONS)))
        .all()
    )
    return dedupe_confirmed_futures_orders(rows)
