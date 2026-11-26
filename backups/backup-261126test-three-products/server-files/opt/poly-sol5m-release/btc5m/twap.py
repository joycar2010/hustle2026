"""TWAP helpers for BTC 5m settlement approximation.

True settlement uses Chainlink BTC/USD 60s TWAP (PolyBolt `price.crypto.twap`
when authenticated). Without credentials we proxy beat/spot from venue medians
and maintain a rolling 60s spot buffer to project the closing average.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass
class TwapProjection:
    beat: float
    spot: float
    projected_close: float
    lead_bp: float
    projected_lead_bp: float
    in_final_minute: bool
    samples: int
    source: str


_spot_ring: Deque[tuple[float, float]] = deque(maxlen=600)


def note_spot(price: float, *, ts: Optional[float] = None) -> None:
    """Record a spot sample for projected TWAP (caller should poll ~1s)."""
    _spot_ring.append((ts if ts is not None else time.time(), float(price)))


def clear_ring() -> None:
    _spot_ring.clear()


def lead_bp(spot: float, beat: float) -> float:
    if beat <= 0:
        return 0.0
    return (spot - beat) / beat * 10_000.0


def projected_close_twap(
    *,
    beat: float,
    spot: float,
    end_ts: float,
    now: Optional[float] = None,
    source: str = "venue-proxy",
) -> TwapProjection:
    """Project closing 60s TWAP inside / before the final minute.

    Before the final minute: projected_close ≈ spot (no TWAP average yet).
    Inside the final minute: average of buffered samples in [end-60, now]
    plus spot filling remaining seconds.
    """
    now_ts = time.time() if now is None else float(now)
    t_left = end_ts - now_ts
    in_final = t_left <= 60.0
    note_spot(spot, ts=now_ts)

    if not in_final:
        px = float(spot)
        return TwapProjection(
            beat=beat,
            spot=spot,
            projected_close=px,
            lead_bp=lead_bp(spot, beat),
            projected_lead_bp=lead_bp(px, beat),
            in_final_minute=False,
            samples=len(_spot_ring),
            source=source,
        )

    window_start = end_ts - 60.0
    samples = [(t, p) for t, p in _spot_ring if t >= window_start - 0.5]
    elapsed = max(0.0, min(60.0 - max(t_left, 0.0), 60.0))
    remaining = max(60.0 - elapsed, 0.0)

    if samples:
        # Time-weighted-ish: average of samples, then blend remaining with spot
        avg_so_far = sum(p for _, p in samples) / len(samples)
    else:
        avg_so_far = float(spot)

    if elapsed <= 1e-9:
        projected = float(spot)
    else:
        projected = (avg_so_far * elapsed + float(spot) * remaining) / 60.0

    return TwapProjection(
        beat=beat,
        spot=spot,
        projected_close=projected,
        lead_bp=lead_bp(spot, beat),
        projected_lead_bp=lead_bp(projected, beat),
        in_final_minute=True,
        samples=len(samples),
        source=source,
    )


def fair_up_prob_from_lead(hold_wr: float, *, lead_bp_signed: float) -> float:
    """Map signed lead to P(Up). hold_wr is for the leading side."""
    if lead_bp_signed >= 0:
        return float(hold_wr)
    return 1.0 - float(hold_wr)
