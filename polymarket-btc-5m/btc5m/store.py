"""SQLite journal for decisions, fills, maker sessions, and fee-aware PnL."""
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
  fee_usd REAL DEFAULT 0,
  pnl_net_usd REAL,
  liquidity TEXT DEFAULT 'taker',
  strategy TEXT DEFAULT 'late_edge',
  dry_run INTEGER NOT NULL,
  order_id TEXT,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  market_slug TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  side TEXT NOT NULL,
  token_id TEXT NOT NULL,
  size REAL NOT NULL,
  price REAL NOT NULL,
  notional_usd REAL NOT NULL,
  fee_usd REAL NOT NULL,
  liquidity TEXT NOT NULL,
  strategy TEXT NOT NULL,
  dry_run INTEGER NOT NULL,
  order_id TEXT,
  session_id INTEGER,
  note TEXT
);
CREATE TABLE IF NOT EXISTS maker_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opened_ts REAL NOT NULL,
  closed_ts REAL,
  market_slug TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  up_token TEXT NOT NULL,
  down_token TEXT NOT NULL,
  up_shares REAL NOT NULL DEFAULT 0,
  down_shares REAL NOT NULL DEFAULT 0,
  up_cost_usd REAL NOT NULL DEFAULT 0,
  down_cost_usd REAL NOT NULL DEFAULT 0,
  up_fee_usd REAL NOT NULL DEFAULT 0,
  down_fee_usd REAL NOT NULL DEFAULT 0,
  paired_shares REAL,
  pair_cost REAL,
  residual_side TEXT,
  residual_shares REAL,
  winner TEXT,
  gross_pnl_usd REAL,
  fee_usd REAL,
  rebate_est_usd REAL,
  net_pnl_usd REAL,
  dry_run INTEGER NOT NULL,
  status TEXT NOT NULL
);
"""

_POSITION_COLS = {
    "fee_usd": "REAL DEFAULT 0",
    "pnl_net_usd": "REAL",
    "liquidity": "TEXT DEFAULT 'taker'",
    "strategy": "TEXT DEFAULT 'late_edge'",
}


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(positions)").fetchall()
        }
        for col, decl in _POSITION_COLS.items():
            if col not in existing:
                self.conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {decl}")

    def log(self, kind: str, payload: dict[str, Any], market_slug: str = "") -> None:
        self.conn.execute(
            "INSERT INTO events(ts, kind, market_slug, payload) VALUES (?, ?, ?, ?)",
            (time.time(), kind, market_slug, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

    def record_fill(
        self,
        *,
        market_slug: str,
        condition_id: str,
        side: str,
        token_id: str,
        size: float,
        price: float,
        fee_usd: float,
        liquidity: str,
        strategy: str,
        dry_run: bool,
        order_id: Optional[str] = None,
        session_id: Optional[int] = None,
        note: str = "",
    ) -> int:
        notional = float(size) * float(price)
        cur = self.conn.execute(
            """
            INSERT INTO fills(
              ts, market_slug, condition_id, side, token_id, size, price,
              notional_usd, fee_usd, liquidity, strategy, dry_run, order_id,
              session_id, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                market_slug,
                condition_id,
                side,
                token_id,
                float(size),
                float(price),
                notional,
                float(fee_usd),
                liquidity,
                strategy,
                1 if dry_run else 0,
                order_id,
                session_id,
                note,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

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
        fee_usd: float = 0.0,
        liquidity: str = "taker",
        strategy: str = "late_edge",
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO positions(
              opened_ts, market_slug, condition_id, side, token_id,
              size, entry_price, fee_usd, liquidity, strategy,
              dry_run, order_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                time.time(),
                market_slug,
                condition_id,
                side,
                token_id,
                size,
                entry_price,
                float(fee_usd),
                liquidity,
                strategy,
                1 if dry_run else 0,
                order_id,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def open_rows(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY id"
            ).fetchall()
        )

    def close_position(
        self,
        position_id: int,
        *,
        exit_price: float,
        pnl_usd: float,
        fee_usd: float = 0.0,
        pnl_net_usd: Optional[float] = None,
    ) -> None:
        net = pnl_usd - fee_usd if pnl_net_usd is None else pnl_net_usd
        self.conn.execute(
            """
            UPDATE positions
            SET closed_ts=?, exit_price=?, pnl_usd=?, fee_usd=?, pnl_net_usd=?, status='closed'
            WHERE id=?
            """,
            (time.time(), exit_price, pnl_usd, fee_usd, net, position_id),
        )
        self.conn.commit()

    def day_realized_pnl(self, day_start_ts: float) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(COALESCE(pnl_net_usd, pnl_usd)), 0) FROM positions
            WHERE status='closed' AND closed_ts >= ?
            """,
            (day_start_ts,),
        ).fetchone()
        pos = float(row[0] or 0.0)
        row2 = self.conn.execute(
            """
            SELECT COALESCE(SUM(COALESCE(net_pnl_usd, 0)), 0) FROM maker_sessions
            WHERE status='closed' AND closed_ts >= ?
            """,
            (day_start_ts,),
        ).fetchone()
        return pos + float(row2[0] or 0.0)

    def open_maker_session(
        self,
        *,
        market_slug: str,
        condition_id: str,
        up_token: str,
        down_token: str,
        dry_run: bool,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO maker_sessions(
              opened_ts, market_slug, condition_id, up_token, down_token, dry_run, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'open')
            """,
            (time.time(), market_slug, condition_id, up_token, down_token, 1 if dry_run else 0),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_open_maker_session(self, condition_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM maker_sessions
            WHERE status='open' AND condition_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (condition_id,),
        ).fetchone()

    def open_maker_sessions(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM maker_sessions WHERE status='open' ORDER BY id"
            ).fetchall()
        )

    def update_maker_inventory(
        self,
        session_id: int,
        *,
        up_shares: float,
        down_shares: float,
        up_cost_usd: float,
        down_cost_usd: float,
        up_fee_usd: float = 0.0,
        down_fee_usd: float = 0.0,
    ) -> None:
        self.conn.execute(
            """
            UPDATE maker_sessions
            SET up_shares=?, down_shares=?, up_cost_usd=?, down_cost_usd=?,
                up_fee_usd=?, down_fee_usd=?
            WHERE id=?
            """,
            (
                up_shares,
                down_shares,
                up_cost_usd,
                down_cost_usd,
                up_fee_usd,
                down_fee_usd,
                session_id,
            ),
        )
        self.conn.commit()

    def close_maker_session(
        self,
        session_id: int,
        *,
        paired_shares: float,
        pair_cost: Optional[float],
        residual_side: Optional[str],
        residual_shares: float,
        winner: str,
        gross_pnl_usd: float,
        fee_usd: float,
        rebate_est_usd: float,
        net_pnl_usd: float,
    ) -> None:
        self.conn.execute(
            """
            UPDATE maker_sessions
            SET closed_ts=?, paired_shares=?, pair_cost=?, residual_side=?,
                residual_shares=?, winner=?, gross_pnl_usd=?, fee_usd=?,
                rebate_est_usd=?, net_pnl_usd=?, status='closed'
            WHERE id=?
            """,
            (
                time.time(),
                paired_shares,
                pair_cost,
                residual_side,
                residual_shares,
                winner,
                gross_pnl_usd,
                fee_usd,
                rebate_est_usd,
                net_pnl_usd,
                session_id,
            ),
        )
        self.conn.commit()
