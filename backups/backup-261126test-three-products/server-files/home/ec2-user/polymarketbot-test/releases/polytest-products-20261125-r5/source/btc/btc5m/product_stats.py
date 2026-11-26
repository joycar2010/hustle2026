"""Common read-only Paper ledger statistics for every product.

The BTC 5m A/B/C dashboard historically had its own aggregation code while
the newer product cards only exposed session counts.  This module provides a
small schema-tolerant reader for all isolated Paper ledgers.  It never writes
to a database and works with both ``positions`` (late-edge) and
``maker_sessions`` (maker/split/sports) ledgers.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _day(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), timezone.utc).astimezone(BEIJING_TZ).date().isoformat()


def _empty_day(key: str) -> dict[str, Any]:
    return {
        "day_key": key,
        "pnl_usd": 0.0,
        "gross_pnl_usd": 0.0,
        "fees_usd": 0.0,
        "rebate_usd": 0.0,
        "settled": 0,
        "wins": 0,
        "losses": 0,
    }


def summarize_ledger(
    path: Path,
    *,
    bankroll_usd: float = 200.0,
    history_limit: int = 31,
    event_limit: int = 50,
) -> dict[str, Any]:
    """Return all-time and Beijing-day Paper statistics for *path*.

    Missing or not-yet-created product ledgers return a zero summary.  The
    return percentage uses the supplied virtual Paper bankroll.  ``events``
    are included so the dashboard can show product decisions in one stream.
    """
    now = time.time()
    today = _day(now)
    out: dict[str, Any] = {
        "db_exists": path.exists(),
        "sessions": 0,
        "open_sessions": 0,
        "filled_sessions": 0,
        "empty_closed_sessions": 0,
        "positions": 0,
        "open_positions": 0,
        "pnl_usd": 0.0,
        "gross_pnl_usd": 0.0,
        "fees_usd": 0.0,
        "rebate_usd": 0.0,
        "wins": 0,
        "losses": 0,
        "last_update_ts": None,
        "events": [],
    }
    days: dict[str, dict[str, Any]] = defaultdict(lambda: _empty_day(""))
    conn = _connect(path)
    if conn is None:
        current = _empty_day(today)
        current["return_pct"] = 0.0
        out["daily"] = {**current, "history": []}
        out["return_pct"] = 0.0
        return out
    try:
        if _has(conn, "maker_sessions"):
            rows = conn.execute("SELECT * FROM maker_sessions").fetchall()
            filled_ids = {
                int(r["session_id"])
                for r in conn.execute(
                    "SELECT DISTINCT session_id FROM fills WHERE session_id IS NOT NULL"
                ).fetchall()
            } if _has(conn, "fills") else set()
            out["sessions"] = len(rows)
            out["open_sessions"] = sum(str(r["status"] or "") == "open" for r in rows)
            out["filled_sessions"] = sum(int(r["id"]) in filled_ids for r in rows)
            out["empty_closed_sessions"] = sum(
                str(r["status"] or "") == "closed" and int(r["id"]) not in filled_ids
                for r in rows
            )
            for r in rows:
                ts = r["closed_ts"] or r["opened_ts"]
                out["last_update_ts"] = max(float(out["last_update_ts"] or 0), float(ts or 0))
                if str(r["status"] or "") != "closed":
                    continue
                net = float(r["net_pnl_usd"] or 0.0)
                gross = float(r["gross_pnl_usd"] or 0.0)
                fee = float(r["fee_usd"] or 0.0)
                rebate = float(r["rebate_est_usd"] or 0.0)
                out["pnl_usd"] += net
                out["gross_pnl_usd"] += gross
                out["fees_usd"] += fee
                out["rebate_usd"] += rebate
                out["wins"] += int(net > 0)
                out["losses"] += int(net < 0)
                key = _day(float(r["closed_ts"] or ts))
                d = days[key]
                d["day_key"] = key
                for name, value in (("pnl_usd", net), ("gross_pnl_usd", gross), ("fees_usd", fee), ("rebate_usd", rebate)):
                    d[name] += value
                d["settled"] += 1
                d["wins"] += int(net > 0)
                d["losses"] += int(net < 0)
        elif _has(conn, "positions"):
            rows = conn.execute("SELECT * FROM positions").fetchall()
            out["positions"] = len(rows)
            out["open_positions"] = sum(str(r["status"] or "") == "open" for r in rows)
            out["filled_sessions"] = len(rows)
            for r in rows:
                ts = r["closed_ts"] or r["opened_ts"]
                out["last_update_ts"] = max(float(out["last_update_ts"] or 0), float(ts or 0))
                if str(r["status"] or "") != "closed":
                    continue
                gross = float(r["pnl_usd"] or 0.0)
                net = float(r["pnl_net_usd"] if r["pnl_net_usd"] is not None else gross)
                fee = float(r["fee_usd"] or 0.0)
                out["pnl_usd"] += net
                out["gross_pnl_usd"] += gross
                out["fees_usd"] += fee
                out["wins"] += int(net > 0)
                out["losses"] += int(net < 0)
                key = _day(float(r["closed_ts"] or ts))
                d = days[key]
                d["day_key"] = key
                d["pnl_usd"] += net
                d["gross_pnl_usd"] += gross
                d["fees_usd"] += fee
                d["settled"] += 1
                d["wins"] += int(net > 0)
                d["losses"] += int(net < 0)
        if _has(conn, "events") and int(event_limit) > 0:
            events = conn.execute(
                "SELECT id, ts, kind, market_slug, payload FROM events ORDER BY id DESC LIMIT ?",
                (max(1, int(event_limit)),),
            ).fetchall()
            for r in events:
                payload: Any = r["payload"]
                try:
                    payload = json.loads(payload)
                except Exception:
                    pass
                out["events"].append({"id": r["id"], "ts": r["ts"], "kind": r["kind"], "market_slug": r["market_slug"], "payload": payload})
    finally:
        conn.close()

    bankroll = max(float(bankroll_usd), 0.01)
    out["return_pct"] = out["pnl_usd"] / bankroll * 100.0
    history: list[dict[str, Any]] = []
    for key in sorted(days, reverse=True)[: max(1, int(history_limit))]:
        d = dict(days[key])
        d["return_pct"] = d["pnl_usd"] / bankroll * 100.0
        history.append(d)
    current = dict(days.get(today, _empty_day(today)))
    current["return_pct"] = current["pnl_usd"] / bankroll * 100.0
    out["daily"] = {**current, "history": history}
    return out
