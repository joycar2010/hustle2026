"""In-place patch #11: micro-caches for the three hot snapshots + 0.25s grid.

Profiling showed state() at ~1.13s -- over the 1.0s grid budget, so the
producer was skipping ticks (the 2s stalls the decision log showed).  The
cost sat in three per-frame re-reads that change on second-scale at most:
_agent_status_snapshot (263ms, heartbeat file + pid probe),
_llm_settings_response (227ms x2 calls, .env re-parse),
_service_status_snapshot (217ms, pid files + os.kill).  TTL wrappers cut
state() to ~100-200ms, after which the publish grid tightens to 0.25s.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard11.py <path>
"""
from __future__ import annotations

import sys

CACHE_BLOCK = '''

# ---- patch11: TTL micro-caches over second-scale snapshots ----------------
# These wrap the module-level names; every call site resolves through module
# globals at runtime, so reassignment here covers state() and the WS producer.
_snap_cache: dict[str, tuple[float, Any]] = {}


def _snap_cached(name: str, ttl: float, fn):
    def wrapper(*args, **kwargs):
        now = time.monotonic()
        hit = _snap_cache.get(name)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
        value = fn(*args, **kwargs)
        _snap_cache[name] = (now, value)
        return value
    return wrapper


_service_status_snapshot = _snap_cached("service", 1.0, _service_status_snapshot)
_agent_status_snapshot = _snap_cached("agents", 0.5, _agent_status_snapshot)
_llm_settings_response = _snap_cached("llm_settings", 2.0, _llm_settings_response)
'''

E = [
    # tighter publish grid
    ("    next_tick = time.monotonic() + 1.0",
     "    next_tick = time.monotonic() + 0.25"),
    ("        while next_tick <= now:  # overran the budget: skip missed grid points\n"
     "            next_tick += 1.0",
     "        while next_tick <= now:  # overran the budget: skip missed grid points\n"
     "            next_tick += 0.25"),
    ("        await asyncio.sleep(next_tick - now)\n        next_tick += 1.0",
     "        await asyncio.sleep(next_tick - now)\n        next_tick += 0.25"),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_snap_cached" in src:
        print("already patched; nothing to do")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT: anchor #{i} count={src.count(old)} (need 1)")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    src = src.rstrip("\n") + "\n" + CACHE_BLOCK
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
