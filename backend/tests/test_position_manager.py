"""Unit tests for PositionManager"""
import pytest
from app.services.position_manager import PositionManager, PositionTracker


class TestPositionTracker:
    """Test cases for PositionTracker"""

    def test_initialization(self):
        """Test tracker initialization"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")
        assert tracker.strategy_id == 1
        assert tracker.ladder_index == 0
        assert tracker.strategy_type == "reverse"
        assert tracker.current_position == 0.0
        assert tracker.total_opened == 0.0
        assert tracker.total_closed == 0.0

    def test_add_opening(self):
        """Test adding opening position"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        result = tracker.add_opening(5.0)
        assert result is True
        assert tracker.current_position == 5.0
        assert tracker.total_opened == 5.0

        result = tracker.add_opening(3.0)
        assert result is True
        assert tracker.current_position == 8.0
        assert tracker.total_opened == 8.0

    def test_add_closing(self):
        """Test adding closing position"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        # Open position first
        tracker.add_opening(10.0)

        # Close partial
        result = tracker.add_closing(3.0)
        assert result is True
        assert tracker.current_position == 7.0
        assert tracker.total_closed == 3.0

        # Close more
        result = tracker.add_closing(4.0)
        assert result is True
        assert tracker.current_position == 3.0
        assert tracker.total_closed == 7.0

    def test_add_closing_insufficient_position(self):
        """Test closing with insufficient position"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        tracker.add_opening(5.0)

        # Try to close more than available
        result = tracker.add_closing(10.0)
        assert result is False
        assert tracker.current_position == 5.0  # Unchanged
        assert tracker.total_closed == 0.0  # Unchanged

    def test_can_open(self):
        """Test can_open check"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        assert tracker.can_open(5.0, 10.0) is True

        tracker.add_opening(7.0)
        assert tracker.can_open(3.0, 10.0) is True
        assert tracker.can_open(4.0, 10.0) is False

    def test_can_close(self):
        """Test can_close check"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        assert tracker.can_close(5.0) is False

        tracker.add_opening(10.0)
        assert tracker.can_close(5.0) is True
        assert tracker.can_close(10.0) is True
        assert tracker.can_close(11.0) is False

    def test_get_remaining_capacity(self):
        """Test remaining capacity calculation"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        assert tracker.get_remaining_capacity(10.0) == 10.0

        tracker.add_opening(7.0)
        assert tracker.get_remaining_capacity(10.0) == 3.0

        tracker.add_opening(5.0)
        assert tracker.get_remaining_capacity(10.0) == 0.0

    def test_reset(self):
        """Test reset functionality"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")

        tracker.add_opening(10.0)
        tracker.add_closing(3.0)

        tracker.reset()

        assert tracker.current_position == 0.0
        assert tracker.total_opened == 0.0
        assert tracker.total_closed == 0.0
        assert tracker.last_update_time is None

    def test_to_dict(self):
        """Test dictionary conversion"""
        tracker = PositionTracker(strategy_id=1, ladder_index=0, strategy_type="reverse")
        tracker.add_opening(5.0)

        data = tracker.to_dict()

        assert data["strategy_id"] == 1
        assert data["ladder_index"] == 0
        assert data["strategy_type"] == "reverse"
        assert data["current_position"] == 5.0
        assert data["total_opened"] == 5.0
        assert data["total_closed"] == 0.0
        assert data["last_update_time"] is not None


