#!/usr/bin/env python3
"""Idempotently correct known Paper accounting omissions.

This script is intentionally explicit and append-only from an audit
perspective: it keeps the original gross/net values in the migration columns
and writes an ``accounting_correction`` event for every changed session.
It never deletes fills, positions, sessions, or prior events.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path


MAKER_COLUMNS = {
    "up_proceeds_usd": "REAL DEFAULT 0",
    "down_proceeds_usd": "REAL DEFAULT 0",
    "merged_shares": "REAL DEFAULT 0",
    "merge_proceeds_usd": "REAL DEFAULT 0",
    "redeem_proceeds_usd": "REAL DEFAULT 0",
    "accounting_original_gross_pnl_usd": "REAL",
    "accounting_original_net_pnl_usd": "REAL",
    "accounting_corrected_ts": "REAL",
}


def ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(maker_sessions)")}
    for name, decl in MAKER_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE maker_sessions ADD COLUMN {name} {decl}")


def payload(row: sqlite3.Row) -> dict:
    try:
        value = json.loads(row[0])
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def correction_event(conn: sqlite3.Connection, *, row: sqlite3.Row, reason: str, before: dict, after: dict) -> None:
    data = {
        "session_id": int(row["id"]),
        "reason": reason,
        "before": before,
        "after": after,
        "source": "ops/correct_paper_ledger.py",
    }
    conn.execute(
        "INSERT INTO events(ts, kind, market_slug, payload) VALUES (?, ?, ?, ?)",
        (time.time(), "accounting_correction", row["market_slug"], json.dumps(data, ensure_ascii=False)),
    )


def correct_split_merges(conn: sqlite3.Connection, db_label: str) -> int:
    changed = 0
    rows = conn.execute(
        "SELECT * FROM maker_sessions WHERE status='closed' ORDER BY id"
    ).fetchall()
    for row in rows:
        if row["accounting_corrected_ts"] is not None:
            continue
        current_merge = float(row["merge_proceeds_usd"] or 0)
        event_rows = conn.execute(
            "SELECT payload FROM events WHERE kind='split_merge' AND market_slug=?",
            (row["market_slug"],),
        ).fetchall()
        proceeds = 0.0
        pairs = 0.0
        for event in event_rows:
            data = payload(event)
            if int(data.get("session_id", -1)) != int(row["id"]):
                continue
            proceeds += float(data.get("proceeds") or 0)
            pairs += float(data.get("pairs") or 0)
        if proceeds <= 0 or current_merge > 1e-9:
            continue
        before_gross = float(row["gross_pnl_usd"] or 0)
        before_net = float(row["net_pnl_usd"] or 0)
        after_gross = before_gross + proceeds
        after_net = before_net + proceeds
        now = time.time()
        conn.execute(
            """UPDATE maker_sessions
               SET merged_shares=?, merge_proceeds_usd=?,
                   accounting_original_gross_pnl_usd=?, accounting_original_net_pnl_usd=?,
                   gross_pnl_usd=?, net_pnl_usd=?, accounting_corrected_ts=?
               WHERE id=?""",
            (pairs, proceeds, before_gross, before_net, after_gross, after_net, now, int(row["id"])),
        )
        correction_event(
            conn, row=row, reason=f"{db_label}: restore persisted split_merge proceeds",
            before={"gross_pnl_usd": before_gross, "net_pnl_usd": before_net, "merge_proceeds_usd": current_merge},
            after={"gross_pnl_usd": after_gross, "net_pnl_usd": after_net, "merge_proceeds_usd": proceeds, "merged_shares": pairs},
        )
        changed += 1
    return changed


def correct_flatten(conn: sqlite3.Connection) -> int:
    changed = 0
    rows = conn.execute(
        "SELECT * FROM maker_sessions WHERE status='closed' ORDER BY id"
    ).fetchall()
    for row in rows:
        flatten = float(row["flatten_pnl_usd"] or 0)
        gross = float(row["gross_pnl_usd"] or 0)
        net = float(row["net_pnl_usd"] or 0)
        if row["accounting_corrected_ts"] is not None or abs(flatten) <= 1e-9:
            continue
        # Old B code closed no-inventory sessions as zero and dropped the
        # realized flatten result.  Only repair that exact signature.
        if abs(gross) > 1e-9 or abs(net) > 1e-9:
            continue
        after_gross = gross + flatten
        after_net = net + flatten
        now = time.time()
        winner = row["winner"]
        if not winner or str(winner).upper() in {"UNRESOLVED", "NONE"}:
            winner = "PAPER_FLATTENED"
        conn.execute(
            """UPDATE maker_sessions
               SET accounting_original_gross_pnl_usd=?, accounting_original_net_pnl_usd=?,
                   gross_pnl_usd=?, net_pnl_usd=?, winner=?, accounting_corrected_ts=?
               WHERE id=?""",
            (gross, net, after_gross, after_net, winner, now, int(row["id"])),
        )
        correction_event(
            conn, row=row, reason="B: restore persisted maker_flatten PnL",
            before={"gross_pnl_usd": gross, "net_pnl_usd": net, "flatten_pnl_usd": flatten},
            after={"gross_pnl_usd": after_gross, "net_pnl_usd": after_net, "winner": winner},
        )
        changed += 1
    return changed


def run(path: Path, label: str, mode: str) -> int:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)
    if mode == "split":
        changed = correct_split_merges(conn, label)
    elif mode == "flatten":
        changed = correct_flatten(conn)
    else:
        raise ValueError(mode)
    conn.commit()
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(net_pnl_usd),0) AS net, COALESCE(SUM(gross_pnl_usd),0) AS gross FROM maker_sessions WHERE status='closed'"
    ).fetchone()
    print(json.dumps({"db": str(path), "label": label, "changed": changed, "closed": row["n"], "net": row["net"], "gross": row["gross"]}))
    conn.close()
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--mode", choices=("split", "flatten"), required=True)
    args = parser.parse_args()
    run(args.db, args.label, args.mode)


if __name__ == "__main__":
    main()
