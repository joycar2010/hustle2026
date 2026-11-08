"""In-place patch #22: consensus opinion history + Beijing-day event counts.

- GET /api/consensus/history: paginated primary/secondary opinions from the
  desk digests (agents/out/digests.jsonl), newest first, mtime-cached.
- `today_counts` in the state payload: decisions/orders counted from the
  Beijing trading-day start (store.local_day_start_ts), so the OpenClaw
  cards' event figures reset at 00:00 Beijing instead of growing forever.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard22.py <dashboard.py>
"""
from __future__ import annotations

import sys

BLOCK = '''_consensus_hist_cache: dict[str, Any] = {"key": None, "rows": []}


@app.get("/api/consensus/history")
def consensus_history(offset: int = 0, limit: int = 10):
    """Primary vs secondary model opinions per desk cycle, newest first."""
    offset = max(0, min(int(offset), 5000))
    limit = max(1, min(int(limit), 50))
    path = ROOT / "agents" / "out" / "digests.jsonl"
    try:
        key = path.stat().st_mtime
    except OSError:
        key = None
    if _consensus_hist_cache["key"] != key:
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                c = d.get("consensus")
                if not c:
                    continue
                # Agreement = the two model TEXTS actually match on a
                # trade token, not merely the arbiter reason string (which
                # has produced "一致" rows over disagreeing BUY/HOLD text in
                # digests written before the two-step advisor flow landed).
                def _norm(t):
                    t = str(t or "").upper()
                    for tok in ("BUY", "SELL", "HOLD"):
                        if tok in t:
                            return tok
                    return ""
                _pt, _st = _norm(c.get("primary_text")), _norm(c.get("secondary_text"))
                _ag = bool(_pt) and _pt == _st
                rows.append({
                    "ts": d.get("ts"),
                    "decision": c.get("decision"),
                    "reason": c.get("reason"),
                    "agreed": _ag,
                    "primary_text": str(c.get("primary_text") or "")[:80],
                    "secondary_text": str(c.get("secondary_text") or "")[:80],
                    "reviews": d.get("reviews"),
                    "pnl_usd": d.get("total_pnl_usd"),
                })
        except OSError:
            rows = []
        rows.reverse()
        _consensus_hist_cache.update(key=key, rows=rows)
    rows = _consensus_hist_cache["rows"]
    return {"rows": rows[offset:offset + limit], "total": len(rows),
            "offset": offset, "limit": limit}


_today_counts_cache: dict[str, Any] = {"ts": 0.0, "value": {"decisions": 0, "orders": 0}}


def _today_counts() -> dict[str, Any]:
    """Beijing-trading-day decision/order counts for the agent cards, 5s cached."""
    now = time.monotonic()
    if now - _today_counts_cache["ts"] > 5.0:
        try:
            day_cutoff = store.local_day_start_ts()
            with db() as c:
                d = c.execute("SELECT COUNT(*) FROM decisions WHERE ts>=?", (day_cutoff,)).fetchone()[0]
                o = c.execute("SELECT COUNT(*) FROM orders WHERE ts>=?", (day_cutoff,)).fetchone()[0]
            _today_counts_cache["value"] = {"decisions": int(d), "orders": int(o),
                                            "since": day_cutoff}
        except Exception:
            pass
        _today_counts_cache["ts"] = now
    return _today_counts_cache["value"]


_pnl_daily_cache: dict[str, dict] = {}'''

E = [
    ("_pnl_daily_cache: dict[str, dict] = {}", BLOCK),
    ('        "feeds": _feeds_status(),',
     '        "feeds": _feeds_status(),\n        "today_counts": _today_counts(),'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_today_counts" in src:
        print("already patched")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT anchor #{i} count={src.count(old)}")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
