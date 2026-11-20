"""C merge accounting persist/repair, B unpaired abort, eth/sol dashboard routing."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from btc5m.audit import late_edge_activity_report
from btc5m.book import TopOfBook
from btc5m.dashboard_api import _filter_slug_prefix, _resolve_group_db, positions, events
from btc5m.maker import MakerEngine, MakerState
from btc5m.markets import LiveMarket
from btc5m.split_sell import (
    SplitSellEngine,
    SplitState,
    repair_split_merge_accounting,
    settle_split_sell,
)
from btc5m.store import Store
from conftest import make_cfg


def _market(end_in: float = 200.0, slug: str = "btc-updown-5m-x") -> LiveMarket:
    now = time.time()
    return LiveMarket(
        condition_id="0xfix",
        market_slug=slug,
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


def test_full_merge_settle_net_near_zero():
    r = settle_split_sell(
        mint_cost=50.0,
        up_proceeds=0.0,
        down_proceeds=0.0,
        merge_proceeds=50.0,
        redeem_proceeds=0.0,
        rebate_est=0.0,
        up_inv=0.0,
        down_inv=0.0,
    )
    assert abs(r["net_pnl_usd"]) < 1e-9


def test_merge_cash_persisted_on_disk(tmp_path: Path):
    cfg = make_cfg(data_dir=tmp_path, split_size=50.0)
    eng = SplitSellEngine(cfg)
    m = _market()
    sid = eng.store.open_maker_session(
        market_slug=m.market_slug,
        condition_id=m.condition_id,
        up_token=m.up_token,
        down_token=m.down_token,
        dry_run=True,
    )
    eng.store.update_maker_inventory(
        sid, up_shares=50, down_shares=50, up_cost_usd=25, down_cost_usd=25
    )
    st = SplitState(
        session_id=sid,
        market=m,
        mint_shares=50,
        up_inv=50,
        down_inv=50,
        mint_cost=50,
    )
    eng._merge_pairs(st)
    row = eng.store.conn.execute(
        "SELECT merge_proceeds_usd, merged_shares, up_shares, down_shares "
        "FROM maker_sessions WHERE id=?",
        (sid,),
    ).fetchone()
    assert float(row["merge_proceeds_usd"]) == 50.0
    assert float(row["merged_shares"]) == 50.0
    assert float(row["up_shares"]) == 0.0
    assert float(row["down_shares"]) == 0.0


def test_repair_split_merge_accounting_case_a(tmp_path: Path):
    db = tmp_path / "split_sell_paper.db"
    store = Store(db)
    sid = store.open_maker_session(
        market_slug="btc-updown-5m-391",
        condition_id="0x391",
        up_token="u",
        down_token="d",
        dry_run=True,
    )
    store.update_maker_inventory(
        sid, up_shares=0, down_shares=0, up_cost_usd=25, down_cost_usd=25
    )
    store.update_split_cash(
        sid,
        merge_proceeds_usd=50.0,
        merged_shares=50.0,
    )
    store.close_maker_session(
        sid,
        paired_shares=50,
        pair_cost=None,
        residual_side=None,
        residual_shares=0,
        winner="UP",
        gross_pnl_usd=-50.0,
        fee_usd=0.0,
        rebate_est_usd=0.0,
        net_pnl_usd=-50.0,
        merge_proceeds_usd=50.0,
        merged_shares=50.0,
    )
    out = repair_split_merge_accounting(db, dry_run=False)
    assert out["repaired"] == 1
    assert sid in out["ids"]
    row = store.conn.execute(
        "SELECT net_pnl_usd, accounting_original_net_pnl_usd FROM maker_sessions WHERE id=?",
        (sid,),
    ).fetchone()
    assert abs(float(row["net_pnl_usd"])) < 1e-6
    assert float(row["accounting_original_net_pnl_usd"]) == -50.0


def test_maker_unpaired_abort_on_pair_complete(tmp_path: Path, monkeypatch):
    cfg = make_cfg(
        data_dir=tmp_path,
        maker_early_flatten=True,
        maker_flatten_residual=True,
        maker_close_on_unpaired_flatten=True,
        maker_pair_complete_sec=12.0,
        maker_start_delay_sec=0.0,
        maker_stop_before_end_sec=10.0,
        maker_zero_fill_kill_sec=5.0,
    )
    eng = MakerEngine(cfg)
    m = _market(end_in=120)
    now = time.time()
    st = MakerState(
        session_id=eng.store.open_maker_session(
            market_slug=m.market_slug,
            condition_id=m.condition_id,
            up_token=m.up_token,
            down_token=m.down_token,
            dry_run=True,
        ),
        market=m,
        up_shares=10,
        up_cost=4.5,
        first_fill_ts=now - 30,
        imbalance_since=now - 25,
        paired_peak=0.0,  # never paired
    )
    eng.store.update_maker_inventory(
        st.session_id,
        up_shares=10,
        down_shares=0,
        up_cost_usd=4.5,
        down_cost_usd=0,
    )
    eng._state = st
    eng._last_slug = m.market_slug

    monkeypatch.setattr("btc5m.maker.fetch_live_market", lambda *a, **k: m)
    monkeypatch.setattr(
        "btc5m.maker.fetch_book", lambda host, token: TopOfBook(0.40, 10, 0.50, 10)
    )
    monkeypatch.setattr(eng, "_resolve_open", lambda: None)
    monkeypatch.setattr(eng, "_ensure_session", lambda market: st)

    eng.tick()
    assert st.closed
    assert st.flattened
    row = eng.store.conn.execute(
        "SELECT status, winner, net_pnl_usd FROM maker_sessions WHERE id=?",
        (st.session_id,),
    ).fetchone()
    assert row["status"] == "closed"
    assert row["winner"] == "UNPAIRED_ABORT"
    # flatten sold 10 @ 0.40 vs avg 0.45 → −0.50
    assert abs(float(row["net_pnl_usd"]) - (-0.50)) < 1e-6


def test_maker_paired_peak_skips_abort(tmp_path: Path):
    cfg = make_cfg(
        data_dir=tmp_path,
        maker_close_on_unpaired_flatten=True,
        maker_flatten_residual=True,
    )
    eng = MakerEngine(cfg)
    m = _market()
    st = MakerState(
        session_id=1,
        market=m,
        up_shares=10,
        down_shares=0,
        up_cost=4.0,
        paired_peak=5.0,  # had a pair earlier
        flattened=False,
    )
    up = TopOfBook(0.40, 10, 0.50, 10)
    dn = TopOfBook(0.40, 10, 0.50, 10)
    eng._flatten_residual(st, up, dn)
    assert not eng._abort_unpaired(st, reason="test")
    assert not st.closed


def test_resolve_group_db_eth_sol_before_abc():
    g, path = _resolve_group_db("eth5m")
    assert g == "eth5m"
    assert path.name == "paper_eth5m.db"
    g2, path2 = _resolve_group_db("SOL5M")
    assert g2 == "sol5m"
    assert path2.name == "paper_sol5m.db"
    g3, path3 = _resolve_group_db("B")
    assert g3 == "B"
    assert path3.name == "maker_paper.db"


def test_slug_prefix_filters_btc_rows():
    items = [
        {"market_slug": "btc-updown-5m-1", "id": 1},
        {"market_slug": "eth-updown-5m-2", "id": 2},
        {"market_slug": "sol-updown-5m-3", "id": 3},
    ]
    eth = _filter_slug_prefix(items, "eth5m")
    assert [i["id"] for i in eth] == [2]
    sol = _filter_slug_prefix(items, "sol5m")
    assert [i["id"] for i in sol] == [3]


def test_positions_events_route_to_product_db(tmp_path: Path, monkeypatch):
    eth_db = tmp_path / "paper_eth5m.db"
    btc_db = tmp_path / "paper.db"
    for path, slug in ((eth_db, "eth-updown-5m-1"), (btc_db, "btc-updown-5m-9")):
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE positions (
              id INTEGER PRIMARY KEY, opened_ts REAL, closed_ts REAL,
              market_slug TEXT, condition_id TEXT, side TEXT, token_id TEXT,
              size REAL, entry_price REAL, exit_price REAL, pnl_usd REAL,
              fee_usd REAL, pnl_net_usd REAL, liquidity TEXT, strategy TEXT,
              dry_run INTEGER, order_id TEXT, status TEXT
            );
            CREATE TABLE events (
              id INTEGER PRIMARY KEY, ts REAL, kind TEXT, market_slug TEXT, payload TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO positions(opened_ts, market_slug, condition_id, side, token_id, "
            "size, entry_price, dry_run, status) VALUES (1, ?, 'c', 'UP', 't', 10, 0.8, 1, 'open')",
            (slug,),
        )
        conn.execute(
            "INSERT INTO events(ts, kind, market_slug, payload) VALUES (1, 'tick', ?, '{}')",
            (slug,),
        )
        conn.commit()
        conn.close()

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # load() reads DATA_DIR — patch dashboard load
    from btc5m import dashboard_api as dash
    from btc5m.config import Config

    cfg = make_cfg(data_dir=tmp_path)
    monkeypatch.setattr(dash, "load", lambda: cfg)

    pos = positions(group="eth5m", limit=50)
    assert pos["db"] == "paper_eth5m.db"
    assert pos["group"] == "eth5m"
    assert len(pos["items"]) == 1
    assert pos["items"][0]["market_slug"].startswith("eth-updown")

    ev = events(group="eth5m", limit=50)
    assert ev["db"] == "paper_eth5m.db"
    assert len(ev["items"]) == 1
    assert ev["items"][0]["market_slug"].startswith("eth-updown")


def test_late_edge_activity_report(tmp_path: Path):
    db = tmp_path / "paper_sol5m.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE positions (
          id INTEGER PRIMARY KEY, opened_ts REAL, closed_ts REAL,
          market_slug TEXT, condition_id TEXT, side TEXT, token_id TEXT,
          size REAL, entry_price REAL, exit_price REAL, pnl_usd REAL,
          fee_usd REAL, pnl_net_usd REAL, liquidity TEXT, strategy TEXT,
          dry_run INTEGER, order_id TEXT, status TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO positions(opened_ts, closed_ts, market_slug, condition_id, side, "
        "token_id, size, entry_price, pnl_usd, pnl_net_usd, dry_run, status) "
        "VALUES (1, 2, 'sol-updown-5m-1', 'c', 'UP', 't', 10, 0.8, 2.0, 1.8, 1, 'closed')"
    )
    conn.execute(
        "INSERT INTO positions(opened_ts, market_slug, condition_id, side, token_id, "
        "size, entry_price, dry_run, status) "
        "VALUES (3, 'sol-updown-5m-2', 'c2', 'DOWN', 't', 5, 0.7, 1, 'open')"
    )
    conn.commit()
    conn.close()
    act = late_edge_activity_report(db)
    assert act["sessions"] == 2
    assert act["open_sessions"] == 1
    assert act["filled_sessions"] == 1
    assert act["wins"] == 1
    assert abs(act["net_pnl_usd"] - 1.8) < 1e-9
