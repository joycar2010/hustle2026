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
  slippage_usd REAL NOT NULL DEFAULT 0,
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
  slippage_usd REAL DEFAULT 0,
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

_FILL_COLS = {
    "slippage_usd": "REAL NOT NULL DEFAULT 0",
    "execution_side": "TEXT DEFAULT 'UNKNOWN'",
    "fee_source": "TEXT DEFAULT 'historical_unknown'",
    "slippage_source": "TEXT DEFAULT 'historical_unknown'",
}

_MAKER_COLS = {
    "flatten_pnl_usd": "REAL DEFAULT 0",
    # P6/P7 split-sell / sports accounting (additive; BTC 5m A untouched)
    "up_proceeds_usd": "REAL DEFAULT 0",
    "down_proceeds_usd": "REAL DEFAULT 0",
    "merged_shares": "REAL DEFAULT 0",
    "merge_proceeds_usd": "REAL DEFAULT 0",
    "redeem_proceeds_usd": "REAL DEFAULT 0",
    "accounting_original_gross_pnl_usd": "REAL",
    "accounting_original_net_pnl_usd": "REAL",
    "accounting_corrected_ts": "REAL",
    "slippage_usd": "REAL DEFAULT 0",
    "resolution_source": "TEXT DEFAULT 'historical_unknown'",
}


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA busy_timeout=10000")
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
        fill_existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(fills)").fetchall()
        }
        for col, decl in _FILL_COLS.items():
            if col not in fill_existing:
                self.conn.execute(f"ALTER TABLE fills ADD COLUMN {col} {decl}")
        maker_existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(maker_sessions)").fetchall()
        }
        for col, decl in _MAKER_COLS.items():
            if col not in maker_existing:
                self.conn.execute(f"ALTER TABLE maker_sessions ADD COLUMN {col} {decl}")

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
        slippage_usd: float = 0.0,
        order_id: Optional[str] = None,
        session_id: Optional[int] = None,
        note: str = "",
        execution_side: str = "UNKNOWN",
        fee_source: str = "historical_unknown",
        slippage_source: str = "historical_unknown",
    ) -> int:
        notional = float(size) * float(price)
        cur = self.conn.execute(
            """
            INSERT INTO fills(
              ts, market_slug, condition_id, side, token_id, size, price,
              notional_usd, fee_usd, slippage_usd, liquidity, strategy,
              dry_run, order_id, session_id, note, execution_side, fee_source, slippage_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                float(slippage_usd),
                liquidity,
                strategy,
                1 if dry_run else 0,
                order_id,
                session_id,
                note,
                execution_side,
                fee_source,
                slippage_source,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_maker_execution(self, session_id: int, *, fill: dict,
                               inventory: dict, accounting: dict) -> int:
        """Atomically journal a fill and its absolute inventory/cash totals."""
        allowed = {"up_shares", "down_shares", "up_cost_usd", "down_cost_usd",
                   "up_fee_usd", "down_fee_usd", "flatten_pnl_usd", "slippage_usd",
                   "up_proceeds_usd", "down_proceeds_usd", "merged_shares",
                   "merge_proceeds_usd", "redeem_proceeds_usd"}
        fields = {**inventory, **accounting}
        if not fields.keys() <= allowed:
            raise ValueError("unsupported maker execution accounting field")
        values = dict(fill)
        values["session_id"] = int(session_id)
        columns = ["ts", "market_slug", "condition_id", "side", "token_id", "size",
                   "price", "notional_usd", "fee_usd", "slippage_usd", "liquidity",
                   "strategy", "dry_run", "order_id", "session_id", "note",
                   "execution_side", "fee_source", "slippage_source"]
        values.update(ts=time.time(), notional_usd=float(values["size"])*float(values["price"]),
                      dry_run=int(bool(values["dry_run"])))
        for name, default in (("slippage_usd", 0.0), ("order_id", None), ("note", ""),
                              ("execution_side", "UNKNOWN"), ("fee_source", "historical_unknown"),
                              ("slippage_source", "historical_unknown")):
            values.setdefault(name, default)
        with self.conn:
            exists = self.conn.execute("SELECT status FROM maker_sessions WHERE id=?", (session_id,)).fetchone()
            if exists is None or exists[0] != "open":
                raise ValueError("execution requires an open maker session")
            cur = self.conn.execute(
                f"INSERT INTO fills({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                [values[name] for name in columns])
            assignments = ','.join(name+'=?' for name in fields) if fields else 'id=id'
            updated = self.conn.execute(
                f"UPDATE maker_sessions SET {assignments} WHERE id=? AND status='open'",
                [float(value) for value in fields.values()] + [int(session_id)])
            if updated.rowcount != 1:
                raise ValueError("execution session closed before inventory update")
        return int(cur.lastrowid)

    def update_maker_state(self, session_id: int, **fields: float) -> None:
        """Persist inventory and mint/merge cashflow in one atomic update."""
        allowed = {"up_shares", "down_shares", "up_cost_usd", "down_cost_usd",
                   "up_fee_usd", "down_fee_usd", "flatten_pnl_usd", "slippage_usd",
                   "up_proceeds_usd", "down_proceeds_usd", "merged_shares",
                   "merge_proceeds_usd", "redeem_proceeds_usd"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("unsupported or empty maker state update")
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE maker_sessions SET {','.join(name+'=?' for name in fields)} WHERE id=? AND status='open'",
                [float(value) for value in fields.values()] + [int(session_id)])
            if cur.rowcount != 1:
                raise ValueError("state update requires an open maker session")

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
        initial_state: Optional[dict[str, float]] = None,
    ) -> int:
        initial = initial_state or {}
        if not initial.keys() <= {"up_shares", "down_shares", "up_cost_usd", "down_cost_usd"}:
            raise ValueError("unsupported initial maker state field")
        cols = ["opened_ts", "market_slug", "condition_id", "up_token", "down_token", "dry_run", "status"]
        vals = [time.time(), market_slug, condition_id, up_token, down_token, int(bool(dry_run)), "open"]
        cols.extend(initial)
        vals.extend(float(v) for v in initial.values())
        cur = self.conn.execute(
            f"INSERT INTO maker_sessions({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", vals,
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
        flatten_pnl_usd: Optional[float] = None,
    ) -> None:
        if flatten_pnl_usd is None:
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
        else:
            self.conn.execute(
                """
                UPDATE maker_sessions
                SET up_shares=?, down_shares=?, up_cost_usd=?, down_cost_usd=?,
                    up_fee_usd=?, down_fee_usd=?, flatten_pnl_usd=?
                WHERE id=?
                """,
                (
                    up_shares,
                    down_shares,
                    up_cost_usd,
                    down_cost_usd,
                    up_fee_usd,
                    down_fee_usd,
                    float(flatten_pnl_usd),
                    session_id,
                ),
            )
        self.conn.commit()

    def update_maker_cash_flow(
        self,
        session_id: int,
        *,
        up_proceeds_usd: Optional[float] = None,
        down_proceeds_usd: Optional[float] = None,
        merged_shares: Optional[float] = None,
        merge_proceeds_usd: Optional[float] = None,
        redeem_proceeds_usd: Optional[float] = None,
    ) -> None:
        """Persist split-sell cash-flow components after every Paper action."""
        fields: list[str] = []
        values: list[float] = []
        for name, value in (
            ("up_proceeds_usd", up_proceeds_usd),
            ("down_proceeds_usd", down_proceeds_usd),
            ("merged_shares", merged_shares),
            ("merge_proceeds_usd", merge_proceeds_usd),
            ("redeem_proceeds_usd", redeem_proceeds_usd),
        ):
            if value is not None:
                fields.append(f"{name}=?")
                values.append(float(value))
        if not fields:
            return
        values.append(int(session_id))
        self.conn.execute(
            f"UPDATE maker_sessions SET {', '.join(fields)} WHERE id=?", values
        )
        self.conn.commit()

    def update_split_cash(
        self,
        session_id: int,
        *,
        up_proceeds_usd: float = 0.0,
        down_proceeds_usd: float = 0.0,
        merged_shares: float = 0.0,
        merge_proceeds_usd: float = 0.0,
        redeem_proceeds_usd: float = 0.0,
        flatten_pnl_usd: Optional[float] = None,
    ) -> None:
        """Persist split cash legs with one commit (restart-safe compatibility API)."""
        fields = [
            "up_proceeds_usd=?", "down_proceeds_usd=?", "merged_shares=?",
            "merge_proceeds_usd=?", "redeem_proceeds_usd=?",
        ]
        values: list[object] = [
            float(up_proceeds_usd), float(down_proceeds_usd), float(merged_shares),
            float(merge_proceeds_usd), float(redeem_proceeds_usd),
        ]
        if flatten_pnl_usd is not None:
            fields.append("flatten_pnl_usd=?")
            values.append(float(flatten_pnl_usd))
        values.append(int(session_id))
        self.conn.execute(f"UPDATE maker_sessions SET {', '.join(fields)} WHERE id=?", tuple(values))
        self.conn.commit()

    def session_sell_stats(self, session_id: int) -> dict[str, float]:
        """Aggregate maker sell fills for a split_sell / maker session."""
        rows = self.conn.execute(
            """
            SELECT side,
                   COALESCE(SUM(size), 0) AS shares,
                   COALESCE(SUM(notional_usd), 0) AS notional,
                   COALESCE(SUM(fee_usd), 0) AS fees,
                   COALESCE(SUM(slippage_usd), 0) AS slippage
            FROM fills
            WHERE session_id=? AND
                  (execution_side='SELL' OR (strategy='split_sell' AND COALESCE(execution_side,'UNKNOWN')='UNKNOWN'))
            GROUP BY side
            """,
            (session_id,),
        ).fetchall()
        out = {
            "up_sold": 0.0,
            "down_sold": 0.0,
            "up_proceeds": 0.0,
            "down_proceeds": 0.0,
            "up_fee": 0.0,
            "down_fee": 0.0,
            "up_slippage": 0.0,
            "down_slippage": 0.0,
        }
        for row in rows:
            side = str(row["side"] or "").upper()
            if side == "UP":
                out["up_sold"] = float(row["shares"] or 0)
                out["up_proceeds"] = float(row["notional"] or 0)
                out["up_fee"] = float(row["fees"] or 0)
                out["up_slippage"] = float(row["slippage"] or 0)
            elif side == "DOWN":
                out["down_sold"] = float(row["shares"] or 0)
                out["down_proceeds"] = float(row["notional"] or 0)
                out["down_fee"] = float(row["fees"] or 0)
                out["down_slippage"] = float(row["slippage"] or 0)
        return out

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
        slippage_usd: float = 0.0,
        resolution_source: str = "official_gamma",
    ) -> None:
        self.conn.execute(
            """
            UPDATE maker_sessions
            SET closed_ts=?, paired_shares=?, pair_cost=?, residual_side=?,
                residual_shares=?, winner=?, gross_pnl_usd=?, fee_usd=?,
                slippage_usd=?, rebate_est_usd=?, net_pnl_usd=?, resolution_source=?, status='closed'
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
                slippage_usd,
                rebate_est_usd,
                net_pnl_usd,
                resolution_source,
                session_id,
            ),
        )
        self.conn.commit()
