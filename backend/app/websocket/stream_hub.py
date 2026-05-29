"""Stream Hub — channel-based pub/sub over existing WebSocket connections.

Usage:
    from app.websocket.stream_hub import stream_hub
    await stream_hub.publish('agent.status', {'mode': 'auto', ...})

Channel naming convention:
    agent.status           — global (admin view)
    agent.llm-stats        — global
    site.status            — public (announcements + maintenance)
    openclaw.toggle        — global
    user.accounts.{uid}    — per-user, server pins subscription by token
    user.fund-flow.{uid}   — per-user
    alerts.{uid}           — per-user
    alerts.global          — fan-out to all openclaw_enabled admins

Design notes:
  * The existing ConnectionManager owns the raw socket set.
  * StreamHub owns `{channel: Set[(websocket, user_id)]}` subscriptions.
  * publish() is fire-and-forget. Client must `subscribe` first to receive.
  * Per-user channels require the server to validate ownership on subscribe
    — see websocket.py dispatcher which rejects subs for other users' uids.
  * Throttling: same-channel publishes within THROTTLE_MS keep only the
    latest payload (important for per-tick account updates).
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, Set, Tuple, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

THROTTLE_MS = 500  # max one publish per channel per 500ms (latest wins)


class StreamHub:
    def __init__(self):
        # channel -> set of (websocket, user_id)
        self._subs: Dict[str, Set[Tuple[WebSocket, Optional[str]]]] = {}
        # channel -> last payload (for snapshot replay on subscribe)
        self._snapshots: Dict[str, Any] = {}
        # channel -> last publish monotonic ms (throttle)
        self._last_pub_ms: Dict[str, float] = {}
        # channel -> pending deferred payload (for throttled coalescing)
        self._pending: Dict[str, Any] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # ─────────── subscription ───────────
    async def subscribe(self, ws: WebSocket, channel: str, user_id: Optional[str] = None) -> None:
        async with self._lock:
            self._subs.setdefault(channel, set()).add((ws, user_id))
            snap = self._snapshots.get(channel)
        # Replay last known snapshot immediately (catch-up semantics)
        if snap is not None:
            try:
                await ws.send_json({"type": "stream", "channel": channel, "payload": snap, "snapshot": True})
            except Exception as e:
                logger.debug(f"[stream_hub] snapshot replay failed: {e}")

    async def unsubscribe(self, ws: WebSocket, channel: str, user_id: Optional[str] = None) -> None:
        async with self._lock:
            s = self._subs.get(channel)
            if s:
                s.discard((ws, user_id))
                if not s:
                    self._subs.pop(channel, None)

    async def unsubscribe_all(self, ws: WebSocket) -> None:
        """Called on disconnect — remove this ws from every channel."""
        async with self._lock:
            for ch in list(self._subs.keys()):
                self._subs[ch] = {t for t in self._subs[ch] if t[0] is not ws}
                if not self._subs[ch]:
                    self._subs.pop(ch, None)

    # ─────────── publish ───────────
    async def publish(self, channel: str, payload: Any) -> int:
        """Push a payload to all subscribers of the channel.

        Stores payload as the channel's latest snapshot so future subscribers
        get an immediate replay. Respects THROTTLE_MS — rapid-fire publishes
        coalesce to one send of the final payload.
        """
        now_ms = time.monotonic() * 1000
        async with self._lock:
            # Always update snapshot (so subscribe-later sees fresh data)
            self._snapshots[channel] = payload
            last = self._last_pub_ms.get(channel, 0)
            if now_ms - last < THROTTLE_MS:
                # Queue deferred flush (if not already queued)
                self._pending[channel] = payload
                if channel not in self._pending_tasks or self._pending_tasks[channel].done():
                    self._pending_tasks[channel] = asyncio.create_task(
                        self._delayed_flush(channel, THROTTLE_MS - (now_ms - last))
                    )
                return 0
            self._last_pub_ms[channel] = now_ms
            subs = list(self._subs.get(channel, set()))

        return await self._send_to(channel, payload, subs)

    async def _delayed_flush(self, channel: str, delay_ms: float) -> None:
        try:
            await asyncio.sleep(max(0.0, delay_ms) / 1000)
        except asyncio.CancelledError:
            return
        async with self._lock:
            payload = self._pending.pop(channel, None)
            if payload is None:
                return
            self._last_pub_ms[channel] = time.monotonic() * 1000
            subs = list(self._subs.get(channel, set()))
        await self._send_to(channel, payload, subs)

    async def _send_to(self, channel: str, payload: Any,
                       subs: list) -> int:
        # ALWAYS bridge to Redis ws:stream channel so Rust Hub can forward
        # to clients connected on its WebSocket endpoint (frontend-www/auto/go).
        # This decouples Python stream_hub from being the only WS authority.
        try:
            from app.core.redis_client import redis_client
            import json
            await redis_client.publish('ws:stream', json.dumps({
                'channel': channel, 'payload': payload
            }, default=str))
        except Exception as e:
            logger.debug(f"[stream_hub] redis bridge publish failed: {e}")

        if not subs:
            return 0
        msg = {"type": "stream", "channel": channel, "payload": payload}
        dead: list = []
        sent = 0
        for ws, _uid in subs:
            try:
                await ws.send_json(msg)
                sent += 1
            except Exception as e:
                logger.debug(f"[stream_hub] send to {channel} failed ({e}); will drop socket")
                dead.append((ws, _uid))
        if dead:
            async with self._lock:
                s = self._subs.get(channel)
                if s:
                    for t in dead:
                        s.discard(t)
        return sent

    def subscriber_count(self, channel: str) -> int:
        return len(self._subs.get(channel, set()))

    def snapshot(self, channel: str) -> Any:
        return self._snapshots.get(channel)


stream_hub = StreamHub()
