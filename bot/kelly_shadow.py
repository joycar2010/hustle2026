"""Log-only shadow for pocket-level Kelly sizing.

Reads the pocket table produced by backtest/kelly_pockets.py and, on every
BUY the engine actually takes, records what the Kelly regime WOULD have done
(fraction, notional, shares) next to what the engine actually did.  Behavior
is never altered: this module only appends JSONL lines, and every failure
path degrades to doing nothing so the shadow can never break trading.

Enable/disable and paths via env (all optional):
  KELLY_SHADOW_ENABLED  default true (no-op anyway if the table is missing)
  KELLY_POCKETS_PATH    default <repo>/backtest/out/kelly_pockets.json
  KELLY_SHADOW_LOG      default <repo>/logs/kelly_shadow.jsonl

Bucket definitions mirror backtest/calibrate.py (keep in sync).
"""
from __future__ import annotations

import json
import os
import time
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


class KellyShadow:
    def __init__(self) -> None:
        self.enabled = os.environ.get("KELLY_SHADOW_ENABLED", "true").strip().lower() in (
            "1", "true", "yes", "on",
        )
        self.log_path = Path(os.environ.get("KELLY_SHADOW_LOG", ROOT / "logs" / "kelly_shadow.jsonl"))
        self.table: dict[str, Any] = {}
        table_path = Path(os.environ.get("KELLY_POCKETS_PATH", ROOT / "backtest" / "out" / "kelly_pockets.json"))
        try:
            data = json.loads(table_path.read_text(encoding="utf-8"))
            self.table = data.get("table", {})
        except Exception:
            self.enabled = False

    def lookup(self, asset: str, t_remaining: float, ask: float):
        """-> (fraction or 0.0, pocket key string or None)."""
        tb = _t_bucket(t_remaining)
        if tb is None or not (0.0 < ask < 1.0):
            return 0.0, None
        pb = _price_bucket(ask)
        cell = self.table.get(asset.upper(), {}).get(tb, {}).get(pb)
        return (float(cell["fraction"]) if cell else 0.0), f"{asset.upper()}/{tb}/{pb}"

    def observe(
        self,
        *,
        asset: str,
        market_slug: str,
        side: Optional[str],
        entry_rule: Optional[str],
        ask: float,
        t_remaining: float,
        equity: Optional[float],
        actual_size: float,
        actual_cost: float,
        dry_run: bool,
    ) -> None:
        if not self.enabled:
            return
        try:
            fraction, pocket = self.lookup(asset, t_remaining, ask)
            would_cost = round(fraction * equity, 4) if equity is not None else None
            would_shares = round(would_cost / ask, 4) if would_cost is not None and ask > 0 else None
            line = {
                "ts": round(time.time(), 3),
                "asset": asset.upper(),
                "market": market_slug,
                "side": side,
                "entry_rule": entry_rule,
                "ask": ask,
                "t_remaining": round(t_remaining, 1),
                "pocket": pocket,
                "kelly_fraction": fraction,
                "equity": equity,
                "kelly_cost_usd": would_cost,
                "kelly_shares": would_shares,
                "actual_shares": actual_size,
                "actual_cost_usd": actual_cost,
                "dry_run": bool(dry_run),
            }
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception:
            pass  # shadow must never interfere with trading


SHADOW = KellyShadow()
