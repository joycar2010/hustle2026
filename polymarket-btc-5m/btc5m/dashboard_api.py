"""Read-only Paper dashboard API with A/B/C ledger separation.

A = late_edge paper.db
B = maker maker_paper.db
C = split_sell split_sell_paper.db
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from btc5m.book import fetch_book
from btc5m.calibration import load_bucket_stats
from btc5m.config import ROOT, load
from btc5m.heartbeat import status_report
from btc5m.markets import fetch_live_market
from btc5m.signal import fetch_btc_signal
from btc5m.audit import fill_quality_report, maker_pair_residual_report

app = FastAPI(title="Poly BTC 5m Paper Dashboard", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = ROOT / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _db_path(group: str) -> Path:
    cfg = load()
    g = group.upper()
    if g == "B":
        return cfg.data_dir / "maker_paper.db"
    if g == "C":
        return cfg.data_dir / "split_sell_paper.db"
    return cfg.data_dir / "paper.db"


def _connect(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _summarize_group(group: str) -> dict[str, Any]:
    path = _db_path(group)
    meta = {
        "A": {"label": "A · late_edge", "version": "p5", "mode": "late_edge"},
        "B": {"label": "B · maker", "version": "p5b", "mode": "maker"},
        "C": {"label": "C · split_sell", "version": "p5a", "mode": "split_sell"},
    }[group.upper()]
    out: dict[str, Any] = {
        **meta,
        "db_exists": path.exists(),
        "db_path": str(path),
        "positions": 0,
        "open_positions": 0,
        "pnl_usd": 0.0,
        "gross_pnl_usd": 0.0,
        "fees_usd": 0.0,
        "rebate_usd": 0.0,
        "wins": 0,
        "losses": 0,
        "last_update_ts": None,
    }
    conn = _connect(path)
    if conn is None:
        return out
    try:
        if group.upper() in {"B", "C"} and _table_exists(conn, "maker_sessions"):
            row = conn.execute(
                """
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_n,
                       COALESCE(SUM(CASE WHEN status='closed' THEN net_pnl_usd END), 0) AS net,
                       COALESCE(SUM(CASE WHEN status='closed' THEN gross_pnl_usd END), 0) AS gross,
                       COALESCE(SUM(CASE WHEN status='closed' THEN fee_usd END), 0) AS fees,
                       COALESCE(SUM(CASE WHEN status='closed' THEN rebate_est_usd END), 0) AS rebates,
                       SUM(CASE WHEN status='closed' AND net_pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status='closed' AND net_pnl_usd < 0 THEN 1 ELSE 0 END) AS losses,
                       MAX(COALESCE(closed_ts, opened_ts)) AS last_ts
                FROM maker_sessions
                """
            ).fetchone()
            out.update(
                {
                    "positions": int(row["n"] or 0),
                    "open_positions": int(row["open_n"] or 0),
                    "pnl_usd": float(row["net"] or 0),
                    "gross_pnl_usd": float(row["gross"] or 0),
                    "fees_usd": float(row["fees"] or 0),
                    "rebate_usd": float(row["rebates"] or 0),
                    "wins": int(row["wins"] or 0),
                    "losses": int(row["losses"] or 0),
                    "last_update_ts": row["last_ts"],
                }
            )
        elif _table_exists(conn, "positions"):
            cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)")}
            net_expr = (
                "COALESCE(pnl_net_usd, pnl_usd)" if "pnl_net_usd" in cols else "pnl_usd"
            )
            fee_expr = "COALESCE(fee_usd, 0)" if "fee_usd" in cols else "0"
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_n,
                       COALESCE(SUM(CASE WHEN status='closed' THEN {net_expr} END), 0) AS net,
                       COALESCE(SUM(CASE WHEN status='closed' THEN pnl_usd END), 0) AS gross,
                       COALESCE(SUM(CASE WHEN status='closed' THEN {fee_expr} END), 0) AS fees,
                       SUM(CASE WHEN status='closed' AND {net_expr} > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status='closed' AND {net_expr} < 0 THEN 1 ELSE 0 END) AS losses,
                       MAX(COALESCE(closed_ts, opened_ts)) AS last_ts
                FROM positions
                """
            ).fetchone()
            out.update(
                {
                    "positions": int(row["n"] or 0),
                    "open_positions": int(row["open_n"] or 0),
                    "pnl_usd": float(row["net"] or 0),
                    "gross_pnl_usd": float(row["gross"] or 0),
                    "fees_usd": float(row["fees"] or 0),
                    "wins": int(row["wins"] or 0),
                    "losses": int(row["losses"] or 0),
                    "last_update_ts": row["last_ts"],
                }
            )
    finally:
        conn.close()
    return out


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise RuntimeError(f"missing dashboard web root: {index_path}")
    return FileResponse(index_path)


