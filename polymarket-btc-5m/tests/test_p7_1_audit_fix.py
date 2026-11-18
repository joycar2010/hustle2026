"""P7.1: discover filters, status labels, activity / residual attribution."""
from __future__ import annotations

import time
from pathlib import Path

from btc5m.audit import maker_session_activity_report, split_edge_attribution_report
from btc5m.dashboard_api import _heartbeat_status_label
from btc5m.event_state import MatchPhase, MatchState
from btc5m.odds_bus import FairQuote, MockSharpProvider, OddsBus
from btc5m.sports_discover import _is_prop, _mainline_score
from btc5m.sports_mm import SportsMmEngine
from btc5m.store import Store
from conftest import make_cfg
from btc5m.products import apply_product


def test_prop_filter_catches_map_and_game_variants():
    assert _is_prop("cs2-x-game1", "Map 1 Winner")
    assert _is_prop("cs2-x-game-1", "Game 1 Winner")
    assert _is_prop("atp-x-first-set-winner", "Set 1 Winner")
    assert _is_prop("nba-x-spread-away-5", "Spread: Away -5")
    assert not _is_prop("cs2-faze-wc1-2026-11-24", "FaZe vs Wildcard (BO1)")
    assert not _is_prop("atp-alcaraz-medvede-2026-11-17", "Alcaraz vs Medvedev")


def test_mainline_score_prefers_event_slug():
    event = "cs2-faze-wc1-2026-11-24"
    assert _mainline_score(event, {"slug": event, "question": "FaZe vs Wildcard"}) > _mainline_score(
        event, {"slug": event + "-game1", "question": "Map 1 Winner"}
    )


def test_status_label_splits_risk_and_empty():
    assert (
        _heartbeat_status_label(
            "product=atp status=risk_blocked reason=daily_loss",
            enabled=True,
            ok=True,
        )
        == "risk blocked"
    )
    assert (
        _heartbeat_status_label(
            "product=cs status=outside_window discover_pre=12 nearest_h=8.50",
            enabled=True,
            ok=True,
        )
        == "outside pregame window"
    )
    assert (
        _heartbeat_status_label(
            "product=cs status=mock_odds_quote_disabled discover_pre=5",
            enabled=True,
            ok=True,
        )
        == "mock odds (no quote)"
    )
    assert (
        _heartbeat_status_label("", enabled=False, ok=False, reason="scaffold")
        == "未启用 / 暂无策略"
    )


def test_activity_and_split_attribution(tmp_path: Path):
    db = tmp_path / "split.db"
    store = Store(db)
    # empty closed
    s1 = store.open_maker_session(
        market_slug="m1", condition_id="c1", up_token="u", down_token="d", dry_run=True
    )
    store.close_maker_session(
        s1,
        paired_shares=0,
        pair_cost=None,
        residual_side=None,
        residual_shares=0,
        winner="EMPTY",
        gross_pnl_usd=0,
        fee_usd=0,
        rebate_est_usd=0,
        net_pnl_usd=0,
    )
    # filled residual winner-ish
    s2 = store.open_maker_session(
        market_slug="m2", condition_id="c2", up_token="u", down_token="d", dry_run=True
    )
    store.update_maker_inventory(s2, up_shares=0, down_shares=5, up_cost_usd=25, down_cost_usd=25)
    store.conn.execute(
        """
        UPDATE maker_sessions SET merged_shares=45, up_proceeds_usd=4.95, down_proceeds_usd=0,
               merge_proceeds_usd=45, redeem_proceeds_usd=5, flatten_pnl_usd=0
        WHERE id=?
        """,
        (s2,),
    )
    store.conn.commit()
    store.close_maker_session(
        s2,
        paired_shares=45,
        pair_cost=None,
        residual_side="DOWN",
        residual_shares=5,
        winner="DOWN",
        gross_pnl_usd=4.95,
        fee_usd=0,
        rebate_est_usd=0.02,
        net_pnl_usd=4.97,
    )

    act = maker_session_activity_report(db)
    assert act["empty_closed_sessions"] == 1
    assert act["filled_sessions"] == 1
    assert act["wins"] == 1

    edge = split_edge_attribution_report(db)
    assert edge["sessions"] == 2
    assert edge["residual_winner_kept"] >= 1


def test_sports_mm_skips_quotes_on_mock_when_disabled(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        series_slug="atp",
        product_key="atp",
        mode="sports_mm",
        sports_quote_on_mock=False,
    )
    cfg, _ = apply_product(cfg, "atp")
    eng = SportsMmEngine(cfg, odds=OddsBus([MockSharpProvider()]))
    assert eng.odds.using_mock
    from btc5m.book import TopOfBook
    from btc5m.sports_discover import MainlineMarket

    now = time.time()
    m = MainlineMarket(
        event_slug="atp-test",
        event_title="A vs B",
        market_slug="atp-test",
        condition_id="0x1",
        question="A vs B",
        home="A",
        away="B",
        home_token="th",
        away_token="ta",
        start_ts=now + 1800,
        tick_size=0.01,
        min_size=5,
        state=MatchState(
            event_slug="atp-test",
            home="A",
            away="B",
            phase=MatchPhase.PRE_GAME,
            start_ts=now + 1800,
        ),
    )
    h, a = eng._target_buys(m, TopOfBook(0.40, 10, 0.45, 10), TopOfBook(0.40, 10, 0.55, 10))
    assert h is None and a is None

    # Inject non-mock fair → may quote
    eng.odds.fair_match = lambda *args, **kwargs: FairQuote(  # type: ignore[method-assign]
        event_key="atp-test",
        home="A",
        away="B",
        p_home=0.60,
        p_away=0.40,
        source="sharp_test",
        ts=now,
    )
    eng.quote_on_mock = False
    h2, a2 = eng._target_buys(m, TopOfBook(0.48, 10, 0.50, 10), TopOfBook(0.48, 10, 0.55, 10))
    assert h2 is not None
    assert a2 is None
