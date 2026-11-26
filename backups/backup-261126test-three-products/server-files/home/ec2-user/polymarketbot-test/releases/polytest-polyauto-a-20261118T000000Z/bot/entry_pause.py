"""Read-only, ledger-scoped Paper BUY pause; exits and settlement keep running."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time


def _state_path(asset: str, db_path: Path | None = None) -> Path:
    key = asset.strip().upper()
    if not key or not key.isascii() or not key.isalnum():
        raise ValueError("invalid asset for Paper entry pause")
    if db_path is None:
        # Resolve the current ledger on every read, including after an import
        # during tests or a change of the process environment at startup.
        from bot import store
        db_path = store.DB_PATH
    ledger = Path(db_path).resolve()
    return ledger.with_name(ledger.name + f".paper-entry-pause-{key}.json")


def _timestamp(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid Paper entry pause " + field)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid Paper entry pause " + field)
    return result


def active_entry_pause(
    asset: str = "BTC", *, now: float | None = None, db_path: Path | None = None,
) -> dict | None:
    """Return a valid active pause without creating, changing or deleting it.

    The operator supplies the exact resume timestamp (normally next Beijing
    midnight). At that instant the pause expires, including after restarts.
    Invalid records raise so callers can block BUYs while retaining exits.
    """
    now = _timestamp(time.time() if now is None else now, "current time")
    path = _state_path(asset, db_path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValueError("invalid Paper entry pause record")
    if state.get("asset") != asset.strip().upper() or state.get("mode") != "paper":
        raise ValueError("invalid Paper entry pause asset or mode")
    reason = state.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("invalid Paper entry pause reason")
    created = _timestamp(state.get("created_at"), "created_at")
    resume = _timestamp(state.get("resume_ts"), "resume_ts")
    if created >= resume or created > now:
        raise ValueError("invalid Paper entry pause time range")
    if now >= resume:
        return None
    return state


def entry_pause_reason(asset: str = "BTC", *, now: float | None = None) -> str | None:
    """Paper callers use this before every BUY; a broken guard fails closed."""
    try:
        state = active_entry_pause(asset, now=now)
        return str(state["reason"]) if state is not None else None
    except Exception as exc:
        return f"Paper entry pause unavailable ({type(exc).__name__}); new entries blocked"
