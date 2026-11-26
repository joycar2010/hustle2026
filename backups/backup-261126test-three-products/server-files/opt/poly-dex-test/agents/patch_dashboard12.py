"""In-place patch #12: stale-while-revalidate snapshot caches.

Patch #11's TTL caches recomputed synchronously on expiry, so every cache
turnover frame paid the full snapshot cost and skipped one 0.25s grid slot
(the residual 0.5s spikes).  SWR returns the stale value immediately and
refreshes in a background thread, keeping state() flat ~15ms every frame.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard12.py <path>
"""
from __future__ import annotations

import sys

OLD = '''_snap_cache: dict[str, tuple[float, Any]] = {}


def _snap_cached(name: str, ttl: float, fn):
    def wrapper(*args, **kwargs):
        now = time.monotonic()
        hit = _snap_cache.get(name)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
        value = fn(*args, **kwargs)
        _snap_cache[name] = (now, value)
        return value
    return wrapper'''

NEW = '''_snap_cache: dict[str, tuple[float, Any]] = {}
_snap_refreshing: set[str] = set()


def _snap_cached(name: str, ttl: float, fn):
    """Stale-while-revalidate: expiry returns the old value instantly and a
    background thread refreshes, so no frame ever pays the snapshot cost."""
    import threading

    def refresh(args, kwargs):
        try:
            value = fn(*args, **kwargs)
            _snap_cache[name] = (time.monotonic(), value)
        except Exception:
            pass  # keep serving the stale value
        finally:
            _snap_refreshing.discard(name)

    def wrapper(*args, **kwargs):
        now = time.monotonic()
        hit = _snap_cache.get(name)
        if hit is None:
            value = fn(*args, **kwargs)  # first call only: compute inline
            _snap_cache[name] = (time.monotonic(), value)
            return value
        if now - hit[0] >= ttl and name not in _snap_refreshing:
            _snap_refreshing.add(name)
            threading.Thread(target=refresh, args=(args, kwargs), daemon=True).start()
        return hit[1]
    return wrapper'''


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_snap_refreshing" in src:
        print("already patched; nothing to do")
        return 0
    if src.count(OLD) != 1:
        print(f"ABORT: anchor count={src.count(OLD)} (need 1)")
        return 2
    open(path, "w", encoding="utf-8").write(src.replace(OLD, NEW, 1))
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
