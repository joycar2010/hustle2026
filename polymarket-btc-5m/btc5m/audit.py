"""Fee-aware performance report from the SQLite journal."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from btc5m.calibration import load_bucket_stats
from btc5m.stress import format_stress, stress_late_edge_db


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


def maker_pair_residual_report(path: Path, *, since_ts: float = 0.0) -> dict[str, Any]:
    """Split maker PnL into paired gross vs residual / flatten components."""
    empty = {
        "sessions": 0,
        "paired_sessions": 0,
        "residual_sessions": 0,
        "paired_gross_est": 0.0,
        "residual_net_est": 0.0,
        "flatten_pnl_usd": 0.0,
        "net_pnl_usd": 0.0,
        "avg_pair_cost": None,
    }
    if not path.exists():
        return empty
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "maker_sessions" not in tables:
            return empty
        cols = _table_cols(conn, "maker_sessions")
        flatten_expr = (
            "COALESCE(flatten_pnl_usd, 0)" if "flatten_pnl_usd" in cols else "0"
        )
        rows = conn.execute(
            f"""
            SELECT paired_shares, pair_cost, residual_shares, residual_side,
                   gross_pnl_usd, net_pnl_usd, {flatten_expr} AS flatten_pnl_usd,
                   up_shares, down_shares, up_cost_usd, down_cost_usd
            FROM maker_sessions
            WHERE status='closed' AND closed_ts >= ?
            """,
            (since_ts,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return empty

    paired_gross = 0.0
    residual_net = 0.0
    flatten = 0.0
    net = 0.0
    pair_costs: list[float] = []
    paired_n = 0
    residual_n = 0
    for row in rows:
        net += float(row["net_pnl_usd"] or 0.0)
        flatten += float(row["flatten_pnl_usd"] or 0.0)
        paired = float(row["paired_shares"] or 0.0)
        residual = float(row["residual_shares"] or 0.0)
        pc = row["pair_cost"]
        if paired > 0 and pc is not None:
            paired_n += 1
            pair_costs.append(float(pc))
            paired_gross += paired * (1.0 - float(pc))
        if residual > 0:
            residual_n += 1
        # residual contribution ≈ total gross - paired_gross (approx)
        residual_net += float(row["gross_pnl_usd"] or 0.0) - (
            paired * (1.0 - float(pc)) if paired > 0 and pc is not None else 0.0
        )

    return {
        "sessions": len(rows),
        "paired_sessions": paired_n,
        "residual_sessions": residual_n,
        "paired_gross_est": paired_gross,
        "residual_net_est": residual_net,
        "flatten_pnl_usd": flatten,
        "net_pnl_usd": net,
        "avg_pair_cost": (sum(pair_costs) / len(pair_costs)) if pair_costs else None,
    }


def maker_session_activity_report(path: Path, *, since_ts: float = 0.0) -> dict[str, Any]:
    """Filled vs empty session counts — stops empty B sessions from looking like trades."""
    empty = {
        "sessions": 0,
        "open_sessions": 0,
        "filled_sessions": 0,
        "empty_closed_sessions": 0,
        "nonzero_pnl_sessions": 0,
        "wins": 0,
        "losses": 0,
        "flats": 0,
        "net_pnl_usd": 0.0,
    }
    if not path.exists():
        return empty
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "maker_sessions" not in tables:
            return empty
        cols = _table_cols(conn, "maker_sessions")
        merge_col = "merged_shares" if "merged_shares" in cols else "0"
        up_pr = "up_proceeds_usd" if "up_proceeds_usd" in cols else "0"
        dn_pr = "down_proceeds_usd" if "down_proceeds_usd" in cols else "0"
        flat_col = "flatten_pnl_usd" if "flatten_pnl_usd" in cols else "0"
        rows = conn.execute(
            f"""
            SELECT status,
                   COALESCE(up_shares,0) AS up_shares,
                   COALESCE(down_shares,0) AS down_shares,
                   COALESCE(paired_shares,0) AS paired_shares,
                   COALESCE({merge_col},0) AS merged_shares,
                   COALESCE({up_pr},0) AS up_proceeds_usd,
                   COALESCE({dn_pr},0) AS down_proceeds_usd,
                   COALESCE({flat_col},0) AS flatten_pnl_usd,
                   net_pnl_usd
            FROM maker_sessions
            WHERE COALESCE(closed_ts, opened_ts) >= ? OR status='open'
            """,
            (since_ts,),
        ).fetchall()
    finally:
        conn.close()

    out = dict(empty)
    out["sessions"] = len(rows)
    for row in rows:
        if row["status"] == "open":
            out["open_sessions"] += 1
            continue
        filled = (
            float(row["up_shares"] or 0) > 0
            or float(row["down_shares"] or 0) > 0
            or float(row["paired_shares"] or 0) > 0
            or float(row["merged_shares"] or 0) > 0
            or float(row["up_proceeds_usd"] or 0) > 0
            or float(row["down_proceeds_usd"] or 0) > 0
            or abs(float(row["flatten_pnl_usd"] or 0)) > 1e-9
            or (row["net_pnl_usd"] is not None and abs(float(row["net_pnl_usd"])) > 1e-9)
        )
        if filled:
            out["filled_sessions"] += 1
        else:
            out["empty_closed_sessions"] += 1
        net = float(row["net_pnl_usd"] or 0.0)
        out["net_pnl_usd"] += net
        if abs(net) > 1e-9:
            out["nonzero_pnl_sessions"] += 1
            if net > 0:
                out["wins"] += 1
            else:
                out["losses"] += 1
        else:
            out["flats"] += 1
    return out


def split_edge_attribution_report(path: Path, *, since_ts: float = 0.0) -> dict[str, Any]:
    """Decompose C PnL into merge-flat vs residual-direction vs flatten."""
    empty = {
        "sessions": 0,
        "full_merge_flat": 0,
        "residual_winner_kept": 0,
        "residual_loser_kept": 0,
        "residual_winner_pnl": 0.0,
        "residual_loser_pnl": 0.0,
        "flatten_pnl_usd": 0.0,
        "pair_ask_edge_est": 0.0,
        "net_pnl_usd": 0.0,
    }
    if not path.exists():
        return empty
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "maker_sessions" not in tables:
            return empty
        cols = _table_cols(conn, "maker_sessions")
        needed = {
            "up_shares",
            "down_shares",
            "merged_shares",
            "up_proceeds_usd",
            "down_proceeds_usd",
            "net_pnl_usd",
        }
        if not needed.issubset(cols):
            return empty
        flatten_expr = (
            "COALESCE(flatten_pnl_usd, 0)" if "flatten_pnl_usd" in cols else "0"
        )
        rows = conn.execute(
            f"""
            SELECT COALESCE(up_shares,0) AS up_shares,
                   COALESCE(down_shares,0) AS down_shares,
                   COALESCE(merged_shares,0) AS merged_shares,
                   COALESCE(up_proceeds_usd,0) AS up_proceeds,
                   COALESCE(down_proceeds_usd,0) AS down_proceeds,
                   COALESCE(redeem_proceeds_usd,0) AS redeem_proceeds,
                   COALESCE(merge_proceeds_usd,0) AS merge_proceeds,
                   COALESCE(up_cost_usd,0)+COALESCE(down_cost_usd,0) AS cost,
                   {flatten_expr} AS flatten_pnl_usd,
                   COALESCE(net_pnl_usd,0) AS net_pnl_usd,
                   winner
            FROM maker_sessions
            WHERE status='closed' AND closed_ts >= ?
            """,
            (since_ts,),
        ).fetchall()
    finally:
        conn.close()

    out = dict(empty)
    out["sessions"] = len(rows)
    for row in rows:
        net = float(row["net_pnl_usd"] or 0)
        out["net_pnl_usd"] += net
        flat = float(row["flatten_pnl_usd"] or 0)
        out["flatten_pnl_usd"] += flat
        sell = float(row["up_proceeds"] or 0) + float(row["down_proceeds"] or 0)
        merged = float(row["merged_shares"] or 0)
        up_sh = float(row["up_shares"] or 0)
        dn_sh = float(row["down_shares"] or 0)
        if sell <= 1e-9 and abs(flat) < 1e-9 and abs(net) < 1e-6:
            out["full_merge_flat"] += 1
            continue
        # Residual kept after partial sell
        if up_sh > dn_sh or (sell > 0 and float(row["down_proceeds"] or 0) > float(row["up_proceeds"] or 0)):
            # sold more DOWN → residual leans UP
            residual_side = "UP"
        elif dn_sh > up_sh or float(row["up_proceeds"] or 0) > float(row["down_proceeds"] or 0):
            residual_side = "DOWN"
        else:
            residual_side = None
        winner = str(row["winner"] or "").upper()
        if residual_side and winner in {"UP", "DOWN"}:
            if residual_side == winner:
                out["residual_winner_kept"] += 1
                out["residual_winner_pnl"] += net
            else:
                out["residual_loser_kept"] += 1
                out["residual_loser_pnl"] += net
        # Crude pair-ask edge: merge proceeds should ≈ merged shares; anything
        # above mint cost on the merged sleeve is ask edge (usually ~0 in paper).
        cost = float(row["cost"] or 0)
        merge_p = float(row["merge_proceeds"] or 0)
        if merged > 0 and cost > 0:
            # mint cost for merged sleeve ≈ merged ( $1 per pair )
            out["pair_ask_edge_est"] += merge_p - merged
    return out


def fill_quality_report(path: Path, *, since_ts: float = 0.0) -> dict[str, Any]:
    """Classify maker fills from note text: touch / crossed / flatten."""
    out = {
        "touch": 0,
        "crossed": 0,
        "flatten": 0,
        "other": 0,
        "total": 0,
        "crossed_rate": 0.0,
    }
    if not path.exists():
        return out
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "fills" not in tables:
            return out
        cols = _table_cols(conn, "fills")
        if "note" not in cols:
            return out
        ts_col = "ts" if "ts" in cols else None
        # Include maker / split_sell / sports fills
        if ts_col:
            rows = conn.execute(
                """
                SELECT note FROM fills
                WHERE ts >= ?
                  AND (
                    strategy IN ('maker_mm','split_sell','sports_mm')
                    OR strategy IS NULL
                    OR note LIKE '%touch%'
                    OR note LIKE '%flatten%'
                    OR note LIKE '%sports%'
                  )
                """,
                (since_ts,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT note FROM fills").fetchall()
    finally:
        conn.close()

    for row in rows:
        note = str(row["note"] or "").lower()
        out["total"] += 1
        if "flatten" in note:
            out["flatten"] += 1
        elif "crossed" in note:
            out["crossed"] += 1
        elif "touch" in note:
            out["touch"] += 1
        else:
            out["other"] += 1
    fills = out["touch"] + out["crossed"]
    out["crossed_rate"] = (out["crossed"] / fills) if fills else 0.0
    return out


def print_report(
    path: Path,
    *,
    day: Optional[str] = None,
    fee_rate: float = 0.07,
    include_stress: bool = True,
) -> str:
    since = _day_start_ts(day)
    rows = summarize_db(path, since_ts=since)
    label = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"Fee-aware audit — {path.name} — since {label} UTC", "-" * 72]
    if not rows:
        lines.append("No closed trades yet.")
    else:
        total_net = 0.0
        total_fees = 0.0
        total_notional = 0.0
        for r in rows:
            total_net += r.net_pnl_usd
            total_fees += r.fees_usd
            total_notional += r.notional_usd
            wr = f"{r.win_rate*100:.1f}%" if r.win_rate is not None else "n/a"
            roi = (
                f"{r.roi_on_notional*100:.2f}%"
                if r.roi_on_notional is not None
                else "n/a"
            )
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

    # P2: entry-price bucket WR (late_edge)
    buckets = load_bucket_stats(path, lookback_sec=7 * 86400, fee_rate=fee_rate)
    if buckets and any(b.n for b in buckets):
        lines.append("")
        lines.append("Entry-price buckets (7d lookback)")
        lines.append("-" * 72)
        for b in buckets:
            if b.n == 0:
                continue
            flag = " BAN" if b.banned else ""
            lines.append(
                f"  [{b.lo:.2f},{b.hi:.2f})  n={b.n:3d}  WR={b.wr:.1%}  "
                f"need≥{b.required_wr:.1%}  net=${b.net_pnl_usd:+.2f}{flag}"
            )

    # P2: maker paired / residual / fill quality
    maker = maker_pair_residual_report(path, since_ts=since)
    if maker["sessions"]:
        avg_pc = (
            f"{maker['avg_pair_cost']:.3f}"
            if maker["avg_pair_cost"] is not None
            else "n/a"
        )
        lines.append("")
        lines.append("Maker pair / residual split")
        lines.append("-" * 72)
        lines.append(
            f"  sessions={maker['sessions']} paired={maker['paired_sessions']} "
            f"residual={maker['residual_sessions']} avg_pair_cost={avg_pc}"
        )
        lines.append(
            f"  paired_gross≈${maker['paired_gross_est']:+.2f}  "
            f"residual_gross≈${maker['residual_net_est']:+.2f}  "
            f"flatten=${maker['flatten_pnl_usd']:+.2f}  "
            f"net=${maker['net_pnl_usd']:+.2f}"
        )
        fq = fill_quality_report(path, since_ts=since)
        if fq["total"]:
            lines.append(
                f"  fill_quality touch={fq['touch']} crossed={fq['crossed']} "
                f"flatten={fq['flatten']} crossed_rate={fq['crossed_rate']:.1%}"
            )

    # P2: friction stress (late_edge positions)
    if include_stress and path.name in {"paper.db", "live.db"}:
        stress = stress_late_edge_db(path, slip_ticks=1.0, fee_rate=fee_rate)
        lines.append("")
        lines.append(format_stress(stress))

    text = "\n".join(lines)
    print(text)
    return text
