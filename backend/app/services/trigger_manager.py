"""Trigger Count Manager for Arbitrage Strategy V2.0"""
import time
from typing import Dict, Optional
from enum import Enum


class CompareOperator(str, Enum):
    """Comparison operators for spread checking"""
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="


class TriggerCountManager:
    """
    Manages trigger counts for arbitrage strategy execution.

    Prevents over-trading by requiring multiple trigger confirmations
    before executing orders.
    """

    def __init__(self, strategy_id: int, action: str):
        """
        Initialize trigger count manager.

        Args:
            strategy_id: Strategy configuration ID
            action: Action type ('reverse_opening', 'reverse_closing',
                   'forward_opening', 'forward_closing')
        """
        self.strategy_id = strategy_id
        self.action = action
        self.count = 0
        self.last_trigger_time: Optional[float] = None
        self.min_trigger_interval = 0.1  # 100ms minimum between triggers

    async def check_and_increment(
        self,
        current_spread: float,
        threshold: float,
        compare_op: CompareOperator
    ) -> bool:
        """
        Check if spread meets condition and increment trigger count.

        Args:
            current_spread: Current market spread value
            threshold: Threshold spread value from configuration
            compare_op: Comparison operator ('>=' or '<=')

        Returns:
            True if trigger was incremented, False otherwise
        """
        # Prevent duplicate triggers within minimum interval
        current_time = time.time()
        if self.last_trigger_time:
            time_since_last = current_time - self.last_trigger_time
            if time_since_last < self.min_trigger_interval:
                return False

        # Check spread condition
        triggered = False
        if compare_op == CompareOperator.GREATER_EQUAL:
            triggered = current_spread >= threshold
        elif compare_op == CompareOperator.LESS_EQUAL:
            triggered = current_spread <= threshold

        if triggered:
            self.count += 1
            self.last_trigger_time = current_time
            return True

        return False

    def reset(self):
        """Reset trigger count and last trigger time"""
        self.count = 0
        self.last_trigger_time = None

    def is_ready(self, required_count: int) -> bool:
        """
        Check if trigger count has reached required threshold.

        Args:
            required_count: Required number of triggers

        Returns:
            True if count >= required_count
        """
        return self.count >= required_count

    def get_progress(self, required_count: int) -> Dict[str, any]:
        """
        Get current trigger progress.

        Args:
            required_count: Required number of triggers

        Returns:
            Dictionary with progress information
        """
        return {
            "current_count": self.count,
            "required_count": required_count,
            "progress_percent": min(100, (self.count / required_count) * 100) if required_count > 0 else 0,
            "is_ready": self.is_ready(required_count),
            "last_trigger_time": self.last_trigger_time
        }


class TriggerManagerRegistry:
    """
    Registry to manage multiple TriggerCountManager instances.

    Maintains separate trigger managers for different strategies and actions.
    """

    def __init__(self):
        self._managers: Dict[str, TriggerCountManager] = {}

    def get_manager(self, strategy_id: int, action: str) -> TriggerCountManager:
        """
        Get or create trigger manager for strategy and action.

        Args:
            strategy_id: Strategy configuration ID
            action: Action type

        Returns:
            TriggerCountManager instance
        """
        key = f"{strategy_id}:{action}"
        if key not in self._managers:
            self._managers[key] = TriggerCountManager(strategy_id, action)
        return self._managers[key]

    def reset_manager(self, strategy_id: int, action: str):
        """Reset trigger manager for strategy and action"""
        key = f"{strategy_id}:{action}"
        if key in self._managers:
            self._managers[key].reset()

    def remove_manager(self, strategy_id: int, action: str):
        """Remove trigger manager from registry"""
        key = f"{strategy_id}:{action}"
        if key in self._managers:
            del self._managers[key]

    def get_all_progress(self) -> Dict[str, Dict]:
        """Get progress for all registered managers"""
        return {
            key: manager.get_progress(1)  # Default required count
            for key, manager in self._managers.items()
        }


# Global registry instance
trigger_registry = TriggerManagerRegistry()