@app.get("/api/health")
def health() -> dict[str, Any]:
    cfg = load()
    hb = status_report(cfg.data_dir, stale_sec=cfg.heartbeat_stale_sec)
    return {
        "ok": True,
        "mode": "PAPER",
        "paper_only": True,
        "live_trading_enabled": cfg.live_trading_enabled,
        "db_exists": (cfg.data_dir / "paper.db").exists(),
        "maker_db_exists": (cfg.data_dir / "maker_paper.db").exists(),
        "split_sell_db_exists": (cfg.data_dir / "split_sell_paper.db").exists(),
        "heartbeat": hb,
        "ts": time.time(),
    }


@app.get("/api/heartbeat")
def heartbeat() -> dict[str, Any]:
    cfg = load()
    return status_report(cfg.data_dir, stale_sec=cfg.heartbeat_stale_sec)


@app.get("/api/calibration")
def calibration(group: str = Query("A")) -> dict[str, Any]:
    cfg = load()
    path = _db_path(group)
    buckets = load_bucket_stats(
        path,
        lookback_sec=cfg.bucket_lookback_sec,
        min_samples=cfg.bucket_min_samples,
        fee_rate=cfg.taker_fee_rate,
        wr_buffer=cfg.bucket_wr_buffer,
    )
    return {
        "group": group.upper(),
        "db_path": str(path),
        "buckets": [
            {
                "lo": b.lo,
                "hi": b.hi,
                "n": b.n,
                "wins": b.wins,
                "wr": b.wr,
                "required_wr": b.required_wr,
                "net_pnl_usd": b.net_pnl_usd,
                "banned": b.banned,
                "reason": b.reason,
            }
            for b in buckets
        ],
    }


@app.get("/api/maker/quality")
def maker_quality(group: str = Query("B")) -> dict[str, Any]:
    g = group.upper() if group else "B"
    path = _db_path(g if g in {"B", "C"} else "B")
    return {
        "group": g if g in {"B", "C"} else "B",
        "pair_residual": maker_pair_residual_report(path),
        "fill_quality": fill_quality_report(path),
    }


@app.get("/api/split/quality")
def split_quality() -> dict[str, Any]:
    path = _db_path("C")
    return {
        "group": "C",
        "pair_residual": maker_pair_residual_report(path),
        "fill_quality": fill_quality_report(path),
    }


@app.get("/api/ab")
def ab() -> dict[str, Any]:
    return {
        "paper_only": True,
        "groups": {
            "A": _summarize_group("A"),
            "B": _summarize_group("B"),
            "C": _summarize_group("C"),
        },
        "updated_at": time.time(),
    }


