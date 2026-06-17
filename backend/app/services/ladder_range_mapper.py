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
        """Find the active ladder for opening — STRICT SEQUENTIAL by position.

        修(20260617): 原为"最高匹配优先"(不 break, 最后一个匹配覆盖) ->
        点差同时越过多个阶梯阈值时会跳过低阶梯(实测 cq002 持仓0
        点差-1.17 同时满足阶梯1(-1.5)/阶梯2(-1.2) -> 错选阶梯2)。
        改为按持仓所处区间严格定位: 找“持仓落在的第一个未填满段”,
        只用该段自己的阈值判定; 达标则开, 不达则 None(绝不因更高段阈值更松而跳过)。
        -> 持仓0 必走阶梯1(0→60), 填满后才进阶梯2(60→150)。平仓侧本就对称(反序首匹配),不动。
        """
        for i, ladder in enumerate(self._ladders):
            lower, upper = self._ranges[i]

            # 该段已填满 -> 看下一段
            if global_pos >= upper:
                continue

            # 持仓落在本段 [lower, upper): 这就是当前唯一应操作的阶梯。
            # 只看本段阈值: 达标则开, 不达则不开(等点差), 绝不跳到更高段。
            if current_spread < ladder.opening_spread:
                return None

            remaining = upper - max(global_pos, lower)
            if remaining <= 0:
                return None

            return ActiveLadder(
                index=i,
                config=ladder,
                remaining_capacity=remaining,
                range_lower=lower,
                range_upper=upper,
            )

        return None

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
