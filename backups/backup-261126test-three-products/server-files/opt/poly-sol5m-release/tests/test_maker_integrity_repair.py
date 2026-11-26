from __future__ import annotations

import time

import pytest

from btc5m.book import TopOfBook
from btc5m.fees import taker_fee_usd
from btc5m.maker import MakerEngine, MakerState, Quote, settle_maker_pnl
from btc5m.markets import LiveMarket
from btc5m.paper_queue import PaperQueue, PublicTradeTape
from conftest import make_cfg


def market(*, end=300.0):
    now = time.time()
    return LiveMarket("condition", "slug", "BTC", "up", "down", now - 30,
                      now + end, .01, 5, False, True)


def engine_state(tmp_path, **kwargs):
    engine = MakerEngine(make_cfg(data_dir=tmp_path, **kwargs))
    m = market()
    sid = engine.store.open_maker_session(
        market_slug=m.market_slug, condition_id=m.condition_id,
        up_token=m.up_token, down_token=m.down_token, dry_run=True,
    )
    return engine, MakerState(sid, m)


def trade(stamp, size, *, token="up", side="SELL", price=.5, tx="tx", cid="condition"):
    return dict(timestamp=stamp, size=size, asset=token, side=side, price=price,
                transactionHash=tx, conditionId=cid)


def test_elapsed_touch_time_alone_never_generates_a_fill(tmp_path):
    engine, state = engine_state(tmp_path)
    now = time.time()
    book = TopOfBook(.5, 4, .51, 20)
    queue = PaperQueue("up", .5, "BUY", now - 60)
    queue.observe_book(book, now - 60)
    state.quotes["UP"] = Quote("UP", "up", .5, 10, now - 60, now - 60, queue)
    engine.trade_tape.fetch = lambda *_: []
    assert not engine._fill_side(state, "UP", book, now)
    assert state.up_shares == 0
    assert engine.store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0


def test_only_fresh_public_trade_volume_beyond_full_queue_fills_at_limit(tmp_path):
    engine, state = engine_state(tmp_path)
    now = time.time()
    book = TopOfBook(.5, 5, .51, 20)
    queue = PaperQueue("up", .5, "BUY", now - 3)
    queue.observe_book(book, now - 3)
    state.quotes["UP"] = Quote("UP", "up", .5, 10, now - 3, queue=queue)
    rows = [trade(now - 2, 8)]
    engine.trade_tape.fetch = lambda *_: rows
    assert engine._fill_side(state, "UP", book, now)
    assert state.up_shares == pytest.approx(3)
    assert state.up_cost == pytest.approx(1.5)
    fill = engine.store.conn.execute("SELECT * FROM fills").fetchone()
    assert fill["price"] == .5
    assert fill["execution_side"] == "BUY"
    assert fill["liquidity"] == "maker"
    assert fill["fee_usd"] == fill["slippage_usd"] == 0
    assert not engine._fill_side(state, "UP", book, now + .1)
    assert state.up_shares == 3


def test_queue_rejects_prequote_stale_wrong_asset_direction_and_market():
    queue = PaperQueue("up", .5, "BUY", 80)
    queue.observe_book(TopOfBook(.5, 0, .51, 20), 80)
    rows = [trade(79, 100), trade(85, 100), trade(101, 100),
            trade(99, 100, token="down"), trade(99, 100, side="BUY"),
            trade(99, 100, cid="other")]
    amount, _ = queue.consume(rows, now=100, freshness_sec=10, max_size=10,
                              condition_id="condition")
    assert amount == 0


def test_sell_queue_uses_opposing_buys_and_never_time_based_fill():
    queue = PaperQueue("up", .6, "SELL", 90)
    queue.observe_book(TopOfBook(.59, 5, .6, 5), 90)
    rows = [trade(99, 7, side="BUY", price=.6)]
    amount, source = queue.consume(rows, now=100, freshness_sec=10, max_size=5,
                                   condition_id="condition")
    assert amount == 2
    assert source == "public_trade_full_visible_queue_model"
    assert queue.consume(rows, now=100, freshness_sec=10, max_size=5,
                         condition_id="condition")[0] == 0


def test_trade_api_error_is_cached_and_creates_no_fill(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise ValueError("invalid response")

    monkeypatch.setattr("btc5m.paper_queue.requests.get", fail)
    tape = PublicTradeTape()
    assert tape.fetch("condition", 100) is None
    assert tape.fetch("condition", 100.5) is None
    assert len(calls) == 1
    assert calls[0]["timeout"] == 2
    assert calls[0]["params"]["condition"] == "condition"
    assert calls[0]["params"]["taker_only"] == "true"
    assert calls[0]["params"]["start"] == 90
    assert calls[0]["headers"]["Cache-Control"] == "no-cache"


def test_trade_api_v2_envelope_and_legacy_host_upgrade(monkeypatch):
    calls = []
    row = dict(timestamp=99, size=8, token_id="up", side="SELL", price=.5,
               transaction_hash="tx", condition_id="condition", proxy_wallet="wallet")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [row], "pagination": {"next_cursor": None}}

    monkeypatch.setattr("btc5m.paper_queue.requests.get",
                        lambda url, **kwargs: calls.append(url) or Response())
    tape = PublicTradeTape(host="https://data-api.polymarket.com")
    rows = tape.fetch("condition", 100)
    assert calls == ["https://data-api.polymarket.com/v2/trades"]
    queue = PaperQueue("up", .5, "BUY", 90)
    queue.observe_book(TopOfBook(.5, 5, .51, 20), 90)
    assert queue.consume(rows, now=100, freshness_sec=10, max_size=10,
                         condition_id="condition")[0] == 3
    assert queue.consume(rows, now=100, freshness_sec=10, max_size=10,
                         condition_id="condition")[0] == 0


