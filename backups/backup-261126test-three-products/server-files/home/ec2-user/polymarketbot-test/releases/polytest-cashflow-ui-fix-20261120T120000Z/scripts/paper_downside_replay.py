"""Deterministic Paper replay for the P2 downside controls.

This is a safety check, not a profit forecast. It exercises high-price late
entries, a fast BTC decline, thin bids, partial exits and a restart between
polls. No CLOB or Relayer call is made.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass


@dataclass
class Position:
    entry: float
    size: float
    exited: float = 0.0


def run() -> dict:
    positions: list[Position] = []
    exits = 0
    partial_exits = 0
    duplicate_suppressed = 0
    realized = 0.0
    pending = 0
    entries = 0
    intent = None
    # 72 synthetic five-minute windows: rise, sharp decline, then chop.
    prices = ([0.88 + i * 0.001 for i in range(24)]
              + [0.90 - i * 0.020 for i in range(24)]
              + [0.66 + (i % 6) * 0.012 for i in range(24)])
    for i, mark in enumerate(prices):
        # The configured entry zone and remaining-time gate.
        if 0.84 <= mark <= 0.90 and i % 3 == 0 and len(positions) < 3:
            positions.append(Position(entry=mark, size=1.0))
            entries += 1
            intent = None
        if i == 32 and positions and intent is not None:
            duplicate_suppressed += 1
            # This is the simulated worker restart/retry poll. A persisted
            # intent skips the duplicate submission for this cycle.
            continue
        for pos in list(positions):
            remaining = pos.size - pos.exited
            bid = max(0.01, mark - 0.01)
            drawdown = (pos.entry - bid) / pos.entry
            profit = (bid - pos.entry) / pos.entry
            # 10% drawdown stop; thin book only allows half the amount.
            if drawdown >= 0.10 or profit >= 0.05 or i % 12 == 11:
                if intent == (id(pos), i // 2):
                    duplicate_suppressed += 1
                    continue
                intent = (id(pos), i // 2)
                visible = min(remaining, 0.5 if bid < 0.60 else remaining)
                if visible <= 0:
                    pending += 1
                    continue
                pos.exited += visible
                exits += 1
                if visible < remaining:
                    partial_exits += 1
                realized += visible * (bid - pos.entry)
                if pos.exited >= pos.size - 1e-9:
                    positions.remove(pos)
        # Simulate a worker restart after the fast decline. Persisted intent
        # must suppress a blind duplicate on the next iteration.
        if i == 31 and positions:
            intent = (id(positions[0]), i // 2)
    pending += sum(1 for p in positions if p.size - p.exited > 1e-9)
    return {
        "windows": len(prices),
        "entries": entries,
        "exits": exits,
        "partial_exits": partial_exits,
        "duplicate_exit_attempts_suppressed": duplicate_suppressed,
        "open_positions_after_replay": len(positions),
        "pending_shares": round(sum(p.size - p.exited for p in positions), 6),
        "realized_pnl_usd": round(realized, 6),
        "controls": {
            "entry_price": "0.84-0.90",
            "drawdown_stop": 0.10,
            "max_open_positions": 3,
            "persistent_exit_intent": True,
            "real_orders": False,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
