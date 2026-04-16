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

    Prevents over-trading by requiring multiple trigger confirmations before
    executing orders (sync_count / trigger_count_required).

    Express Mode (极速模式) — dual trigger:
    Fires when EITHER condition is met:

    1. ABSOLUTE: excess >= EXPRESS_ABSOLUTE_POINTS (default 2.0 pts)
       For XAUUSD, 2 points is already extreme. Captures large sudden moves
       regardless of how small the threshold is.

    2. RELATIVE: excess >= EXPRESS_RELATIVE_FACTOR × abs(threshold)
       When threshold itself is large (e.g. 6.0), a 2-pt excess is normal,
       so we additionally require proportional deviation.

    Either condition alone is sufficient to skip all remaining sync confirmations
    and fire on the very next loop iteration.

    Example (threshold=0.5, sync_count=9, ABSOLUTE=2.0):
      spread=0.6  → excess=0.1 < 2.0  → normal accumulate
      spread=2.5  → excess=2.0 >= 2.0 → EXPRESS FIRE  ← 2 pts above threshold
      spread=5.0  → excess=4.5 >= 2.0 → EXPRESS FIRE

    Example (threshold=-6.0 forward_closing, ABSOLUTE=2.0, RELATIVE=4.0):
      spread=-7.0  → excess=1.0 < 2.0, ratio=0.17 < 4.0 → normal accumulate
      spread=-8.0  → excess=2.0 >= 2.0 → EXPRESS FIRE  ← 2 pts below threshold
      spread=-30.0 → excess=24 >= 2.0  → EXPRESS FIRE
    """

    EXPRESS_ABSOLUTE_POINTS = 2.0   # Any excess >= 2 pts → express fire
    EXPRESS_RELATIVE_FACTOR = 4.0   # Or excess >= 4× abs(threshold) → express fire

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
        compare_op: CompareOperator,
        required_count: int = 1,
    ) -> bool:
        """
        Check if spread meets condition and increment trigger count.

        Express Mode fires when either:
          - absolute excess >= EXPRESS_ABSOLUTE_POINTS (2 pts), OR
          - relative excess >= EXPRESS_RELATIVE_FACTOR × abs(threshold)

        Args:
            current_spread: Current market spread value
            threshold: Threshold spread value from configuration
            compare_op: Comparison operator ('>=' or '<=')
            required_count: Total confirmations needed (used by express mode skip)

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

        if not triggered:
            return False

        # ── Express Mode: dual-trigger ─────────────────────────────────────
        # XAUUSD normal spread range is 0.3-1.5 pts. "2 pts is already a lot."
        # → Skip remaining sync confirmations when EITHER condition fires:
        #
        # A) ABSOLUTE: excess >= 2.0 pts
        #    e.g. threshold=0.5, spread=2.5 → excess=2.0 → EXPRESS ✅
        #    e.g. threshold=-6, spread=-8.0 → excess=2.0 → EXPRESS ✅
        #
        # B) RELATIVE: excess >= 4× abs(threshold)  (large-threshold safety)
        #    e.g. threshold=6.0, spread=30 → ratio=4.0 → EXPRESS ✅
        if required_count > 1:
            if compare_op == CompareOperator.GREATER_EQUAL:
                excess = current_spread - threshold
            else:
                excess = threshold - current_spread  # positive when triggered

            express_absolute = excess >= self.EXPRESS_ABSOLUTE_POINTS
            ref = abs(threshold)
            express_relative = (ref > 0) and ((excess / ref) >= self.EXPRESS_RELATIVE_FACTOR)

            if express_absolute or express_relative:
                self.count = required_count
                self.last_trigger_time = current_time
                return True

        self.count += 1
        self.last_trigger_time = current_time
        return True

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

    def get_count(self) -> int:
        """
        Get current trigger count.

        Returns:
            Current trigger count
        """
        return self.count

    def set_count(self, count: int):
        """
        Set trigger count (primarily for testing).

        Args:
            count: Trigger count to set
        """
        self.count = max(0, count)  # Ensure non-negative


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
