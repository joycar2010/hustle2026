"""Position Manager for tracking arbitrage positions"""
from typing import Dict, List, Optional
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.account import Account


class PositionTracker:
    """
    Tracks positions for a specific strategy and ladder.

    Prevents over-trading by maintaining accurate position counts.
    """

    def __init__(self, strategy_id: int, ladder_index: int, strategy_type: str):
        """
        Initialize position tracker.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index (0-4)
            strategy_type: 'forward' or 'reverse'
        """
        self.strategy_id = strategy_id
        self.ladder_index = ladder_index
        self.strategy_type = strategy_type
        self.current_position = 0.0
        self.total_opened = 0.0
        self.total_closed = 0.0
        self.last_update_time: Optional[datetime] = None

    def add_opening(self, quantity: float) -> bool:
        """
        Add opening position.

        Args:
            quantity: Quantity to add

        Returns:
            True if successful
        """
        self.current_position += quantity
        self.total_opened += quantity
        self.last_update_time = datetime.utcnow()
        return True

    def add_closing(self, quantity: float) -> bool:
        """
        Add closing position.

        Args:
            quantity: Quantity to close

        Returns:
            True if successful, False if insufficient position
        """
        if quantity > self.current_position:
            return False

        self.current_position -= quantity
        self.total_closed += quantity
        self.last_update_time = datetime.utcnow()
        return True

    def can_open(self, quantity: float, max_position: float) -> bool:
        """
        Check if can open more positions.

        Args:
            quantity: Quantity to open
            max_position: Maximum allowed position

        Returns:
            True if can open
        """
        return (self.current_position + quantity) <= max_position

    def can_close(self, quantity: float) -> bool:
        """
        Check if can close positions.

        Args:
            quantity: Quantity to close

        Returns:
            True if can close
        """
        return quantity <= self.current_position

    def get_remaining_capacity(self, max_position: float) -> float:
        """
        Get remaining capacity for opening.

        Args:
            max_position: Maximum allowed position

        Returns:
            Remaining capacity
        """
        return max(0, max_position - self.current_position)

    def reset(self):
        """Reset position tracker"""
        self.current_position = 0.0
        self.total_opened = 0.0
        self.total_closed = 0.0
        self.last_update_time = None

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "strategy_id": self.strategy_id,
            "ladder_index": self.ladder_index,
            "strategy_type": self.strategy_type,
            "current_position": self.current_position,
            "total_opened": self.total_opened,
            "total_closed": self.total_closed,
            "last_update_time": self.last_update_time.isoformat() if self.last_update_time else None,
        }


