"""Fee-aware performance report from the SQLite journal."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AuditSummary:
    strategy: str
    trades: int
    notional_usd: float
    gross_pnl_usd: float
    fees_usd: float
    rebate_est_usd: float
    net_pnl_usd: float
    win_rate: Optional[float]
    roi_on_notional: Optional[float]


def _day_start_ts(day: Optional[str] = None) -> float:
    if day:
        dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.timestamp()


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def summarize_db(path: Path, *, since_ts: Optional[float] = None) -> list[AuditSummary]:
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    since = since_ts if since_ts is not None else 0.0
    out: list[AuditSummary] = []

    pos_cols = _table_cols(conn, "positions")
    if pos_cols:
        strategy_expr = "strategy" if "strategy" in pos_cols else "'late_edge'"
        fee_expr = "COALESCE(fee_usd, 0)" if "fee_usd" in pos_cols else "0"
        net_expr = (
            "COALESCE(pnl_net_usd, pnl_usd)"
            if "pnl_net_usd" in pos_cols
            else "pnl_usd"
        )
        pos_rows = conn.execute(
            f"""
            SELECT {strategy_expr} AS strategy,
                   COUNT(*) AS n,
                   COALESCE(SUM(size * entry_price), 0) AS notional,
                   COALESCE(SUM(pnl_usd), 0) AS gross,
                   COALESCE(SUM({fee_expr}), 0) AS fees,
                   COALESCE(SUM({net_expr}), 0) AS net,
                   SUM(CASE WHEN {net_expr} > 0 THEN 1 ELSE 0 END) AS wins
            FROM positions
            WHERE status='closed' AND closed_ts >= ?
            GROUP BY {strategy_expr}
            """,
            (since,),
        ).fetchall()
        for row in pos_rows:
            n = int(row["n"] or 0)
            notional = float(row["notional"] or 0.0)
            net = float(row["net"] or 0.0)
            out.append(
                AuditSummary(
                    strategy=str(row["strategy"] or "late_edge"),
                    trades=n,
                    notional_usd=notional,
                    gross_pnl_usd=float(row["gross"] or 0.0),
                    fees_usd=float(row["fees"] or 0.0),
                    rebate_est_usd=0.0,
                    net_pnl_usd=net,
                    win_rate=(float(row["wins"]) / n) if n else None,
                    roi_on_notional=(net / notional) if notional > 0 else None,
                )
            )

    if "maker_sessions" in {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }:
        maker_rows = conn.execute(
            """
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(up_cost_usd + down_cost_usd), 0) AS notional,
                   COALESCE(SUM(gross_pnl_usd), 0) AS gross,
                   COALESCE(SUM(fee_usd), 0) AS fees,
                   COALESCE(SUM(rebate_est_usd), 0) AS rebates,
                   COALESCE(SUM(net_pnl_usd), 0) AS net,
                   SUM(CASE WHEN net_pnl_usd > 0 THEN 1 ELSE 0 END) AS wins
            FROM maker_sessions
            WHERE status='closed' AND closed_ts >= ?
            """,
            (since,),
        ).fetchone()
        if maker_rows and int(maker_rows["n"] or 0) > 0:
            n = int(maker_rows["n"])
            notional = float(maker_rows["notional"] or 0.0)
            net = float(maker_rows["net"] or 0.0)
            out.append(
                AuditSummary(
                    strategy="maker_mm",
                    trades=n,
                    notional_usd=notional,
                    gross_pnl_usd=float(maker_rows["gross"] or 0.0),
                    fees_usd=float(maker_rows["fees"] or 0.0),
                    rebate_est_usd=float(maker_rows["rebates"] or 0.0),
                    net_pnl_usd=net,
                    win_rate=(float(maker_rows["wins"]) / n) if n else None,
                    roi_on_notional=(net / notional) if notional > 0 else None,
                )
            )

    conn.close()
    return out


def print_report(path: Path, *, day: Optional[str] = None) -> str:
    since = _day_start_ts(day)
    rows = summarize_db(path, since_ts=since)
    label = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"Fee-aware audit — {path.name} — since {label} UTC", "-" * 72]
    if not rows:
        lines.append("No closed trades yet.")
        text = "\n".join(lines)
        print(text)
        return text

    total_net = 0.0
    total_fees = 0.0
    total_notional = 0.0
    for r in rows:
        total_net += r.net_pnl_usd
        total_fees += r.fees_usd
        total_notional += r.notional_usd
        wr = f"{r.win_rate*100:.1f}%" if r.win_rate is not None else "n/a"
        roi = f"{r.roi_on_notional*100:.2f}%" if r.roi_on_notional is not None else "n/a"
        lines.append(
            f"{r.strategy:12s}  n={r.trades:4d}  notional=${r.notional_usd:,.2f}  "
            f"gross=${r.gross_pnl_usd:+.2f}  fees=${r.fees_usd:.2f}  "
            f"rebate≈${r.rebate_est_usd:.2f}  net=${r.net_pnl_usd:+.2f}  "
            f"WR={wr}  ROI={roi}"
        )
    lines.append("-" * 72)
    roi_all = (total_net / total_notional * 100) if total_notional > 0 else 0.0
    lines.append(
        f"{'TOTAL':12s}  notional=${total_notional:,.2f}  fees=${total_fees:.2f}  "
        f"net=${total_net:+.2f}  ROI={roi_all:.2f}%"
    )
    text = "\n".join(lines)
    print(text)
    return text
