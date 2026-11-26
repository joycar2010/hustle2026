"""In-place patch #4: WebSocket state push + eth_signal error debounce.

- /api/ws/state pushes the exact GET /api/state payload every ~350ms per
  connected client; REST stays as the fallback transport.
- Transient ETH feed hiccups no longer red-flag the UI: the error surfaces
  only after 30s of continuous failure (one bad poll self-heals silently).

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard4.py <path>
"""
from __future__ import annotations

import sys

E = []

# 1) fastapi imports gain WebSocket types
E.append((
    "from fastapi import FastAPI, HTTPException, Query, Request",
    "from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect",
))

# 2) success-timestamp global for the debounce
E.append((
    "async def poll_eth_signal_loop():",
    '_eth_signal_ok = {"ts": 0.0}\n\n\nasync def poll_eth_signal_loop():',
))

# 3) record success time next to the error self-clear
E.append((
    '            _state["errors"].pop("eth_signal", None)',
    '            _state["errors"].pop("eth_signal", None)\n'
    '            _eth_signal_ok["ts"] = time.time()',
))

# 4) debounced error surfacing
E.append((
    '        except Exception as e:\n'
    '            _state["eth_signal"] = None\n'
    '            _state["errors"]["eth_signal"] = str(e)',
    '        except Exception as e:\n'
    '            _state["eth_signal"] = None\n'
    '            # Debounce transient feed hiccups: surface only after 30s of\n'
    '            # continuous failure so one bad poll cannot red-flag the UI.\n'
    '            if time.time() - _eth_signal_ok["ts"] > 30.0:\n'
    '                _state["errors"]["eth_signal"] = str(e)',
))

# 5) websocket endpoint in front of the REST route it mirrors
E.append((
    '@app.get("/api/state")',
    '@app.websocket("/api/ws/state")\n'
    'async def ws_state(websocket: WebSocket):\n'
    '    """Push the GET /api/state payload every ~350ms over one socket.\n'
    '\n'
    '    REST stays available as the fallback transport; both serialize the\n'
    '    same dict, so the UI can switch channels without translation."""\n'
    '    await websocket.accept()\n'
    '    try:\n'
    '        while True:\n'
    '            payload = await asyncio.to_thread(state)\n'
    '            await websocket.send_text(json.dumps(payload, default=str))\n'
    '            await asyncio.sleep(0.35)\n'
    '    except (WebSocketDisconnect, ConnectionError, RuntimeError):\n'
    '        return\n'
    '\n'
    '\n'
    '@app.get("/api/state")',
))


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "/api/ws/state" in src:
        print("already patched; nothing to do")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT: anchor #{i} count={src.count(old)} (need 1): {old[:60]!r}")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
