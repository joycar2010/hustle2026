"""C execution/settlement invariants against an isolated, real SQLite ledger."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from btc5m.book import TopOfBook
from btc5m.markets import LiveMarket
from btc5m.paper_queue import PaperQueue
from btc5m.split_sell import AskQuote, SplitSellEngine, settle_split_sell


def _cfg(tmp_path, **overrides):
    values = dict(
        data_dir=tmp_path,
        split_db_name="isolated_c.db",
        series_slug="btc-up-or-down-5m",
        product_key="btc5m",
        gamma_host="https://unused.invalid",
        split_size=50.0,
        split_fair_edge=0.01,
        split_max_lean_shares=5.0,
        split_clip_shares=5.0,
        split_min_pair_ask=1.01,
        split_min_ask_price=0.20,
        split_join_touch=True,
        split_residual_sla_sec=20.0,
        split_residual_flatten=True,
        split_touch_fill_sec=5.0,
        split_catchup_touch_fill_sec=3.0,
        split_catchup_min_ask=0.15,
        split_rebate_bps=42.0,
        paper_slippage_ticks=1.0,
        paper_slippage_pct=0.0,
        taker_fee_rate=0.07,
        daily_loss_limit_usd=40.0,
        max_open_positions=1,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _market(*, expired=False, suffix="one", window_sec=300):
    now = time.time()
    end = now - 90 if expired else now + 180
    return LiveMarket(
        condition_id=f"condition-{suffix}",
        market_slug=f"btc-updown-{window_sec // 60}m-{suffix}",
        title="isolated market",
        up_token=f"up-{suffix}",
        down_token=f"down-{suffix}",
        start_ts=end - window_sec,
        end_ts=end,
        tick_size=0.01,
        min_size=5.0,
        neg_risk=False,
        enable_order_book=True,
    )


def _sell_maker(engine, state, *, price=0.60, trade_size=15):
    now = time.time()
    queue = PaperQueue(state.market.up_token, price, "SELL", now - 10)
    queue.observe_book(TopOfBook(price - .01, 10, price, 10), now - 10)
    state.quotes["UP"] = AskQuote(
        "UP", state.market.up_token, price, 5.0, now - 10,
        at_touch_since=now - 10, queue=queue, original_size=5,
    )
    rows = [{
        "transactionHash": "trade-1", "asset": state.market.up_token,
        "conditionId": state.market.condition_id, "side": "BUY",
        "timestamp": now - 1, "price": price, "size": trade_size,
    }]
    engine._trade_tape = SimpleNamespace(freshness_sec=10, fetch=lambda *a: rows)
    return engine._fill_ask(state, "UP", TopOfBook(price, 10, price + .01, 10), now)


@pytest.mark.parametrize("window_sec", [300, 900])
def test_official_pending_never_uses_spot_and_retries(tmp_path, monkeypatch, window_sec):
    engine = SplitSellEngine(_cfg(tmp_path))
    market = _market(expired=True, window_sec=window_sec)
    state = engine._ensure_session(market)
    assert state is not None
    monkeypatch.setattr("btc5m.split_sell.fetch_market_by_slug", lambda *a: market)
    monkeypatch.setattr("btc5m.split_sell.gamma_winner_side", lambda *a: None)
    monkeypatch.setattr(
        "btc5m.split_sell.fetch_btc_signal",
        lambda *a: pytest.fail("an expired market must not settle from spot"),
    )
    engine._resolve_open()
    row = engine.store.open_maker_sessions()[0]
    assert row["winner"] is None and row["net_pnl_usd"] is None
    event = engine.store.conn.execute(
        "SELECT payload FROM events WHERE kind='split_unresolved'"
    ).fetchone()
    payload = json.loads(event[0])
    assert payload["reason"] == "gamma_result_pending"
    assert payload["resolution_source"] == "official_gamma"
    assert payload["attempt"] == 1
    engine._resolve_open()  # repeated ticks must not hammer official endpoints
    assert engine.store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind='split_unresolved'"
    ).fetchone()[0] == 1
    engine._resolution_retry_at[state.session_id] = 0
    monkeypatch.setattr("btc5m.split_sell.gamma_winner_side", lambda *a: "DOWN")
    engine._resolve_open()
    closed = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert closed["status"] == "closed"
    assert closed["winner"] == "DOWN"
    assert closed["resolution_source"] == "official_gamma"
    assert closed["net_pnl_usd"] == pytest.approx(0)


def test_merged_pending_does_not_block_next_window_but_residual_does(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    first = engine._ensure_session(_market(suffix="first"))
    assert first is not None and engine.risk.open_positions == 1
    assert engine._ensure_session(_market(suffix="blocked")) is None
    engine._merge_pairs(first)
    assert first.up_inv == first.down_inv == 0
    assert engine.risk.open_positions == 0
    assert len(engine.store.open_maker_sessions()) == 1  # still awaits official outcome
    second = engine._ensure_session(_market(suffix="second"))
    assert second is not None and engine.risk.open_positions == 1
    engine._hydrate_risk()
    assert engine.risk.open_positions == 1


def test_maker_sell_respects_limit_depth_and_has_zero_price_slippage(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path, paper_slippage_ticks=20.0))
    state = engine._ensure_session(_market())
    assert state is not None
    assert not _sell_maker(engine, state, price=.60, trade_size=10)
    assert not engine.store.conn.execute("SELECT * FROM fills").fetchall()
    assert _sell_maker(engine, state, price=.60, trade_size=15)
    fill = engine.store.conn.execute("SELECT * FROM fills").fetchone()
    assert fill["price"] == pytest.approx(.60)
    assert fill["notional_usd"] == pytest.approx(3)
    assert fill["size"] == 5
    assert fill["fee_usd"] == fill["slippage_usd"] == 0
    assert fill["execution_side"] == "SELL"
    assert fill["slippage_source"] == "maker_limit_no_price_slippage"
    assert state.up_inv == 45 and state.down_inv == 50


def test_taker_depth_partial_then_merge_and_redeem_costs_booked_once(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None and _sell_maker(engine, state)
    # Five shares requested, only three displayed; the remaining two stay at risk.
    assert engine._flatten_residual(
        state, TopOfBook(.6, 10, .61, 10), TopOfBook(.40, 3, .41, 10), reason="test"
    )
    taker = engine.store.conn.execute(
        "SELECT * FROM fills WHERE liquidity='taker'"
    ).fetchone()
    assert taker["size"] == 3
    assert taker["price"] == pytest.approx(.39)
    assert taker["slippage_usd"] == pytest.approx(.03)
    fee = .07 * .39 * .61 * 3
    assert taker["fee_usd"] == pytest.approx(fee)
    assert taker["fee_source"] == "paper_model_v1"
    assert taker["slippage_source"] == "paper_adverse_model"
    assert state.up_inv == 45 and state.down_inv == 47
    engine._close_session(state, "DOWN")
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["merge_proceeds_usd"] == 45
    assert row["redeem_proceeds_usd"] == 2
    assert row["up_proceeds_usd"] == 3
    assert row["down_proceeds_usd"] == pytest.approx(1.17)
    expected_net = 3 + 1.17 + 45 + 2 - 50 - fee
    assert row["gross_pnl_usd"] == pytest.approx(1.17)
    assert row["net_pnl_usd"] == pytest.approx(expected_net)
    assert row["rebate_est_usd"] == pytest.approx(3 * .0042)  # maker only, unpaid
    assert row["slippage_usd"] == pytest.approx(.03)  # audit, not another deduction
    assert engine.risk.realized_pnl_usd == pytest.approx(expected_net)
    engine._close_session(state, "DOWN")
    assert len(engine.store.conn.execute("SELECT * FROM fills").fetchall()) == 2
    assert engine.risk.realized_pnl_usd == pytest.approx(expected_net)


def test_full_merge_cashflow_is_principal_not_profit():
    result = settle_split_sell(
        mint_cost=50, up_proceeds=0, down_proceeds=0,
        merge_proceeds=50, redeem_proceeds=0, rebate_est=1,
        up_inv=0, down_inv=0, flatten_pnl_usd=99,
        fee_usd=0, slippage_usd=5,
    )
    assert result["gross_pnl_usd"] == result["net_pnl_usd"] == 0
    assert result["rebate_est_usd"] == 1


def test_hydration_uses_beijing_midnight_not_utc_midnight(tmp_path, monkeypatch):
    from btc5m.risk import beijing_day_start_ts

    anchor = datetime(2026, 11, 19, 1, tzinfo=timezone.utc)
    beijing_start = beijing_day_start_ts(anchor)
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None
    engine._close_session(state, "UP")
    engine.store.conn.execute(
        "UPDATE maker_sessions SET closed_ts=?, net_pnl_usd=? WHERE id=?",
        (beijing_start + 60, -3.25, state.session_id),
    )
    engine.store.conn.commit()
    monkeypatch.setattr("btc5m.split_sell.beijing_day_start_ts", lambda: beijing_start)
    engine._hydrate_risk()
    assert engine.risk.realized_pnl_usd == -3.25
    assert engine.risk.open_positions == 0


def test_restored_session_keeps_original_mint_cost_after_config_change(tmp_path):
    original = SplitSellEngine(_cfg(tmp_path))
    market = _market()
    state = original._ensure_session(market)
    assert state is not None
    original.store.conn.close()
    restored = SplitSellEngine(_cfg(tmp_path, split_size=100))
    hydrated = restored._ensure_session(market)
    assert hydrated is not None
    assert hydrated.mint_cost == 50


def test_static_touched_book_never_creates_a_maker_fill(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None
    assert not _sell_maker(engine, state, trade_size=0)
    quote = state.quotes["UP"]
    engine._trade_tape = SimpleNamespace(freshness_sec=10, fetch=lambda *a: [])
    for _ in range(3):
        assert not engine._fill_ask(state, "UP", TopOfBook(.60, 100, .61, 100), time.time())
    assert quote.queue.queue_ahead == 10
    assert state.up_inv == 50
    assert not engine.store.conn.execute("SELECT * FROM fills").fetchall()


def test_public_trades_allow_partial_fill_without_reusing_evidence(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None
    assert _sell_maker(engine, state, trade_size=12)  # 10 ahead, 2 to our 5-share order
    assert state.up_inv == 48 and state.quotes["UP"].size == 3
    assert not engine._fill_ask(state, "UP", TopOfBook(.60, 100, .61, 100), time.time())
    rows = [{
        "transactionHash": "trade-2", "asset": state.market.up_token,
        "conditionId": state.market.condition_id, "side": "BUY",
        "timestamp": time.time() - .001, "price": .60, "size": 3,
    }]
    engine._trade_tape = SimpleNamespace(freshness_sec=10, fetch=lambda *a: rows)
    assert engine._fill_ask(state, "UP", TopOfBook(.60, 100, .61, 100), time.time())
    assert "UP" not in state.quotes
    sizes = [row[0] for row in engine.store.conn.execute("SELECT size FROM fills")]
    assert sizes == [2, 3]
    assert state.up_inv == 45 and state.up_sold == 5


def test_dust_cannot_submit_new_taker_order_and_waits_for_official_settlement(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None
    # Existing 5-share maker order legitimately receives a 2-share partial fill.
    assert _sell_maker(engine, state, trade_size=12)
    assert state.up_inv == 48 and state.down_inv == 50
    assert not engine._flatten_residual(
        state, TopOfBook(.60, 100, .61, 100),
        TopOfBook(.40, 100, .41, 100), reason="dust_test",
    )
    assert state.up_inv == 48 and state.down_inv == 50
    assert engine.risk.open_positions == 1
    assert engine.store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
    event = engine.store.conn.execute(
        "SELECT payload FROM events WHERE kind='split_flatten_unfilled' ORDER BY id DESC"
    ).fetchone()
    payload = json.loads(event[0])
    assert payload["reason"] == "dust_below_min_order"
    assert payload["requested_size"] == 2 and payload["min_order_size"] == 5
    engine._close_session(state, "DOWN")
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["merge_proceeds_usd"] == 48
    assert row["redeem_proceeds_usd"] == 2
    assert row["net_pnl_usd"] == pytest.approx(1.2)


def test_execution_failure_rolls_back_fill_inventory_and_cash(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None and _sell_maker(engine, state)
    before = dict(engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone())
    engine.store.conn.executescript(
        "CREATE TRIGGER injected_failure BEFORE UPDATE OF down_shares ON maker_sessions "
        "BEGIN SELECT RAISE(ABORT, 'injected failure'); END;"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        engine._flatten_residual(
            state, TopOfBook(.60, 10, .61, 10), TopOfBook(.40, 5, .41, 10), reason="test"
        )
    assert state.up_inv == 45 and state.down_inv == 50
    assert state.down_proceeds == state.down_fee == state.down_slippage == 0
    after = dict(engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone())
    assert after == before
    assert engine.store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1


def test_restart_recovers_partial_exit_merge_fees_without_remint(tmp_path):
    original = SplitSellEngine(_cfg(tmp_path))
    market = _market()
    state = original._ensure_session(market)
    assert state is not None and _sell_maker(original, state)
    assert original._flatten_residual(
        state, TopOfBook(.60, 10, .61, 10), TopOfBook(.40, 3, .41, 10), reason="test"
    )
    original._merge_pairs(state)
    original.store.conn.close()
    restarted = SplitSellEngine(_cfg(tmp_path, split_size=100))
    recovered = restarted._ensure_session(market)
    assert recovered is not None
    assert recovered.session_id == state.session_id
    assert recovered.mint_cost == 50 and recovered.merge_proceeds == 45
    assert recovered.up_inv == 0 and recovered.down_inv == 2
    assert recovered.up_proceeds == 3 and recovered.down_proceeds == pytest.approx(1.17)
    assert recovered.down_fee == pytest.approx(.07 * .39 * .61 * 3)
    assert recovered.down_slippage == pytest.approx(.03)
    restarted._close_session(recovered, "DOWN")
    closed = restarted.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert closed["net_pnl_usd"] == pytest.approx(1.17 - .07 * .39 * .61 * 3)
    assert restarted.store.conn.execute("SELECT COUNT(*) FROM maker_sessions").fetchone()[0] == 1


def test_pending_resolver_limits_requests_without_starving_newer_sessions(tmp_path, monkeypatch):
    engine = SplitSellEngine(_cfg(tmp_path, max_open_positions=3))
    markets = [_market(expired=True, suffix=str(i)) for i in range(3)]
    for market in markets:
        assert engine._ensure_session(market) is not None
    by_slug = {market.market_slug: market for market in markets}
    calls = []
    def fetch(_host, slug):
        calls.append(slug)
        return by_slug[slug]
    monkeypatch.setattr("btc5m.split_sell.fetch_market_by_slug", fetch)
    monkeypatch.setattr("btc5m.split_sell.gamma_winner_side", lambda *a: None)
    engine._resolve_open()
    assert len(calls) == 2
    engine._resolve_open()
    assert len(calls) == 3 and len(set(calls)) == 3


def test_uninitialized_legacy_shell_never_invents_a_mint_loss(tmp_path, monkeypatch):
    engine = SplitSellEngine(_cfg(tmp_path))
    market = _market(expired=True)
    engine.store.open_maker_session(
        market_slug=market.market_slug, condition_id=market.condition_id,
        up_token=market.up_token, down_token=market.down_token, dry_run=True,
    )  # legacy crash between row creation and mint initialization
    monkeypatch.setattr("btc5m.split_sell.fetch_market_by_slug", lambda *a: market)
    monkeypatch.setattr("btc5m.split_sell.gamma_winner_side", lambda *a: "UP")
    engine._resolve_open()
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["net_pnl_usd"] == row["gross_pnl_usd"] == 0
    assert row["merge_proceeds_usd"] == row["redeem_proceeds_usd"] == 0


def test_merge_failure_cannot_lose_fifty_dollars_of_pair_proceeds(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None
    engine.store.conn.executescript(
        "CREATE TRIGGER injected_merge_failure BEFORE UPDATE OF merge_proceeds_usd "
        "ON maker_sessions BEGIN SELECT RAISE(ABORT, 'merge failure'); END;"
    )
    with pytest.raises(sqlite3.IntegrityError, match="merge failure"):
        engine._merge_pairs(state)
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["up_shares"] == row["down_shares"] == 50
    assert row["merged_shares"] == row["merge_proceeds_usd"] == 0
    assert state.up_inv == state.down_inv == 50
    assert state.merged == state.merge_proceeds == 0
    engine.store.conn.execute("DROP TRIGGER injected_merge_failure")
    engine._merge_pairs(state)
    engine._close_session(state, "UP")
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["merge_proceeds_usd"] == 50
    assert row["net_pnl_usd"] == 0


def test_redeem_failure_retains_inventory_and_retry_never_double_pays(tmp_path):
    engine = SplitSellEngine(_cfg(tmp_path))
    state = engine._ensure_session(_market())
    assert state is not None and _sell_maker(engine, state)
    engine._merge_pairs(state)
    engine.store.conn.executescript(
        "CREATE TRIGGER injected_redeem_failure BEFORE UPDATE OF redeem_proceeds_usd "
        "ON maker_sessions BEGIN SELECT RAISE(ABORT, 'redeem failure'); END;"
    )
    with pytest.raises(sqlite3.IntegrityError, match="redeem failure"):
        engine._close_session(state, "DOWN")
    assert state.down_inv == 5 and state.redeem_proceeds == 0
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["down_shares"] == 5 and row["redeem_proceeds_usd"] == 0
    assert row["status"] == "open"
    engine.store.conn.execute("DROP TRIGGER injected_redeem_failure")
    engine._close_session(state, "DOWN")
    engine._close_session(state, "DOWN")
    row = engine.store.conn.execute("SELECT * FROM maker_sessions").fetchone()
    assert row["redeem_proceeds_usd"] == 5
    assert row["net_pnl_usd"] == pytest.approx(3)
