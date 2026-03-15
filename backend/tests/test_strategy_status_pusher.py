"""
Unit tests for StrategyExecutionStatusPusher
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from app.services.strategy_status_pusher import StrategyExecutionStatusPusher


@pytest.fixture
def mock_websocket_manager():
    """Create mock WebSocket manager"""
    manager = Mock()
    manager.send_to_user = AsyncMock()
    manager.broadcast = AsyncMock()
    return manager


@pytest.fixture
async def status_pusher(mock_websocket_manager):
    """Create StrategyExecutionStatusPusher instance"""
    pusher = StrategyExecutionStatusPusher(mock_websocket_manager)
    yield pusher
    # Cleanup
    await pusher.stop()


@pytest.mark.asyncio
async def test_push_execution_started(status_pusher, mock_websocket_manager):
    """Test push_execution_started method"""
    strategy_id = 1
    user_id = 100
    strategy_type = "reverse_opening"

    await status_pusher.push_execution_started(strategy_id, user_id, strategy_type)

    # Wait for queue processing
    await asyncio.sleep(0.1)

    # Verify WebSocket send was called
    assert mock_websocket_manager.send_to_user.called
    call_args = mock_websocket_manager.send_to_user.call_args

    assert call_args[0][0] == user_id
    message = call_args[0][1]
    assert message["type"] == "strategy_execution_started"
    assert message["data"]["strategy_id"] == strategy_id
    assert message["data"]["strategy_type"] == strategy_type


@pytest.mark.asyncio
async def test_push_trigger_progress(status_pusher, mock_websocket_manager):
    """Test push_trigger_progress method"""
    strategy_id = 1
    user_id = 100
    current_count = 2
    required_count = 3

    await status_pusher.push_trigger_progress(
        strategy_id, user_id, current_count, required_count
    )

    # Wait for queue processing
    await asyncio.sleep(0.1)

    # Verify WebSocket send was called
    assert mock_websocket_manager.send_to_user.called
    call_args = mock_websocket_manager.send_to_user.call_args

    assert call_args[0][0] == user_id
    message = call_args[0][1]
    assert message["type"] == "strategy_trigger_progress"
    assert message["data"]["strategy_id"] == strategy_id
    assert message["data"]["current_count"] == current_count
    assert message["data"]["required_count"] == required_count


@pytest.mark.asyncio
async def test_push_position_change(status_pusher, mock_websocket_manager):
    """Test push_position_change method"""
    strategy_id = 1
    user_id = 100
    exchange = "bybit"
    position_data = {
        "symbol": "BTCUSDT",
        "side": "sell",
        "quantity": 0.01,
        "entry_price": 50000.0
    }

    await status_pusher.push_position_change(
        strategy_id, user_id, exchange, position_data
    )

    # Wait for queue processing
    await asyncio.sleep(0.1)

    # Verify WebSocket send was called
    assert mock_websocket_manager.send_to_user.called
    call_args = mock_websocket_manager.send_to_user.call_args

    assert call_args[0][0] == user_id
    message = call_args[0][1]
    assert message["type"] == "strategy_position_change"
    assert message["data"]["strategy_id"] == strategy_id
    assert message["data"]["exchange"] == exchange
    assert message["data"]["position"] == position_data


@pytest.mark.asyncio
async def test_push_order_executed(status_pusher, mock_websocket_manager):
    """Test push_order_executed method"""
    strategy_id = 1
    user_id = 100
    exchange = "mt5"
    order_data = {
        "symbol": "BTCUSD",
        "side": "buy",
        "quantity": 0.01,
        "price": 50000.0,
        "order_id": "12345"
    }

    await status_pusher.push_order_executed(
        strategy_id, user_id, exchange, order_data
    )

    # Wait for queue processing
    await asyncio.sleep(0.1)

    # Verify WebSocket send was called
    assert mock_websocket_manager.send_to_user.called
    call_args = mock_websocket_manager.send_to_user.call_args

    assert call_args[0][0] == user_id
    message = call_args[0][1]
    assert message["type"] == "strategy_order_executed"
    assert message["data"]["strategy_id"] == strategy_id
    assert message["data"]["exchange"] == exchange
    assert message["data"]["order"] == order_data


@pytest.mark.asyncio
async def test_push_error(status_pusher, mock_websocket_manager):
    """Test push_error method"""
    strategy_id = 1
    user_id = 100
    error_message = "Exchange API timeout"
    error_details = {"exchange": "bybit", "error_code": "TIMEOUT"}

    await status_pusher.push_error(
        strategy_id, user_id, error_message, error_details
    )

    # Wait for queue processing
    await asyncio.sleep(0.1)

    # Verify WebSocket send was called
    assert mock_websocket_manager.send_to_user.called
    call_args = mock_websocket_manager.send_to_user.call_args

    assert call_args[0][0] == user_id
    message = call_args[0][1]
    assert message["type"] == "strategy_error"
    assert message["data"]["strategy_id"] == strategy_id
    assert message["data"]["error"] == error_message
    assert message["data"]["details"] == error_details


@pytest.mark.asyncio
async def test_queue_processing(status_pusher, mock_websocket_manager):
    """Test async queue processing"""
    strategy_id = 1
    user_id = 100

    # Push multiple events
    await status_pusher.push_execution_started(strategy_id, user_id, "reverse_opening")
    await status_pusher.push_trigger_progress(strategy_id, user_id, 1, 3)
    await status_pusher.push_trigger_progress(strategy_id, user_id, 2, 3)
    await status_pusher.push_trigger_progress(strategy_id, user_id, 3, 3)

    # Wait for queue processing
    await asyncio.sleep(0.2)

    # Verify all events were sent
    assert mock_websocket_manager.send_to_user.call_count == 4


@pytest.mark.asyncio
async def test_broadcast_vs_targeted(status_pusher, mock_websocket_manager):
    """Test broadcast vs targeted push"""
    strategy_id = 1

    # Test targeted push (with user_id)
    await status_pusher.push_execution_started(strategy_id, 100, "reverse_opening")
    await asyncio.sleep(0.1)
    assert mock_websocket_manager.send_to_user.called
    assert not mock_websocket_manager.broadcast.called

    # Reset mocks
    mock_websocket_manager.send_to_user.reset_mock()
    mock_websocket_manager.broadcast.reset_mock()

    # Test broadcast push (without user_id)
    await status_pusher.push_execution_started(strategy_id, None, "reverse_opening")
    await asyncio.sleep(0.1)
    assert not mock_websocket_manager.send_to_user.called
    assert mock_websocket_manager.broadcast.called


@pytest.mark.asyncio
async def test_connection_failure(status_pusher, mock_websocket_manager):
    """Test connection failure handling"""
    strategy_id = 1
    user_id = 100

    # Simulate connection failure
    mock_websocket_manager.send_to_user.side_effect = Exception("Connection lost")

    # Push event should not raise exception
    await status_pusher.push_execution_started(strategy_id, user_id, "reverse_opening")
    await asyncio.sleep(0.1)

    # Verify error was logged but execution continued
    assert mock_websocket_manager.send_to_user.called


@pytest.mark.asyncio
async def test_execution_completed(status_pusher, mock_websocket_manager):
    """Test push_execution_completed method"""
    strategy_id = 1
    user_id = 100
    result = {
        "success": True,
        "profit": 10.5,
        "positions_closed": 2
    }

    await status_pusher.push_execution_completed(strategy_id, user_id, result)

    # Wait for queue processing
    await asyncio.sleep(0.1)

    # Verify WebSocket send was called
    assert mock_websocket_manager.send_to_user.called
    call_args = mock_websocket_manager.send_to_user.call_args

    assert call_args[0][0] == user_id
    message = call_args[0][1]
    assert message["type"] == "strategy_execution_completed"
    assert message["data"]["strategy_id"] == strategy_id
    assert message["data"]["result"] == result


@pytest.mark.asyncio
async def test_stop_pusher(status_pusher, mock_websocket_manager):
    """Test stopping the pusher"""
    strategy_id = 1
    user_id = 100

    # Push event
    await status_pusher.push_execution_started(strategy_id, user_id, "reverse_opening")

    # Stop pusher
    await status_pusher.stop()

    # Verify worker task is cancelled
    assert status_pusher._worker_task.cancelled() or status_pusher._worker_task.done()

