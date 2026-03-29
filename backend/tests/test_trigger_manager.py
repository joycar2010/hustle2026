"""Unit tests for TriggerCountManager"""
import pytest
import asyncio
import time
from app.services.trigger_manager import (
    TriggerCountManager,
    TriggerManagerRegistry,
    CompareOperator
)


class TestTriggerCountManager:
    """Test cases for TriggerCountManager"""

    def test_initialization(self):
        """Test manager initialization"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_opening")
        assert manager.strategy_id == 1
        assert manager.action == "reverse_opening"
        assert manager.count == 0
        assert manager.last_trigger_time is None

    @pytest.mark.asyncio
    async def test_check_and_increment_greater_equal(self):
        """Test trigger increment with >= operator"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_opening")

        # Spread meets condition
        result = await manager.check_and_increment(
            current_spread=10.5,
            threshold=10.0,
            compare_op=CompareOperator.GREATER_EQUAL
        )
        assert result is True
        assert manager.count == 1

        # Spread doesn't meet condition
        result = await manager.check_and_increment(
            current_spread=9.5,
            threshold=10.0,
            compare_op=CompareOperator.GREATER_EQUAL
        )
        assert result is False
        assert manager.count == 1  # Count unchanged

    @pytest.mark.asyncio
    async def test_check_and_increment_less_equal(self):
        """Test trigger increment with <= operator"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_closing")

        # Spread meets condition
        result = await manager.check_and_increment(
            current_spread=5.0,
            threshold=10.0,
            compare_op=CompareOperator.LESS_EQUAL
        )
        assert result is True
        assert manager.count == 1

        # Spread doesn't meet condition
        result = await manager.check_and_increment(
            current_spread=15.0,
            threshold=10.0,
            compare_op=CompareOperator.LESS_EQUAL
        )
        assert result is False
        assert manager.count == 1  # Count unchanged

    @pytest.mark.asyncio
    async def test_anti_duplicate_trigger(self):
        """Test anti-duplicate trigger mechanism"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_opening")

        # First trigger
        result1 = await manager.check_and_increment(
            current_spread=10.5,
            threshold=10.0,
            compare_op=CompareOperator.GREATER_EQUAL
        )
        assert result1 is True
        assert manager.count == 1

        # Immediate second trigger (should be blocked)
        result2 = await manager.check_and_increment(
            current_spread=10.5,
            threshold=10.0,
            compare_op=CompareOperator.GREATER_EQUAL
        )
        assert result2 is False
        assert manager.count == 1  # Count unchanged

        # Wait for minimum interval
        await asyncio.sleep(0.11)

        # Third trigger (should succeed)
        result3 = await manager.check_and_increment(
            current_spread=10.5,
            threshold=10.0,
            compare_op=CompareOperator.GREATER_EQUAL
        )
        assert result3 is True
        assert manager.count == 2

    def test_reset(self):
        """Test reset functionality"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_opening")
        manager.count = 5
        manager.last_trigger_time = time.time()

        manager.reset()

        assert manager.count == 0
        assert manager.last_trigger_time is None

    def test_is_ready(self):
        """Test is_ready check"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_opening")

        assert manager.is_ready(3) is False

        manager.count = 2
        assert manager.is_ready(3) is False

        manager.count = 3
        assert manager.is_ready(3) is True

        manager.count = 5
        assert manager.is_ready(3) is True

    def test_get_progress(self):
        """Test progress reporting"""
        manager = TriggerCountManager(strategy_id=1, action="reverse_opening")
        manager.count = 2

        progress = manager.get_progress(required_count=5)

        assert progress["current_count"] == 2
        assert progress["required_count"] == 5
        assert progress["progress_percent"] == 40.0
        assert progress["is_ready"] is False

        manager.count = 5
        progress = manager.get_progress(required_count=5)
        assert progress["progress_percent"] == 100.0
        assert progress["is_ready"] is True


class TestTriggerManagerRegistry:
    """Test cases for TriggerManagerRegistry"""

    def test_get_manager(self):
        """Test getting manager from registry"""
        registry = TriggerManagerRegistry()

        manager1 = registry.get_manager(strategy_id=1, action="reverse_opening")
        assert manager1.strategy_id == 1
        assert manager1.action == "reverse_opening"

        # Getting same manager should return same instance
        manager2 = registry.get_manager(strategy_id=1, action="reverse_opening")
        assert manager1 is manager2

        # Different strategy/action should return different instance
        manager3 = registry.get_manager(strategy_id=1, action="reverse_closing")
        assert manager1 is not manager3

    def test_reset_manager(self):
        """Test resetting manager in registry"""
        registry = TriggerManagerRegistry()

        manager = registry.get_manager(strategy_id=1, action="reverse_opening")
        manager.count = 5

        registry.reset_manager(strategy_id=1, action="reverse_opening")

        assert manager.count == 0

    def test_remove_manager(self):
        """Test removing manager from registry"""
        registry = TriggerManagerRegistry()

        manager1 = registry.get_manager(strategy_id=1, action="reverse_opening")
        manager1.count = 5

        registry.remove_manager(strategy_id=1, action="reverse_opening")

        # Getting manager again should create new instance
        manager2 = registry.get_manager(strategy_id=1, action="reverse_opening")
        assert manager2.count == 0
        assert manager1 is not manager2

    def test_get_all_progress(self):
        """Test getting progress for all managers"""
        registry = TriggerManagerRegistry()

        manager1 = registry.get_manager(strategy_id=1, action="reverse_opening")
        manager1.count = 2

        manager2 = registry.get_manager(strategy_id=1, action="reverse_closing")
        manager2.count = 3

        all_progress = registry.get_all_progress()

        assert "1:reverse_opening" in all_progress
        assert "1:reverse_closing" in all_progress
        assert all_progress["1:reverse_opening"]["current_count"] == 2
        assert all_progress["1:reverse_closing"]["current_count"] == 3
