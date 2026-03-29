"""Unit tests for ArbitrageStrategyExecutorV2"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from backend.app.services.strategy_executor_v2 import (
    ArbitrageStrategyExecutorV2,
    StrategyConfig,
    LadderConfig
)
from backend.app.services.trigger_manager import CompareOperator


@pytest.fixture
def mock_binance_api():
    """Mock Binance API"""
    api = Mock()
    api.get_orderbook = AsyncMock(return_value={
        'bid': 100.0,
        'ask': 101.0
    })
    return api


@pytest.fixture
def mock_bybit_api():
    """Mock Bybit API"""
    api = Mock()
    api.get_orderbook = AsyncMock(return_value={
        'bid': 99.5,
        'ask': 100.5
    })
    return api


@pytest.fixture
def mock_position_manager():
    """Mock Position Manager"""
    mgr = Mock()
    mgr.get_position = Mock(return_value={
        'current_position': 0,
        'total_opened': 0,
        'total_closed': 0
    })
    mgr.check_can_open = Mock(return_value=(True, None))
    mgr.check_can_close = Mock(return_value=(True, None))
    mgr.record_opening = Mock()
    mgr.record_closing = Mock()
    return mgr


@pytest.fixture
def strategy_config():
    """Sample strategy configuration"""
    return StrategyConfig(
        strategy_id=1,
        symbol='BTCUSDT',
        strategy_type='reverse',
        opening_m_coin=5.0,
        closing_m_coin=5.0,
        ladders=[
            LadderConfig(
                enabled=True,
                opening_spread=1.5,
                closing_spread=0.5,
                total_qty=10.0,
                opening_trigger_count=2,
                closing_trigger_count=2
            )
        ]
    )


@pytest.mark.asyncio
async def test_spread_calculations(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test spread calculation methods"""
    executor = ArbitrageStrategyExecutorV2(
        strategy_config,
        mock_binance_api,
        mock_bybit_api,
        mock_position_manager
    )

    # Test bybit long spread (reverse opening)
    spread = await executor._calc_bybit_long_spread()
    assert spread == 0.5  # binance_ask (101.0) - bybit_ask (100.5)

    # Test bybit close spread (reverse closing)
    spread = await executor._calc_bybit_close_spread()
    assert spread == 0.5  # binance_bid (100.0) - bybit_bid (99.5)

    # Test binance long spread (forward opening)
    spread = await executor._calc_binance_long_spread()
    assert spread == -0.5  # bybit_bid (99.5) - binance_bid (100.0)

    # Test binance close spread (forward closing)
    spread = await executor._calc_binance_close_spread()
    assert spread == -0.5  # bybit_ask (100.5) - binance_ask (101.0)


