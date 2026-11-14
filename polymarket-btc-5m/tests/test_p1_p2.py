from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from btc5m.calibration import bucket_ban_reason, load_bucket_stats, required_wr_for_price
from btc5m.heartbeat import read_heartbeat, status_report, write_heartbeat
from btc5m.maker import MakerEngine, settle_maker_pnl
from btc5m.stress import stress_late_edge_db
from btc5m.config import Config


def test_required_wr_rises_with_price():
    lo = required_wr_for_price(0.80)
    hi = required_wr_for_price(0.95)
    assert hi > lo
    assert hi >= 0.96


def test_bucket_ban_when_wr_below_required(tmp_path: Path):
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
    for i in range(10):
        # mix: 7 wins tiny, 3 losses large at 0.95 → WR 70% << ~97% need
        net = 0.4 if i < 7 else -9.5
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?)",
            (i + 1, "closed", 0.95, now, net, net),
        )
    conn.commit()
    conn.close()
    stats = load_bucket_stats(db, min_samples=8)
    banned = [s for s in stats if s.lo == 0.95 and s.banned]
    assert banned
    assert bucket_ban_reason(0.95, db, min_samples=8)


def test_heartbeat_stale_alert(tmp_path: Path):
    write_heartbeat(tmp_path, mode="maker", market_slug="x", detail="ok")
    hb = read_heartbeat(tmp_path, "maker")
    assert hb is not None
    assert hb.age_sec < 5
    # force stale by rewriting old ts
    path = tmp_path / "heartbeat_maker.json"
    path.write_text(
        json.dumps(
            {
                "mode": "maker",
                "ts": time.time() - 500,
                "market_slug": "x",
                "detail": "old",
                "pnl_usd": 0,
                "open_positions": 0,
            }
        )
    )
    report = status_report(tmp_path, stale_sec=120)
    assert report["ok"] is False
    assert any("stale" in a for a in report["alerts"])


def test_stress_applies_slip_and_fee(tmp_path: Path):
    db = tmp_path / "paper.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE positions (
          id INTEGER PRIMARY KEY,
          status TEXT,
          side TEXT,
          size REAL,
          entry_price REAL,
          exit_price REAL,
          pnl_usd REAL,
          pnl_net_usd REAL,
          fee_usd REAL
        )
        """
    )
    # win: bought 10 @0.85, exit 1.0; fee ≈ 0.07*0.85*0.15*10 = 0.08925 → net ≈ 1.41075
    fee = 0.07 * 0.85 * 0.15 * 10
    net = 10 * (1.0 - 0.85) - fee
    conn.execute(
        "INSERT INTO positions VALUES (1,'closed','UP',10,0.85,1.0,?,?,?)",
        (10 * 0.15, net, fee),
    )
    conn.commit()
    conn.close()
    result = stress_late_edge_db(db, slip_ticks=1.0, fee_rate=0.07)
    assert result is not None
    assert result.n == 1
    # 1-tick adverse slip worsens entry → lower net
    assert result.stressed_net < result.baseline_net
    assert result.delta < 0


def test_maker_pair_profit_min_tightens_cap():
    # settle still works; profit min is enforced at quote time via config
    r = settle_maker_pnl(
        up_shares=10,
        down_shares=10,
        up_cost=4.7,
        down_cost=5.0,
        up_fee=0.0,
        down_fee=0.0,
        winner="UP",
    )
    assert r["pair_cost"] == 0.97
    assert r["gross_pnl_usd"] > 0


def _cfg(tmp_path: Path, **overrides) -> Config:
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
        max_entry_price=0.88,
        min_net_edge=0.08,
        taker_fee_rate=0.07,
        confirm_checks=3,
        poll_interval_sec=1.0,
        delta_filter_enabled=True,
        up_min_delta_usd=25.0,
        down_max_delta_usd=-25.0,
        price_hosts="okx",
        signal_require_consensus=True,
        signal_min_venues=2,
        order_shares=10.0,
        max_order_usd=15.0,
        daily_loss_limit_usd=40.0,
        max_open_positions=1,
        paper_bankroll_usd=200.0,
        live_trading_enabled=False,
        mode="maker",
        late_edge_hard_ban_price=0.90,
        late_edge_edge_safety=1.25,
        bucket_calibration_enabled=True,
        bucket_lookback_sec=7 * 86400.0,
        bucket_min_samples=8,
        bucket_wr_buffer=0.02,
        maker_pair_cost_max=0.97,
        maker_pair_profit_min=0.03,
        maker_quote_shares=10.0,
        maker_start_delay_sec=15.0,
        maker_stop_before_end_sec=60.0,
        maker_touch_fill_sec=12.0,
        maker_max_imbalance_shares=10.0,
        maker_allow_crossed_fills=False,
        maker_flatten_residual=True,
        heartbeat_stale_sec=120.0,
        data_dir=tmp_path,
    )
    base.update(overrides)
    return Config(**base)


def test_maker_effective_pair_max_uses_profit_floor(tmp_path: Path):
    eng = MakerEngine(_cfg(tmp_path))
    # max(0.97, via profit 1-0.03=0.97) → 0.97; with profit_min=0.05 → 0.95
    assert abs(eng._effective_pair_max() - 0.97) < 1e-9
    eng2 = MakerEngine(_cfg(tmp_path, maker_pair_profit_min=0.05, maker_pair_cost_max=0.97))
    assert abs(eng2._effective_pair_max() - 0.95) < 1e-9
