"""In-place patch #20: per-asset breakdown rides the lot accounting itself.

store.realized_pnl_summary_today now tags each buy lot with its asset and
returns a `by_asset` aggregation of the SAME lot_pnl map that produces the
headline numbers -- so the asset cards, the KPIs and the daily history are
three views of one computation.  The dashboard's entry-attribution helper
(_asset_lane_pnl) is retired from the payload path.

Usage:  python3 patch_dashboard20.py <app_root>
"""
from __future__ import annotations

import sys
from pathlib import Path

S1_OLD = '''        buys = c.execute(
            "SELECT id, ts, condition_id, token_id, side, size, price "
            "FROM orders "'''
S1_NEW = '''        buys = c.execute(
            "SELECT id, ts, condition_id, token_id, side, size, price, "
            "COALESCE(asset,'BTC') AS asset "
            "FROM orders "'''

S2_OLD = '''            "price": float(row["price"] or 0.0),
        }'''
S2_NEW = '''            "price": float(row["price"] or 0.0),
            "asset": str(row["asset"] or "BTC"),
        }'''

S3_OLD = '''    wins = sum(1 for pnl in lot_pnl_today.values() if pnl >= 0)
    losses = sum(1 for pnl in lot_pnl_today.values() if pnl < 0)'''
S3_NEW = '''    wins = sum(1 for pnl in lot_pnl_today.values() if pnl >= 0)
    losses = sum(1 for pnl in lot_pnl_today.values() if pnl < 0)
    by_asset: dict[str, dict] = {}
    for lot_id, pnl in lot_pnl_today.items():
        asset = buy_lots[lot_id]["asset"]
        bucket = by_asset.setdefault(
            asset, {"realized_usd": 0.0, "wins": 0, "losses": 0})
        bucket["realized_usd"] += pnl
        if pnl >= 0:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
    for bucket in by_asset.values():
        bucket["realized_usd"] = round(bucket["realized_usd"], 4)'''

S4_OLD = '        "period_start_ts": cutoff,'
S4_NEW = ('        "period_start_ts": cutoff,\n'
          '        "by_asset": by_asset,')

D_OLD = '''    by_asset = _asset_lane_pnl(float(paper.get("period_start_ts") or 0.0))
    paper["by_asset"] = by_asset.get("paper", {})
    live["by_asset"] = by_asset.get("live", {})'''
D_NEW = '''    # by_asset now arrives inside the store summaries themselves (lot
    # accounting, patch #20); the entry-attribution helper is retired from
    # this path so cards and KPIs are views of one computation.
    paper.setdefault("by_asset", {})
    live.setdefault("by_asset", {})'''


def patch(path: Path, edits, marker: str) -> str:
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
               [(S1_OLD, S1_NEW), (S2_OLD, S2_NEW), (S3_OLD, S3_NEW), (S4_OLD, S4_NEW)],
               '"by_asset": by_asset,')
    print("store.py:", r1)
    r2 = patch(root / "server" / "dashboard.py", [(D_OLD, D_NEW)],
               "retired from")
    print("dashboard.py:", r2)
    ok = all(("OK" in r or "already" in r) for r in (r1, r2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
