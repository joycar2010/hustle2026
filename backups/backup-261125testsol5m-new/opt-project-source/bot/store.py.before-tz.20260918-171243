"""SQLite logger for every decision and order outcome."""
from __future__ import annotations

import sqlite3
import os
import time
from contextlib import contextmanager
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(os.getenv("TRADES_DB_PATH", str(Path(__file__).resolve().parent.parent / "trades.db"))).expanduser()

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    asset TEXT,
    market_slug TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT,                  -- 'UP' or 'DOWN'
    t_remaining REAL,
    ask_price REAL,
    ask_size REAL,
    action TEXT,                -- 'BUY', 'SKIP_PRICE', 'SKIP_TIME', 'SKIP_SIZE', 'SKIP_AMBIGUOUS', 'SKIP_RISK'
    reason TEXT,
    dry_run INTEGER NOT NULL    -- 1 if shadow, 0 if live
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    asset TEXT,
    market_slug TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT,
    size REAL,
    price REAL,
    order_id TEXT,
    status TEXT,
    filled_size REAL,
    error TEXT,
    entry_rule TEXT,
    dry_run INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS resolutions (
    condition_id TEXT PRIMARY KEY,
    winning_token TEXT,
    resolved_ts REAL
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
"""


def effective_order_statuses(dry_run: bool) -> tuple[str, ...]:
    return ("dry_run",) if dry_run else ("filled", "matched")


def effective_exit_statuses(dry_run: bool) -> tuple[str, ...]:
    return ("exit_dry_run",) if dry_run else ("exit_filled", "exit_matched", "exit_partial")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    _migrate(c)
    return c


def _migrate(c: sqlite3.Connection) -> None:
    order_columns = {row["name"] for row in c.execute("PRAGMA table_info(orders)")}
    if "entry_rule" not in order_columns:
        c.execute("ALTER TABLE orders ADD COLUMN entry_rule TEXT")
    if "asset" not in order_columns:
        c.execute("ALTER TABLE orders ADD COLUMN asset TEXT")
        c.execute(
            "UPDATE orders SET asset=CASE "
            "WHEN market_slug LIKE 'eth-%' THEN 'ETH' ELSE 'BTC' END "
            "WHERE asset IS NULL"
        )
    decision_columns = {row["name"] for row in c.execute("PRAGMA table_info(decisions)")}
    if "asset" not in decision_columns:
        c.execute("ALTER TABLE decisions ADD COLUMN asset TEXT")
        c.execute(
            "UPDATE decisions SET asset=CASE "
            "WHEN market_slug LIKE 'eth-%' THEN 'ETH' ELSE 'BTC' END "
            "WHERE asset IS NULL"
        )


def infer_asset(market_slug: Optional[str]) -> str:
    slug = (market_slug or "").lower()
    if slug.startswith("eth-"):
        return "ETH"
    return "BTC"


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    c = _conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def log_decision(
    *,
    asset: Optional[str] = None,
    market_slug: str,
    condition_id: str,
    token_id: Optional[str],
    side: Optional[str],
    t_remaining: float,
    ask_price: Optional[float],
    ask_size: Optional[float],
    action: str,
    reason: str,
    dry_run: bool,
) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO decisions (ts, asset, market_slug, condition_id, token_id, side, "
            "t_remaining, ask_price, ask_size, action, reason, dry_run) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                asset or infer_asset(market_slug),
                market_slug,
                condition_id,
                token_id,
                side,
                t_remaining,
                ask_price,
                ask_size,
                action,
                reason,
                int(dry_run),
            ),
        )


def log_order(
    *,
    asset: Optional[str] = None,
    market_slug: str,
    condition_id: str,
    token_id: str,
    side: str,
    size: float,
    price: float,
    order_id: Optional[str],
    status: str,
    filled_size: float = 0.0,
    error: Optional[str] = None,
    entry_rule: Optional[str] = None,
    dry_run: bool,
) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO orders (ts, asset, market_slug, condition_id, token_id, side, "
            "size, price, order_id, status, filled_size, error, entry_rule, dry_run) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                asset or infer_asset(market_slug),
                market_slug,
                condition_id,
                token_id,
                side,
                size,
                price,
                order_id,
                status,
                filled_size,
                error,
                entry_rule,
                int(dry_run),
            ),
        )


def unresolved_condition_ids(dry_run: bool) -> list[str]:
    """Condition ids with a remaining filled position and no resolution."""
    statuses = effective_order_statuses(dry_run)
    exit_statuses = effective_exit_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    exit_placeholders = ",".join("?" for _ in exit_statuses)
    with db() as c:
        rows = c.execute(
            "SELECT DISTINCT o.condition_id FROM orders o "
            "LEFT JOIN resolutions r ON r.condition_id = o.condition_id "
            "LEFT JOIN ("
            "  SELECT condition_id, token_id, dry_run, SUM(size) AS exit_size "
            "  FROM orders "
            f"  WHERE status IN ({exit_placeholders}) "
            "  GROUP BY condition_id, token_id, dry_run"
            ") x ON x.condition_id=o.condition_id AND x.token_id=o.token_id "
            "AND x.dry_run=o.dry_run "
            f"WHERE o.status IN ({placeholders}) AND o.side IN ('UP','DOWN') "
            "AND o.dry_run=? AND r.condition_id IS NULL "
            "AND COALESCE(x.exit_size, 0) < (o.size - 0.02)",
            (*exit_statuses, *statuses, int(dry_run)),
        ).fetchall()
        return [r[0] for r in rows]


def unresolved_with_slug(dry_run: bool) -> list[tuple[str, str]]:
    """(condition_id, market_slug) pairs with remaining positions to resolve."""
    statuses = effective_order_statuses(dry_run)
    exit_statuses = effective_exit_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    exit_placeholders = ",".join("?" for _ in exit_statuses)
    with db() as c:
        rows = c.execute(
            "SELECT DISTINCT o.condition_id, o.market_slug FROM orders o "
            "LEFT JOIN resolutions r ON r.condition_id = o.condition_id "
            "LEFT JOIN ("
            "  SELECT condition_id, token_id, dry_run, SUM(size) AS exit_size "
            "  FROM orders "
            f"  WHERE status IN ({exit_placeholders}) "
            "  GROUP BY condition_id, token_id, dry_run"
            ") x ON x.condition_id=o.condition_id AND x.token_id=o.token_id "
            "AND x.dry_run=o.dry_run "
            f"WHERE o.status IN ({placeholders}) AND o.side IN ('UP','DOWN') "
            "AND o.dry_run=? AND r.condition_id IS NULL "
            "AND COALESCE(x.exit_size, 0) < (o.size - 0.02)",
            (*exit_statuses, *statuses, int(dry_run)),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]


def has_executed_order(condition_id: str, dry_run: bool) -> bool:
    """True if this mode already has an effective trade for the market."""
    statuses = effective_order_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    with db() as c:
        row = c.execute(
            f"SELECT 1 FROM orders WHERE condition_id=? AND dry_run=? "
            f"AND side IN ('UP','DOWN') AND status IN ({placeholders}) LIMIT 1",
            (condition_id, int(dry_run), *statuses),
        ).fetchone()
        return row is not None


def has_order_attempt(condition_id: str, dry_run: bool) -> bool:
    """True if this mode has already submitted/logged any order for the market."""
    with db() as c:
        row = c.execute(
            "SELECT 1 FROM orders WHERE condition_id=? AND dry_run=? LIMIT 1",
            (condition_id, int(dry_run)),
        ).fetchone()
        return row is not None


def buy_attempt_count_for_market(condition_id: str, dry_run: bool) -> int:
    """Count buy submissions/logs for this market in this mode."""
    with db() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM orders "
            "WHERE condition_id=? AND dry_run=? AND side IN ('UP','DOWN')",
            (condition_id, int(dry_run)),
        ).fetchone()
        return int(row[0] if row else 0)


def effective_buy_orders_for_market(condition_id: str, dry_run: bool) -> list[dict]:
    """Filled/dry-run buys for this market, oldest first."""
    statuses = effective_order_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    with db() as c:
        rows = c.execute(
            "SELECT id, ts, asset, market_slug, condition_id, token_id, side, size, price, "
            "order_id, status, filled_size, error, entry_rule, dry_run "
            "FROM orders WHERE condition_id=? AND dry_run=? "
            f"AND side IN ('UP','DOWN') AND status IN ({placeholders}) "
            "ORDER BY ts ASC",
            (condition_id, int(dry_run), *statuses),
        ).fetchall()
        return [dict(r) for r in rows]


def has_exit_attempt(condition_id: str, dry_run: bool) -> bool:
    """True once an early-exit sell was attempted for this market."""
    with db() as c:
        row = c.execute(
            "SELECT 1 FROM orders WHERE condition_id=? AND dry_run=? AND status LIKE 'exit_%' LIMIT 1",
            (condition_id, int(dry_run)),
        ).fetchone()
        return row is not None


def open_orders_for_market(condition_id: str, dry_run: bool) -> list[dict]:
    """Filled buys in this market with a remaining unexited share balance."""
    statuses = effective_order_statuses(dry_run)
    exit_statuses = effective_exit_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    exit_placeholders = ",".join("?" for _ in exit_statuses)
    with db() as c:
        rows = c.execute(
            "SELECT o.id, o.ts, o.market_slug, o.condition_id, o.token_id, "
            "o.side, o.entry_rule, "
            "(o.size - COALESCE(x.exit_size, 0)) AS size, "
            "o.size AS original_size, COALESCE(x.exit_size, 0) AS exited_size, "
            "o.price, o.order_id, o.status, o.filled_size, o.dry_run "
            "FROM orders o LEFT JOIN resolutions r ON r.condition_id=o.condition_id "
            "LEFT JOIN ("
            "  SELECT condition_id, token_id, dry_run, SUM(size) AS exit_size "
            "  FROM orders "
            f"  WHERE status IN ({exit_placeholders}) "
            "  GROUP BY condition_id, token_id, dry_run"
            ") x ON x.condition_id=o.condition_id AND x.token_id=o.token_id "
            "AND x.dry_run=o.dry_run "
            f"WHERE o.condition_id=? AND o.dry_run=? AND o.side IN ('UP','DOWN') "
            f"AND o.status IN ({placeholders}) AND r.condition_id IS NULL "
            "AND (o.size - COALESCE(x.exit_size, 0)) > 0.02 "
            "ORDER BY o.ts ASC",
            (*exit_statuses, condition_id, int(dry_run), *statuses),
        ).fetchall()
        return [dict(r) for r in rows]


def order_attempts_since(cutoff_ts: float, dry_run: bool) -> int:
    """Count submitted/logged orders for this mode since cutoff_ts."""
    with db() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM orders WHERE dry_run=? AND ts>=?",
            (int(dry_run), cutoff_ts),
        ).fetchone()
        return int(row[0] if row else 0)


def record_resolution(condition_id: str, winning_token: str) -> None:
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO resolutions (condition_id, winning_token, resolved_ts) "
            "VALUES (?,?,?)",
            (condition_id, winning_token, time.time()),
        )


def local_day_start_ts(now: Optional[float] = None) -> float:
    """Start of the local calendar day used by the dashboard and risk gate."""
    local_now = datetime.fromtimestamp(now if now is not None else time.time())
    return datetime.combine(local_now.date(), dt_time.min).timestamp()


def open_positions_count(dry_run: bool) -> int:
    """Count distinct condition_ids where we've bought but not yet resolved."""
    return len(unresolved_condition_ids(dry_run))


def consecutive_losses(dry_run: bool, limit: int = 10) -> int:
    """Count consecutive losing resolved markets from most recent backwards."""
    statuses = effective_order_statuses(dry_run)
    exit_statuses = effective_exit_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    exit_placeholders = ",".join("?" for _ in exit_statuses)
    with db() as c:
        rows = c.execute(
            "SELECT o.token_id, r.winning_token FROM orders o "
            "JOIN resolutions r ON r.condition_id=o.condition_id "
            "LEFT JOIN ("
            "  SELECT condition_id, token_id, dry_run, SUM(size) AS exit_size "
            "  FROM orders "
            f"  WHERE status IN ({exit_placeholders}) "
            "  GROUP BY condition_id, token_id, dry_run"
            ") x ON x.condition_id=o.condition_id AND x.token_id=o.token_id "
            "AND x.dry_run=o.dry_run "
            f"WHERE o.status IN ({placeholders}) AND o.side IN ('UP','DOWN') AND o.dry_run=? "
            "AND COALESCE(x.exit_size, 0) < (o.size - 0.02) "
            "ORDER BY r.resolved_ts DESC LIMIT ?",
            (*exit_statuses, *statuses, int(dry_run), limit),
        ).fetchall()
        streak = 0
        for token, winner in rows:
            if token == winner:
                break
            streak += 1
        return streak


def realized_pnl_summary_today(dry_run: bool) -> dict:
    """Return today's realized PnL using exit time or settlement time.

    A position bought before midnight but settled today is realized today. This
    is also the accounting basis used by the bot's daily loss gate.
    """
    cutoff = local_day_start_ts()
    statuses = effective_order_statuses(dry_run)
    exit_statuses = effective_exit_statuses(dry_run)
    placeholders = ",".join("?" for _ in statuses)
    exit_placeholders = ",".join("?" for _ in exit_statuses)
    with db() as c:
        buys = c.execute(
            "SELECT id, ts, condition_id, token_id, side, size, price "
            "FROM orders "
            f"WHERE status IN ({placeholders}) AND side IN ('UP','DOWN') "
            "AND dry_run=? "
            "ORDER BY condition_id, token_id, ts, id",
            (*statuses, int(dry_run)),
        ).fetchall()
        exits = c.execute(
            "SELECT ts, condition_id, token_id, side, size, price "
            "FROM orders "
            f"WHERE status IN ({exit_placeholders}) AND side LIKE 'SELL_%' "
            "AND dry_run=? "
            "ORDER BY condition_id, token_id, ts, id",
            (*exit_statuses, int(dry_run)),
        ).fetchall()
        resolutions = {
            row["condition_id"]: row
            for row in c.execute(
                "SELECT condition_id, winning_token, resolved_ts FROM resolutions"
            ).fetchall()
        }

    realized = 0.0
    buy_lots: dict[int, dict] = {}
    lots_by_market_token: dict[tuple[str, str], list[dict]] = {}
    lot_pnl_today: dict[int, float] = {}

    for row in buys:
        lot = {
            "id": int(row["id"]),
            "ts": float(row["ts"] or 0.0),
            "condition_id": row["condition_id"],
            "token_id": row["token_id"],
            "side": row["side"],
            "size": float(row["size"] or 0.0),
            "remaining": float(row["size"] or 0.0),
            "price": float(row["price"] or 0.0),
        }
        buy_lots[lot["id"]] = lot
        lots_by_market_token.setdefault(
            (lot["condition_id"], lot["token_id"]), []
        ).append(lot)

    for exit_row in exits:
        sell_side = str(exit_row["side"] or "")
        buy_side = sell_side.removeprefix("SELL_")
        remaining_exit = float(exit_row["size"] or 0.0)
        exit_price = float(exit_row["price"] or 0.0)
        lots = lots_by_market_token.get(
            (exit_row["condition_id"], exit_row["token_id"]), []
        )
        for lot in lots:
            if remaining_exit <= 0:
                break
            if lot["side"] != buy_side or lot["remaining"] <= 0:
                continue
            allocated = min(lot["remaining"], remaining_exit)
            lot["remaining"] -= allocated
            remaining_exit -= allocated
            if float(exit_row["ts"] or 0.0) > cutoff:
                pnl = allocated * (exit_price - lot["price"])
                realized += pnl
                lot_pnl_today[lot["id"]] = lot_pnl_today.get(lot["id"], 0.0) + pnl

    for lot in buy_lots.values():
        if lot["remaining"] <= 0.02:
            continue
        resolution = resolutions.get(lot["condition_id"])
        if not resolution or float(resolution["resolved_ts"] or 0.0) <= cutoff:
            continue
        if lot["token_id"] == resolution["winning_token"]:
            pnl = lot["remaining"] * (1.0 - lot["price"])
        else:
            pnl = -(lot["remaining"] * lot["price"])
        realized += pnl
        lot_pnl_today[lot["id"]] = lot_pnl_today.get(lot["id"], 0.0) + pnl

    wins = sum(1 for pnl in lot_pnl_today.values() if pnl >= 0)
    losses = sum(1 for pnl in lot_pnl_today.values() if pnl < 0)
    pending = sum(
        1
        for lot in buy_lots.values()
        if lot["remaining"] > 0.02
        and lot["condition_id"] not in resolutions
        and lot["ts"] > cutoff
    )

    return {
        "realized_usd": realized,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "period_start_ts": cutoff,
    }


def realized_pnl_today(dry_run: bool) -> float:
    """Sum gain/loss across resolved markets since local midnight."""
    return float(realized_pnl_summary_today(dry_run)["realized_usd"])
