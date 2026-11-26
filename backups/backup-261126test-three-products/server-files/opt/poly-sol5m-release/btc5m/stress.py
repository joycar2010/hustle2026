"""Friction stress replay: apply extra slippage + fee to closed paper trades."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from btc5m.fees import taker_fee_usd


@dataclass(frozen=True)
class StressResult:
    n: int
    baseline_net: float
    stressed_net: float
    delta: float
    slip_ticks: float
    fee_mult: float


def stress_late_edge_db(
    path: Path,
    *,
    slip_ticks: float = 1.0,
    tick: float = 0.01,
    fee_rate: float = 0.07,
    fee_mult: float = 1.0,
) -> Optional[StressResult]:
    """Replay closed late_edge positions with worse entry and full fee curve."""
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)")}
        if "entry_price" not in cols:
            return None
        net_expr = "COALESCE(pnl_net_usd, pnl_usd)" if "pnl_net_usd" in cols else "pnl_usd"
        rows = conn.execute(
            f"""
            SELECT side, size, entry_price, exit_price, {net_expr} AS net,
                   COALESCE(fee_usd, 0) AS fee
            FROM positions WHERE status='closed'
            """
        ).fetchall()
    finally:
        conn.close()

    baseline = 0.0
    stressed = 0.0
    n = 0
    for row in rows:
        try:
            size = float(row["size"])
            entry = float(row["entry_price"])
            exit_px = float(row["exit_price"] if row["exit_price"] is not None else 0.0)
            net = float(row["net"] or 0.0)
        except (TypeError, ValueError):
            continue
        n += 1
        baseline += net
        # Adverse slip on entry for taker buys
        entry_x = min(0.99, entry + slip_ticks * tick)
        fee = taker_fee_usd(entry_x, size, fee_rate) * fee_mult
        # Binary settlement
        gross = size * (exit_px - entry_x)
        stressed += gross - fee

    return StressResult(
        n=n,
        baseline_net=baseline,
        stressed_net=stressed,
        delta=stressed - baseline,
        slip_ticks=slip_ticks,
        fee_mult=fee_mult,
    )


def format_stress(result: Optional[StressResult]) -> str:
    if result is None:
        return "No late_edge positions to stress."
    return (
        f"Friction stress n={result.n} slip={result.slip_ticks:.1f}tick "
        f"fee_mult={result.fee_mult:.2f}\n"
        f"  baseline_net=${result.baseline_net:+.2f}\n"
        f"  stressed_net=${result.stressed_net:+.2f}\n"
        f"  delta=${result.delta:+.2f}"
    )
