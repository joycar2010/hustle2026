import asyncio
import json
import logging

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def _verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


@router.websocket("/ws/stream")
async def websocket_stream(ws: WebSocket, token: str = ""):
    payload = _verify_token(token)
    if not payload:
        await ws.close(code=4001, reason="Invalid token")
        return

    await manager.connect(ws)
    logger.info(f"WebSocket connected: user={payload.get('sub', '?')}, total={len(manager.active)}")

    redis_conn = None
    pubsub = None
    listener_task = None
    flush_task = None

    try:
        try:
            from app.services.spread_reader import spread_reader
            all_spreads = spread_reader.get_all()
            await ws.send_json({
                "type": "spread_snapshot",
                "data": [json.loads(s.model_dump_json()) for s in all_spreads],
            })
        except Exception as e:
            logger.warning(f"Failed to send initial spread snapshot: {e}")
            await ws.send_json({"type": "spread_snapshot", "data": []})

        redis_conn = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = redis_conn.pubsub()
        await pubsub.subscribe("spread:updates", "position:updates", "worker:status")

        batch: dict[str, dict] = {}
        batch_lock = asyncio.Lock()

        async def flush_loop():
            while True:
                await asyncio.sleep(0.2)
                async with batch_lock:
                    if not batch:
                        continue
                    items = list(batch.values())
                    batch.clear()
                try:
                    await ws.send_json({"type": "spread_batch", "data": items})
                except Exception:
                    break

        async def redis_listener():
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                channel = msg["channel"]
                data_str = msg["data"]

                if channel == "spread:updates":
                    raw = await redis_conn.hget("spreads", data_str)
                    if raw:
                        parsed = json.loads(raw)
                        async with batch_lock:
                            batch[data_str] = parsed

                elif channel == "position:updates":
                    try:
                        parsed = json.loads(data_str)
                        await ws.send_json({"type": "position_update", "data": parsed})
                    except Exception:
                        pass

                elif channel == "worker:status":
                    try:
                        parsed = json.loads(data_str)
                        await ws.send_json({"type": "worker_status", "data": parsed})
                    except Exception:
                        pass

        listener_task = asyncio.create_task(redis_listener())
        flush_task = asyncio.create_task(flush_loop())

        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        if listener_task:
            listener_task.cancel()
        if flush_task:
            flush_task.cancel()
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:
                pass
        if redis_conn:
            try:
                await redis_conn.aclose()
            except Exception:
                pass
        manager.disconnect(ws)
        logger.info(f"WebSocket disconnected, remaining={len(manager.active)}")
