"""In-place patch #2 for dashboard.py: mode-aware KPIs + slow-loop extras.

Fixes the paper-instance blind spot (PnL/exposure computed live-only while
bot.mode=paper => permanent zeros) and exposes pending agent proposals plus
the latest desk digest for the UI toast layer.  Anchored, uniqueness-checked,
idempotent.  Usage:  python3 patch_dashboard2.py <path>
"""
from __future__ import annotations

import sys

HELPERS = '''_paper_open_cache: dict[str, Any] = {"ts": 0.0, "n": 0, "usd": 0.0}


def _paper_open_stats() -> tuple[int, float]:
    """Open (unresolved) paper entries: count and notional, 2s cached."""
    now = time.time()
    if now - _paper_open_cache["ts"] > 2.0:
        n, usd = 0, 0.0
        try:
            with db() as c:
                row = c.execute(
                    "SELECT COUNT(*), COALESCE(SUM(COALESCE(size,0)*COALESCE(price,0)),0) "
                    "FROM orders o WHERE o.dry_run=1 AND o.status='dry_run' "
                    "AND o.side IN ('UP','DOWN') AND NOT EXISTS "
                    "(SELECT 1 FROM resolutions r WHERE r.condition_id=o.condition_id)"
                ).fetchone()
            if row:
                n, usd = int(row[0] or 0), float(row[1] or 0.0)
        except Exception:
            pass
        _paper_open_cache.update(ts=now, n=n, usd=round(usd, 4))
    return _paper_open_cache["n"], _paper_open_cache["usd"]


_slow_loop_cache: dict[str, Any] = {"key": None, "value": {}}


def _slow_loop_extras() -> dict[str, Any]:
    """Pending agent proposals + latest desk digest, mtime-cached."""
    props_path = ROOT / "agents" / "out" / "proposals.jsonl"
    dig_path = ROOT / "agents" / "out" / "digests.jsonl"
    try:
        key = (props_path.stat().st_mtime if props_path.exists() else 0,
               dig_path.stat().st_mtime if dig_path.exists() else 0)
    except OSError:
        key = (0, 0)
    if _slow_loop_cache["key"] == key:
        return _slow_loop_cache["value"]
    proposals, digest = [], None
    try:
        if props_path.exists():
            latest: dict[str, dict] = {}
            for line in props_path.read_text(encoding="utf-8").strip().splitlines()[-40:]:
                try:
                    p = json.loads(line)
                except ValueError:
                    continue
                if p.get("status") == "PENDING_HUMAN":
                    latest[str(p.get("key")) + ":" + str(p.get("proposed"))] = p
            proposals = sorted(latest.values(), key=lambda p: -float(p.get("ts") or 0))[:6]
        if dig_path.exists():
            tail = dig_path.read_text(encoding="utf-8").strip().splitlines()
            if tail:
                d = json.loads(tail[-1])
                digest = {k: d.get(k) for k in (
                    "period", "reviews", "total_pnl_usd", "win_rate", "consensus", "ts")}
    except (OSError, ValueError):
        pass
    value = {"proposals": proposals, "digest": digest}
    _slow_loop_cache.update(key=key, value=value)
    return value


'''

EDITS = [
    # 1) mode-aware PnL (the root cause)
    ("    return realized_pnl_summary_today(False)",
     "    return realized_pnl_summary_today(_state.get(\"bot_mode\") != \"live\")"),
    # 2) helpers inserted before the risk snapshot block
    ("_resolved_cache: dict[str, Optional[str]] = {}",
     HELPERS + "_resolved_cache: dict[str, Optional[str]] = {}"),
    # 3) paper-aware position count/value in the risk snapshot
    ('        "position_count": len(positions),',
     '        "position_count": len(positions) if _state.get("bot_mode") == "live" '
     'else (len(positions) or _paper_open_stats()[0]),'),
    ('        "position_value_usd": round(position_value, 4),',
     '        "position_value_usd": round(position_value, 4) if _state.get("bot_mode") == "live" '
     'else round(position_value or _paper_open_stats()[1], 4),'),
    # 4) paper-aware wallet holdings value (KPI strip)
    ('            "value_usd": _state.get("value_usd"),',
     '            "value_usd": _state.get("value_usd") if _state.get("bot_mode") == "live" '
     'else (_state.get("value_usd") or _paper_open_stats()[1]),'),
    # 5) expose slow-loop extras to the UI
    ('        "pnl": pnl,',
     '        "pnl": pnl,\n        "slow_loop": _slow_loop_extras(),'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_slow_loop_extras" in src:
        print("already patched; nothing to do")
        return 0
    for old, _ in EDITS:
        if src.count(old) != 1:
            print(f"ABORT: anchor count={src.count(old)} (need 1): {old[:60]!r}")
            return 2
    for old, new in EDITS:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
