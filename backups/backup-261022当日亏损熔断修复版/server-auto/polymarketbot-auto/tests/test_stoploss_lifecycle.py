from dataclasses import replace

import pytest

from bot.book import TopOfBook
from bot.main import maybe_reversal_exit
from bot.strategy import StrategyState
from test_btc_stop_loss import _base_cfg, _market, _book_down, _seed_local_position


def _fixture(monkeypatch, *, size=10.0, price=0.9):
    state = StrategyState()
    market = _market()
    _seed_local_position(state, market, size=size, price=price)
    orders, decisions = [], []
    monkeypatch.setattr("bot.main.store.log_order", lambda **kw: orders.append(kw))
    monkeypatch.setattr("bot.main.store.log_decision", lambda **kw: decisions.append(kw))
    monkeypatch.setattr("bot.main.store.open_orders_for_market", lambda *args: [])
    return state, market, orders, decisions


def _run(cfg, state, market, book, *, remaining=80, attempts=None, confirmations=None):
    return maybe_reversal_exit(
        cfg, None, market, TopOfBook(0.1, 20, 0.11, 20), book,
        remaining, True,
        {} if confirmations is None else confirmations,
        {} if attempts is None else attempts,
        state,
    )


@pytest.mark.parametrize(
    ("remaining", "should_exit"),
    [(250, False), (170, False), (90, True), (0.5, True)],
)
def test_paper_stop_respects_configured_exit_window(monkeypatch, remaining, should_exit):
    state, market, orders, _ = _fixture(monkeypatch)
    assert _run(_base_cfg(), state, market, _book_down((0.7, 20)), remaining=remaining) is should_exit
    if should_exit:
        assert orders[0]["size"] == 10
        assert state.active_position(market.condition_id, "down-token", "DOWN") is None
    else:
        assert not orders
        assert state.active_position(market.condition_id, "down-token", "DOWN") is not None


def test_expired_contract_goes_to_resolver_not_fabricated_sell(monkeypatch):
    state, market, orders, _ = _fixture(monkeypatch)
    assert not _run(_base_cfg(), state, market, _book_down((0.2, 20)), remaining=0)
    assert not orders
    assert state.active_position(market.condition_id, "down-token", "DOWN").remaining_size == 10


def test_empty_book_retains_position_and_recovers(monkeypatch):
    state, market, orders, decisions = _fixture(monkeypatch)
    attempts = {}
    empty = TopOfBook(None, 0, 0.8, 20)
    assert not _run(_base_cfg(), state, market, empty, attempts=attempts)
    assert not _run(_base_cfg(), state, market, empty, attempts=attempts)
    assert not orders
    assert len(decisions) == 1
    assert decisions[0]["action"] == "SKIP_EXIT_BOOK"
    assert _run(_base_cfg(), state, market, _book_down((0.7, 20)), attempts=attempts)
    assert orders[0]["size"] == 10


def test_partial_paper_exit_respects_depth_and_cooldown(monkeypatch):
    state, market, orders, _ = _fixture(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr("bot.main.time.time", lambda: clock[0])
    cfg = replace(_base_cfg(), order_retry_cooldown_sec=5)
    attempts = {}
    assert _run(cfg, state, market, _book_down((0.7, 3)), attempts=attempts)
    pos = state.active_position(market.condition_id, "down-token", "DOWN")
    assert pos.remaining_size == 7
    assert pos.stop_loss_pending
    assert orders[0]["size"] == 3
    assert not _run(cfg, state, market, _book_down((0.85, 20)), attempts=attempts)
    assert len(orders) == 1
    clock[0] += 6
    assert _run(cfg, state, market, _book_down((0.85, 20)), attempts=attempts)
    assert orders[1]["size"] == 7
    assert sum(o["size"] for o in orders) == 10
    assert state.active_position(market.condition_id, "down-token", "DOWN") is None
    assert not _run(cfg, state, market, _book_down((0.5, 20)), attempts=attempts)


def test_insufficient_depth_fok_only_does_not_record_fill(monkeypatch):
    state, market, orders, decisions = _fixture(monkeypatch)
    cfg = replace(_base_cfg(), sell_exit_fak_fallback_enabled=False)
    assert not _run(cfg, state, market, _book_down((0.7, 3)))
    assert not orders
    assert decisions[-1]["action"] == "SKIP_EXIT_SIZE"
    assert state.active_position(market.condition_id, "down-token", "DOWN").remaining_size == 10


def test_armed_stop_survives_temporary_empty_book(monkeypatch):
    state, market, orders, _ = _fixture(monkeypatch)
    assert _run(_base_cfg(), state, market, _book_down((0.7, 3)))
    assert not _run(_base_cfg(), state, market, TopOfBook(None, 0, 0.8, 20))
    assert _run(_base_cfg(), state, market, _book_down((0.85, 20)))
    assert [o["size"] for o in orders] == [3, 7]


def test_above_threshold_is_not_forced_exit(monkeypatch):
    state, market, orders, _ = _fixture(monkeypatch)
    assert not _run(_base_cfg(), state, market, _book_down((0.75, 20)))
    assert not orders


def test_partial_exit_resumes_after_worker_restart(monkeypatch):
    state = StrategyState()
    market = _market()
    orders = []
    monkeypatch.setattr("bot.main.store.log_order", lambda **kw: orders.append(kw))
    monkeypatch.setattr("bot.main.store.log_decision", lambda **kw: None)
    monkeypatch.setattr("bot.main.store.open_orders_for_market", lambda *args: [{
        "side": "DOWN", "token_id": "down-token", "size": 7,
        "original_size": 10, "exited_size": 3, "price": 0.9,
    }])
    assert _run(_base_cfg(), state, market, _book_down((0.85, 20)))
    assert orders[0]["size"] == 7


def test_live_path_keeps_existing_window_until_paper_validation(monkeypatch):
    state, market, orders, _ = _fixture(monkeypatch)
    assert not maybe_reversal_exit(
        _base_cfg(), object(), market,
        TopOfBook(0.1, 20, 0.11, 20), _book_down((0.7, 20)),
        170, False, {}, {}, state,
    )
    assert not orders
