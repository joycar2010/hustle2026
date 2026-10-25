"""Runtime policy for symbols explicitly pushed into a dashboard slot.

Manual pushes are deliberately conservative: until the user saves an explicit
single-symbol rule, both automatic removal and automatic/manual repayment are
blocked.  The Redis marker is the live source for push origin; the legacy
``pushed_origin`` hash is accepted during migration.  A saved custom
``SymbolRule`` is the explicit opt-in and its ``allow_*`` value is authoritative.
"""

from __future__ import annotations

from app.db.models import AccountSymbolRule, SymbolRule
from app.services.pushed_symbols import manual_push_marker_key


def _canonical_candidates(symbol: str) -> tuple[str, ...]:
    value = str(symbol or "").strip().upper()
    if not value:
        return ()
    if value.endswith("USDT"):
        bare = value[:-4]
        return (value, bare) if bare else (value,)
    return (value + "USDT", value)


def _is_manual_marker(redis_client, user_id: int, symbol: str) -> bool:
    candidates = _canonical_candidates(symbol)
    if not candidates:
        return False
    try:
        for candidate in candidates:
            if redis_client.exists(manual_push_marker_key(user_id, candidate)):
                return True
    except Exception:
        # A Redis outage must not turn a protected push into an allowed
        # destructive operation.  Fall back to the compatibility hash only
        # when it can be read; otherwise fail closed.
        return True
    try:
        for candidate in candidates:
            origin = redis_client.hget(f"engine:{user_id}:pushed_origin", candidate)
            if isinstance(origin, bytes):
                origin = origin.decode(errors="replace")
            if str(origin or "").lower() == "manual":
                return True
        return False
    except Exception:
        return True


def manual_push_operation_allowed(
    db,
    redis_client,
    user_id: int,
    symbol: str,
    operation: str,
    sub_account_id: int | None = None,
    manual: bool = False,
) -> bool:
    """Return whether a manual-pushed symbol may be removed or repaid.

    ``operation`` is ``remove`` or ``repay``.  Non-manual symbols keep their
    existing behavior.  For a manual symbol, only a persisted custom rule
    with the corresponding explicit ``allow_* = true`` opts in; a false or
    absent value remains blocked.

    ``manual=True`` marks an operation a HUMAN just requested through the
    HTTP endpoints (remove dialog / repay buttons / force close). The re-arm
    protection exists to stop the WORKER from acting on stale rules within
    milliseconds of a push -- a human click IS the user's newest intent and
    must never be blocked by their own earlier push. The opt-in rule flags
    therefore only govern the worker's automatic remove/repay paths.
    """
    if operation not in {"remove", "repay"}:
        raise ValueError(f"unsupported manual push operation: {operation}")
    if manual:
        return True
    if not _is_manual_marker(redis_client, user_id, symbol):
        return True
    return explicit_rule_optin_persisted(
        db, user_id, symbol, operation, sub_account_id=sub_account_id
    )


def rearm_manual_push_protection(db, user_id: int, symbol: str) -> bool:
    """Reset leftover explicit ``allow_*=True`` opt-ins before a manual push.

    A manual push is the user's most recent explicit intent and defaults to
    禁移禁还.  A single-symbol rule saved earlier (or a rule dialog that
    persisted the truthy defaults) must not instantly bypass the manual-push
    protection and delete the freshly pushed slot.  Only explicit ``True``
    values are flipped to ``False``; ``NULL`` (inherit) values are already
    blocked by the opt-in policy and stay untouched.  The caller commits and
    publishes the rules reload when this returns ``True``.  A later explicit
    single-symbol save re-enables removal/repayment per the existing policy.
    """
    candidates = list(_canonical_candidates(symbol))
    if not candidates:
        return False
    changed = False
    rows = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol.in_(candidates),
    ).all()
    account_rows = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.symbol.in_(candidates),
    ).all()
    for row in list(rows) + list(account_rows):
        if getattr(row, "allow_remove", None) is True:
            row.allow_remove = False
            changed = True
        if getattr(row, "allow_repay", None) is True:
            row.allow_repay = False
            changed = True
    return changed


def explicit_rule_optin_persisted(
    db,
    user_id: int,
    symbol: str,
    operation: str,
    sub_account_id: int | None = None,
) -> bool:
    """Return whether the CURRENT persisted rules opt this symbol in.

    This is the database portion of ``manual_push_operation_allowed`` and is
    the single source of truth shared by the HTTP removal/repay endpoints and
    the Worker's automatic-removal bypass.  The Worker must consult the
    persisted value (not only its in-memory rule snapshot) because a manual
    push re-arms protection by resetting ``allow_*`` flags immediately before
    list membership is written; a stale snapshot from before that reset must
    not be able to delete the freshly pushed symbol.
    """
    if operation not in {"remove", "repay"}:
        raise ValueError(f"unsupported manual push operation: {operation}")

    candidates = _canonical_candidates(symbol)
    if not candidates:
        return False
    rows = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol.in_(candidates),
    ).all()
    # Prefer the canonical USDT row when both a legacy bare row and a current
    # row exist.  ``source=custom`` distinguishes an explicit save from a
    # compatibility/global placeholder.
    canonical = candidates[0] if candidates else ""
    row = next((item for item in rows if item.symbol == canonical), None)
    if row is None and rows:
        row = rows[0]
    if row is not None and str(getattr(row, "source", "") or "").lower() == "custom":
        if getattr(row, f"allow_{operation}", None) is True:
            return True

    # The dashboard's per-sub-account single-rule row is equally explicit.
    # A partial repayment supplies the account id; symbol removal accepts an
    # opt-in row for any owned sub-account because removal is symbol-scoped.
    query = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.symbol.in_(candidates),
    )
    if sub_account_id is not None:
        query = query.filter(AccountSymbolRule.sub_account_id == sub_account_id)
    return any(getattr(item, f"allow_{operation}", None) is True for item in query.all())
