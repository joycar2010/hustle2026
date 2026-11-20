"""P7 multi-series: products, BTC15 overlays, odds bus, event state — BTC5m untouched."""
from __future__ import annotations

import time
from pathlib import Path

from btc5m.config import Config
from btc5m.event_state import MatchPhase, MatchState, infer_phase, transition
from btc5m.markets import window_start_ts
from btc5m.odds_bus import MockSharpProvider, OddsBus, deveig_two_way
from btc5m.phase_stubs import (
    assert_dota_soccer_live_ready,
    assert_nba_nfl_ready,
)
from btc5m.products import BTC_5M, BTC_15M, apply_product, get_product, list_products
from btc5m.sports_discover import _is_prop
from btc5m.sports_mm import SportsMmEngine
from conftest import make_cfg


def test_btc5m_apply_is_identity_on_critical_defaults():
    cfg = make_cfg()
    out, product = apply_product(cfg, "btc-up-or-down-5m")
    assert product.key == "btc5m"
    assert out.series_slug == "btc-up-or-down-5m"
    assert out.window_sec == 300
    assert out.market_slug_prefix == "btc-updown-5m"
    assert out.split_db_name == "split_sell_paper.db"
    assert out.maker_db_name == "maker_paper.db"
    # Split defaults unchanged vs input cfg
    assert out.split_residual_sla_sec == cfg.split_residual_sla_sec
    assert out.split_lean_abort_sec == cfg.split_lean_abort_sec


def test_btc15m_overlays_longer_slas_and_separate_ledger():
    cfg = make_cfg()
    out, product = apply_product(cfg, "btc15m")
    assert product is BTC_15M
    assert out.series_slug == "btc-up-or-down-15m"
    assert out.window_sec == 900
    assert out.market_slug_prefix == "btc-updown-15m"
    assert out.split_db_name == "split_sell_15m_paper.db"
    assert out.split_residual_sla_sec == 35.0
    assert out.split_lean_abort_sec == 35.0
    assert out.split_stop_before_end_sec == 90.0
    assert out.mode == "split_sell"
    # 5m ledger name must remain available on baseline product
    assert BTC_5M.split_db_name == "split_sell_paper.db"


def test_window_start_ts_15m_alignment():
    # 1794938400 is on a 900s boundary from live sample
    assert window_start_ts(1794938400, window_sec=900) == 1794938400
    assert window_start_ts(1794938400 + 100, window_sec=900) == 1794938400
    # 5m baseline still 300
    assert window_start_ts(1_794_595_574) == 1_794_595_500


def test_phase3_4_enabled_for_paper_sports_mm():
    # P8: gates are soft (log only); products are enabled
    assert_nba_nfl_ready()
    assert_dota_soccer_live_ready()
    cfg, product = apply_product(make_cfg(), "nba-2026")
    assert product.key == "nba"
    assert cfg.mode == "sports_mm"


def test_odds_bus_mock_and_deveig():
    bus = OddsBus([MockSharpProvider()])
    q1 = bus.fair_match("evt-a", "A", "B")
    q2 = bus.fair_match("evt-a", "A", "B")
    assert q1 is not None and q2 is not None
    assert abs(q1.p_home - q2.p_home) < 1e-12
    assert abs(q1.p_home + q1.p_away - 1.0) < 1e-9
    p_h, p_a = deveig_two_way(2.10, 1.80)
    assert abs(p_h + p_a - 1.0) < 1e-9


def test_event_state_pre_game_gate():
    now = time.time()
    st = MatchState(
        event_slug="atp-x",
        home="A",
        away="B",
        phase=MatchPhase.PRE_GAME,
        start_ts=now + 3600,
    )
    assert st.may_quote_mainline(now=now)
    live = transition(st, now=now + 4000)
    assert live.phase == MatchPhase.LIVE
    assert not live.may_quote_mainline(now=now + 4000)
    assert infer_phase(now=now, start_ts=now + 10) == MatchPhase.PRE_GAME


def test_prop_filter_keeps_mainline():
    assert not _is_prop("atp-cobolli-tiafoe-2026-11-17", "Cobolli vs Tiafoe")
    assert _is_prop(
        "atp-cobolli-tiafoe-2026-11-17-first-set-winner",
        "Set 1 Winner",
    )
    assert _is_prop("dota2-x-game-1", "Game 1: Both Teams Beat Roshan?")
    assert _is_prop("cs2-x-game1", "Map 1 Winner")


def test_sports_mm_quotes_when_fair_edge(tmp_path: Path, monkeypatch):
    cfg = make_cfg(
        data_dir=tmp_path,
        series_slug="atp",
        product_key="atp",
        mode="sports_mm",
        order_shares=10.0,
    )
    cfg, _ = apply_product(cfg, "atp")
    eng = SportsMmEngine(cfg)

    from btc5m.odds_bus import FairQuote
    from btc5m.sports_discover import MainlineMarket
    from btc5m.book import TopOfBook

    now = time.time()
    m = MainlineMarket(
        event_slug="atp-test",
        event_title="A vs B",
        market_slug="atp-test",
        condition_id="0xsports",
        question="A vs B",
        home="Alice",
        away="Bob",
        home_token="th",
        away_token="ta",
        start_ts=now + 1800,
        tick_size=0.01,
        min_size=5,
        state=MatchState(
            event_slug="atp-test",
            home="Alice",
            away="Bob",
            phase=MatchPhase.PRE_GAME,
            start_ts=now + 1800,
        ),
    )
    # Fair home 0.60, poly ask 0.50 → edge 0.10 ≥ 0.04
    eng.odds.fair_match = lambda *a, **k: FairQuote(  # type: ignore[method-assign]
        event_key="atp-test",
        home="Alice",
        away="Bob",
        p_home=0.60,
        p_away=0.40,
        source="test",
        ts=now,
    )
    home_book = TopOfBook(0.48, 10, 0.50, 10)
    away_book = TopOfBook(0.48, 10, 0.55, 10)
    h_px, a_px = eng._target_buys(m, home_book, away_book)
    assert h_px is not None
    assert a_px is None  # away ask 0.55 not cheap vs 0.40


def test_list_products_ordered_phases():
    keys = [p.key for p in list_products()]
    assert keys[:4] == ["btc5m", "btc15m", "eth5m", "sol5m"]
    assert "atp" in keys and "cs" in keys
    assert get_product("counter-strike").key == "cs"
