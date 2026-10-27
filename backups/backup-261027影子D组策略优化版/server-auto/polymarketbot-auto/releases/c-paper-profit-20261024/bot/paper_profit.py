"""Paper-only daily entry stop; persisted separately for each ledger and asset."""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bot import store

_pnl_cache: dict[tuple, tuple[float, float]] = {}


def invalidate_paper_profit_cache() -> None:
    _pnl_cache.clear()


def _state_path(asset: str, db_path: Path | None = None) -> Path:
    key = asset.strip().upper()
    if not key.isalnum():
        raise ValueError("invalid asset for Paper profit stop")
    ledger = Path(db_path if db_path is not None else store.DB_PATH).resolve()
    return ledger.with_name(ledger.name + f".paper-profit-{key}.json")


def active_paper_profit_stop(
    asset: str = "BTC", *, now: float | None = None, db_path: Path | None = None,
) -> dict | None:
    """Read only: an expired record never pauses the new Beijing trading day."""
    now = time.time() if now is None else now
    path = _state_path(asset, db_path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if state.get("asset") != asset.strip().upper() or state.get("mode") != "paper":
        raise ValueError("invalid Paper profit stop state")
    if float(state["day_start_ts"]) != store.local_day_start_ts(now):
        return None
    if not state.get("reason") or float(state["resume_ts"]) <= now:
        raise ValueError("invalid Paper profit resume time")
    return state


def paper_profit_stop_reason(
    cfg, asset: str = "BTC", *, cache_ttl_sec: float = 0.0,
) -> str | None:
    """Latch a reached percentage target; never stop exits or a live worker.

    Invalid accounting/state blocks new entries conservatively. The caller must
    continue settlement and position management even when a reason is returned.
    """
    try:
        now = time.time()
        key = asset.strip().upper()
        active = active_paper_profit_stop(key, now=now)
        if active:
            return str(active["reason"])
        fraction = float(cfg.max_daily_realized_profit_fraction)
        if not math.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError("invalid Paper daily profit fraction")
        if fraction == 0:
            return None
        capital = float(cfg.paper_equity_usd)
        if not math.isfinite(capital) or capital <= 0:
            raise ValueError("invalid Paper capital")
        day_start = store.local_day_start_ts(now)
        cache_key = (str(store.DB_PATH), key, day_start, capital, fraction)
        cached = _pnl_cache.get(cache_key)
        # Only background polling opts into caching. BUY admission always
        # reads current accounting (default TTL=0), including retry admission.
        if cached and 0 <= now - cached[0] < cache_ttl_sec:
            pnl = cached[1]
        else:
            summary = store.realized_pnl_summary_today(True, cutoff=day_start, end=now)
            bucket = summary.get("by_asset", {}).get(key, {})
            pnl = float(bucket.get("realized_usd", 0.0))
            _pnl_cache.clear()
            _pnl_cache[cache_key] = (now, pnl)
        if not math.isfinite(pnl):
            raise ValueError("invalid Paper realized PnL")
        limit = capital * fraction
        if pnl < limit:
            return None
        resume_ts = day_start + 86400
        resume_label = datetime.fromtimestamp(
            resume_ts, timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S Beijing")
        reason = (
            f"{key} Paper daily realized profit ${pnl:.4f} >= "
            f"{fraction:.1%} of ${capital:.2f} (${limit:.2f}); "
            f"new entries paused until {resume_label}"
        )
        state = {
            "asset": key, "mode": "paper", "day_start_ts": day_start,
            "resume_ts": resume_ts, "triggered_at": now,
            "trigger_pnl_usd": pnl, "capital_usd": capital,
            "profit_fraction": fraction, "limit_usd": limit, "reason": reason,
        }
        path = _state_path(key)
        # Same-directory atomic replace prevents a restart or dashboard read
        # from seeing a partially written stop record. The old ledger is intact.
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False,
            ) as out:
                tmp_path = Path(out.name)
                json.dump(state, out, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        return reason
    except Exception as exc:
        return f"Paper profit guard unavailable ({type(exc).__name__}); new entries blocked"
