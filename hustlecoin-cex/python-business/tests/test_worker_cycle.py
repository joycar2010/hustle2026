import asyncio
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.worker import Worker, MAX_POSITIONS_PER_ACCOUNT
from engine.config_loader import ConfigLoader, GlobalRulesSnapshot
from engine.spread_feed import SpreadFeed, SpreadSnapshot
from engine.models import Position


def _now_ms():
    return int(time.time() * 1000)


def _make_spread(symbol, spread_short):
    return SpreadSnapshot(
        symbol=symbol,
        spot_bid=Decimal("100"), spot_ask=Decimal("101"),
        fut_bid=Decimal("102"), fut_ask=Decimal("103"),
        spread_long=Decimal("0.5"), spread_short=Decimal(str(spread_short)),
        ts=_now_ms(),
    )


def _make_position(symbol, status="OPEN", **kw):
    pos = MagicMock(spec=Position)
    pos.symbol = symbol
    pos.status = status
    pos.opened_at = None
    pos.funding_rate_ratio = kw.get("funding_rate_ratio", None)
    return pos


async def _sync_to_thread(func, *args):
    return func(*args)


@pytest.fixture
def config():
    rules = GlobalRulesSnapshot(
        open_spread=Decimal("0.8"),
        close_spread=Decimal("0.2"),
        repay_ban_minutes=30,
        close_funding_ratio=Decimal("1.2"),
    )
    c = MagicMock(spec=ConfigLoader)
    c.global_rules = rules
    c.blacklist = set()
    return c


@pytest.fixture
def spread_feed():
    return SpreadFeed()


@pytest.fixture
def worker(config, spread_feed):
    w = Worker(sub_account_id=1, config=config, spread_feed=spread_feed)
    w._trading_client = AsyncMock()
    w._notifier = AsyncMock()
    w._running = True
    w._cycle_count = 1
    w._open_position = AsyncMock()
    w._close_position = AsyncMock()
    w._update_state = AsyncMock()
    w._load_open_positions = MagicMock(return_value=[])
    return w


@pytest.mark.asyncio
async def test_open_condition_triggers(worker, spread_feed):
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "1.5")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._open_position.assert_called_once()
    assert worker._open_position.call_args[0][0] == "BTCUSDT"


@pytest.mark.asyncio
async def test_skip_blacklisted_symbol(worker, spread_feed, config):
    config.blacklist = {"BTCUSDT"}
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "1.5")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_close_condition_triggers(worker, spread_feed):
    pos = _make_position("BTCUSDT")
    worker._load_open_positions = MagicMock(return_value=[pos])
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "0.1")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._close_position.assert_called_once()
    assert worker._close_position.call_args[0][0] == pos


@pytest.mark.asyncio
async def test_position_limit_enforced(worker, spread_feed):
    positions = [_make_position(f"SYM{i}") for i in range(MAX_POSITIONS_PER_ACCOUNT)]
    worker._load_open_positions = MagicMock(return_value=positions)
    spread_feed._cache["NEWCOIN"] = _make_spread("NEWCOIN", "2.0")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"NEWCOIN"}, "test")

    worker._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_repay_ban_prevents_open(worker, spread_feed):
    worker._repay_ban["BTCUSDT"] = datetime.now(timezone.utc)
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "1.5")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_margin_safe_blocks_open(worker, spread_feed):
    """Verify that when _margin_safe is False, no new positions are opened."""
    worker._margin_safe = False
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "1.5")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_margin_safe_allows_close(worker, spread_feed):
    """Verify that _margin_safe=False does not prevent closing existing positions."""
    worker._margin_safe = False
    pos = _make_position("BTCUSDT")
    worker._load_open_positions = MagicMock(return_value=[pos])
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "0.1")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._close_position.assert_called_once()


@pytest.mark.asyncio
async def test_funding_ratio_triggers_close(worker, spread_feed, config):
    """Verify position closes when funding_rate_ratio exceeds threshold."""
    pos = _make_position("BTCUSDT", funding_rate_ratio=Decimal("1.5"))
    worker._load_open_positions = MagicMock(return_value=[pos])
    spread_feed._cache["BTCUSDT"] = _make_spread("BTCUSDT", "0.9")

    with patch("engine.worker.asyncio.to_thread", _sync_to_thread):
        await worker._cycle({"BTCUSDT"}, "test")

    worker._close_position.assert_called_once()
