"""In-place patch #17: feeds observability in the state payload.

The kalshi loop was setting an internal key state() never exposed, so a
legitimately quiet feed looked like a dead one.  Adds a `feeds` block to
/api/state: kalshi scanned/quoted counters, odds-api remaining credits and
audit-match count, and the sports source class actually in use.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard17.py <path>
"""
from __future__ import annotations

import sys

HELPER = '''

_feeds_status_cache: dict[str, Any] = {"ts": 0.0, "value": {}}


def _feeds_status() -> dict[str, Any]:
    """External-feed health for the UI, 3s cached."""
    now = time.monotonic()
    if now - _feeds_status_cache["ts"] < 3.0:
        return _feeds_status_cache["value"]
    kalshi = dict(_state.get("kalshi_weather") or {})
    try:
        from bot.feeds.kalshi_weather import LAST_STATS
        kalshi.setdefault("scanned", LAST_STATS.get("scanned", 0))
        kalshi.setdefault("quoted", LAST_STATS.get("quoted", 0))
    except Exception:
        pass
    odds: dict[str, Any] = {
        "source": type(getattr(_sports_service, "data_source", None)).__name__,
    }
    try:
        budget_path = ROOT / "agents" / "out" / "odds_budget.json"
        if budget_path.exists():
            odds["remaining"] = json.loads(budget_path.read_text()).get("remaining")
        matches_path = ROOT / "agents" / "out" / "odds_matches.jsonl"
        odds["matches"] = sum(1 for _ in matches_path.open()) if matches_path.exists() else 0
        src = getattr(_sports_service, "data_source", None)
        cache = getattr(src, "_cache", None)
        if isinstance(cache, dict):
            odds["events_cached"] = sum(len(v[1]) for v in cache.values())
    except Exception:
        pass
    value = {"kalshi_weather": kalshi, "odds": odds}
    _feeds_status_cache.update(ts=now, value=value)
    return value
'''

E = [
    ('    return {"decisions": _ledger_totals_cache["decisions"],',
     None),  # placeholder replaced below with proper anchor handling
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_feeds_status" in src:
        print("already patched; nothing to do")
        return 0
    anchor_fn = '    return {"decisions": _ledger_totals_cache["decisions"],\n            "orders": _ledger_totals_cache["orders"]}'
    anchor_state = '        "slow_loop": _slow_loop_extras(),'
    for name, a in (("helper-pos", anchor_fn), ("state-line", anchor_state)):
        if src.count(a) != 1:
            print(f"ABORT: anchor {name} count={src.count(a)} (need 1)")
            return 2
    src = src.replace(anchor_fn, anchor_fn + HELPER, 1)
    src = src.replace(anchor_state,
                      anchor_state + '\n        "feeds": _feeds_status(),', 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
