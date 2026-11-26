"""In-place patch #21: per-asset filter on the daily PnL history.

/api/pnl/daily gains `asset=` (BTC/ETH/WEATHER/SPORTS): rows are then drawn
from each day's lot-accounted by_asset bucket (patch #20) instead of the
lane headline -- same computation, narrower view, so the period selectors on
the weather/sports panels stay on the unified accounting basis.

Usage:  python3 patch_dashboard21.py <dashboard.py>
"""
from __future__ import annotations

import sys

SIG_OLD = 'def pnl_daily(lane: str = "paper", offset: int = 0, limit: int = 14):'
SIG_NEW = 'def pnl_daily(lane: str = "paper", offset: int = 0, limit: int = 14, asset: str = ""):'

ROWS_OLD = '''        wins = int(summary.get("wins") or 0)
        losses = int(summary.get("losses") or 0)
        pnl = float(summary.get("realized_usd") or 0.0)'''
ROWS_NEW = '''        if asset:
            bucket = (summary.get("by_asset") or {}).get(asset.upper()) or {}
            wins = int(bucket.get("wins") or 0)
            losses = int(bucket.get("losses") or 0)
            pnl = float(bucket.get("realized_usd") or 0.0)
        else:
            wins = int(summary.get("wins") or 0)
            losses = int(summary.get("losses") or 0)
            pnl = float(summary.get("realized_usd") or 0.0)'''

RET_OLD = '    return {"lane": lane, "rows": rows_out, "total_days": total_days,'
RET_NEW = '    return {"lane": lane, "asset": asset.upper(), "rows": rows_out, "total_days": total_days,'


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if 'asset: str = ""' in src:
        print("already patched")
        return 0
    for i, a in enumerate((SIG_OLD, ROWS_OLD, RET_OLD)):
        if src.count(a) != 1:
            print(f"ABORT anchor #{i} count={src.count(a)}")
            return 2
    src = src.replace(SIG_OLD, SIG_NEW, 1)
    src = src.replace(ROWS_OLD, ROWS_NEW, 1)
    src = src.replace(RET_OLD, RET_NEW, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
