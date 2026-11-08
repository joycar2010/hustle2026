from __future__ import annotations

from dataclasses import replace

from bot.book import BookLevel, TopOfBook
from bot.config import Config
from bot.main import _locked_market_side, maybe_reversal_exit
from bot.markets import LiveMarket
from bot.orders import OrderResult
from bot.strategy import StrategyState


def _base_cfg() -> Config:
    return replace(
        Config(
            private_key="0x" + "1" * 64,
            wallet_address="0x" + "2" * 40,
            funder_address="0x" + "3" * 40,
            signature_type=3,
            chain_id=137,
            clob_host="https://clob.polymarket.com",
            gamma_host="https://gamma-api.polymarket.com",
            polygon_rpc="https://polygon-bor-rpc.publicnode.com",
            api_key="key",
            api_secret="secret",
            api_passphrase="passphrase",
        ),
        reversal_exit_enabled=True,
        early_reversal_exit_enabled=False,
        reversal_exit_window_sec=90,
        reversal_exit_min_t_remaining_sec=0,
        reversal_normal_min_t_remaining_sec=0,
        reversal_partial_exit_enabled=False,
        reversal_late_exit_enabled=False,
        reversal_held_bid_threshold=0,
        reversal_held_bid_drawdown=0.20,
        reversal_confirm_checks=0,
        reversal_exit_order_fraction=1.0,
        sell_fok_slippage_ticks=0,
        sell_exit_max_depth_ticks=5,
        sell_exit_max_depth_levels=10,
        sell_exit_fak_fallback_enabled=True,
        sell_exit_reconcile_trades=False,
        order_retry_cooldown_sec=0,
    )


def _market() -> LiveMarket:
    return LiveMarket(
        condition_id="condition",
        market_slug="btc-up-or-down-5m-1",
        up_token="up-token",
        down_token="down-token",
        start_ts=0,
        end_ts=300,
        tick_size=0.01,
        neg_risk=False,
    )


def _book_down(*levels: tuple[float, float]) -> TopOfBook:
    bid_levels = tuple(BookLevel(price=p, size=s) for p, s in levels)
    return TopOfBook(
        best_bid=bid_levels[0].price,
        bid_size=bid_levels[0].size,
        best_ask=0.80,
        ask_size=10.0,
        bids=bid_levels,
    )


def _patch_open_down_order(
    monkeypatch,
    size: float = 21.3939,
    price: float = 0.99,
) -> list[dict]:
    logged_orders: list[dict] = []
    monkeypatch.setattr(
        "bot.main.store.open_orders_for_market",
        lambda condition_id, dry_run: [
            {
                "side": "DOWN",
                "token_id": "down-token",
                "price": price,
                "size": size,
                "entry_rule": "edge",
                "exited_size": 0.0,
            }
        ],
    )
    monkeypatch.setattr("bot.main.store.log_decision", lambda **kwargs: None)
    monkeypatch.setattr(
        "bot.main.store.log_order",
        lambda **kwargs: logged_orders.append(kwargs),
    )
    return logged_orders


def _seed_local_position(
    state: StrategyState,
    market: LiveMarket,
    *,
    size: float = 21.3939,
    price: float = 0.99,
) -> None:
    state.reset_for_market(market.condition_id)
    state.note_buy_fill(
        market,
        token_id="down-token",
        side="DOWN",
        size=size,
        avg_price=price,
        order_id="buy-1",
        ts=1.0,
    )


def test_one_side_lock_only_locks_effective_filled_direction():
    assert _locked_market_side([{"side": "UP"}]) == "UP"
    assert _locked_market_side([{"side": "DOWN"}]) == "DOWN"
    assert _locked_market_side([]) is None
    assert _locked_market_side([{"side": "UP"}, {"side": "DOWN"}]) is None


