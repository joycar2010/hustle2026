"""Switchable pocket-Kelly position sizing (default OFF).

When enabled, the BUY path replaces the flat risk fraction with the pocket
table's Kelly fraction: f = min(lambda * kelly_full, cap) for the decision's
(asset, t_remaining bucket, ask bucket); an UNQUALIFIED pocket returns 0.0,
which the caller treats as "skip this entry".  When disabled -- or when the
table cannot be loaded -- `fraction()` returns None and the caller keeps the
legacy sizing unchanged, so the switch is safe to ship dark.

Env knobs:
  KELLY_SIZING_ENABLED  master switch, default false
  KELLY_LAMBDA          Kelly scale, default 0.25 (quarter-Kelly)
  KELLY_CAP_FRACTION    per-order equity cap, default 0.10
  KELLY_POCKETS_PATH    default <repo>/backtest/out/kelly_pockets.json

The companion daily loss stop needs no code: risk.allowed_to_trade already
blocks the day at MAX_DAILY_LOSS_FRACTION (0.05 in .env = the 5% stop that
backtesting selected).  Bucket definitions mirror backtest/calibrate.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

# keep in sync with backtest/calibrate.py
T_BUCKETS = [(0, 15), (15, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 300)]
PRICE_STEP = 0.02


def _t_bucket(t_remaining: float) -> Optional[str]:
    for lo, hi in T_BUCKETS:
        if lo <= t_remaining < hi:
            return f"{lo}-{hi}s"
    return None


def _price_bucket(ask: float) -> str:
    return f"{min(int(ask / PRICE_STEP) * PRICE_STEP, 0.98):.2f}"


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class KellySizing:
    def __init__(self) -> None:
        self.enabled = _env_flag("KELLY_SIZING_ENABLED", "false")
        self.lam = _env_float("KELLY_LAMBDA", 0.25)
        self.cap = _env_float("KELLY_CAP_FRACTION", 0.10)
        self.table: dict[str, Any] = {}
        if not self.enabled:
            return
        path = Path(os.environ.get("KELLY_POCKETS_PATH", ROOT / "backtest" / "out" / "kelly_pockets.json"))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.table = data.get("table", {})
        except Exception:
            # No table -> behave as disabled so legacy sizing keeps working.
            self.enabled = False

    def fraction(self, asset: str, t_remaining: float, ask: float) -> Optional[float]:
        """None = switch off / no table (use legacy sizing).
        0.0  = pocket unqualified (caller should skip the entry).
        >0   = fraction of equity to risk on this order."""
        if not self.enabled:
            return None
        tb = _t_bucket(t_remaining)
        if tb is None or not (0.0 < ask < 1.0):
            return 0.0
        cell = self.table.get(asset.upper(), {}).get(tb, {}).get(_price_bucket(ask))
        if not cell:
            return 0.0
        kelly_full = float(cell.get("kelly_full") or 0.0)
        if kelly_full <= 0.0:
            return 0.0
        return max(0.0, min(self.lam * kelly_full, self.cap))


SIZING = KellySizing()
