"""In-place patch #18: trading-day boundary = Beijing midnight (UTC+8).

The server runs UTC, so "today" flipped 8 hours late for the operator.  The
single choke point store.local_day_start_ts() now derives the day from a
configurable TRADING_DAY_UTC_OFFSET_HOURS (default 8 = Asia/Shanghai), which
simultaneously moves: the dashboard's today-KPIs, mode_split/by_asset period,
AND the worker's daily loss/profit gates (shared accounting basis by design).
The /api/pnl/daily grouping shifts by the same offset so history rows align.

Usage:  python3 patch_dashboard18.py <app_root>
"""
from __future__ import annotations

import sys
from pathlib import Path

STORE_OLD = '''def local_day_start_ts(now: Optional[float] = None) -> float:
    """Start of the local calendar day used by the dashboard and risk gate."""
    local_now = datetime.fromtimestamp(now if now is not None else time.time())
    return datetime.combine(local_now.date(), dt_time.min).timestamp()'''

STORE_NEW = '''TRADING_DAY_UTC_OFFSET_HOURS = float(os.environ.get("TRADING_DAY_UTC_OFFSET_HOURS", "8"))


def local_day_start_ts(now: Optional[float] = None) -> float:
    """Start of the current TRADING day (Beijing/UTC+8 by default).

    This is the shared boundary for the dashboard's today-KPIs and the
    worker's daily loss/profit gates; tune via TRADING_DAY_UTC_OFFSET_HOURS.
    The host clock stays UTC -- only the accounting day shifts."""
    offset = TRADING_DAY_UTC_OFFSET_HOURS * 3600.0
    ts = now if now is not None else time.time()
    return ((ts + offset) // 86400.0) * 86400.0 - offset'''

DASH_MARK = '@app.get("/api/pnl/daily")'
DASH_SHIFT = ('_TRADING_DAY_SHIFT = int(float(os.environ.get('
              '"TRADING_DAY_UTC_OFFSET_HOURS", "8")) * 3600)\n\n\n'
              '@app.get("/api/pnl/daily")')
DASH_OLD1 = '"SELECT COUNT(DISTINCT date(r.resolved_ts,\'unixepoch\')) "'
DASH_NEW1 = 'f"SELECT COUNT(DISTINCT date(r.resolved_ts + {_TRADING_DAY_SHIFT}, \'unixepoch\')) "'
DASH_OLD2 = '"SELECT date(r.resolved_ts,\'unixepoch\') AS day, "'
DASH_NEW2 = 'f"SELECT date(r.resolved_ts + {_TRADING_DAY_SHIFT}, \'unixepoch\') AS day, "'


def patch(path: Path, edits: list[tuple[str, str]], marker: str) -> str:
    src = path.read_text(encoding="utf-8")
    if marker in src:
        return "already patched"
    for i, (old, _new) in enumerate(edits):
        if src.count(old) != 1:
            return f"ABORT anchor #{i} count={src.count(old)}"
    for old, new in edits:
        src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    return "patched OK"


def main() -> int:
    root = Path(sys.argv[1])
    r1 = patch(root / "bot" / "store.py",
               [(STORE_OLD, STORE_NEW)], "TRADING_DAY_UTC_OFFSET_HOURS")
    print("store.py:", r1)
    r2 = patch(root / "server" / "dashboard.py",
               [(DASH_MARK, DASH_SHIFT), (DASH_OLD1, DASH_NEW1), (DASH_OLD2, DASH_NEW2)],
               "_TRADING_DAY_SHIFT")
    print("dashboard.py:", r2)
    return 0 if ("OK" in r1 or "already" in r1) and ("OK" in r2 or "already" in r2) else 2


if __name__ == "__main__":
    raise SystemExit(main())
