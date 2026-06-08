import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from engine.models import Position, TradeLog
from engine.config_loader import GlobalRulesSnapshot
from engine.spread_feed import SpreadFeed, SpreadSnapshot
from engine.trading.order_executor import (
    execute_open, execute_close,
    TAKER_FEE_RATE, FEE_BUFFER,
)
from engine.trading.binance_trading import BinanceAPIError


@pytest.fixture
def executor_db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)


def _spread():
    return SpreadSnapshot(
        symbol="ETHUSDT",
        spot_bid=Decimal("99.9"), spot_ask=Decimal("100"),
        fut_bid=Decimal("100.4"), fut_ask=Decimal("100.6"),
        spread_long=Decimal("0.3"), spread_short=Decimal("1.0"),
        ts=int(time.time() * 1000),
    )


def _rules(**kw):
    defaults = dict(borrow_delay_sec=0)
    defaults.update(kw)
    return GlobalRulesSnapshot(**defaults)


def _client():
    c = AsyncMock()
    c.get_margin_interest_rate.return_value = Decimal("0.001")
    c.get_lot_size.return_value = {
        "stepSize": "0.01", "minQty": "0.01", "maxQty": "999999",
    }
    c.margin_borrow.return_value = {"tranId": 123}
    c.spot_market_sell.return_value = {
        "orderId": "S001", "executedQty": "5.00",
        "fills": [{"price": "100.0", "qty": "5.00"}],
    }
    c.futures_market_long.return_value = {
        "orderId": "F001", "executedQty": "5.00", "avgPrice": "100.5",
    }
    c.margin_repay.return_value = {"tranId": 124}
    c.spot_market_buy_qty.return_value = {
        "orderId": "S002", "executedQty": "5.00",
        "fills": [{"price": "99.5", "qty": "5.00"}],
    }
    c.futures_market_close.return_value = {
        "orderId": "F002", "avgPrice": "100.8",
    }
    c.get_futures_position.return_value = None
    c.get_margin_account.return_value = {
        "userAssets": [
            {"asset": "ETH", "borrowed": "5.00", "interest": "0.001"},
            {"asset": "USDT", "borrowed": "0", "interest": "0"},
        ],
    }
    return c


def _notifier():
    n = AsyncMock()
    n.notify_position_opened = AsyncMock()
    n.notify_position_closed = AsyncMock()
    n.notify_error = AsyncMock()
    n.notify_anomaly = AsyncMock()
    return n


def _api_error(msg="test error"):
    return BinanceAPIError(400, -1000, msg)


def _open_position_record(**kw):
    defaults = dict(
        sub_account_id=1, symbol="ETHUSDT", base_asset="ETH",
        status="OPEN",
        borrow_qty=Decimal("5"), borrow_interest_rate=Decimal("0.001"),
        spot_sell_qty=Decimal("5"), spot_sell_price=Decimal("100"),
        spot_sell_order_id="S001",
        futures_long_qty=Decimal("5"), futures_long_price=Decimal("100.5"),
        futures_long_order_id="F001",
        open_spread=Decimal("1.0"), open_usdt_amount=Decimal("500"),
        retry_count=0,
    )
    defaults.update(kw)
    return Position(**defaults)


def _expected_net_pnl():
    """Calculate expected net PnL for standard test fixture."""
    spot_pnl = Decimal("5") * Decimal("100") - Decimal("5") * Decimal("99.5")  # 2.5
    futures_pnl = (Decimal("100.8") - Decimal("100.5")) * Decimal("5")  # 1.5
    spot_sell_notional = Decimal("5") * Decimal("100")
    spot_buy_notional = Decimal("5") * Decimal("99.5")
    futures_open_notional = Decimal("5") * Decimal("100.5")
    futures_close_notional = Decimal("5") * Decimal("100.8")
    total_fee = (spot_sell_notional + spot_buy_notional + futures_open_notional + futures_close_notional) * TAKER_FEE_RATE
    interest_cost = Decimal("0.001") * Decimal("99.5")
    return spot_pnl + futures_pnl - total_fee - interest_cost


# --- Open tests ---

@pytest.mark.asyncio
async def test_open_full_flow(executor_db):
    notifier = _notifier()
    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(1, "ETHUSDT", _spread(), _rules(), _client(), notifier, "test")

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "OPEN"
    assert pos.symbol == "ETHUSDT"
    assert pos.borrow_qty == Decimal("5.00")
    assert pos.spot_sell_order_id == "S001"
    assert pos.futures_long_order_id == "F001"
    notifier.notify_position_opened.assert_called_once()

    logs = session.query(TradeLog).all()
    actions = {log.action for log in logs}
    assert "BORROW" in actions
    assert "SPOT_SELL" in actions
    assert "FUTURES_LONG" in actions
    session.close()


