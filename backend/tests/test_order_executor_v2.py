"""Unit tests for OrderExecutorV2"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from app.services.order_executor_v2 import OrderExecutorV2
from app.models.account import Account


@pytest.fixture
def mock_binance_account():
    """Mock Binance account"""
    account = Mock(spec=Account)
    account.account_id = "binance-123"
    account.api_key = "test_key"
    account.api_secret = "test_secret"
    return account


@pytest.fixture
def mock_bybit_account():
    """Mock Bybit account"""
    account = Mock(spec=Account)
    account.account_id = "bybit-456"
    account.api_key = "test_key"
    account.api_secret = "test_secret"
    return account


@pytest.fixture
def executor():
    """Create OrderExecutorV2 instance"""
    return OrderExecutorV2()


class TestOrderExecutorV2:
    """Test cases for OrderExecutorV2"""

    def test_initialization(self, executor):
        """Test executor initialization"""
        assert executor.binance_timeout == 0.2
        assert executor.bybit_timeout == 0.1
        assert executor.max_retries == 1

    @pytest.mark.asyncio
    async def test_monitor_binance_order_filled(self, executor, mock_binance_account):
        """Test monitoring Binance order that gets filled"""
        with patch.object(executor.base_executor, 'check_binance_order_status') as mock_check:
            mock_check.return_value = {
                "success": True,
                "filled": True,
                "filled_qty": 5.0
            }

            filled_qty = await executor._monitor_binance_order(
                mock_binance_account,
                "XAUUSDT",
                12345,
                0.2
            )

            assert filled_qty == 5.0

    @pytest.mark.asyncio
    async def test_monitor_binance_order_timeout(self, executor, mock_binance_account):
        """Test monitoring Binance order that times out"""
        with patch.object(executor.base_executor, 'check_binance_order_status') as mock_check, \
             patch.object(executor.base_executor, 'cancel_binance_order') as mock_cancel:

            # Order never fills
            mock_check.return_value = {
                "success": True,
                "filled": False,
                "filled_qty": 0
            }

            filled_qty = await executor._monitor_binance_order(
                mock_binance_account,
                "XAUUSDT",
                12345,
                0.05  # Short timeout for testing
            )

            # Should have cancelled the order
            mock_cancel.assert_called_once()
            assert filled_qty == 0

    @pytest.mark.asyncio
    async def test_execute_bybit_market_buy_full_fill(self, executor, mock_bybit_account):
        """Test Bybit market buy that fills completely"""
        with patch.object(executor.base_executor, 'place_bybit_order') as mock_place, \
             patch.object(executor.base_executor, 'check_bybit_order_status') as mock_check:

            mock_place.return_value = {
                "success": True,
                "order_id": "bybit-order-1"
            }

            mock_check.return_value = {
                "success": True,
                "filled_qty": 0.05
            }

            filled_qty = await executor._execute_bybit_market_buy(
                mock_bybit_account,
                "XAUUSD+",
                0.05
            )

            assert filled_qty == 0.05
            # Should only place order once (no retry needed)
            assert mock_place.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_bybit_market_buy_partial_fill_retry(self, executor, mock_bybit_account):
        """Test Bybit market buy with partial fill and retry"""
        with patch.object(executor.base_executor, 'place_bybit_order') as mock_place, \
             patch.object(executor.base_executor, 'check_bybit_order_status') as mock_check, \
             patch.object(executor.base_executor, 'cancel_bybit_order') as mock_cancel:

            mock_place.side_effect = [
                {"success": True, "order_id": "order-1"},
                {"success": True, "order_id": "order-2"}
            ]

            mock_check.side_effect = [
                {"success": True, "filled_qty": 0.03},  # First order partially filled
                {"success": True, "filled_qty": 0.02}   # Second order fills remaining
            ]

            filled_qty = await executor._execute_bybit_market_buy(
                mock_bybit_account,
                "XAUUSD+",
                0.05
            )

            assert filled_qty == 0.05
            # Should place order twice (initial + 1 retry)
            assert mock_place.call_count == 2
            # Should cancel first order
            assert mock_cancel.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_reverse_opening_success(self, executor, mock_binance_account, mock_bybit_account):
        """Test successful reverse opening execution"""
        with patch.object(executor.base_executor, 'place_binance_order') as mock_binance_place, \
             patch.object(executor, '_monitor_binance_order') as mock_monitor, \
             patch.object(executor, '_execute_bybit_market_buy') as mock_bybit_buy:

            mock_binance_place.return_value = {
                "success": True,
                "order_id": 12345
            }

            mock_monitor.return_value = 5.0  # Binance filled 5 XAU

            mock_bybit_buy.return_value = 0.05  # Bybit filled 0.05 lots

            result = await executor.execute_reverse_opening(
                mock_binance_account,
                mock_bybit_account,
                quantity=5.0,
                binance_price=2700.50,
                bybit_price=2700.60
            )

            assert result["success"] is True
            assert result["binance_filled_qty"] == 5.0
            assert result["bybit_filled_qty"] == 0.05

    @pytest.mark.asyncio
    async def test_execute_reverse_opening_binance_fails(self, executor, mock_binance_account, mock_bybit_account):
        """Test reverse opening when Binance order fails"""
        with patch.object(executor.base_executor, 'place_binance_order') as mock_binance_place:

            mock_binance_place.return_value = {
                "success": False,
                "error": "Insufficient balance"
            }

            result = await executor.execute_reverse_opening(
                mock_binance_account,
                mock_bybit_account,
                quantity=5.0,
                binance_price=2700.50,
                bybit_price=2700.60
            )

            assert result["success"] is False
            assert "Binance order failed" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_reverse_opening_binance_not_filled(self, executor, mock_binance_account, mock_bybit_account):
        """Test reverse opening when Binance order not filled within timeout"""
        with patch.object(executor.base_executor, 'place_binance_order') as mock_binance_place, \
             patch.object(executor, '_monitor_binance_order') as mock_monitor, \
             patch.object(executor.base_executor, 'cancel_binance_order') as mock_cancel:

            mock_binance_place.return_value = {
                "success": True,
                "order_id": 12345
            }

            mock_monitor.return_value = 0  # Not filled

            result = await executor.execute_reverse_opening(
                mock_binance_account,
                mock_bybit_account,
                quantity=5.0,
                binance_price=2700.50,
                bybit_price=2700.60
            )

            assert result["success"] is False
            assert "not filled within 0.2s" in result["error"]
            # Should not have cancelled (monitor already cancels)
            assert mock_cancel.call_count == 0

    @pytest.mark.asyncio
    async def test_execute_forward_opening_success(self, executor, mock_binance_account, mock_bybit_account):
        """Test successful forward opening execution"""
        with patch.object(executor.base_executor, 'place_binance_order') as mock_binance_place, \
             patch.object(executor, '_monitor_binance_order') as mock_monitor, \
             patch.object(executor, '_execute_bybit_market_sell') as mock_bybit_sell:

            mock_binance_place.return_value = {
                "success": True,
                "order_id": 12345
            }

            mock_monitor.return_value = 5.0  # Binance filled 5 XAU

            mock_bybit_sell.return_value = 0.05  # Bybit filled 0.05 lots

            result = await executor.execute_forward_opening(
                mock_binance_account,
                mock_bybit_account,
                quantity=5.0,
                binance_price=2700.50,
                bybit_price=2700.60
            )

            assert result["success"] is True
            assert result["binance_filled_qty"] == 5.0
            assert result["bybit_filled_qty"] == 0.05

    @pytest.mark.asyncio
    async def test_timeout_values(self, executor):
        """Test that timeout values match V2.0 specifications"""
        assert executor.binance_timeout == 0.2, "Binance timeout should be 0.2 seconds"
        assert executor.bybit_timeout == 0.1, "Bybit timeout should be 0.1 seconds"
        assert executor.max_retries == 1, "Max retries should be 1 (循环一次)"
