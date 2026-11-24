#!/usr/bin/env python3
"""Persistent sports Paper producer for the isolated PolyDexTest lane."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

# Sports has no built-in persistent ledger.  Use the shared Paper feed DB,
# separate from the P1 crypto ledger, so the read-only dashboard can account
# for these rows without granting any trading capability.
FEED_DB = Path(os.getenv("PAPER_FEED_DB_PATH", "/var/lib/poly-dex-test/paper-feeds/paper-feeds.db"))

from bot import config
from bot.sports_main import SportsPaperService


STATE_DIR = Path(os.getenv("SPORTS_STATE_DIR", "/opt/poly-dex-test/agents/out"))
STATE_PATH = STATE_DIR / "sports_paper_state.json"


def _write(payload: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _ensure_feed_db() -> None:
    FEED_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(FEED_DB) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
          asset TEXT, market_slug TEXT, condition_id TEXT, token_id TEXT,
          side TEXT, t_remaining REAL, ask_price REAL, ask_size REAL,
          action TEXT, reason TEXT, dry_run INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
          asset TEXT, market_slug TEXT, condition_id TEXT, token_id TEXT,
          side TEXT, size REAL, price REAL, status TEXT, filled_size REAL,
          dry_run INTEGER NOT NULL
        );
        """)


def _persist_new(service: SportsPaperService, decision_count: int, order_count: int) -> tuple[int, int]:
    """Append only newly produced sports rows to the shared Paper ledger."""
    _ensure_feed_db()
    decisions = service.decisions[decision_count:]
    orders = service.orders[order_count:]
    with sqlite3.connect(FEED_DB) as db:
        for item in decisions:
            try:
                ts = datetime.fromisoformat(item.timestamp).timestamp()
            except (TypeError, ValueError):
                ts = time.time()
            db.execute(
                "INSERT INTO decisions(ts,asset,market_slug,condition_id,token_id,side,t_remaining,ask_price,ask_size,action,reason,dry_run) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                (ts, "SPORTS", item.slug, item.market_key, "", "", 0.0, None, None, item.action, item.reason),
            )
        for item in orders:
            try:
                ts = datetime.fromisoformat(item.timestamp).timestamp()
            except (TypeError, ValueError):
                ts = time.time()
            db.execute(
                "INSERT INTO orders(ts,asset,market_slug,condition_id,token_id,side,size,price,status,filled_size,dry_run) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                (ts, "SPORTS", item.slug, item.market_key, item.token_id, item.outcome, item.size, item.price, "paper_simulated", 0.0),
            )
        db.commit()
    return len(service.decisions), len(service.orders)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=float(os.getenv("SPORTS_PAPER_INTERVAL_SEC", "300")))
    args = parser.parse_args()
    cfg = config.load()
    service = SportsPaperService(cfg)
    decision_count = order_count = 0
    while True:
        now = time.time()
        try:
            snapshot = service.run_once()
            decision_count, order_count = _persist_new(service, decision_count, order_count)
            status = snapshot.get("status", "ok") if snapshot.get("markets") else "no_markets"
            error = None
        except Exception as exc:  # preserve heartbeat and error diagnostics
            snapshot = service.snapshot(status="error")
            status = "error"
            error = str(exc)[:500]
        payload = dict(snapshot)
        payload.update({
            "updated_ts": now,
            "heartbeat_ts": now,
            "running": True,
            "status": status,
            "error": error,
            "mode": "paper",
            "paper_only": True,
            "live_enabled": False,
            "live_orders": False,
            "rows": list(payload.get("markets") or []),
            "market_count": len(payload.get("markets") or []),
            "orders_new": len(payload.get("orders") or []),
        })
        _write(payload)
        print(f"sports paper cycle status={status} markets={len(payload.get('markets') or [])} orders={len(payload.get('orders') or [])}", flush=True)
        if args.once:
            return
        time.sleep(max(args.interval, 30.0))


if __name__ == "__main__":
    main()