def test_local_position_uses_real_fill_price_for_20pct_stop(monkeypatch):
    logged_orders: list[dict] = []
    state = StrategyState()
    market = _market()
    _seed_local_position(state, market, size=21.39, price=0.99)

    monkeypatch.setattr(
        "bot.main.store.open_orders_for_market",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("DB fallback should not run when local position exists")
        ),
    )
    monkeypatch.setattr("bot.main.store.log_decision", lambda **kwargs: None)
    monkeypatch.setattr(
        "bot.main.store.log_order",
        lambda **kwargs: logged_orders.append(kwargs),
    )

    def fake_fok(client, **kwargs):
        kwargs["client"] = client
        return OrderResult(
            order_id="fok-1",
            status="matched",
            filled_size=21.39,
            error=None,
            submitted=True,
            avg_price=0.84,
            filled_amount=17.9676,
        )

    def fake_fak(client, **kwargs):
        raise AssertionError("FAK should not run after a full FOK fill")

    monkeypatch.setattr("bot.main.place_sell_fok", fake_fok)
    monkeypatch.setattr("bot.main.place_sell_fak", fake_fak)

    exited = maybe_reversal_exit(
        _base_cfg(),
        client=object(),
        current=market,
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.79, 30.0)),
        t_rem=80,
        dry_run=False,
        confirmations={},
        exit_attempts={},
        strategy_state=state,
    )

    assert exited is True
    assert len(logged_orders) == 1
    assert logged_orders[0]["side"] == "SELL_DOWN"
    assert logged_orders[0]["size"] == 21.39
    assert logged_orders[0]["price"] == 0.84
    assert state.active_position(market.condition_id, "down-token", "DOWN") is None


def test_stop_loss_keeps_retrying_after_failed_sell_even_if_bid_recovers(monkeypatch):
    state = StrategyState()
    market = _market()
    _seed_local_position(state, market, size=21.39, price=0.99)

    monkeypatch.setattr(
        "bot.main.store.open_orders_for_market",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("DB fallback should not run when local position exists")
        ),
    )
    monkeypatch.setattr("bot.main.store.log_decision", lambda **kwargs: None)
    monkeypatch.setattr("bot.main.store.log_order", lambda **kwargs: None)

    calls: list[tuple[str, dict]] = []

    def fake_fok(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FOK", kwargs))
        return OrderResult(
            order_id=None,
            status="error",
            filled_size=0.0,
            error="fok killed",
            submitted=True,
        )

    def fake_fak(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FAK", kwargs))
        return OrderResult(
            order_id=None,
            status="error",
            filled_size=0.0,
            error="fak killed",
            submitted=True,
        )

    monkeypatch.setattr("bot.main.place_sell_fok", fake_fok)
    monkeypatch.setattr("bot.main.place_sell_fak", fake_fak)

    cfg = replace(_base_cfg(), order_retry_cooldown_sec=999)
    first = maybe_reversal_exit(
        cfg,
        client=object(),
        current=market,
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.79, 30.0)),
        t_rem=80,
        dry_run=False,
        confirmations={},
        exit_attempts={},
        strategy_state=state,
    )

    assert first is True
    assert [call[0] for call in calls] == ["FOK", "FAK"]
    pos = state.active_position(market.condition_id, "down-token", "DOWN")
    assert pos is not None
    assert pos.stop_loss_pending is True
    assert pos.remaining_size == 21.39

    calls.clear()
    second = maybe_reversal_exit(
        cfg,
        client=object(),
        current=market,
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.90, 30.0)),
        t_rem=79,
        dry_run=False,
        confirmations={},
        exit_attempts={},
        strategy_state=state,
    )

    assert second is True
    assert [call[0] for call in calls] == ["FOK", "FAK"]
    pos = state.active_position(market.condition_id, "down-token", "DOWN")
    assert pos is not None
    assert pos.stop_loss_pending is True
    assert pos.remaining_size == 21.39


def test_stop_loss_triggers_at_20_percent_drawdown(monkeypatch):
    logged_orders = _patch_open_down_order(monkeypatch, price=0.80)

    exited = maybe_reversal_exit(
        _base_cfg(),
        client=None,
        current=_market(),
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.63, 30.0)),
        t_rem=80,
        dry_run=True,
        confirmations={},
        exit_attempts={},
    )

    assert exited is True
    assert logged_orders[0]["side"] == "SELL_DOWN"
    assert logged_orders[0]["price"] == 0.63