class TestPositionManager:
    """Test cases for PositionManager"""

    def test_initialization(self):
        """Test manager initialization"""
        manager = PositionManager()
        assert len(manager._trackers) == 0

    def test_get_tracker(self):
        """Test getting tracker"""
        manager = PositionManager()

        tracker1 = manager.get_tracker(1, 0, "reverse")
        assert tracker1.strategy_id == 1
        assert tracker1.ladder_index == 0

        # Getting same tracker should return same instance
        tracker2 = manager.get_tracker(1, 0, "reverse")
        assert tracker1 is tracker2

        # Different ladder should return different instance
        tracker3 = manager.get_tracker(1, 1, "reverse")
        assert tracker1 is not tracker3

    def test_record_opening(self):
        """Test recording opening"""
        manager = PositionManager()

        result = manager.record_opening(1, 0, "reverse", 5.0)
        assert result is True

        tracker = manager.get_tracker(1, 0, "reverse")
        assert tracker.current_position == 5.0

    def test_record_closing(self):
        """Test recording closing"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 10.0)
        result = manager.record_closing(1, 0, "reverse", 3.0)
        assert result is True

        tracker = manager.get_tracker(1, 0, "reverse")
        assert tracker.current_position == 7.0

    def test_record_closing_insufficient(self):
        """Test recording closing with insufficient position"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 5.0)
        result = manager.record_closing(1, 0, "reverse", 10.0)
        assert result is False

        tracker = manager.get_tracker(1, 0, "reverse")
        assert tracker.current_position == 5.0  # Unchanged

    def test_check_can_open(self):
        """Test can open check"""
        manager = PositionManager()

        result = manager.check_can_open(1, 0, "reverse", 5.0, 10.0)
        assert result["can_open"] is True
        assert result["remaining_capacity"] == 10.0

        manager.record_opening(1, 0, "reverse", 7.0)
        result = manager.check_can_open(1, 0, "reverse", 5.0, 10.0)
        assert result["can_open"] is False
        assert result["remaining_capacity"] == 3.0
        assert "超出最大持仓限制" in result["reason"]

    def test_check_can_close(self):
        """Test can close check"""
        manager = PositionManager()

        result = manager.check_can_close(1, 0, "reverse", 5.0)
        assert result["can_close"] is False
        assert "持仓不足" in result["reason"]

        manager.record_opening(1, 0, "reverse", 10.0)
        result = manager.check_can_close(1, 0, "reverse", 5.0)
        assert result["can_close"] is True
        assert result["reason"] is None

    def test_get_position(self):
        """Test getting position"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 5.0)
        position = manager.get_position(1, 0, "reverse")

        assert position["current_position"] == 5.0
        assert position["total_opened"] == 5.0

    def test_get_all_positions(self):
        """Test getting all positions"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 5.0)
        manager.record_opening(1, 1, "reverse", 3.0)
        manager.record_opening(2, 0, "forward", 7.0)

        all_positions = manager.get_all_positions()
        assert len(all_positions) == 3

        strategy1_positions = manager.get_all_positions(strategy_id=1)
        assert len(strategy1_positions) == 2

    def test_reset_strategy(self):
        """Test resetting strategy"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 5.0)
        manager.record_opening(1, 1, "reverse", 3.0)
        manager.record_opening(2, 0, "forward", 7.0)

        manager.reset_strategy(1)

        tracker1_0 = manager.get_tracker(1, 0, "reverse")
        tracker1_1 = manager.get_tracker(1, 1, "reverse")
        tracker2_0 = manager.get_tracker(2, 0, "forward")

        assert tracker1_0.current_position == 0.0
        assert tracker1_1.current_position == 0.0
        assert tracker2_0.current_position == 7.0  # Unchanged

    def test_reset_ladder(self):
        """Test resetting ladder"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 5.0)
        manager.record_opening(1, 1, "reverse", 3.0)

        manager.reset_ladder(1, 0)

        tracker1_0 = manager.get_tracker(1, 0, "reverse")
        tracker1_1 = manager.get_tracker(1, 1, "reverse")

        assert tracker1_0.current_position == 0.0
        assert tracker1_1.current_position == 3.0  # Unchanged

    def test_get_strategy_summary(self):
        """Test getting strategy summary"""
        manager = PositionManager()

        manager.record_opening(1, 0, "reverse", 5.0)
        manager.record_opening(1, 1, "reverse", 3.0)
        manager.record_closing(1, 0, "reverse", 2.0)

        summary = manager.get_strategy_summary(1)

        assert summary["strategy_id"] == 1
        assert summary["total_current_position"] == 6.0  # 5-2+3
        assert summary["total_opened"] == 8.0
        assert summary["total_closed"] == 2.0
        assert summary["ladder_count"] == 2
