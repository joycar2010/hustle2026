"""In-place patch #9: producer/consumer WS framing (flat 1s cadence).

Patch #8 rebuilt the frame inside the send path, so the rebuild tick carried
state()'s ~0.5s compute and the drift-corrected sleep then shortened the
next tick: a 1.4s/0.5s sawtooth.  This patch decouples them: one lazily
started producer task rebuilds the frame on a drift-corrected 1.0s schedule
and flips a fresh asyncio.Event per frame; sockets just await the event and
send the cached text, so every client sees a flat ~1.0s cadence regardless
of compute time or client count.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard9.py <path>
"""
from __future__ import annotations

import sys

OLD = '''_ws_frame: dict[str, Any] = {"ts": 0.0, "text": ""}
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

NEW = '''_ws_frame: dict[str, Any] = {"text": "", "event": None}
_ws_producer_task: "asyncio.Task | None" = None


async def _ws_produce_loop() -> None:
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
        await asyncio.sleep(max(0.05, 1.0 - (time.monotonic() - started)))


@app.websocket("/api/ws/state")
async def ws_state(websocket: WebSocket):
    """Push the shared state frame at a flat ~1s cadence.

    A single producer task (started lazily with the first socket) rebuilds
    the frame; sockets only await the new-frame event and send the cached
    text, so compute time and client count never distort the tick.
    GET /api/state remains the fallback transport."""
    global _ws_producer_task
    await websocket.accept()
    if _ws_producer_task is None or _ws_producer_task.done():
        if _ws_frame["event"] is None:
            _ws_frame["event"] = asyncio.Event()
        _ws_producer_task = asyncio.create_task(_ws_produce_loop())
    try:
        if _ws_frame["text"]:
            await websocket.send_text(_ws_frame["text"])
        while True:
            event = _ws_frame["event"]
            await event.wait()
            await websocket.send_text(_ws_frame["text"])
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return'''


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_ws_produce_loop" in src:
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