@app.get("/api/positions")
def positions(
    group: str = Query("A"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    g = group.upper() if group else "A"
    path = _db_path(g)
    conn = _connect(path)
    items: list[dict[str, Any]] = []
    if conn is not None:
        try:
            if g in {"B", "C"} and _table_exists(conn, "maker_sessions"):
                rows = conn.execute(
                    """
                    SELECT * FROM maker_sessions
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                items = [dict(r) for r in rows]
            elif _table_exists(conn, "positions"):
                rows = conn.execute(
                    """
                    SELECT * FROM positions
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                items = [dict(r) for r in rows]
        finally:
            conn.close()
    return {"items": items, "mode": "PAPER", "paper_only": True, "group": g}


@app.get("/api/events")
def events(
    limit: int = Query(50, ge=1, le=500),
    group: str = Query("A"),
) -> dict[str, Any]:
    path = _db_path(group)
    conn = _connect(path)
    items: list[dict[str, Any]] = []
    if conn is not None and _table_exists(conn, "events"):
        try:
            rows = conn.execute(
                "SELECT id, ts, kind, market_slug, payload FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for r in rows:
                payload = r["payload"]
                try:
                    payload = json.loads(payload)
                except Exception:  # noqa: BLE001
                    pass
                items.append(
                    {
                        "id": r["id"],
                        "ts": r["ts"],
                        "kind": r["kind"],
                        "market_slug": r["market_slug"],
                        "payload": payload,
                    }
                )
        finally:
            conn.close()
    return {"items": items, "mode": "PAPER", "paper_only": True, "group": group.upper()}


@app.get("/api/state")
def state() -> dict[str, Any]:
    cfg = load()
    errors: list[str] = []
    market_obj = None
    up = down = signal = None
    try:
        m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
        if m:
            market_obj = {
                "slug": m.market_slug,
                "title": m.title,
                "remaining_sec": m.t_remaining(),
                "start_ts": m.start_ts,
                "end_ts": m.end_ts,
            }
            up = fetch_book(cfg.clob_host, m.up_token).__dict__
            down = fetch_book(cfg.clob_host, m.down_token).__dict__
            try:
                sig = fetch_btc_signal(cfg, m)
                signal = {
                    "current_price": sig.current_price,
                    "price_to_beat": sig.price_to_beat,
                    "delta_usd": sig.delta_usd,
                    "side": sig.signal_side,
                    "decision_side": sig.decision_side,
                    "source": sig.source,
                    "venue_count": sig.venue_count,
                    "consensus": sig.consensus,
                    "lead_bp": sig.lead_bp,
                    "projected_lead_bp": sig.projected_lead_bp,
                    "hold_wr": sig.hold_wr,
                    "in_final_minute": sig.in_final_minute,
                    "opening_gap_bp": sig.opening_gap_bp,
                }
            except Exception as exc:  # noqa: BLE001
                errors.append(f"signal: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"market: {exc}")

    journal = _summarize_group("A")
    return {
        "mode": "PAPER",
        "live_trading_enabled": False,
        "paper_only": True,
        "fetched_at": time.time(),
        "market": market_obj,
        "up": up,
        "down": down,
        "signal": signal,
        "journal": journal,
        "ab": ab(),
        "config": {
            "series_slug": cfg.series_slug,
            "entry_window_sec": cfg.entry_window_sec,
            "min_t_remaining_sec": cfg.min_t_remaining_sec,
            "min_entry_price": cfg.min_entry_price,
            "max_entry_price": cfg.max_entry_price,
            "min_net_edge": cfg.min_net_edge,
            "taker_fee_rate": cfg.taker_fee_rate,
            "confirm_checks": cfg.confirm_checks,
            "poll_interval_sec": cfg.poll_interval_sec,
            "delta_filter_enabled": cfg.delta_filter_enabled,
            "up_min_delta_usd": cfg.up_min_delta_usd,
            "down_max_delta_usd": cfg.down_max_delta_usd,
            "order_shares": cfg.order_shares,
            "max_order_usd": cfg.max_order_usd,
            "daily_loss_limit_usd": cfg.daily_loss_limit_usd,
            "max_open_positions": cfg.max_open_positions,
            "paper_bankroll_usd": cfg.paper_bankroll_usd,
            "live_trading_enabled": cfg.live_trading_enabled,
            "late_edge_hard_ban_price": cfg.late_edge_hard_ban_price,
            "bucket_calibration_enabled": cfg.bucket_calibration_enabled,
            "signal_require_consensus": cfg.signal_require_consensus,
            "signal_min_venues": cfg.signal_min_venues,
            "lead_table_enabled": cfg.lead_table_enabled,
            "lead_edge_margin": cfg.lead_edge_margin,
            "opening_gap_enabled": cfg.opening_gap_enabled,
            "maker_pair_cost_max": cfg.maker_pair_cost_max,
            "maker_pair_profit_min": cfg.maker_pair_profit_min,
            "maker_flatten_residual": cfg.maker_flatten_residual,
            "maker_allow_crossed_fills": cfg.maker_allow_crossed_fills,
            "maker_min_bid_price": cfg.maker_min_bid_price,
            "maker_pair_complete_sec": cfg.maker_pair_complete_sec,
            "maker_zero_fill_kill_sec": cfg.maker_zero_fill_kill_sec,
            "maker_early_flatten": cfg.maker_early_flatten,
            "split_size": cfg.split_size,
            "split_fair_edge": cfg.split_fair_edge,
            "split_max_lean_shares": cfg.split_max_lean_shares,
            "split_min_pair_ask": cfg.split_min_pair_ask,
            "split_min_ask_price": cfg.split_min_ask_price,
            "split_lean_abort_sec": cfg.split_lean_abort_sec,
            "heartbeat_stale_sec": cfg.heartbeat_stale_sec,
            "ws_book": __import__("btc5m.ws_book", fromlist=["status"]).status(),
        },
        "heartbeat": status_report(cfg.data_dir, stale_sec=cfg.heartbeat_stale_sec),
        "errors": errors,
    }
