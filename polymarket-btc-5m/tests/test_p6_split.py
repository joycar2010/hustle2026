"""P6: C split_sell bilateral touch quotes + residual closed loop."""
from __future__ import annotations

import time
from pathlib import Path

from btc5m.book import TopOfBook
from btc5m.markets import LiveMarket
from btc5m.split_sell import SplitSellEngine, SplitState, settle_split_sell
from conftest import make_cfg


def _market(end_in: float = 200.0) -> LiveMarket:
    now = time.time()
    return LiveMarket(
        condition_id="0xp6",
        market_slug="btc-updown-5m-p6",
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


def test_join_touch_quotes_both_when_pair_ok(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        split_join_touch=True,
        split_min_pair_ask=1.01,
        split_min_ask_price=0.15,
    )
    eng = SplitSellEngine(cfg)
    st = SplitState(
        session_id=1,
        market=_market(),
        mint_shares=50,
        up_inv=50,
        down_inv=50,
        mint_cost=50,
    )
    # Skewed book but touch pair 0.84+0.18=1.02 ≥ 1.01
    up = TopOfBook(0.80, 10, 0.84, 10)
    dn = TopOfBook(0.15, 10, 0.18, 10)
    up_px, dn_px = eng._target_asks(st, up, dn)
    assert up_px is not None and dn_px is not None
    assert abs(up_px - 0.84) < 1e-9
    assert abs(dn_px - 0.18) < 1e-9
    assert up_px + dn_px + 1e-12 >= 1.01


def test_join_touch_does_not_lift_weak_side_to_fair(tmp_path: Path):
    """Regression: old logic quoted weak side ~0.60 while touch was ~0.18."""
    cfg = make_cfg(
        data_dir=tmp_path,
        split_join_touch=True,
        split_fair_edge=0.03,
        split_min_ask_price=0.15,
    )
    eng = SplitSellEngine(cfg)
    # Force skewed fair (UP heavy) — fair_dn+edge≈0.18; must not lift to ~0.60
    eng._fair_probs = lambda market: (0.85, 0.15)  # type: ignore[method-assign]
    st = SplitState(
        session_id=1,
        market=_market(),
        mint_shares=50,
        up_inv=50,
        down_inv=50,
        mint_cost=50,
    )
    up = TopOfBook(0.80, 10, 0.84, 10)
    dn = TopOfBook(0.15, 10, 0.18, 10)
    _up_px, dn_px = eng._target_asks(st, up, dn)
    assert dn_px is not None
    assert dn_px <= 0.20 + 1e-9  # join touch, not lofty fair lift


def test_catchup_only_quotes_lagging_leg(tmp_path: Path):
    cfg = make_cfg(data_dir=tmp_path, split_max_lean_shares=3.0, split_join_touch=True)
    eng = SplitSellEngine(cfg)
    st = SplitState(
        session_id=1,
        market=_market(),
        mint_shares=50,
        up_inv=30,
        down_inv=50,
        mint_cost=50,
        up_sold=20,
        down_sold=0,
    )
    up = TopOfBook(0.48, 10, 0.52, 10)
    dn = TopOfBook(0.48, 10, 0.52, 10)
    up_px, dn_px = eng._target_asks(st, up, dn)
    assert up_px is None
    assert dn_px is not None


def test_residual_sla_flattens_and_merges(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        split_residual_flatten=True,
        split_residual_sla_sec=20.0,
    )
    eng = SplitSellEngine(cfg)
    m = _market()
    sid = eng.store.open_maker_session(
        market_slug=m.market_slug,
        condition_id=m.condition_id,
        up_token=m.up_token,
        down_token=m.down_token,
        dry_run=True,
    )
    st = SplitState(
        session_id=sid,
        market=m,
        mint_shares=50,
        up_inv=40,
        down_inv=50,
        mint_cost=50,
        up_sold=10,
        down_sold=0,
        residual_since=time.time() - 25,
    )
    eng.store.update_maker_inventory(
        sid, up_shares=40, down_shares=50, up_cost_usd=25, down_cost_usd=25
    )
    up = TopOfBook(0.40, 10, 0.50, 10)
    dn = TopOfBook(0.40, 10, 0.50, 10)
    assert eng._maybe_residual_sla(st, up, dn, time.time())
    assert st.residual_flattened
    assert not st.quoting
    assert abs(st.up_inv) < 1e-9
    assert abs(st.down_inv) < 1e-9
    assert st.merged == 40


def test_settle_reports_flatten_without_double_count():
    r = settle_split_sell(
        mint_cost=50.0,
        up_proceeds=10.0,
        down_proceeds=8.0,  # includes flatten sell cash
        merge_proceeds=40.0,
        redeem_proceeds=0.0,
        rebate_est=0.5,
        up_inv=0.0,
        down_inv=0.0,
        flatten_pnl_usd=-1.0,
    )
    # cash = 10+8+40+0.5 = 58.5; net = 8.5 (flatten pnl not added again)
    assert abs(r["net_pnl_usd"] - 8.5) < 1e-9
    assert abs(r["flatten_pnl_usd"] + 1.0) < 1e-9
