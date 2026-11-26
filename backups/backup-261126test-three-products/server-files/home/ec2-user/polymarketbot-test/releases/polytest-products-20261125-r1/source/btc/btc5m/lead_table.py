"""Empirical lead-hold win rates for BTC 5m Up/Down.

Source: Polymtradebot replay of 34,559 windows under 60s Chainlink TWAP
(May–Sep 2026). Cells are P(side ahead wins | lead size, time into window).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Columns: lead magnitude in basis points
_LEAD_BINS = (
    (0.0, 1.0),
    (1.0, 2.0),
    (2.0, 5.0),
    (5.0, 10.0),
    (10.0, 15.0),
    (15.0, 1e9),
)

# Rows: seconds elapsed into the 300s window → hold WR by lead bin
# At bell / 1:00 / 2:00 / 3:00 / 3:30 / 4:00 / 4:30 into window
_HOLD_TABLE: list[tuple[float, tuple[float, ...]]] = [
    (0.0, (0.533, 0.589, 0.621, 0.661, 0.709, 0.735)),
    (60.0, (0.562, 0.615, 0.709, 0.779, 0.836, 0.874)),
    (120.0, (0.574, 0.676, 0.758, 0.856, 0.899, 0.932)),
    (180.0, (0.625, 0.713, 0.835, 0.923, 0.956, 0.982)),
    (210.0, (0.654, 0.771, 0.884, 0.956, 0.982, 0.996)),
    (240.0, (0.710, 0.853, 0.943, 0.986, 0.997, 0.999)),
    (270.0, (0.799, 0.958, 0.993, 0.999, 1.000, 1.000)),
]


@dataclass(frozen=True)
class LeadLookup:
    elapsed_sec: float
    lead_bp: float
    hold_wr: float
    bin_lo: float
    bin_hi: float


def _bin_index(lead_bp: float) -> int:
    mag = abs(float(lead_bp))
    for i, (lo, hi) in enumerate(_LEAD_BINS):
        if lo <= mag < hi:
            return i
    return len(_LEAD_BINS) - 1


def hold_win_rate(*, elapsed_sec: float, lead_bp: float) -> LeadLookup:
    """Interpolate hold WR for |lead| at elapsed seconds into the window."""
    elapsed = max(0.0, min(float(elapsed_sec), 300.0))
    idx = _bin_index(lead_bp)
    lo_bp, hi_bp = _LEAD_BINS[idx]

    # Find surrounding table rows
    rows = _HOLD_TABLE
    if elapsed <= rows[0][0]:
        wr = rows[0][1][idx]
        return LeadLookup(elapsed, lead_bp, wr, lo_bp, hi_bp)
    if elapsed >= rows[-1][0]:
        wr = rows[-1][1][idx]
        return LeadLookup(elapsed, lead_bp, wr, lo_bp, hi_bp)

    for i in range(1, len(rows)):
        t0, w0 = rows[i - 1]
        t1, w1 = rows[i]
        if t0 <= elapsed <= t1:
            a = (elapsed - t0) / max(t1 - t0, 1e-9)
            wr = w0[idx] * (1.0 - a) + w1[idx] * a
            return LeadLookup(elapsed, lead_bp, wr, lo_bp, hi_bp)

    wr = rows[-1][1][idx]
    return LeadLookup(elapsed, lead_bp, wr, lo_bp, hi_bp)


def edge_after_fee(
    ask: float,
    hold_wr: float,
    *,
    fee_rate: float = 0.07,
    margin: float = 0.03,
) -> float:
    """Positive ⇒ ask is cheap vs empirical hold WR after fee + safety margin."""
    fee = fee_rate * ask * (1.0 - ask)
    return hold_wr - (ask + fee + margin)


def is_cheap_vs_hold(
    ask: float,
    hold_wr: float,
    *,
    fee_rate: float = 0.07,
    margin: float = 0.03,
) -> bool:
    return edge_after_fee(ask, hold_wr, fee_rate=fee_rate, margin=margin) > 0.0
