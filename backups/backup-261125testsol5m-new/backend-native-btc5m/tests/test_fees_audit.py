from __future__ import annotations

from pathlib import Path

from btc5m.audit import summarize_db
from btc5m.fees import net_edge_after_taker_fee, taker_fee_per_share, taker_fee_usd
from btc5m.store import Store


def test_taker_fee_curve():
    assert abs(taker_fee_per_share(0.50) - 0.0175) < 1e-9
    assert abs(taker_fee_usd(0.90, 10) - 0.063) < 1e-9
    assert net_edge_after_taker_fee(0.90) > 0.09


def test_audit_from_maker_session(tmp_path: Path):
    db = tmp_path / "t.db"
    store = Store(db)
    sid = store.open_maker_session(
        market_slug="btc-updown-5m-1",
        condition_id="0x1",
        up_token="u",
        down_token="d",
        dry_run=True,
    )
    store.update_maker_inventory(
        sid,
        up_shares=10,
        down_shares=10,
        up_cost_usd=4.7,
        down_cost_usd=5.0,
    )
    store.close_maker_session(
        sid,
        paired_shares=10,
        pair_cost=0.97,
        residual_side=None,
        residual_shares=0,
        winner="UP",
        gross_pnl_usd=0.30,
        fee_usd=0.0,
        rebate_est_usd=0.0,
        net_pnl_usd=0.30,
    )
    rows = summarize_db(db, since_ts=0)
    assert len(rows) == 1
    assert rows[0].strategy == "maker_mm"
    assert abs(rows[0].net_pnl_usd - 0.30) < 1e-9
