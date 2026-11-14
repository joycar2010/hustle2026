from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from btc5m.calibration import bucket_ban_reason, load_bucket_stats, required_wr_for_price
from btc5m.heartbeat import read_heartbeat, status_report, write_heartbeat
from btc5m.maker import MakerEngine, settle_maker_pnl
from btc5m.stress import stress_late_edge_db
from conftest import make_cfg


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


def test_maker_effective_pair_max_uses_profit_floor(tmp_path: Path):
    eng = MakerEngine(make_cfg(data_dir=tmp_path, maker_pair_profit_min=0.03))
    assert abs(eng._effective_pair_max() - 0.97) < 1e-9
    eng2 = MakerEngine(
        make_cfg(data_dir=tmp_path, maker_pair_profit_min=0.05, maker_pair_cost_max=0.97)
    )
    assert abs(eng2._effective_pair_max() - 0.95) < 1e-9