def test_excess_trade_volume_is_not_reused_to_fill_future_orders():
    queue = PaperQueue("up", .5, "BUY", 90)
    queue.observe_book(TopOfBook(.5, 5, .51, 20), 90)
    rows = [trade(99, 100)]
    assert queue.consume(rows, now=100, freshness_sec=10, max_size=5,
                         condition_id="condition")[0] == 5
    assert queue.consume(rows, now=101, freshness_sec=10, max_size=5,
                         condition_id="condition")[0] == 0


def test_stale_tape_reports_a_stale_source_instead_of_a_fill():
    queue = PaperQueue("up", .5, "BUY", 70)
    queue.observe_book(TopOfBook(.5, 5, .51, 20), 70)
    assert queue.consume([trade(80, 100)], now=100, freshness_sec=10, max_size=5,
                         condition_id="condition") == (0, "public_trade_stale")


def test_partial_taker_exit_survives_restart_without_double_cost_or_slip(tmp_path):
    engine, state = engine_state(tmp_path, paper_slippage_ticks=1)
    state.up_shares, state.up_cost = 10, 5
    engine.store.update_maker_inventory(state.session_id, up_shares=10, down_shares=0,
                                        up_cost_usd=5, down_cost_usd=0)
    down = TopOfBook(.1, 10, .2, 10)
    engine._flatten_residual(state, TopOfBook(.4, 3, .41, 10), down)
    assert not state.flattened
    assert state.exiting
    assert state.up_shares == 7
    assert state.up_cost == 3.5
    assert state.flatten_pnl_usd == pytest.approx(-.33)
    assert state.slippage_usd == pytest.approx(.03)
    restarted = MakerEngine(engine.cfg)
    restored = restarted._ensure_session(state.market)
    assert restored.exiting
    assert restored.flatten_pnl_usd == pytest.approx(-.33)
    assert restored.slippage_usd == pytest.approx(.03)
    restarted._flatten_residual(restored, TopOfBook(.3, 7, .31, 10), down)
    assert restored.flattened
    assert restored.up_shares == restored.up_cost == 0
    assert restored.flatten_pnl_usd == pytest.approx(-1.8)
    assert restored.slippage_usd == pytest.approx(.1)
    fee = taker_fee_usd(.39, 3, .07) + taker_fee_usd(.29, 7, .07)
    assert restored.up_fee == pytest.approx(fee)
    restarted._resolve_session(restored, "FLAT_NO_EXPOSURE", resolution_source="flat_no_exposure")
    result = restarted.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert result["gross_pnl_usd"] == pytest.approx(-1.8)
    assert result["net_pnl_usd"] == pytest.approx(-1.8 - fee)
    assert result["slippage_usd"] == pytest.approx(.1)
    fills = restarted.store.conn.execute("SELECT * FROM fills").fetchall()
    assert [fill["size"] for fill in fills] == [3, 7]
    assert all(fill["execution_side"] == "SELL" and fill["liquidity"] == "taker" for fill in fills)


def test_no_exit_depth_preserves_inventory_and_continues_exit(tmp_path):
    engine, state = engine_state(tmp_path)
    state.up_shares, state.up_cost = 10, 5
    engine._flatten_residual(state, TopOfBook(.4, 0, .5, 5), TopOfBook(.1, 5, .2, 5))
    assert state.exiting and not state.flattened
    assert state.up_shares == 10
    assert state.up_cost == 5
    assert engine.store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0


def test_new_exit_order_below_market_minimum_waits_for_settlement(tmp_path):
    engine, state = engine_state(tmp_path)
    state.up_shares, state.up_cost = 2, 1
    engine._flatten_residual(state, TopOfBook(.4, 100, .5, 5), TopOfBook(.1, 5, .2, 5))
    assert state.exiting and not state.flattened
    assert state.up_shares == 2 and state.up_cost == 1
    assert engine.store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0


def test_inventory_waits_for_official_resolution_without_spot_guess(tmp_path, monkeypatch):
    engine, state = engine_state(tmp_path)
    engine.store.update_maker_inventory(state.session_id, up_shares=10, down_shares=0,
                                        up_cost_usd=5, down_cost_usd=0)
    expired = market(end=-100)
    monkeypatch.setattr("btc5m.maker.fetch_market_by_slug", lambda *_: expired)
    monkeypatch.setattr("btc5m.maker.gamma_winner_side", lambda *_: None)
    engine._resolve_open()
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["status"] == "open"
    assert row["net_pnl_usd"] is None


def test_flat_loss_is_closed_without_waiting_for_a_btc_outcome(tmp_path, monkeypatch):
    engine, state = engine_state(tmp_path)
    engine.store.conn.execute("UPDATE maker_sessions SET flatten_pnl_usd=-1.2,up_fee_usd=.05")
    engine.store.conn.commit()
    monkeypatch.setattr("btc5m.maker.fetch_market_by_slug", lambda *_: market(end=-100))

    def unwanted(*_):
        raise AssertionError("No outcome is needed for an empty position")

    monkeypatch.setattr("btc5m.maker.gamma_winner_side", unwanted)
    engine._resolve_open()
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["status"] == "closed"
    assert row["net_pnl_usd"] == pytest.approx(-1.25)
    assert row["resolution_source"] == "flat_no_exposure"


def test_estimated_rebate_is_not_realized_income():
    result = settle_maker_pnl(up_shares=5, down_shares=5, up_cost=2, down_cost=2.5,
                              up_fee=0, down_fee=.1, winner="UP", rebate_est=.3)
    assert result["gross_pnl_usd"] == .5
    assert result["net_pnl_usd"] == pytest.approx(.4)
    assert result["rebate_est_usd"] == .3
