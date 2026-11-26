"""P5a split_sell floors / lean abort + P5b maker SLA / min bid."""
from __future__ import annotations

import time
from pathlib import Path

from btc5m.book import TopOfBook
from btc5m.maker import MakerEngine, MakerState
from btc5m.markets import LiveMarket
from btc5m.split_sell import SplitSellEngine, SplitState
from conftest import make_cfg


def _market(end_in: float = 200.0) -> LiveMarket:
    now = time.time()
    return LiveMarket(
        condition_id="0xp5",
        market_slug="btc-updown-5m-p5",
        title="t",
        up_token="u",
        down_token="d",
        start_ts=now - 30,
        end_ts=now + end_in,
        tick_size=0.01,
        min_size=5,
        neg_risk=False,
        enable_order_book=True,
    )


def test_maker_min_bid_lifts_lottery_book(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        maker_min_bid_price=0.20,
        maker_pair_cost_max=0.96,
        maker_pair_profit_min=0.03,
    )
    eng = MakerEngine(cfg)
    m = _market()
    st = MakerState(session_id=1, market=m)
    # Cheap book — lift to min bid (pair 0.40 still under cap)
    up = TopOfBook(0.05, 10, 0.08, 10)
    dn = TopOfBook(0.05, 10, 0.08, 10)
    up_px, dn_px = eng._target_bids(m, up, dn, st)
    assert up_px == 0.20 and dn_px == 0.20

    # Already long expensive UP → cannot complete pair at min bid under cap
    st2 = MakerState(session_id=2, market=m, up_shares=10, up_cost=8.0)  # avg 0.80
    up_px2, dn_px2 = eng._target_bids(m, up, dn, st2)
    assert up_px2 is None and dn_px2 is None


def test_maker_missing_leg_only_and_min_bid(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        maker_min_bid_price=0.20,
        maker_pair_cost_max=0.96,
        maker_pair_profit_min=0.03,
    )
    eng = MakerEngine(cfg)
    m = _market()
    st = MakerState(
        session_id=1,
        market=m,
        up_shares=10,
        up_cost=4.5,  # avg 0.45 → missing DOWN must be ≤ 0.51
    )
    up = TopOfBook(0.40, 10, 0.50, 10)
    dn = TopOfBook(0.48, 10, 0.52, 10)
    up_px, dn_px = eng._target_bids(m, up, dn, st)
    assert up_px is None
    assert dn_px is not None
    assert dn_px >= 0.20
    assert 0.45 + dn_px <= 0.97 + 1e-9


def test_maker_pair_complete_sla_flattens(tmp_path: Path, monkeypatch):
    cfg = make_cfg(
        data_dir=tmp_path,
        maker_early_flatten=True,
        maker_flatten_residual=True,
        maker_pair_complete_sec=20.0,
        maker_start_delay_sec=0.0,
        maker_stop_before_end_sec=10.0,
        maker_zero_fill_kill_sec=5.0,  # won't trigger: we already have inventory
    )
    eng = MakerEngine(cfg)
    m = _market(end_in=120)
    now = time.time()
    st = MakerState(
        session_id=1,
        market=m,
        up_shares=10,
        up_cost=4.5,
        first_fill_ts=now - 30,
        imbalance_since=now - 25,  # > 20s
    )
    eng._state = st
    eng._last_slug = m.market_slug

    monkeypatch.setattr("btc5m.maker.fetch_live_market", lambda *a, **k: m)
    monkeypatch.setattr("btc5m.maker.fetch_book", lambda host, token: TopOfBook(0.40, 10, 0.50, 10))
    monkeypatch.setattr(eng, "_resolve_open", lambda: None)
    monkeypatch.setattr(eng, "_ensure_session", lambda market: st)

    eng.tick()
    assert st.flattened
    assert not st.quoting
    assert abs(st.up_shares) < 1e-9
    assert st.fill_quality.flatten >= 1


def test_maker_zero_fill_kill(tmp_path: Path, monkeypatch):
    cfg = make_cfg(
        data_dir=tmp_path,
        maker_start_delay_sec=0.0,
        maker_stop_before_end_sec=10.0,
        maker_zero_fill_kill_sec=90.0,
    )
    eng = MakerEngine(cfg)
    m = _market(end_in=80)  # t_left < 90, no fills
    st = MakerState(session_id=1, market=m, quoting=True)
    eng._state = st

    monkeypatch.setattr("btc5m.maker.fetch_live_market", lambda *a, **k: m)
    monkeypatch.setattr("btc5m.maker.fetch_book", lambda host, token: TopOfBook(0.45, 10, 0.55, 10))
    monkeypatch.setattr(eng, "_resolve_open", lambda: None)
    monkeypatch.setattr(eng, "_ensure_session", lambda market: st)

    eng.tick()
    assert st.killed_zero_fill
    assert not st.quoting
    assert not st.quotes


def test_split_min_pair_ask_blocks_cheap_dual(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        split_min_pair_ask=1.02,
        split_min_ask_price=0.35,
        split_fair_edge=0.01,
    )
    eng = SplitSellEngine(cfg)
    m = _market()
    st = SplitState(
        session_id=1,
        market=m,
        mint_shares=50,
        up_inv=50,
        down_inv=50,
        mint_cost=50,
    )
    # Force fair asks via monkeypatched _fair_asks returning cheap pair
    eng._fair_asks = lambda market, up, down: (0.48, 0.48)  # type: ignore[method-assign]
    up = TopOfBook(0.45, 10, 0.48, 10)
    dn = TopOfBook(0.45, 10, 0.48, 10)
    up_px, dn_px = eng._target_asks(st, up, dn)
    assert up_px is None and dn_px is None


def test_split_lean_abort_merges(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        split_max_lean_shares=3.0,
        split_lean_abort_sec=25.0,
    )
    eng = SplitSellEngine(cfg)
    m = _market()
    st = SplitState(
        session_id=1,
        market=m,
        mint_shares=50,
        up_inv=30,
        down_inv=50,
        mint_cost=50,
        up_sold=20,
        down_sold=0,
        lean_breach_since=time.time() - 30,
    )
    # open a real session row so inventory update works
    sid = eng.store.open_maker_session(
        market_slug=m.market_slug,
        condition_id=m.condition_id,
        up_token=m.up_token,
        down_token=m.down_token,
        dry_run=True,
    )
    st.session_id = sid
    eng.store.update_maker_inventory(
        sid, up_shares=30, down_shares=50, up_cost_usd=25, down_cost_usd=25
    )
    assert eng._maybe_lean_abort(st, time.time())
    assert st.lean_aborted
    assert not st.quoting
    assert st.merged == 30
    assert abs(st.up_inv) < 1e-9
    assert abs(st.down_inv - 20) < 1e-9
