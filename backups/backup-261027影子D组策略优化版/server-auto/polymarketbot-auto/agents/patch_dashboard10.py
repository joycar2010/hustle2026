"""In-place patch #10: publish WS frames ON a fixed 1.0s grid.

Patch #9's producer slept `1 - this_compute`, so the client-visible interval
became (1 - C_i) + C_{i+1}: state()'s compute variance leaked straight into
cadence (0.7-1.3s wobble).  Now compute runs BETWEEN ticks and the event
flip lands exactly on a monotonic 1.0s grid; variance moves frame latency
(bounded by 1s) but never spacing.  Overruns skip to the next grid point.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard10.py <path>
"""
from __future__ import annotations

import sys

OLD = '''async def _ws_produce_loop() -> None:
    """Rebuild the shared frame on a drift-corrected 1.0s schedule."""
    while True:
        started = time.monotonic()
        try:
            payload = await asyncio.to_thread(state)
            text = json.dumps(payload, default=str)
        except Exception:
            text = _ws_frame["text"]  # keep pushing the last good frame
        prev_event = _ws_frame["event"]
        _ws_frame["text"] = text
        _ws_frame["event"] = asyncio.Event()
        if prev_event is not None:
            prev_event.set()  # wake every socket waiting on this frame
        await asyncio.sleep(max(0.05, 1.0 - (time.monotonic() - started)))'''

NEW = '''async def _ws_produce_loop() -> None:
    """Publish frames ON a fixed 1.0s monotonic grid.

    Compute happens between ticks; the event flip (which sets the spacing
    every client sees) lands exactly on the grid, so compute-time variance
    becomes bounded latency instead of cadence jitter."""
    next_tick = time.monotonic() + 1.0
    while True:
        try:
            payload = await asyncio.to_thread(state)
            text = json.dumps(payload, default=str)
        except Exception:
            text = _ws_frame["text"]  # keep pushing the last good frame
        now = time.monotonic()
        while next_tick <= now:  # overran the budget: skip missed grid points
            next_tick += 1.0
        await asyncio.sleep(next_tick - now)
        next_tick += 1.0
        prev_event = _ws_frame["event"]
        _ws_frame["text"] = text
        _ws_frame["event"] = asyncio.Event()
        if prev_event is not None:
            prev_event.set()'''


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "fixed 1.0s monotonic grid" in src:
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