@pytest.mark.asyncio
async def test_open_interest_too_high(executor_db):
    client = _client()
    client.get_margin_interest_rate.return_value = Decimal("0.05")
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(1, "ETHUSDT", _spread(), _rules(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "FAILED"
    assert "too high" in pos.error_message
    client.margin_borrow.assert_not_called()
    session.close()


@pytest.mark.asyncio
async def test_open_borrow_fails(executor_db):
    client = _client()
    client.margin_borrow.side_effect = _api_error("insufficient balance")
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(1, "ETHUSDT", _spread(), _rules(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "FAILED"
    notifier.notify_error.assert_called_once()
    session.close()


@pytest.mark.asyncio
async def test_open_spot_sell_fails_rollback(executor_db):
    client = _client()
    client.spot_market_sell.side_effect = _api_error("spot error")
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(1, "ETHUSDT", _spread(), _rules(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "FAILED"
    assert "Borrow rolled back" in pos.error_message
    client.margin_repay.assert_called_once()
    session.close()


@pytest.mark.asyncio
async def test_open_futures_fails_rollback(executor_db):
    client = _client()
    client.futures_market_long.side_effect = _api_error("futures error")
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(1, "ETHUSDT", _spread(), _rules(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "FAILED"
    assert "Rolled back" in pos.error_message
    client.spot_market_buy_qty.assert_called_once()
    client.margin_repay.assert_called_once()
    session.close()


# --- Close tests ---

@pytest.mark.asyncio
async def test_close_full_flow(executor_db):
    session = executor_db()
    pos = _open_position_record()
    session.add(pos)
    session.commit()
    pos_id = pos.id
    session.close()

    mock_pos = MagicMock()
    mock_pos.id = pos_id
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_close(mock_pos, _spread(), _client(), notifier, "test")

    session = executor_db()
    pos = session.query(Position).get(pos_id)
    assert pos.status == "CLOSED"
    assert pos.futures_close_price == Decimal("100.8")
    assert pos.repay_qty is not None and pos.repay_qty > 0
    assert pos.repay_interest is not None
    expected = _expected_net_pnl()
    assert float(pos.realized_pnl) == pytest.approx(float(expected), abs=0.05)
    assert pos.fee_total is not None and pos.fee_total > 0
    notifier.notify_position_closed.assert_called_once()
    session.close()


@pytest.mark.asyncio
async def test_close_api_error_increments_retry(executor_db):
    session = executor_db()
    pos = _open_position_record()
    session.add(pos)
    session.commit()
    pos_id = pos.id
    session.close()

    mock_pos = MagicMock()
    mock_pos.id = pos_id
    client = _client()
    client.futures_market_close.side_effect = _api_error("timeout")
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_close(mock_pos, _spread(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).get(pos_id)
    assert pos.status != "CLOSED"
    assert pos.retry_count == 1
    notifier.notify_error.assert_called_once()
    session.close()


# --- New feature tests ---

@pytest.mark.asyncio
async def test_close_includes_interest_repay(executor_db):
    """Verify close flow queries actual debt including interest and repays it."""
    session = executor_db()
    pos = _open_position_record()
    session.add(pos)
    session.commit()
    pos_id = pos.id
    session.close()

    client = _client()
    client.get_margin_account.return_value = {
        "userAssets": [
            {"asset": "ETH", "borrowed": "5.00", "interest": "0.05"},
        ],
    }

    mock_pos = MagicMock()
    mock_pos.id = pos_id
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_close(mock_pos, _spread(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).get(pos_id)
    assert pos.status == "CLOSED"
    assert pos.repay_interest == Decimal("0.05")
    assert pos.repay_qty == Decimal("5.05")
    assert pos.fee_total > 0
    interest_cost = Decimal("0.05") * pos.spot_buy_price
    assert pos.fee_total >= interest_cost
    session.close()


@pytest.mark.asyncio
async def test_open_spread_reconfirm_aborts(executor_db):
    """Verify opening aborts if spread degrades after borrow delay."""
    client = _client()
    notifier = _notifier()

    degraded_spread = SpreadSnapshot(
        symbol="ETHUSDT",
        spot_bid=Decimal("99.9"), spot_ask=Decimal("100"),
        fut_bid=Decimal("100.1"), fut_ask=Decimal("100.2"),
        spread_long=Decimal("0.1"), spread_short=Decimal("0.3"),
        ts=int(time.time() * 1000),
    )
    feed = MagicMock(spec=SpreadFeed)
    feed.get_symbol.return_value = degraded_spread

    rules = _rules(borrow_delay_sec=0, open_spread=Decimal("0.8"))

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(
            1, "ETHUSDT", _spread(), rules, client, notifier, "test",
            spread_feed=feed,
        )

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "FAILED"
    assert "Spread degraded" in pos.error_message
    client.margin_borrow.assert_not_called()
    session.close()


@pytest.mark.asyncio
async def test_open_rollback_uses_spot_sell_qty(executor_db):
    """Verify futures-fail rollback uses actual spot_sell_qty, not borrow_qty."""
    client = _client()
    client.spot_market_sell.return_value = {
        "orderId": "S001", "executedQty": "4.99",
        "fills": [{"price": "100.0", "qty": "4.99"}],
    }
    client.futures_market_long.side_effect = _api_error("futures error")
    client.get_margin_account.return_value = {
        "userAssets": [
            {"asset": "ETH", "borrowed": "5.00", "interest": "0.002"},
        ],
    }
    notifier = _notifier()

    with patch("engine.trading.order_executor.SessionLocal", executor_db):
        await execute_open(1, "ETHUSDT", _spread(), _rules(), client, notifier, "test")

    session = executor_db()
    pos = session.query(Position).first()
    assert pos.status == "FAILED"

    buy_back_call = client.spot_market_buy_qty.call_args
    assert buy_back_call[0][1] == Decimal("4.99")

    repay_call = client.margin_repay.call_args
    assert repay_call[0][1] == Decimal("5.002")
    session.close()
