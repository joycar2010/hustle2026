"""In-place patch #6: paper position rows + per-asset lane PnL.

- `paper_positions`: the actual unresolved dry-run entries behind the paper
  open-value number, so the positions modal can show real rows (stale
  windows included -- the UI labels them instead of hiding them).
- `mode_split.*.by_asset`: today's settled entry PnL per asset per lane,
  computed against the same period start as the headline pnl, so the asset
  cards stop deriving numbers from the 30-order response window.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard6.py <path>
"""
from __future__ import annotations

import sys

HELPER = '''

_paper_positions_cache: dict[str, Any] = {"ts": 0.0, "rows": []}


def _paper_positions() -> list[dict[str, Any]]:
    """Unresolved dry-run entries (the rows behind the paper open value)."""
    now = time.time()
    if now - _paper_positions_cache["ts"] > 2.0:
        rows: list[dict[str, Any]] = []
        try:
            with db() as c:
                for r in c.execute(
                    "SELECT ts, market_slug, COALESCE(asset,'BTC') AS asset, side, "
                    "size, price FROM orders o WHERE o.dry_run=1 AND o.status='dry_run' "
                    "AND o.side IN ('UP','DOWN') AND NOT EXISTS "
                    "(SELECT 1 FROM resolutions r WHERE r.condition_id=o.condition_id) "
                    "ORDER BY ts DESC LIMIT 50"
                ):
                    ts, slug, asset, side, size, price = r
                    rows.append({
                        "ts": ts, "market_slug": slug, "asset": asset,
                        "side": side, "size": size, "price": price,
                        "notional_usd": round((size or 0) * (price or 0), 4),
                    })
        except Exception:
            rows = _paper_positions_cache["rows"]
        _paper_positions_cache.update(ts=now, rows=rows)
    return _paper_positions_cache["rows"]


_asset_pnl_cache: dict[str, Any] = {"ts": 0.0, "key": None, "value": {}}


def _asset_lane_pnl(period_start: float) -> dict[str, dict[str, Any]]:
    """Settled ENTRY PnL per (lane, asset) since period_start.

    Entry-order scope (exits excluded), matching backtest attribution; the
    headline pnl stays the canonical store number -- this powers the per-
    asset cards only."""
    now = time.time()
    if now - _asset_pnl_cache["ts"] > 5.0 or _asset_pnl_cache["key"] != int(period_start):
        out: dict[str, dict[str, Any]] = {"paper": {}, "live": {}}
        try:
            with db() as c:
                for r in c.execute(
                    "SELECT COALESCE(o.asset,'BTC'), o.dry_run, o.side, o.token_id, "
                    "o.size, o.price, o.filled_size, o.status, r.winning_token "
                    "FROM orders o JOIN resolutions r ON r.condition_id=o.condition_id "
                    "WHERE r.resolved_ts >= ? AND o.side IN ('UP','DOWN') "
                    "AND o.status IN ('filled','matched','dry_run')",
                    (period_start,),
                ):
                    asset, dry, _side, tok, size, price, filled, status, win_tok = r
                    if not price or not (0 < price < 1):
                        continue
                    if status in ("filled", "matched"):
                        stake = filled or (size or 0) * price  # USD notional
                        shares = stake / price
                    else:
                        shares = size or 0.0
                        stake = shares * price
                    if shares <= 0:
                        continue
                    lane = "paper" if dry else "live"
                    a = out[lane].setdefault(asset, {"realized_usd": 0.0, "wins": 0, "losses": 0})
                    if tok == win_tok:
                        a["realized_usd"] += shares * (1 - price)
                        a["wins"] += 1
                    else:
                        a["realized_usd"] -= stake
                        a["losses"] += 1
            for lane in out.values():
                for a in lane.values():
                    a["realized_usd"] = round(a["realized_usd"], 4)
        except Exception:
            out = _asset_pnl_cache["value"]
        _asset_pnl_cache.update(ts=now, key=int(period_start), value=out)
    return _asset_pnl_cache["value"]
'''

E = [
    # helpers ride behind the paper-open-stats block from patch #2
    ('    return _paper_open_cache["n"], _paper_open_cache["usd"]',
     '    return _paper_open_cache["n"], _paper_open_cache["usd"]' + HELPER),
    # attach by_asset inside _mode_split and expose paper position rows
    ('    return {"paper": paper, "live": live}',
     '    by_asset = _asset_lane_pnl(float(paper.get("period_start_ts") or 0.0))\n'
     '    paper["by_asset"] = by_asset.get("paper", {})\n'
     '    live["by_asset"] = by_asset.get("live", {})\n'
     '    return {"paper": paper, "live": live}'),
    ('        "mode_split": _mode_split(),',
     '        "mode_split": _mode_split(),\n'
     '        "paper_positions": _paper_positions(),'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_paper_positions" in src:
        print("already patched; nothing to do")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT: anchor #{i} count={src.count(old)} (need 1)")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