def test_depth_exit_uses_full_size_fok_when_multilevel_depth_is_enough(monkeypatch):
    logged_orders = _patch_open_down_order(monkeypatch)
    calls = []

    def fake_fok(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FOK", kwargs))
        return OrderResult(
            order_id="fok-1",
            status="matched",
            filled_size=21.39,
            error=None,
            submitted=True,
            avg_price=0.565,
            filled_amount=12.08535,
        )

    def fake_fak(client, **kwargs):
        raise AssertionError("FAK should not run after a full FOK fill")

    monkeypatch.setattr("bot.main.place_sell_fok", fake_fok)
    monkeypatch.setattr("bot.main.place_sell_fak", fake_fak)

    client = object()
    exited = maybe_reversal_exit(
        _base_cfg(),
        client=client,
        current=_market(),
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.57, 10.0), (0.56, 20.0)),
        t_rem=80,
        dry_run=False,
        confirmations={},
        exit_attempts={},
    )

    assert exited is True
    assert len(calls) == 1
    assert calls[0][0] == "FOK"
    assert calls[0][1]["client"] is client
    assert calls[0][1]["token_id"] == "down-token"
    assert calls[0][1]["price"] == 0.56
    assert calls[0][1]["size"] == 21.39
    assert calls[0][1]["tick_size"] == 0.01
    assert calls[0][1]["neg_risk"] is False
    assert logged_orders == [
        {
            "market_slug": "btc-up-or-down-5m-1",
            "condition_id": "condition",
            "token_id": "down-token",
            "side": "SELL_DOWN",
            "size": 21.39,
            "price": 0.565,
            "order_id": "fok-1",
            "status": "exit_matched",
            "filled_size": 12.08535,
            "error": None,
            "dry_run": False,
        }
    ]


def test_depth_exit_uses_fok_then_fak_partial_when_depth_cannot_fill_full_size(monkeypatch):
    logged_orders = _patch_open_down_order(monkeypatch)
    calls = []

    def fake_fok(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FOK", kwargs))
        return OrderResult(
            order_id=None,
            status="error",
            filled_size=0.0,
            error="fok killed",
            submitted=True,
        )

    def fake_fak(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FAK", kwargs))
        return OrderResult(
            order_id="fak-1",
            status="matched",
            filled_size=13.0,
            error=None,
            submitted=True,
            avg_price=0.567,
            filled_amount=7.371,
        )

    monkeypatch.setattr("bot.main.place_sell_fok", fake_fok)
    monkeypatch.setattr("bot.main.place_sell_fak", fake_fak)

    exited = maybe_reversal_exit(
        _base_cfg(),
        client=object(),
        current=_market(),
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.57, 10.0), (0.56, 3.0)),
        t_rem=80,
        dry_run=False,
        confirmations={},
        exit_attempts={},
    )

    assert exited is True
    assert [call[0] for call in calls] == ["FOK", "FAK"]
    assert calls[0][1]["price"] == 0.56
    assert calls[0][1]["size"] == 21.39
    assert calls[1][1]["price"] == 0.56
    assert calls[1][1]["size"] == 21.39
    assert [row["status"] for row in logged_orders] == ["exit_error", "exit_partial"]
    assert logged_orders[0]["size"] == 21.39
    assert logged_orders[0]["filled_size"] == 0.0
    assert logged_orders[1]["size"] == 13.0
    assert logged_orders[1]["price"] == 0.567
    assert logged_orders[1]["filled_size"] == 7.371


def test_depth_exit_failed_fok_and_fak_do_not_reduce_remaining_position(monkeypatch):
    logged_orders = _patch_open_down_order(monkeypatch)
    calls = []

    def fake_fok(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FOK", kwargs))
        return OrderResult(
            order_id=None,
            status="error",
            filled_size=0.0,
            error="fok killed",
            submitted=True,
        )

    def fake_fak(client, **kwargs):
        kwargs["client"] = client
        calls.append(("FAK", kwargs))
        return OrderResult(
            order_id=None,
            status="error",
            filled_size=0.0,
            error="fak killed",
            submitted=True,
        )

    monkeypatch.setattr("bot.main.place_sell_fok", fake_fok)
    monkeypatch.setattr("bot.main.place_sell_fak", fake_fak)

    exited = maybe_reversal_exit(
        _base_cfg(),
        client=object(),
        current=_market(),
        book_up=TopOfBook(best_bid=0.20, bid_size=10.0, best_ask=0.21, ask_size=10.0),
        book_down=_book_down((0.57, 10.0), (0.56, 20.0)),
        t_rem=80,
        dry_run=False,
        confirmations={},
        exit_attempts={},
    )

    assert exited is True
    assert [call[0] for call in calls] == ["FOK", "FAK"]
    assert [row["status"] for row in logged_orders] == ["exit_error", "exit_error"]
    assert [row["filled_size"] for row in logged_orders] == [0.0, 0.0]
    assert all(row["size"] == 21.39 for row in logged_orders)
