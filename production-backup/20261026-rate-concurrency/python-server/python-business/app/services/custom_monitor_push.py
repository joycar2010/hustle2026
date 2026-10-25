"""Shared read-only gates for custom-monitor candidate pushes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Blacklist, CustomMonitorSymbol, Symbol


@dataclass(frozen=True, slots=True)
class CustomMonitorInfo:
    """Detached monitor metadata used by the Worker after its DB read."""

    monitor_id: int
    user_id: int
    spot_symbol: str
    futures_symbol: str
    display_symbol: str


def _compact_symbol(value: object) -> str:
    return re.sub(r"[-_/\s]+", "", str(value or "").strip().upper())


def custom_monitor_aliases(row: CustomMonitorSymbol | CustomMonitorInfo) -> set[str]:
    """Return symbols that must share blacklist/delisting protections."""
    aliases: set[str] = set()
    for value in (
        getattr(row, "spot_symbol", None),
        getattr(row, "futures_symbol", None),
        getattr(row, "display_symbol", None),
    ):
        compact = _compact_symbol(value)
        if not compact:
            continue
        aliases.add(compact)
        if not compact.endswith("USDT"):
            aliases.add(f"{compact}USDT")
    return aliases


def custom_monitor_block_reason(
    db: Session,
    user_id: int,
    row: CustomMonitorSymbol | CustomMonitorInfo,
) -> str | None:
    """Return a stable reason when a candidate must not be pushed."""
    aliases = custom_monitor_aliases(row)
    if not aliases:
        return "invalid_symbols"

    blacklisted = {
        str(value[0] if isinstance(value, tuple) else value).strip().upper()
        for value in db.query(Blacklist.symbol).filter(
            Blacklist.symbol.in_(aliases),
            or_(Blacklist.user_id == user_id, Blacklist.user_id.is_(None)),
        ).all()
        if value
    }
    if blacklisted:
        return f"blacklist:{','.join(sorted(blacklisted))}"

    # Custom mappings may intentionally point at symbols absent from the
    # executable universe.  Only an explicit known delisting blocks them.
    delisted = {
        str(getattr(symbol, "symbol", "") or "").strip().upper()
        for symbol in db.query(Symbol).filter(Symbol.symbol.in_(aliases)).all()
        if bool(getattr(symbol, "is_delisting", False))
    }
    if delisted:
        return f"delisting:{','.join(sorted(delisted))}"
    return None


def load_active_custom_monitor_infos(db: Session, user_id: int) -> list[CustomMonitorInfo]:
    """Read only active rows owned by one tenant, detached from the session."""
    rows = db.query(CustomMonitorSymbol).filter(
        CustomMonitorSymbol.user_id == int(user_id),
        CustomMonitorSymbol.is_active.is_(True),
        CustomMonitorSymbol.is_removed.is_(False),
    ).all()
    result: list[CustomMonitorInfo] = []
    for row in rows:
        result.append(
            CustomMonitorInfo(
                monitor_id=int(row.id),
                user_id=int(row.user_id),
                spot_symbol=str(row.spot_symbol or "").upper(),
                futures_symbol=str(row.futures_symbol or "").upper(),
                display_symbol=str(
                    row.display_symbol
                    or str(row.spot_symbol or "").upper().removesuffix("USDT")
                ).upper(),
            )
        )
    return result