class PositionManager:
    """
    Manages positions for all strategies and ladders.

    Provides centralized position tracking and query capabilities.
    """

    def __init__(self):
        self._trackers: Dict[str, PositionTracker] = {}

    def _get_key(self, strategy_id: int, ladder_index: int) -> str:
        """Generate unique key for tracker"""
        return f"{strategy_id}:{ladder_index}"

    def get_tracker(
        self,
        strategy_id: int,
        ladder_index: int,
        strategy_type: str
    ) -> PositionTracker:
        """
        Get or create position tracker.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
            strategy_type: Strategy type

        Returns:
            PositionTracker instance
        """
        key = self._get_key(strategy_id, ladder_index)
        if key not in self._trackers:
            self._trackers[key] = PositionTracker(
                strategy_id, ladder_index, strategy_type
            )
        return self._trackers[key]

    def record_opening(
        self,
        strategy_id: int,
        ladder_index: int,
        strategy_type: str,
        quantity: float
    ) -> bool:
        """
        Record opening position.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
            strategy_type: Strategy type
            quantity: Quantity opened

        Returns:
            True if successful
        """
        tracker = self.get_tracker(strategy_id, ladder_index, strategy_type)
        return tracker.add_opening(quantity)

    def record_closing(
        self,
        strategy_id: int,
        ladder_index: int,
        strategy_type: str,
        quantity: float
    ) -> bool:
        """
        Record closing position.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
            strategy_type: Strategy type
            quantity: Quantity closed

        Returns:
            True if successful, False if insufficient position
        """
        tracker = self.get_tracker(strategy_id, ladder_index, strategy_type)
        return tracker.add_closing(quantity)

    def check_can_open(
        self,
        strategy_id: int,
        ladder_index: int,
        strategy_type: str,
        quantity: float,
        max_position: float
    ) -> Dict[str, any]:
        """
        Check if can open position.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
            strategy_type: Strategy type
            quantity: Quantity to open
            max_position: Maximum allowed position

        Returns:
            Dictionary with check result
        """
        tracker = self.get_tracker(strategy_id, ladder_index, strategy_type)

        can_open = tracker.can_open(quantity, max_position)
        remaining = tracker.get_remaining_capacity(max_position)

        return {
            "can_open": can_open,
            "current_position": tracker.current_position,
            "requested_quantity": quantity,
            "max_position": max_position,
            "remaining_capacity": remaining,
            "reason": None if can_open else f"超出最大持仓限制: 当前{tracker.current_position} + 请求{quantity} > 最大{max_position}"
        }

    def check_can_close(
        self,
        strategy_id: int,
        ladder_index: int,
        strategy_type: str,
        quantity: float
    ) -> Dict[str, any]:
        """
        Check if can close position.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
            strategy_type: Strategy type
            quantity: Quantity to close

        Returns:
            Dictionary with check result
        """
        tracker = self.get_tracker(strategy_id, ladder_index, strategy_type)

        can_close = tracker.can_close(quantity)

        return {
            "can_close": can_close,
            "current_position": tracker.current_position,
            "requested_quantity": quantity,
            "reason": None if can_close else f"持仓不足: 当前{tracker.current_position} < 请求{quantity}"
        }

    def get_position(
        self,
        strategy_id: int,
        ladder_index: int,
        strategy_type: str
    ) -> Dict:
        """
        Get current position for strategy and ladder.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
            strategy_type: Strategy type

        Returns:
            Position information dictionary
        """
        tracker = self.get_tracker(strategy_id, ladder_index, strategy_type)
        return tracker.to_dict()

    def get_all_positions(self, strategy_id: Optional[int] = None) -> List[Dict]:
        """
        Get all positions, optionally filtered by strategy.

        Args:
            strategy_id: Optional strategy ID filter

        Returns:
            List of position dictionaries
        """
        positions = []
        for tracker in self._trackers.values():
            if strategy_id is None or tracker.strategy_id == strategy_id:
                positions.append(tracker.to_dict())
        return positions

    def reset_strategy(self, strategy_id: int):
        """
        Reset all positions for a strategy.

        Args:
            strategy_id: Strategy configuration ID
        """
        keys_to_reset = [
            key for key, tracker in self._trackers.items()
            if tracker.strategy_id == strategy_id
        ]
        for key in keys_to_reset:
            self._trackers[key].reset()

    def reset_ladder(self, strategy_id: int, ladder_index: int):
        """
        Reset position for specific ladder.

        Args:
            strategy_id: Strategy configuration ID
            ladder_index: Ladder index
        """
        key = self._get_key(strategy_id, ladder_index)
        if key in self._trackers:
            self._trackers[key].reset()

    def get_strategy_summary(self, strategy_id: int) -> Dict:
        """
        Get summary of all positions for a strategy.

        Args:
            strategy_id: Strategy configuration ID

        Returns:
            Summary dictionary
        """
        positions = self.get_all_positions(strategy_id)

        total_current = sum(p["current_position"] for p in positions)
        total_opened = sum(p["total_opened"] for p in positions)
        total_closed = sum(p["total_closed"] for p in positions)

        return {
            "strategy_id": strategy_id,
            "total_current_position": total_current,
            "total_opened": total_opened,
            "total_closed": total_closed,
            "ladder_count": len(positions),
            "ladders": positions
        }


# Global instance
position_manager = PositionManager()
