"""SQLite logger for every decision and order outcome."""
from __future__ import annotations

import sqlite3
import os
import time
from contextlib import contextmanager
from datetime import datetime, time as dt_time, timezone
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
    """Condition ids with an effective FIFO remainder and no resolution."""
    return list(dict.fromkeys(p["condition_id"] for p in remaining_positions(dry_run)))

def unresolved_with_slug(dry_run: bool) -> list[tuple[str, str]]:
    """Markets to resolve, using the same FIFO remainder as positions."""
    return list(dict.fromkeys((p["condition_id"], p["market_slug"])
                              for p in remaining_positions(dry_run)))

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
    """Remaining effective FIFO lots for the stop-loss worker."""
    lots, _, resolutions = _fifo_ledger(dry_run, condition_id=condition_id)
    return _remaining_positions(lots, resolutions)

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


TRADING_TIMEZONE = timezone.utc
POSITION_DUST_SHARES = 0.02


def local_day_start_ts(now: Optional[float] = None) -> float:
    """UTC trading-day boundary, matching the production worker's risk day."""
    local_now = datetime.fromtimestamp(now if now is not None else time.time(), TRADING_TIMEZONE)
    return datetime.combine(local_now.date(), dt_time.min, tzinfo=TRADING_TIMEZONE).timestamp()


def _fifo_ledger(dry_run: bool, condition_id: Optional[str] = None) -> tuple[list[dict], list[dict], dict]:
    """Read one consistent ledger and match effective exits to earlier buys.

    `size` is shares; historical `filled_size` stores USDC notional. Failed or
    unconfirmed exits do not reduce holdings, and a sell never consumes a buy
    logged after it. Matching always stays within mode, condition, token and side.
    """
    buy_statuses = effective_order_statuses(dry_run)
    exit_statuses = effective_exit_statuses(dry_run)
    statuses = (*buy_statuses, *exit_statuses)
    placeholders = ",".join("?" for _ in statuses)
    with db() as c:
        if not c.in_transaction:
            c.execute("BEGIN")
        condition_filter = " AND condition_id=?" if condition_id is not None else ""
        params = (int(dry_run), *statuses, condition_id) if condition_id is not None else (int(dry_run), *statuses)
        rows = c.execute(
            f"SELECT * FROM orders WHERE dry_run=? AND status IN ({placeholders})"
            f"{condition_filter} ORDER BY ts,id", params,
        ).fetchall()
        resolutions = {
            row["condition_id"]: dict(row)
            for row in c.execute("SELECT condition_id,winning_token,resolved_ts FROM resolutions")
        }

    lots: list[dict] = []
    groups: dict[tuple[str, str, str], list[dict]] = {}
    events: list[dict] = []
    for row in rows:
        order = dict(row)
        side = str(order.get("side") or "")
        shares = max(float(order.get("size") or 0.0), 0.0)
        if order["status"] in buy_statuses and side in ("UP", "DOWN"):
            lot = {
                **order,
                "asset": str(order.get("asset") or infer_asset(order.get("market_slug"))).upper(),
                "size": shares, "original_size": shares, "remaining": shares,
                "price": float(order.get("price") or 0.0),
            }
            lots.append(lot)
            groups.setdefault((lot["condition_id"], lot["token_id"], side), []).append(lot)
        elif order["status"] in exit_statuses and side.startswith("SELL_"):
            key = (order["condition_id"], order["token_id"], side.removeprefix("SELL_"))
            did_fill = False
            for lot in groups.get(key, []):
                if shares <= 0:
                    break
                allocated = min(lot["remaining"], shares)
                if allocated <= 0:
                    continue
                lot["remaining"] = max(lot["remaining"] - allocated, 0.0)
                shares -= allocated
                did_fill = True
                events.append({
                    "lot_id": lot["id"], "asset": lot["asset"],
                    "realize_ts": float(order["ts"]),
                    "pnl": allocated * (float(order.get("price") or 0.0) - lot["price"]),
                })
            if did_fill:
                # A protective sell may exactly consume an earlier lot. The
                # other lots already held still belong to that armed exit;
                # later buys have not entered the chronological groups yet.
                for lot in groups.get(key, []):
                    if lot["remaining"] > POSITION_DUST_SHARES:
                        lot["stop_loss_pending"] = True

    for lot in lots:
        resolution = resolutions.get(lot["condition_id"])
        if lot["remaining"] <= POSITION_DUST_SHARES or not resolution:
            continue
        payout = 1.0 if lot["token_id"] == resolution["winning_token"] else 0.0
        events.append({
            "lot_id": lot["id"], "asset": lot["asset"],
            "realize_ts": float(resolution.get("resolved_ts") or 0.0),
            "pnl": lot["remaining"] * (payout - lot["price"]),
        })
    return lots, events, resolutions


