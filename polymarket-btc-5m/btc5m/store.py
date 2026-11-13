"""SQLite journal for decisions, fills, and resolutions."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  market_slug TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opened_ts REAL NOT NULL,
  closed_ts REAL,
  market_slug TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  side TEXT NOT NULL,
  token_id TEXT NOT NULL,
  size REAL NOT NULL,
  entry_price REAL NOT NULL,
  exit_price REAL,
  pnl_usd REAL,
  dry_run INTEGER NOT NULL,
  order_id TEXT,
  status TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def log(self, kind: str, payload: dict[str, Any], market_slug: str = "") -> None:
        self.conn.execute(
            "INSERT INTO events(ts, kind, market_slug, payload) VALUES (?, ?, ?, ?)",
            (time.time(), kind, market_slug, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

    def open_position(
        self,
        *,
        market_slug: str,
        condition_id: str,
        side: str,
        token_id: str,
        size: float,
        entry_price: float,
        dry_run: bool,
        order_id: Optional[str],
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO positions(
              opened_ts, market_slug, condition_id, side, token_id,
              size, entry_price, dry_run, order_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                time.time(),
                market_slug,
                condition_id,
                side,
                token_id,
                size,
                entry_price,
                1 if dry_run else 0,
                order_id,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def open_rows(self) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        rows = self.conn.execute(
            "SELECT * FROM positions WHERE status='open' ORDER BY id"
        ).fetchall()
        return list(rows)

    def close_position(self, position_id: int, *, exit_price: float, pnl_usd: float) -> None:
        self.conn.execute(
            """
            UPDATE positions
            SET closed_ts=?, exit_price=?, pnl_usd=?, status='closed'
            WHERE id=?
            """,
            (time.time(), exit_price, pnl_usd, position_id),
        )
        self.conn.commit()

    def day_realized_pnl(self, day_start_ts: float) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(pnl_usd), 0) FROM positions
            WHERE status='closed' AND closed_ts >= ?
            """,
            (day_start_ts,),
        ).fetchone()
        return float(row[0] or 0.0)
