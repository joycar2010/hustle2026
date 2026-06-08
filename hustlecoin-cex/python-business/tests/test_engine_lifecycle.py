"""Integration test: Worker runs cycles, positions open/close end-to-end."""
import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, SubAccount
from engine.models import Position, EngineState
from engine.config_loader import ConfigLoader, GlobalRulesSnapshot, FundRulesSnapshot
from engine.spread_feed import SpreadFeed, SpreadSnapshot
from engine.worker import Worker


def _now_ms():
    return int(time.time() * 1000)


@pytest.fixture
def lifecycle_db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)

    session = Session()
    account = SubAccount(
        id=1, note="test-account", email="test@test.com",
        api_key="key", api_secret="secret",
        is_enabled=True, margin_enabled=True, futures_enabled=True,
    )
    session.add(account)
    session.commit()
    session.close()
    return Session


@pytest.fixture
def mock_trading_client():
    c = AsyncMock()
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
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
    c.get_margin_account.return_value = {
        "marginLevel": "2.5",
        "userAssets": [
            {"asset": "ETH", "borrowed": "5.00", "interest": "0.01"},
            {"asset": "USDT", "borrowed": "0", "interest": "0"},
            {"asset": "BNB", "free": "0.3", "borrowed": "0", "interest": "0"},
        ],
    }
    c.get_funding_rate.return_value = Decimal("0.0005")
    c.get_bnb_balance.return_value = {"margin": Decimal("0.3")}
    return c


def _patch_all_session_local(lifecycle_db):
    """Patch SessionLocal in all modules that import it."""
    return [
        patch("engine.worker.SessionLocal", lifecycle_db),
        patch("engine.trading.order_executor.SessionLocal", lifecycle_db),
    ]


@pytest.mark.asyncio
async def test_worker_open_close_lifecycle(lifecycle_db, mock_trading_client):
    """Full lifecycle: Worker opens a position when spread is wide, closes when spread narrows."""
    feed = SpreadFeed()
    feed._cache["ETHUSDT"] = SpreadSnapshot(
        symbol="ETHUSDT",
        spot_bid=Decimal("99.9"), spot_ask=Decimal("100"),
        fut_bid=Decimal("100.8"), fut_ask=Decimal("101"),
        spread_long=Decimal("0.3"), spread_short=Decimal("1.5"),
        ts=_now_ms(),
    )

    config = MagicMock(spec=ConfigLoader)
    config.global_rules = GlobalRulesSnapshot(
        open_spread=Decimal("0.8"),
        close_spread=Decimal("0.2"),
        borrow_delay_sec=0,
        repay_ban_minutes=0,
    )
    config.fund_rules = FundRulesSnapshot()
    config.blacklist = set()

    worker = Worker(sub_account_id=1, config=config, spread_feed=feed)
    worker._trading_client = mock_trading_client
    worker._notifier = AsyncMock()
    worker._notifier.notify_position_opened = AsyncMock()
    worker._notifier.notify_position_closed = AsyncMock()
    worker._notifier.notify_error = AsyncMock()
    worker._running = True
    worker._margin_safe = True

    patches = _patch_all_session_local(lifecycle_db)
    for p in patches:
        p.start()
    try:
        with patch("engine.worker.asyncio.to_thread", side_effect=lambda f, *a: f(*a)):
            tradable = {"ETHUSDT"}
            await worker._cycle(tradable, "test")

        session = lifecycle_db()
        pos = session.query(Position).filter(Position.status == "OPEN").first()
        assert pos is not None, "Position should be opened"
        assert pos.symbol == "ETHUSDT"
        assert pos.spot_sell_qty > 0
        pos_id = pos.id
        session.close()

        feed._cache["ETHUSDT"] = SpreadSnapshot(
            symbol="ETHUSDT",
            spot_bid=Decimal("100.3"), spot_ask=Decimal("100.5"),
            fut_bid=Decimal("100.4"), fut_ask=Decimal("100.6"),
            spread_long=Decimal("0.05"), spread_short=Decimal("0.1"),
            ts=_now_ms(),
        )

        with patch("engine.worker.asyncio.to_thread", side_effect=lambda f, *a: f(*a)):
            await worker._cycle(tradable, "test")

        session2 = lifecycle_db()
        pos = session2.query(Position).get(pos_id)
        assert pos.status == "CLOSED"
        assert pos.realized_pnl is not None
        assert pos.fee_total is not None and pos.fee_total > 0
        assert pos.repay_qty is not None and pos.repay_qty > 0
        session2.close()
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_worker_state_tracking(lifecycle_db):
    """Verify worker writes engine state to DB."""
    config = MagicMock(spec=ConfigLoader)
    config.global_rules = GlobalRulesSnapshot(borrow_delay_sec=0)
    config.fund_rules = FundRulesSnapshot()
    config.blacklist = set()

    feed = SpreadFeed()
    worker = Worker(sub_account_id=1, config=config, spread_feed=feed)

    with patch("engine.worker.asyncio.to_thread", side_effect=lambda f, *a: f(*a)), \
         patch("engine.worker.SessionLocal", lifecycle_db):
        await worker._update_state("RUNNING", active_positions=3)

    session = lifecycle_db()
    state = session.query(EngineState).filter(EngineState.scope == "sub:1").first()
    assert state is not None
    assert state.status == "RUNNING"
    assert state.active_positions == 3
    session.close()
