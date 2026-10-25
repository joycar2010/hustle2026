"""Validate remove-threshold hysteresis across the full rule hierarchy."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AccountSymbolRule, SymbolRule
from engine.thresholds import push_remove_conflict


def _canonical_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if symbol and not symbol.endswith("USDT"):
        symbol += "USDT"
    return symbol


def _prefer_canonical(rows: Iterable[Any]) -> dict[Any, Any]:
    """Collapse legacy bare/canonical duplicates using runtime precedence."""
    selected: dict[Any, Any] = {}
    for row in sorted(rows, key=lambda item: int(getattr(item, "id", 0) or 0)):
        symbol = _canonical_symbol(getattr(row, "symbol", None))
        if not symbol:
            continue
        account_id = getattr(row, "sub_account_id", None)
        key = (account_id, symbol) if account_id is not None else symbol
        current = selected.get(key)
        if current is None or str(row.symbol).strip().upper() == symbol:
            selected[key] = row
    return selected


def remove_hierarchy_has_conflict(
    db: Session,
    user_id: int | None,
    *,
    auto_push_spread: Any,
    global_remove_spread: Any,
    exclude_symbol_rule_ids: Iterable[int] = (),
    exclude_account_rule_ids: Iterable[int] = (),
    only_symbols: Iterable[str] | None = None,
) -> bool:
    """Return whether any enabled effective remove line conflicts with entry.

    The projection mirrors Worker precedence: account override, then symbol
    override, then global default. ``allow_remove=False`` protects the whole
    symbol, and disabled account rules do not participate in auto-removal.
    """
    if push_remove_conflict(auto_push_spread, global_remove_spread):
        return True

    excluded = {int(value) for value in exclude_symbol_rule_ids}
    excluded_accounts = {int(value) for value in exclude_account_rule_ids}
    symbol_rows = db.query(SymbolRule).filter(SymbolRule.user_id == user_id).all()
    symbol_rows = [
        row for row in symbol_rows if int(getattr(row, "id", 0) or 0) not in excluded
    ]
    account_rows = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id
    ).all()
    account_rows = [
        row
        for row in account_rows
        if int(getattr(row, "id", 0) or 0) not in excluded_accounts
    ]

    symbols = _prefer_canonical(symbol_rows)
    accounts = _prefer_canonical(account_rows)
    symbol_names = set(symbols)
    symbol_names.update(key[1] for key in accounts)
    if only_symbols is not None:
        selected_symbols = {
            _canonical_symbol(symbol) for symbol in only_symbols if _canonical_symbol(symbol)
        }
        symbol_names.intersection_update(selected_symbols)

    for symbol in symbol_names:
        symbol_rule = symbols.get(symbol)
        if symbol_rule is not None and symbol_rule.allow_remove is False:
            continue

        base_remove = global_remove_spread
        if symbol_rule is not None and symbol_rule.remove_spread is not None:
            base_remove = symbol_rule.remove_spread
        if push_remove_conflict(auto_push_spread, base_remove):
            return True

        for (account_id, account_symbol), account_rule in accounts.items():
            if account_symbol != symbol or account_rule.is_enabled is False:
                continue
            effective_remove = (
                account_rule.remove_spread
                if account_rule.remove_spread is not None
                else base_remove
            )
            if push_remove_conflict(auto_push_spread, effective_remove):
                return True
    return False
