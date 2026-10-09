"""In-place patch #19: daily history uses the SAME lot accounting as the KPIs.

Root cause of the all-100% history: /api/pnl/daily attributed win/loss by
entry-token-vs-settlement only, while the headline KPIs use store's FIFO lot
accounting where an early exit realizes its own gain/LOSS lot.  A stop-out
whose entry token later matched the winner showed as a "win" day-side and a
"loss" KPI-side.

Fix: parameterize store.realized_pnl_summary_today with an optional
(cutoff, end) window -- default behavior unchanged for every existing caller
(worker gates included) -- and rebuild pnl_daily as a per-day loop over that
exact function, with immutable-day caching.

Usage:  python3 patch_dashboard19.py <app_root>
"""
from __future__ import annotations

import sys
from pathlib import Path

S_DEF_OLD = "def realized_pnl_summary_today(dry_run: bool) -> dict:"
S_DEF_NEW = ("def realized_pnl_summary_today(dry_run: bool, "
             "cutoff: Optional[float] = None, end: Optional[float] = None) -> dict:")

S_CUT_OLD = "    cutoff = local_day_start_ts()\n"
S_CUT_NEW = ("    if cutoff is None:\n"
             "        cutoff = local_day_start_ts()\n"
             "    end_ts = float(\"inf\") if end is None else float(end)\n")

S_EXIT_OLD = "            if float(exit_row[\"ts\"] or 0.0) > cutoff:"
S_EXIT_NEW = "            if cutoff < float(exit_row[\"ts\"] or 0.0) <= end_ts:"

S_RES_OLD = ("        if not resolution or float(resolution[\"resolved_ts\"] or 0.0) <= cutoff:\n"
             "            continue")
S_RES_NEW = ("        if not resolution:\n"
             "            continue\n"
             "        _r_ts = float(resolution[\"resolved_ts\"] or 0.0)\n"
             "        if _r_ts <= cutoff or _r_ts > end_ts:\n"
             "            continue")

DASH_START = '@app.get("/api/pnl/daily")'
DASH_END = '            "capital_base_usd": round(capital, 4)}'

DASH_NEW = '''_pnl_daily_cache: dict[str, dict] = {}


@app.get("/api/pnl/daily")
def pnl_daily(lane: str = "paper", offset: int = 0, limit: int = 14):
    """Per trading-day history with the SAME lot accounting as the headline
    KPIs (store.realized_pnl_summary_today windowed day by day): early exits
    realize their own win/loss lots, so day win rates match what the risk
    gate saw.  Finished days are cached immutably; today recomputes live."""
    lane = lane if lane in ("paper", "live") else "paper"
    offset = max(0, min(int(offset), 3650))
    limit = max(1, min(int(limit), 60))
    dry = lane == "paper"
    dry_i = 1 if dry else 0
    try:
        with db() as c:
            row = c.execute(
                "SELECT MIN(x) FROM ("
                "SELECT MIN(r.resolved_ts) AS x FROM resolutions r "
                "JOIN orders o ON o.condition_id=r.condition_id AND o.dry_run=? "
                "UNION ALL "
                "SELECT MIN(ts) FROM orders WHERE dry_run=? AND side LIKE 'SELL_%')",
                (dry_i, dry_i)).fetchone()
        first_ts = float(row[0]) if row and row[0] else None
    except Exception:
        first_ts = None
    today_start = store.local_day_start_ts()
    first_day = store.local_day_start_ts(first_ts) if first_ts else today_start
    span = min(120, int((today_start - first_day) // 86400.0) + 1)
    rows_out: list[dict[str, Any]] = []
    for k in range(span):
        day_start = today_start - k * 86400.0
        key = f"{lane}:{int(day_start)}"
        if k > 0 and key in _pnl_daily_cache:
            summary = _pnl_daily_cache[key]
        else:
            summary = store.realized_pnl_summary_today(
                dry, cutoff=day_start, end=day_start + 86400.0)
            if k > 0:  # finished trading days never change
                _pnl_daily_cache[key] = summary
        wins = int(summary.get("wins") or 0)
        losses = int(summary.get("losses") or 0)
        pnl = float(summary.get("realized_usd") or 0.0)
        if wins == 0 and losses == 0 and abs(pnl) < 1e-9:
            continue
        rows_out.append({
            "day": time.strftime("%Y-%m-%d", time.gmtime(day_start + store.TRADING_DAY_UTC_OFFSET_HOURS * 3600.0)),
            "pnl_usd": round(pnl, 4), "wins": wins, "losses": losses,
        })
    total_days = len(rows_out)
    rows_out = rows_out[offset:offset + limit]
    if lane == "paper":
        capital = float(getattr(cfg, "paper_equity_usd", 100.0))
    else:
        capital = float(_state.get("balance_pusd") or 0.0)
    return {"lane": lane, "rows": rows_out, "total_days": total_days,
            "offset": offset, "limit": limit,
            "capital_base_usd": round(capital, 4)}'''


def patch_store(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    if "end_ts = float(\"inf\")" in src:
        return "already patched"
    for i, a in enumerate((S_DEF_OLD, S_CUT_OLD, S_EXIT_OLD, S_RES_OLD)):
        if src.count(a) != 1:
            return f"ABORT anchor #{i} count={src.count(a)}"
    src = src.replace(S_DEF_OLD, S_DEF_NEW, 1)
    src = src.replace(S_CUT_OLD, S_CUT_NEW, 1)
    src = src.replace(S_EXIT_OLD, S_EXIT_NEW, 1)
    src = src.replace(S_RES_OLD, S_RES_NEW, 1)
    path.write_text(src, encoding="utf-8")
    return "patched OK"


def patch_dashboard(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    if "_pnl_daily_cache" in src:
        return "already patched"
    start = src.find(DASH_START)
    if start < 0:
        return "ABORT start anchor missing"
    end = src.find(DASH_END, start)
    if end < 0:
        return "ABORT end anchor missing"
    end += len(DASH_END)
    src = src[:start] + DASH_NEW + src[end:]
    path.write_text(src, encoding="utf-8")
    return "patched OK"


def main() -> int:
    root = Path(sys.argv[1])
    r1 = patch_store(root / "bot" / "store.py")
    print("store.py:", r1)
    r2 = patch_dashboard(root / "server" / "dashboard.py")
    print("dashboard.py:", r2)
    ok = all(("OK" in r or "already" in r) for r in (r1, r2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
