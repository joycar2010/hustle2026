"""Single source of truth for the Binance execution universe.

The market engine is intentionally fed a conservative intersection.  A
symbol must be live on spot, margin-enabled, and a USDT perpetual before the
database-level controls (manual gate, delisting flag, and global blacklist)
are applied.  Worker-level account and tenant rules remain a later gate; they
must not widen this shared feed.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.db.models import Blacklist, Symbol


def exchange_eligible_symbols(
    spot_symbols: Iterable[dict],
    futures_symbols: Iterable[dict],
) -> set[str]:
    """Return the exchange-side spot+margin+USDT-perpetual intersection.

    ``isMarginTradingAllowed`` is the canonical spot flag.  Some Binance
    responses omit it while advertising ``MARGIN`` in ``permissions``; both
    representations are accepted, but a missing flag never grants access.
    """

    spot: set[str] = set()
    for item in spot_symbols:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        permissions = item.get("permissions") or []
        if (
            symbol
            and str(item.get("status") or "").upper() == "TRADING"
            and str(item.get("quoteAsset") or "").upper() == "USDT"
            and (
                bool(item.get("isMarginTradingAllowed"))
                or "MARGIN" in {str(p).upper() for p in permissions}
            )
        ):
            spot.add(symbol)

    futures: set[str] = set()
    for item in futures_symbols:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if (
            symbol
            and str(item.get("status") or "").upper() == "TRADING"
            and str(item.get("contractType") or "").upper() == "PERPETUAL"
            and str(item.get("quoteAsset") or "").upper() == "USDT"
        ):
            futures.add(symbol)
    return spot & futures


def database_eligible_symbols(db: Session, candidates: Iterable[str] | None = None) -> set[str]:
    """Apply database gates to an exchange candidate set.

    Global blacklist rows (``user_id IS NULL``) are execution-wide.  Personal
    blacklists are intentionally excluded here and remain tenant/Worker
    gates; including them would make one user's settings remove a symbol from
    every user's shared market feed.
    """

    # ``NOT IN`` with a NULL symbol is undefined in SQL.  Symbols are
    # expected to be non-null, but filter malformed legacy blacklist rows so
    # they can never turn the entire universe into UNKNOWN.
    global_blacklist = db.query(Blacklist.symbol).filter(
        Blacklist.user_id.is_(None), Blacklist.symbol.isnot(None)
    )
    query = db.query(Symbol.symbol).filter(
        Symbol.is_active.is_(True),
        Symbol.margin_tradable.is_(True),
        Symbol.futures_tradable.is_(True),
        Symbol.allow_open.is_(True),
        Symbol.is_delisting.is_(False),
        ~Symbol.symbol.in_(global_blacklist),
    )
    if candidates is not None:
        normalized = {str(s).upper().strip() for s in candidates if str(s).strip()}
        if not normalized:
            return set()
        query = query.filter(Symbol.symbol.in_(normalized))
    return {str(row[0]).upper() for row in query.all()}


def eligible_symbols(
    db: Session,
    spot_symbols: Iterable[dict],
    futures_symbols: Iterable[dict],
) -> set[str]:
    """Combine exchange and database gates in one call for callers/tests."""

    return database_eligible_symbols(db, exchange_eligible_symbols(spot_symbols, futures_symbols))
