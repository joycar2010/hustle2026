"""Rolling entry-price bucket calibration / circuit breaker for late_edge."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


BUCKETS = (
    (0.75, 0.80),
    (0.80, 0.85),
    (0.85, 0.90),
    (0.90, 0.95),
    (0.95, 1.01),
)

# P0 manual ban: live A [0.80,0.85) WR≈57% vs ~85% BE (n=7, −$18).
# Remains banned even before min_samples / if MAX_ENTRY is later raised.
FORCE_BAN_BUCKETS = frozenset({(0.80, 0.85)})


@dataclass(frozen=True)
class BucketStats:
    lo: float
    hi: float
    n: int
    wins: int
    wr: float
    required_wr: float
    net_pnl_usd: float
    banned: bool
    reason: str = ""


def _bucket_for(price: float) -> tuple[float, float]:
    for lo, hi in BUCKETS:
        if lo <= price < hi:
            return lo, hi
    return BUCKETS[-1]


def required_wr_for_price(price: float, *, fee_rate: float = 0.07, buffer: float = 0.02) -> float:
    """Breakeven WR ≈ entry + fee cushion + safety buffer."""
    fee = fee_rate * price * (1.0 - price)
    # Capital at risk is roughly entry; need WR > (entry+fee) for positive EV after fee
    return min(0.999, max(price + fee + buffer, price + buffer))


def load_bucket_stats(
    db_path: Path,
    *,
    lookback_sec: float = 7 * 86400,
    min_samples: int = 8,
    fee_rate: float = 0.07,
    wr_buffer: float = 0.02,
) -> list[BucketStats]:
    if not db_path.exists():
        return []
    since = time.time() - lookback_sec
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)")}
        if "entry_price" not in cols:
            return []
        net_expr = "COALESCE(pnl_net_usd, pnl_usd)" if "pnl_net_usd" in cols else "pnl_usd"
        rows = conn.execute(
            f"""
            SELECT entry_price, {net_expr} AS net
            FROM positions
            WHERE status='closed' AND closed_ts >= ? AND entry_price IS NOT NULL
            """,
            (since,),
        ).fetchall()
    finally:
        conn.close()

    agg: dict[tuple[float, float], list[float]] = {b: [] for b in BUCKETS}
    for row in rows:
        try:
            px = float(row["entry_price"])
            net = float(row["net"] or 0.0)
        except (TypeError, ValueError):
            continue
        agg[_bucket_for(px)].append(net)

    out: list[BucketStats] = []
    for lo, hi in BUCKETS:
        vals = agg[(lo, hi)]
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        wr = (wins / n) if n else 0.0
        mid = (lo + min(hi, 0.99)) / 2.0
        req = required_wr_for_price(mid, fee_rate=fee_rate, buffer=wr_buffer)
        banned = False
        reason = ""
        if (lo, hi) in FORCE_BAN_BUCKETS:
            banned = True
            reason = (
                f"bucket[{lo:.2f},{hi:.2f}) force-banned (P0 toxic band; "
                f"WR={wr:.1%} n={n} required {req:.1%})"
            )
        elif n >= min_samples and wr + 1e-12 < req:
            banned = True
            reason = f"bucket[{lo:.2f},{hi:.2f}) WR={wr:.1%} < required {req:.1%} (n={n})"
        out.append(
            BucketStats(
                lo=lo,
                hi=hi,
                n=n,
                wins=wins,
                wr=wr,
                required_wr=req,
                net_pnl_usd=sum(vals),
                banned=banned,
                reason=reason,
            )
        )
    return out


def bucket_ban_reason(
    price: float,
    db_path: Path,
    *,
    lookback_sec: float = 7 * 86400,
    min_samples: int = 8,
    fee_rate: float = 0.07,
    wr_buffer: float = 0.02,
) -> Optional[str]:
    stats = load_bucket_stats(
        db_path,
        lookback_sec=lookback_sec,
        min_samples=min_samples,
        fee_rate=fee_rate,
        wr_buffer=wr_buffer,
    )
    lo, hi = _bucket_for(price)
    for s in stats:
        if s.lo == lo and s.hi == hi and s.banned:
            return s.reason
    return None
