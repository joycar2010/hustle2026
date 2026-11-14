from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from btc5m.book import TopOfBook
from btc5m.markets import LiveMarket
from btc5m.signal import BtcSignal
from btc5m.strategy import StrategyState, decide, net_edge, taker_fee_per_share
from conftest import make_cfg


def _market(t_left: float = 30.0, *, elapsed: float | None = None) -> LiveMarket:
    if elapsed is not None:
        start = time.time() - elapsed
        end = start + 300
    else:
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


def _signal(
    side: str = "UP",
    delta: float = 30.0,
    *,
    consensus: bool = True,
    venues: int = 2,
    hold_wr: float = 0.90,
    lead_bp: float = 8.0,
) -> BtcSignal:
    return BtcSignal(
        ts=0,
        source="test",
        price_to_beat=100,
        current_price=100 + delta,
        delta_usd=delta,
        signal_side=side,
        venue_count=venues,
        consensus=consensus,
        lead_bp=lead_bp,
        projected_close=100 + delta,
        projected_lead_bp=lead_bp,
        projected_delta_usd=delta,
        hold_wr=hold_wr,
        in_final_minute=False,
        opening_gap_bp=lead_bp,
        decision_side=side,
    )


def test_taker_fee_peaks_near_half():
    fee = taker_fee_per_share(0.07, 0.50)
    assert abs(fee - 0.0175) < 1e-9
    assert net_edge(0.90, 0.07) > 0.09


def test_skips_outside_window():
    cfg = make_cfg()
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
    assert "waiting" in d.reason or "outside" in d.reason


def test_hard_bans_high_price_bucket():
    cfg = make_cfg(delta_filter_enabled=False, confirm_checks=1, max_entry_price=0.95)
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
    cfg = make_cfg(
        delta_filter_enabled=True,
        confirm_checks=2,
        max_entry_price=0.90,
        min_net_edge=0.05,
        late_edge_hard_ban_price=0.90,
        lead_table_enabled=False,
    )
    state = StrategyState()
    market = _market(t_left=25)
    up = TopOfBook(0.80, 50, 0.85, 50)
    down = TopOfBook(0.01, 50, 0.99, 50)
    signal = _signal("UP", 30)
    d1 = decide(cfg, market, up, down, signal, state, already_in_market=False)
    assert d1.action == "SKIP"
    assert "confirm 1/2" in d1.reason
    d2 = decide(cfg, market, up, down, signal, state, already_in_market=False)
    assert d2.action == "BUY"
    assert d2.side == "UP"
    assert d2.price == 0.85


def test_blocks_failed_consensus():
    cfg = make_cfg(delta_filter_enabled=True, confirm_checks=1, signal_min_venues=2)
    state = StrategyState()
    d = decide(
        cfg,
        _market(t_left=25),
        TopOfBook(0.80, 50, 0.85, 50),
        TopOfBook(0.01, 50, 0.99, 50),
        _signal("UP", 30, consensus=False, venues=2),
        state,
        already_in_market=False,
    )
    assert d.action == "SKIP"
    assert "consensus" in d.reason


def test_lead_table_rejects_expensive_ask():
    cfg = make_cfg(
        delta_filter_enabled=False,
        confirm_checks=1,
        lead_table_enabled=True,
        lead_edge_margin=0.03,
        max_entry_price=0.90,
        min_net_edge=0.01,
    )
    # hold ~0.66 at bell with 5-10bp → ask 0.85 is expensive after fee+margin
    state = StrategyState()
    d = decide(
        cfg,
        _market(elapsed=5.0),
        TopOfBook(0.80, 50, 0.85, 50),
        TopOfBook(0.01, 50, 0.99, 50),
        _signal("UP", 40, hold_wr=0.66, lead_bp=6.0),
        state,
        already_in_market=False,
    )
    # opening_gap disabled → outside late window at elapsed=5 → skip waiting
    assert d.action == "SKIP"


def test_opening_gap_buy_when_cheap():
    cfg = make_cfg(
        delta_filter_enabled=True,
        confirm_checks=1,
        opening_gap_enabled=True,
        opening_gap_min_bp=5.0,
        opening_gap_window_sec=60.0,
        lead_table_enabled=True,
        lead_edge_margin=0.03,
        max_entry_price=0.70,
        min_entry_price=0.50,
        min_net_edge=0.01,
        late_edge_hard_ban_price=0.90,
        up_min_delta_usd=1.0,
    )
    state = StrategyState()
    # At bell with 8bp lead, hold≈66%; ask 0.55 is cheap
    d = decide(
        cfg,
        _market(elapsed=10.0),
        TopOfBook(0.50, 50, 0.55, 50),
        TopOfBook(0.40, 50, 0.50, 50),
        _signal("UP", 50, hold_wr=0.66, lead_bp=8.0),
        state,
        already_in_market=False,
    )
    assert d.action == "BUY"
    assert d.phase == "opening_gap"
    assert d.side == "UP"


def test_bucket_calibration_ban(tmp_path: Path):
    db = tmp_path / "paper.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE positions (
          id INTEGER PRIMARY KEY,
          status TEXT,
          entry_price REAL,
          closed_ts REAL,
          pnl_usd REAL,
          pnl_net_usd REAL
        )
        """
    )
    now = time.time()
    for i in range(8):
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?)",
            (i + 1, "closed", 0.87, now, -8.0, -8.5),
        )
    conn.commit()
    conn.close()

    cfg = make_cfg(
        delta_filter_enabled=False,
        confirm_checks=1,
        max_entry_price=0.90,
        min_net_edge=0.05,
        bucket_calibration_enabled=True,
        bucket_min_samples=8,
        lead_table_enabled=False,
    )
    state = StrategyState()
    d = decide(
        cfg,
        _market(t_left=25),
        TopOfBook(0.80, 50, 0.87, 50),
        TopOfBook(0.01, 50, 0.99, 50),
        None,
        state,
        already_in_market=False,
        db_path=db,
    )
    assert d.action == "SKIP"
    assert "bucket_cal_ban" in d.reason