@pytest.mark.asyncio
async def test_reverse_opening_success(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test successful reverse opening execution"""
    # Mock order executor
    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2') as MockExecutor:
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_reverse_opening = AsyncMock(return_value={
            'success': True,
            'binance_filled': 5.0,
            'bybit_filled': 5.0
        })

        executor = ArbitrageStrategyExecutorV2(
            strategy_config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        # Mock trigger manager to be ready immediately
        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            # Mock position to complete after one iteration
            mock_position_manager.get_position.side_effect = [
                {'current_position': 0, 'total_opened': 0, 'total_closed': 0},
                {'current_position': 5.0, 'total_opened': 5.0, 'total_closed': 0},
                {'current_position': 10.0, 'total_opened': 10.0, 'total_closed': 0}
            ]

            result = await executor.start_reverse_opening()

            assert result['success'] is True
            assert mock_position_manager.record_opening.called


@pytest.mark.asyncio
async def test_reverse_closing_success(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test successful reverse closing execution"""
    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2') as MockExecutor:
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_reverse_closing = AsyncMock(return_value={
            'success': True,
            'binance_filled': 5.0,
            'bybit_filled': 5.0
        })

        executor = ArbitrageStrategyExecutorV2(
            strategy_config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            # Mock position with existing position to close
            mock_position_manager.get_position.side_effect = [
                {'current_position': 10.0, 'total_opened': 10.0, 'total_closed': 0},
                {'current_position': 5.0, 'total_opened': 10.0, 'total_closed': 5.0},
                {'current_position': 0, 'total_opened': 10.0, 'total_closed': 10.0}
            ]

            result = await executor.start_reverse_closing()

            assert result['success'] is True
            assert mock_position_manager.record_closing.called


@pytest.mark.asyncio
async def test_forward_opening_success(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test successful forward opening execution"""
    strategy_config.strategy_type = 'forward'

    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2') as MockExecutor:
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_forward_opening = AsyncMock(return_value={
            'success': True,
            'binance_filled': 5.0,
            'bybit_filled': 5.0
        })

        executor = ArbitrageStrategyExecutorV2(
            strategy_config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            mock_position_manager.get_position.side_effect = [
                {'current_position': 0, 'total_opened': 0, 'total_closed': 0},
                {'current_position': 5.0, 'total_opened': 5.0, 'total_closed': 0},
                {'current_position': 10.0, 'total_opened': 10.0, 'total_closed': 0}
            ]

            result = await executor.start_forward_opening()

            assert result['success'] is True


@pytest.mark.asyncio
async def test_forward_closing_success(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test successful forward closing execution"""
    strategy_config.strategy_type = 'forward'

    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2') as MockExecutor:
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_forward_closing = AsyncMock(return_value={
            'success': True,
            'binance_filled': 5.0,
            'bybit_filled': 5.0
        })

        executor = ArbitrageStrategyExecutorV2(
            strategy_config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            mock_position_manager.get_position.side_effect = [
                {'current_position': 10.0, 'total_opened': 10.0, 'total_closed': 0},
                {'current_position': 5.0, 'total_opened': 10.0, 'total_closed': 5.0},
                {'current_position': 0, 'total_opened': 10.0, 'total_closed': 10.0}
            ]

            result = await executor.start_forward_closing()

            assert result['success'] is True


@pytest.mark.asyncio
async def test_execution_failure(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test execution failure handling"""
    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2') as MockExecutor:
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_reverse_opening = AsyncMock(return_value={
            'success': False,
            'reason': 'Order failed'
        })

        executor = ArbitrageStrategyExecutorV2(
            strategy_config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            result = await executor.start_reverse_opening()

            assert result['success'] is False
            assert 'error' in result


@pytest.mark.asyncio
async def test_position_limit_check(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test position limit checking"""
    # Mock position manager to reject opening
    mock_position_manager.check_can_open.return_value = (False, "Position limit reached")

    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2'):
        executor = ArbitrageStrategyExecutorV2(
            strategy_config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            result = await executor.start_reverse_opening()

            # Should complete without error but not execute orders
            assert result['success'] is True


@pytest.mark.asyncio
async def test_stop_execution(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test stopping execution"""
    executor = ArbitrageStrategyExecutorV2(
        strategy_config,
        mock_binance_api,
        mock_bybit_api,
        mock_position_manager
    )

    executor.is_running = True
    executor.stop()

    assert executor.is_running is False


def test_get_status(strategy_config, mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test getting execution status"""
    executor = ArbitrageStrategyExecutorV2(
        strategy_config,
        mock_binance_api,
        mock_bybit_api,
        mock_position_manager
    )

    status = executor.get_status()

    assert 'is_running' in status
    assert 'current_ladder_index' in status
    assert 'trigger_progress' in status
    assert status['is_running'] is False


@pytest.mark.asyncio
async def test_multiple_ladders(mock_binance_api, mock_bybit_api, mock_position_manager):
    """Test execution with multiple ladders"""
    config = StrategyConfig(
        strategy_id=1,
        symbol='BTCUSDT',
        strategy_type='reverse',
        opening_m_coin=5.0,
        closing_m_coin=5.0,
        ladders=[
            LadderConfig(
                enabled=True,
                opening_spread=1.5,
                closing_spread=0.5,
                total_qty=10.0,
                opening_trigger_count=2,
                closing_trigger_count=2
            ),
            LadderConfig(
                enabled=True,
                opening_spread=2.0,
                closing_spread=0.3,
                total_qty=15.0,
                opening_trigger_count=3,
                closing_trigger_count=3
            )
        ]
    )

    with patch('backend.app.services.strategy_executor_v2.OrderExecutorV2') as MockExecutor:
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_reverse_opening = AsyncMock(return_value={
            'success': True,
            'binance_filled': 5.0,
            'bybit_filled': 5.0
        })

        executor = ArbitrageStrategyExecutorV2(
            config,
            mock_binance_api,
            mock_bybit_api,
            mock_position_manager
        )

        with patch.object(executor, '_wait_for_triggers', new_callable=AsyncMock):
            # Mock positions for both ladders
            mock_position_manager.get_position.side_effect = [
                # Ladder 0
                {'current_position': 0, 'total_opened': 0, 'total_closed': 0},
                {'current_position': 5.0, 'total_opened': 5.0, 'total_closed': 0},
                {'current_position': 10.0, 'total_opened': 10.0, 'total_closed': 0},
                # Ladder 1
                {'current_position': 0, 'total_opened': 0, 'total_closed': 0},
                {'current_position': 5.0, 'total_opened': 5.0, 'total_closed': 0},
                {'current_position': 10.0, 'total_opened': 10.0, 'total_closed': 0},
                {'current_position': 15.0, 'total_opened': 15.0, 'total_closed': 0}
            ]

            result = await executor.start_reverse_opening()

            assert result['success'] is True
            # Should have executed both ladders
            assert executor.current_ladder_index == 1
