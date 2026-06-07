"""Ladder Range Mapper — Position-based ladder selection for cumulative qtyLimit model.

Maps global position + current spread to the active ladder for opening or closing.
Ladders use cumulative total_qty: ladder[0]=[0, qty0], ladder[1]=[qty0, qty1], etc.
"""
from dataclasses import dataclass
from typing import List, Optional

from app.services.continuous_executor import LadderConfig


@dataclass
class ActiveLadder:
    """Result of ladder selection — describes what to do next."""
    index: int
    config: LadderConfig
    remaining_capacity: float
    range_lower: float
    range_upper: float


class LadderRangeMapper:
    """Maps global position to active ladder based on cumulative qtyLimit ranges.

    Example with ladders [total_qty=100, total_qty=200]:
      - Ladder 0 range: [0, 100)
      - Ladder 1 range: [100, 200)
      - Global capacity: 200
    """

    def __init__(self, ladders: List[LadderConfig]):
        self._ladders = [l for l in ladders if l.enabled]
        self._ranges: List[tuple] = []

        prev_upper = 0.0
        for ladder in self._ladders:
            # total_qty 允许相同/非递增：相同→空区间(无害无操作)，不再报错
            self._ranges.append((prev_upper, ladder.total_qty))
            prev_upper = ladder.total_qty

    def get_active_ladder_for_opening(
        self, global_pos: float, current_spread: float
    ) -> Optional[ActiveLadder]:
        """Find the active ladder for opening based on spread and position.

        Logic: Walk ladders in order. For each ladder where
        current_spread >= opening_spread AND global_pos < upper_bound,
        return it with remaining capacity.

        The highest-matching ladder wins (spread=4.5 with ladder1.open=3, ladder2.open=4
        -> ladder2 is active, provided position allows).
        But position must reach each ladder's lower bound first (sequential filling).
        """
        result = None
        for i, ladder in enumerate(self._ladders):
            lower, upper = self._ranges[i]

            if current_spread < ladder.opening_spread:
                continue

            if global_pos >= upper:
                continue

            remaining = upper - max(global_pos, lower)
            if remaining <= 0:
                continue

            result = ActiveLadder(
                index=i,
                config=ladder,
                remaining_capacity=remaining,
                range_lower=lower,
                range_upper=upper,
            )

        return result

    def get_active_ladder_for_closing(
        self, live_position: float, current_spread: float
    ) -> Optional[ActiveLadder]:
        """Find the active ladder for closing based on LIVE POSITION and spread.

        Args:
            live_position: Actual position from exchange (Binance short/long qty)
            current_spread: Current closing spread value

        Logic: Walk ladders in REVERSE (highest to lowest). For each ladder where
        live_position > lower_bound AND current_spread <= closing_spread,
        close down to lower_bound.

        Example: holding 200, ladder2.threshold=2, spread=1.98
        -> close from 200 to 100 (ladder1 upper = ladder2 lower)
        """
        global_pos = live_position
        for i in range(len(self._ladders) - 1, -1, -1):
            ladder = self._ladders[i]
            lower, upper = self._ranges[i]

            if global_pos <= lower:
                continue

            if current_spread > ladder.closing_spread:
                continue

            close_qty = global_pos - lower
            if close_qty <= 0:
                continue

            return ActiveLadder(
                index=i,
                config=ladder,
                remaining_capacity=close_qty,
                range_lower=lower,
                range_upper=upper,
            )

        return None

    def get_global_capacity(self) -> float:
        """Maximum position across all ladders (last ladder's total_qty)."""
        if not self._ladders:
            return 0.0
        return self._ranges[-1][1]
