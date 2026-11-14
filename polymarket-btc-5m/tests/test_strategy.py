from __future__ import annotations

from btc5m.book import TopOfBook
from btc5m.config import Config
from btc5m.markets import LiveMarket
from btc5m.signal import BtcSignal
from btc5m.strategy import StrategyState, decide, net_edge, taker_fee_per_share


def _cfg(**overrides) -> Config:
    base = dict(
        private_key="",
        funder_address="",
        signature_type=3,
        chain_id=137,
        api_key="",
        api_secret="",
        api_passphrase="",
        clob_host="https://clob.polymarket.com",
        gamma_host="https://gamma-api.polymarket.com",
        polygon_rpc="https://polygon-rpc.com",
        series_slug="btc-up-or-down-5m",
        entry_window_sec=60.0,
        min_t_remaining_sec=12.0,
        min_entry_price=0.75,
        max_entry_price=0.95,
        min_net_edge=0.02,
        taker_fee_rate=0.07,
        confirm_checks=2,
        poll_interval_sec=1.0,
        delta_filter_enabled=True,
        up_min_delta_usd=15.0,
        down_max_delta_usd=-15.0,
        price_hosts="okx",
        order_shares=10.0,
        max_order_usd=15.0,
        daily_loss_limit_usd=40.0,
        max_open_positions=1,
        paper_bankroll_usd=200.0,
        live_trading_enabled=False,
        mode="late_edge",
        late_edge_hard_ban_price=0.90,
        late_edge_edge_safety=1.25,
        maker_pair_cost_max=0.97,
        maker_quote_shares=10.0,
        maker_start_delay_sec=15.0,
        maker_stop_before_end_sec=60.0,
        maker_touch_fill_sec=12.0,
        maker_max_imbalance_shares=10.0,
        maker_allow_crossed_fills=False,
        maker_flatten_residual=True,
        data_dir=__import__("pathlib").Path("/tmp"),
    )
    base.update(overrides)
    return Config(**base)


def _market(t_left: float = 30.0) -> LiveMarket:
    import time

    end = time.time() + t_left
    start = end - 300
    return LiveMarket(
        condition_id="0xabc",
        market_slug="btc-updown-5m-1",
        title="test",
        up_token="1",
        down_token="2",
        start_ts=start,
        end_ts=end,
        tick_size=0.01,
        min_size=5,
        neg_risk=False,
        enable_order_book=True,
    )


def test_taker_fee_peaks_near_half():
    fee = taker_fee_per_share(0.07, 0.50)
    assert abs(fee - 0.0175) < 1e-9
    assert net_edge(0.90, 0.07) > 0.09


def test_skips_outside_window():
    cfg = _cfg()
    state = StrategyState()
    d = decide(
        cfg,
        _market(t_left=120),
        TopOfBook(0.1, 100, 0.90, 100),
        TopOfBook(0.1, 100, 0.99, 100),
        None,
        state,
        already_in_market=False,
    )
    assert d.action == "SKIP"
    assert "waiting" in d.reason


def test_hard_bans_high_price_bucket():
    cfg = _cfg(delta_filter_enabled=False, confirm_checks=1, max_entry_price=0.95)
    state = StrategyState()
    d = decide(
        cfg,
        _market(t_left=25),
        TopOfBook(0.90, 50, 0.95, 50),
        TopOfBook(0.01, 50, 0.99, 50),
        None,
        state,
        already_in_market=False,
    )
    assert d.action == "SKIP"
    assert "banned_high" in d.reason


def test_buy_after_confirm_with_delta():
    cfg = _cfg(
        delta_filter_enabled=True,
        confirm_checks=2,
        max_entry_price=0.90,
        min_net_edge=0.05,
        late_edge_hard_ban_price=0.90,
    )
    state = StrategyState()
    market = _market(t_left=25)
    up = TopOfBook(0.80, 50, 0.85, 50)
    down = TopOfBook(0.01, 50, 0.99, 50)
    signal = BtcSignal(
        ts=0,
        source="test",
        price_to_beat=100,
        current_price=130,
        delta_usd=30,
        signal_side="UP",
    )
    d1 = decide(cfg, market, up, down, signal, state, already_in_market=False)
    assert d1.action == "SKIP"
    assert "confirm 1/2" in d1.reason
    d2 = decide(cfg, market, up, down, signal, state, already_in_market=False)
    assert d2.action == "BUY"
    assert d2.side == "UP"
    assert d2.price == 0.85
