"""Paper-only conditional recovery after the realized daily-loss circuit.

The loss cap remains the default hard gate.  Recovery is deliberately narrow:
it requires an existing position, conservative executable-bid marking, a
stable net daily mark for several samples, and a small entry budget.  Live
workers never use this path.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from bot import store


@dataclass(frozen=True)
class RecoveryDecision:
    state: str
    allow_entries: bool
    risk_fraction: Optional[float]
    entries_used: int
    net_pnl_usd: Optional[float]
    reason: str


def _state_path(asset: str, db_path: Path | None = None) -> Path:
    key = asset.strip().upper()
    if not key.isalnum():
        raise ValueError("invalid asset for Paper loss recovery")
    ledger = Path(db_path if db_path is not None else store.DB_PATH).resolve()
    return ledger.with_name(ledger.name + f".loss-recovery-{key}.json")


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as out:
            tmp_path = Path(out.name)
            json.dump(state, out, ensure_ascii=False, allow_nan=False, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _read_state(path: Path, asset: str, day_start: float) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    if (
        state.get("asset") != asset
        or state.get("mode") not in {"LOSS_CAP_HOLD", "RECOVERY_PENDING", "RECOVERY_ACTIVE"}
        or float(state.get("day_start_ts", -1)) != float(day_start)
    ):
        state = {
            "asset": asset,
            "mode": "LOSS_CAP_HOLD",
            "day_start_ts": day_start,
            "samples": [],
            "entries_used": 0,
        }
    state.setdefault("samples", [])
    state.setdefault("entries_used", 0)
    return state


def _save_if_changed(path: Path, old: dict, new: dict) -> None:
    if old != new:
        _write_state(path, new)


def _decision(
    state: str,
    reason: str,
    *,
    allow_entries: bool = False,
    risk_fraction: Optional[float] = None,
    entries_used: int = 0,
    net_pnl_usd: Optional[float] = None,
) -> RecoveryDecision:
    return RecoveryDecision(
        state=state,
        allow_entries=allow_entries,
        risk_fraction=risk_fraction,
        entries_used=entries_used,
        net_pnl_usd=net_pnl_usd,
        reason=reason,
    )


def _position_rows(asset: str, dry_run: bool) -> list[dict]:
    rows: list[dict] = []
    # Ask the ledger for the explicit asset bucket.  Falling back to
    # ``infer_asset`` here would classify weather/sports slugs as BTC and could
    # incorrectly unlock the BTC recovery gate.
    for condition_id, _market_slug in store.unresolved_with_slug(
        dry_run, asset=asset
    ):
        rows.extend(store.open_orders_for_market(condition_id, dry_run))
    return rows


def evaluate(
    cfg,
    asset: str,
    dry_run: bool,
    *,
    books_by_token: Mapping[str, tuple[object, float]],
    fetch_book: Optional[Callable[[str], object]] = None,
    now: Optional[float] = None,
) -> RecoveryDecision:
    """Evaluate conditional Paper recovery using conservative executable bids.

    ``books_by_token`` values are ``(TopOfBook, fetched_at)``.  A missing book,
    stale timestamp, or missing bid is fail-closed.  The optional fetcher is
    used only for other currently open markets and is never called for live.
    """
    asset = asset.strip().upper()
    now = time.time() if now is None else float(now)
    if not dry_run or not bool(getattr(cfg, "loss_cap_recovery_enabled", False)):
        return _decision("DISABLED", "Paper loss recovery disabled")

    equity = float(cfg.paper_equity_usd)
    loss_fraction = float(cfg.max_daily_loss_fraction)
    realized = float(store.realized_pnl_today(dry_run, asset=asset))
    loss_limit = equity * loss_fraction
    if loss_fraction <= 0 or realized > -loss_limit:
        return _decision("NORMAL", "daily realized loss is below the circuit threshold", net_pnl_usd=realized)

    day_start = store.local_day_start_ts(now)
    path = _state_path(asset)
    old = _read_state(path, asset, day_start)
    state = dict(old)
    rows = _position_rows(asset, dry_run)
    entries_used = int(state.get("entries_used", 0))
    if not rows:
        state["mode"] = "LOSS_CAP_HOLD"
        state["samples"] = []
        state["last_mark_ts"] = now
        state["last_net_pnl_usd"] = realized
        _save_if_changed(path, old, state)
        return _decision(
            "LOSS_CAP_HOLD",
            f"daily loss ${realized:.4f} reached; no open position for recovery",
            entries_used=entries_used,
            net_pnl_usd=realized,
        )

    max_age = max(0.1, float(cfg.loss_cap_recovery_mark_max_age_sec))
    unrealized = 0.0
    mark_valid = True
    oldest_mark_age = 0.0
    for row in rows:
        token = str(row.get("token_id") or "")
        item = books_by_token.get(token)
        if item is None and fetch_book is not None:
            try:
                fetched = fetch_book(token)
                # A callback may return ``(book, fetched_at)`` so callers can
                # use a bounded cache without making an old mark look fresh.
                if (
                    isinstance(fetched, tuple)
                    and len(fetched) == 2
                    and isinstance(fetched[1], (int, float))
                ):
                    item = (fetched[0], float(fetched[1]))
                else:
                    item = (fetched, now)
            except Exception:
                item = None
        if item is None:
            mark_valid = False
            continue
        book, fetched_at = item
        age = max(0.0, now - float(fetched_at))
        oldest_mark_age = max(oldest_mark_age, age)
        bid = getattr(book, "best_bid", None)
        try:
            bid = float(bid)
            size = float(row.get("size") or 0.0)
            entry_price = float(row.get("price") or 0.0)
        except (TypeError, ValueError):
            mark_valid = False
            continue
        if not math.isfinite(bid) or bid <= 0 or size <= 0 or not math.isfinite(entry_price):
            mark_valid = False
            continue
        if age > max_age:
            mark_valid = False
        # Mark at executable bid and subtract the configured taker fee.
        fee = max(0.0, float(cfg.taker_fee_rate) * bid * (1.0 - bid))
        unrealized += size * (bid - entry_price - fee)

    net_pnl = realized + unrealized
    threshold = equity * float(cfg.loss_cap_recovery_min_net_pnl_fraction)
    if not mark_valid or oldest_mark_age > max_age:
        state["mode"] = "LOSS_CAP_HOLD"
        state["samples"] = []
        state["last_mark_ts"] = now
        state["last_net_pnl_usd"] = net_pnl if math.isfinite(net_pnl) else None
        _save_if_changed(path, old, state)
        return _decision(
            "LOSS_CAP_HOLD",
            f"daily loss ${realized:.4f} reached; recovery mark unavailable or stale",
            entries_used=entries_used,
            net_pnl_usd=net_pnl if math.isfinite(net_pnl) else None,
        )

    if not math.isfinite(net_pnl) or net_pnl < threshold:
        state["mode"] = "LOSS_CAP_HOLD"
        state["samples"] = []
        state["last_mark_ts"] = now
        state["last_net_pnl_usd"] = net_pnl if math.isfinite(net_pnl) else None
        _save_if_changed(path, old, state)
        return _decision(
            "LOSS_CAP_HOLD",
            f"recovery net mark ${net_pnl:.4f} below threshold ${threshold:.4f}",
            entries_used=entries_used,
            net_pnl_usd=net_pnl,
        )

    samples = [
        float(x)
        for x in state.get("samples", [])
        if isinstance(x, (int, float)) and math.isfinite(float(x))
    ]
    window = max(1.0, float(cfg.loss_cap_recovery_confirm_window_sec))
    confirmations = max(1, int(cfg.loss_cap_recovery_confirm_samples))
    interval = window / max(confirmations - 1, 1)
    samples = [x for x in samples if now - x <= window]
    if not samples or now - samples[-1] >= interval:
        samples.append(now)
    active = len(samples) >= confirmations
    state["mode"] = "RECOVERY_ACTIVE" if active else "RECOVERY_PENDING"
    state["samples"] = samples[-confirmations:]
    state["last_mark_ts"] = now
    state["last_net_pnl_usd"] = net_pnl
    _save_if_changed(path, old, state)

    if not active:
        return _decision(
            "RECOVERY_PENDING",
            f"recovery confirmation {len(samples)}/{confirmations}; net mark ${net_pnl:.4f}",
            entries_used=entries_used,
            net_pnl_usd=net_pnl,
        )
    if entries_used >= int(cfg.loss_cap_recovery_max_entries_per_day):
        return _decision(
            "RECOVERY_ACTIVE",
            f"recovery entry budget exhausted ({entries_used}/{cfg.loss_cap_recovery_max_entries_per_day})",
            entries_used=entries_used,
            net_pnl_usd=net_pnl,
        )
    return _decision(
        "RECOVERY_ACTIVE",
        f"recovery active; net mark ${net_pnl:.4f}, entries {entries_used}/{cfg.loss_cap_recovery_max_entries_per_day}",
        allow_entries=True,
        risk_fraction=max(
            0.0,
            min(
                float(cfg.order_risk_fraction)
                * float(cfg.loss_cap_recovery_size_multiplier),
                float(cfg.loss_cap_recovery_max_risk_fraction),
            ),
        ),
        entries_used=entries_used,
        net_pnl_usd=net_pnl,
    )


def record_entry(asset: str, *, now: Optional[float] = None) -> None:
    """Consume one recovery entry budget after a Paper buy is recorded."""
    now = time.time() if now is None else float(now)
    day_start = store.local_day_start_ts(now)
    path = _state_path(asset)
    state = _read_state(path, asset.strip().upper(), day_start)
    if state.get("mode") != "RECOVERY_ACTIVE":
        return
    state["entries_used"] = int(state.get("entries_used", 0)) + 1
    state["last_entry_ts"] = now
    _write_state(path, state)

