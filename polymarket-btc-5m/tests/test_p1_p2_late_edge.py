"""P1/P2 late_edge structure fixes: phase cap, high-ask edge, size scale, eth overlays."""
from __future__ import annotations

import time

from btc5m.book import TopOfBook
from btc5m.markets import LiveMarket
from btc5m.products import apply_product
from btc5m.signal import BtcSignal
from btc5m.strategy import (
    StrategyState,
    _confirm_needed,
    _min_edge_for_ask,
    _scaled_size,
    decide,
)
from conftest import make_cfg


def _market(*, elapsed: float = 250.0) -> LiveMarket:
    start = time.time() - elapsed
    return LiveMarket(
        condition_id="0xp1",
        market_slug="btc-updown-5m-p1",
        title="t",
        up_token="u",
        down_token="d",
        start_ts=start,
        end_ts=start + 300,
        tick_size=0.01,
        min_size=5,
        neg_risk=False,
        enable_order_book=True,
    )


def _sig(side: str = "DOWN", delta: float = -40.0) -> BtcSignal:
    return BtcSignal(
        ts=0,
        source="t",
        price_to_beat=100,
        current_price=100 + delta,
        delta_usd=delta,
        signal_side=side,
        venue_count=2,
        consensus=True,
        lead_bp=-8.0 if side == "DOWN" else 8.0,
        projected_close=100 + delta,
        projected_lead_bp=-8.0 if side == "DOWN" else 8.0,
        projected_delta_usd=delta,
        hold_wr=0.9,
        opening_gap_bp=-8.0 if side == "DOWN" else 8.0,
        decision_side=side,
    )


def test_opening_gap_phase_cap_rejects_079():
    cfg = make_cfg(
        delta_filter_enabled=False,
        confirm_checks=1,
        opening_gap_enabled=True,
        opening_gap_min_bp=5.0,
        opening_gap_max_entry_price=0.78,
        max_entry_price=0.79,
        min_net_edge=0.05,
    )
    # elapsed=10 → opening_gap; DOWN ask 0.79 > gap cap 0.78
    d = decide(
        cfg,
        _market(elapsed=10.0),
        TopOfBook(0.20, 50, 0.99, 50),
        TopOfBook(0.70, 50, 0.79, 50),
        _sig("DOWN", -40),
        StrategyState(),
        already_in_market=False,
    )
    assert d.action == "SKIP"
    assert "phase_cap" in d.reason or "no edge" in d.reason


def test_high_ask_needs_larger_min_edge():
    cfg = make_cfg(min_net_edge=0.08, min_net_edge_high=0.12, high_ask_threshold=0.80)
    assert _min_edge_for_ask(cfg, 0.77) == 0.08
    assert _min_edge_for_ask(cfg, 0.80) == 0.12
    assert _confirm_needed(
        make_cfg(confirm_checks=3, confirm_checks_high=5, high_ask_threshold=0.80),
        0.81,
    ) == 5


def test_size_scales_down_at_higher_ask():
    cfg = make_cfg(
        order_shares=10.0,
        size_scale_enabled=True,
        size_scale_ref_ask=0.75,
    )
    s75 = _scaled_size(cfg, 0.75, 5.0)
    s79 = _scaled_size(cfg, 0.79, 5.0)
    assert s75 == 10.0
    assert s79 < s75
    assert s79 >= 5.0


def test_size_scale_buys_smaller_at_079():
    cfg = make_cfg(
        delta_filter_enabled=False,
        confirm_checks=1,
        max_entry_price=0.79,
        min_net_edge=0.05,
        order_shares=10.0,
        size_scale_enabled=True,
        size_scale_ref_ask=0.75,
        max_order_usd=20.0,
    )
    d = decide(
        cfg,
        _market(elapsed=250.0),
        TopOfBook(0.20, 50, 0.99, 50),
        TopOfBook(0.70, 50, 0.79, 50),
        None,
        StrategyState(),
        already_in_market=False,
    )
    assert d.action == "BUY"
    assert d.size is not None and d.size < 10.0


def test_eth5m_disables_btc_hold_table_and_tightens_band():
    cfg, product = apply_product(make_cfg(), "eth5m")
    assert product.key == "eth5m"
    assert cfg.lead_table_enabled is False
    assert cfg.max_entry_price == 0.78
    assert cfg.opening_gap_max_entry_price == 0.76
    assert cfg.down_max_delta_usd <= -1.0


def test_sol5m_also_no_btc_hold_table():
    cfg, _ = apply_product(make_cfg(), "sol5m")
    assert cfg.lead_table_enabled is False
    assert cfg.max_entry_price == 0.78
