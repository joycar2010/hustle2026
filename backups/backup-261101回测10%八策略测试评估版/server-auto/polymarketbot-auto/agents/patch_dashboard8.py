"""In-place patch #8: stable 1s shared-frame WS broadcast.

Replaces the per-client compute loop (state() per socket every 0.35s, whose
variable cost made the cadence jitter and multiplied with client count) with
a shared frame: state() is serialized at most once per second behind an
asyncio lock, every socket sends that cached frame, and the per-socket sleep
is drift-corrected to a clean 1.0s tick.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard8.py <path>
"""
from __future__ import annotations

import sys

OLD = '''@app.websocket("/api/ws/state")
async def ws_state(websocket: WebSocket):
    """Push the GET /api/state payload every ~350ms over one socket.

    REST stays available as the fallback transport; both serialize the
    same dict, so the UI can switch channels without translation."""
    await websocket.accept()
    try:
        while True:
            payload = await asyncio.to_thread(state)
            await websocket.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(0.35)
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return'''

NEW = '''_ws_frame: dict[str, Any] = {"ts": 0.0, "text": ""}
_ws_frame_lock: "asyncio.Lock | None" = None


async def _ws_current_frame() -> str:
    """Serialize state() at most once per second, shared by all sockets."""
    global _ws_frame_lock
    if _ws_frame_lock is None:
        _ws_frame_lock = asyncio.Lock()
    if time.monotonic() - _ws_frame["ts"] < 0.9 and _ws_frame["text"]:
        return _ws_frame["text"]
    async with _ws_frame_lock:
        if time.monotonic() - _ws_frame["ts"] < 0.9 and _ws_frame["text"]:
            return _ws_frame["text"]
        payload = await asyncio.to_thread(state)
        _ws_frame["text"] = json.dumps(payload, default=str)
        _ws_frame["ts"] = time.monotonic()
        return _ws_frame["text"]


@app.websocket("/api/ws/state")
async def ws_state(websocket: WebSocket):
    """Push the state frame on a stable 1s cadence over one socket.

    The frame is computed once per second and SHARED across sockets, so
    client count cannot stretch the tick and the cadence stays flat;
    GET /api/state remains the fallback transport."""
    await websocket.accept()
    try:
        while True:
            tick = time.monotonic()
            await websocket.send_text(await _ws_current_frame())
            await asyncio.sleep(max(0.05, 1.0 - (time.monotonic() - tick)))
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return'''


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_ws_current_frame" in src:
        print("already patched; nothing to do")
        return 0
    if src.count(OLD) != 1:
        print(f"ABORT: handler anchor count={src.count(OLD)} (need 1)")
        return 2
    open(path, "w", encoding="utf-8").write(src.replace(OLD, NEW, 1))
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
