from __future__ import annotations

from btc5m.lead_table import edge_after_fee, hold_win_rate, is_cheap_vs_hold
from btc5m.split_sell import settle_split_sell
from btc5m.twap import clear_ring, lead_bp, note_spot, projected_close_twap
import time


def test_hold_table_rises_with_lead_and_time():
    early = hold_win_rate(elapsed_sec=0, lead_bp=6)
    late = hold_win_rate(elapsed_sec=240, lead_bp=6)
    assert late.hold_wr > early.hold_wr
    big = hold_win_rate(elapsed_sec=180, lead_bp=20)
    small = hold_win_rate(elapsed_sec=180, lead_bp=0.5)
    assert big.hold_wr > small.hold_wr


def test_cheap_vs_hold_gate():
    # 92% hold, ask 0.85 → after fee+3¢ still cheap
    assert is_cheap_vs_hold(0.85, 0.92, margin=0.03)
    # 66% hold, ask 0.85 → expensive
    assert not is_cheap_vs_hold(0.85, 0.66, margin=0.03)
    assert edge_after_fee(0.55, 0.66, margin=0.03) > 0


def test_projected_twap_blends_final_minute():
    clear_ring()
    end = time.time() + 30  # 30s left → in final minute
    # Seed samples older in the final minute
    for i in range(20):
        note_spot(100.0 + i * 0.1, ts=end - 60 + i)
    proj = projected_close_twap(beat=100.0, spot=110.0, end_ts=end, now=end - 30)
    assert proj.in_final_minute
    assert proj.projected_close != 110.0
    assert abs(lead_bp(110, 100) - 1000.0) < 1e-6


def test_split_sell_settlement_profit_and_rebate():
    # Mint 50, sell 20 up @0.55 and 20 down @0.52, merge 30, redeem 0
    r = settle_split_sell(
        mint_cost=50.0,
        up_proceeds=20 * 0.55,
        down_proceeds=20 * 0.52,
        merge_proceeds=30.0,
        redeem_proceeds=0.0,
        rebate_est=0.5,
        up_inv=0.0,
        down_inv=0.0,
    )
    # Cash = 11+10.4+30 = 51.4. Unpaid estimated rebates stay independent.
    assert abs(r["net_pnl_usd"] - 1.4) < 1e-9
    assert r["rebate_est_usd"] == 0.5
    assert r["sell_proceeds"] == 21.4


def test_split_sell_engine_pair_max_lean_logic(tmp_path):
    from btc5m.split_sell import SplitSellEngine, SplitState
    from btc5m.markets import LiveMarket
    from conftest import make_cfg
    from pathlib import Path

    cfg = make_cfg(data_dir=tmp_path, split_max_lean_shares=5.0, split_clip_shares=5.0)
    eng = SplitSellEngine(cfg)
    m = LiveMarket(
        condition_id="0x1",
        market_slug="s",
        title="t",
        up_token="u",
        down_token="d",
        start_ts=time.time(),
        end_ts=time.time() + 200,
        tick_size=0.01,
        min_size=5,
        neg_risk=False,
        enable_order_book=True,
    )
    st = SplitState(
        session_id=1,
        market=m,
        mint_shares=50,
        up_inv=30,
        down_inv=50,
        mint_cost=50,
        up_sold=20,
        down_sold=0,
    )
    from btc5m.book import TopOfBook

    up = TopOfBook(0.48, 10, 0.52, 10)
    dn = TopOfBook(0.48, 10, 0.52, 10)
    up_px, dn_px = eng._target_asks(st, up, dn)
    # Historical abnormal inventory: lean = +20 > 5 → pull UP ask.
    assert up_px is None
    assert dn_px is not None