def _remaining_positions(lots: list[dict], resolutions: dict, asset: Optional[str] = None) -> list[dict]:
    wanted = asset.strip().upper() if asset else None
    positions = []
    for lot in lots:
        if (lot["remaining"] <= POSITION_DUST_SHARES or lot["condition_id"] in resolutions
                or (wanted and lot["asset"] != wanted)):
            continue
        remaining = lot["remaining"]
        positions.append({
            **lot, "size": remaining,
            "exited_size": lot["original_size"] - remaining,
            # A partial protective exit must keep draining its remainder after
            # worker hydration; failed/unconfirmed attempts never consume shares.
            "stop_loss_pending": bool(lot.get("stop_loss_pending")) or lot["original_size"] - remaining > 1e-9,
            "notional_usd": remaining * lot["price"],
            # Cost basis is explicit: no stale entry is presented as a live quote.
            "valuation": "entry_cost",
        })
    return positions


def remaining_positions(dry_run: bool, asset: Optional[str] = None) -> list[dict]:
    """Unresolved FIFO lots after valid exits, excluding <= 0.02-share dust."""
    lots, _, resolutions = _fifo_ledger(dry_run)
    return _remaining_positions(lots, resolutions, asset)


def accounting_snapshot(dry_run: bool, now: Optional[float] = None) -> dict:
    """One ledger read backs pending detail, daily totals and per-asset totals."""
    cutoff = local_day_start_ts(now)
    lots, events, resolutions = _fifo_ledger(dry_run)
    positions = _remaining_positions(lots, resolutions)
    lot_today: dict[int, float] = {}
    lot_assets = {lot["id"]: lot["asset"] for lot in lots}
    for event in events:
        if event["realize_ts"] >= cutoff:
            lot_id = event["lot_id"]
            lot_today[lot_id] = lot_today.get(lot_id, 0.0) + event["pnl"]

    by_asset: dict[str, dict] = {}
    for lot_id, pnl in lot_today.items():
        item = by_asset.setdefault(lot_assets[lot_id], {
            "realized_usd": 0.0, "wins": 0, "losses": 0, "pending": 0, "open_value_usd": 0.0,
        })
        item["realized_usd"] += pnl
        item["wins" if pnl >= 0 else "losses"] += 1
    for position in positions:
        item = by_asset.setdefault(position["asset"], {
            "realized_usd": 0.0, "wins": 0, "losses": 0, "pending": 0, "open_value_usd": 0.0,
        })
        item["pending"] += 1
        item["open_value_usd"] += position["notional_usd"]
    return {
        "pnl": {
            "realized_usd": sum(lot_today.values()),
            "wins": sum(1 for pnl in lot_today.values() if pnl >= 0),
            "losses": sum(1 for pnl in lot_today.values() if pnl < 0),
            # Pending is a current balance, so carry-over lots remain visible.
            "pending": len(positions),
            "period_start_ts": cutoff,
            "trading_timezone": "UTC",
        },
        "positions": positions, "by_asset": by_asset,
        "open_value_usd": sum(p["notional_usd"] for p in positions),
        "valuation": "entry_cost",
    }


def open_positions_count(dry_run: bool) -> int:
    """Count distinct unresolved conditions after effective FIFO exits."""
    return len({p["condition_id"] for p in remaining_positions(dry_run)})


def consecutive_losses(dry_run: bool, limit: int = 10) -> int:
    """Resolved losing lots, using the same remaining shares as the ledger."""
    lots, _, resolutions = _fifo_ledger(dry_run)
    resolved = [lot for lot in lots if lot["remaining"] > POSITION_DUST_SHARES
                and lot["condition_id"] in resolutions]
    resolved.sort(key=lambda lot: (resolutions[lot["condition_id"]]["resolved_ts"], lot["id"]), reverse=True)
    streak = 0
    for lot in resolved[:limit]:
        if lot["token_id"] == resolutions[lot["condition_id"]]["winning_token"]:
            break
        streak += 1
    return streak


def realized_pnl_summary_today(dry_run: bool) -> dict:
    """Realized exits/settlements in the UTC day plus all outstanding lots."""
    return accounting_snapshot(dry_run)["pnl"]


def realized_pnl_today(dry_run: bool) -> float:
    return float(realized_pnl_summary_today(dry_run)["realized_usd"])


def realized_pnl_by_day(dry_run: bool, days: int = 50, asset: Optional[str] = None) -> list[dict]:
    """Daily FIFO PnL filtered by asset; count each entry lot once per day."""
    _, events, _ = _fifo_ledger(dry_run)
    wanted = asset.strip().upper() if asset else None
    daily: dict[str, dict[int, float]] = {}
    for event in events:
        if wanted and event["asset"] != wanted:
            continue
        day = datetime.fromtimestamp(event["realize_ts"], TRADING_TIMEZONE).strftime("%Y-%m-%d")
        lots = daily.setdefault(day, {})
        lots[event["lot_id"]] = lots.get(event["lot_id"], 0.0) + event["pnl"]
    result = []
    for day in sorted(daily, reverse=True)[:max(days, 0)]:
        pnls = list(daily[day].values())
        result.append({
            "day": day, "pnl_usd": sum(pnls),
            "wins": sum(1 for pnl in pnls if pnl >= 0),
            "losses": sum(1 for pnl in pnls if pnl < 0),
        })
    return result


def realized_pnl_by_asset_today(dry_run: bool) -> dict[str, dict]:
    """Asset totals share FIFO allocation, daily boundary and lot win counts."""
    return accounting_snapshot(dry_run)["by_asset"]
