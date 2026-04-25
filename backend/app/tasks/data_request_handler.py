"""
DataRequestListener — subscribes to Redis ws:data_request channel.
Handles on-demand data requests from frontend via WebSocket:
  - pnl_daily: Fetch PnL data and push back via ws:user_event
  - fund_flow: Fetch fund flow data and push back via ws:user_event

Flow: Client -> Go WS Hub -> Redis ws:data_request -> This listener ->
      Internal API call -> Redis ws:user_event -> Go Hub -> Client
"""
import asyncio
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Simple in-memory cache: key -> (data, expire_ts)
_cache: dict = {}
_CACHE_TTL = 60  # seconds


def _cache_get(key: str):
    if key in _cache:
        data, exp = _cache[key]
        if time.time() < exp:
            return data
        del _cache[key]
    return None


def _cache_set(key: str, data, ttl: int = _CACHE_TTL):
    _cache[key] = (data, time.time() + ttl)


class DataRequestListener:
    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("DataRequestListener started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        from app.core.redis_client import redis_client as _rc
        while self.running:
            pubsub = None
            try:
                if not _rc.client:
                    await asyncio.sleep(2)
                    continue
                pubsub = _rc.client.pubsub()
                await pubsub.subscribe("ws:data_request")
                async for msg in pubsub.listen():
                    if not self.running:
                        break
                    if msg.get("type") != "message":
                        continue
                    try:
                        data = json.loads(msg.get("data") or "{}")
                        user_id = data.get("user_id")
                        channel = data.get("channel")
                        params = data.get("params") or {}
                        if user_id and channel:
                            asyncio.create_task(
                                self._handle_request(user_id, channel, params)
                            )
                    except Exception as e:
                        logger.debug(f"[DataRequestListener] msg parse error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DataRequestListener] loop error: {e}")
                await asyncio.sleep(2)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe()
                        await pubsub.close()
                    except Exception:
                        pass

    async def _handle_request(self, user_id: str, channel: str, params: dict):
        try:
            if channel == "pnl_daily":
                await self._handle_pnl(user_id, params)
            elif channel == "fund_flow":
                await self._handle_fund_flow(user_id, params)
            else:
                logger.warning(f"[DataRequestListener] unknown channel: {channel}")
        except Exception as e:
            logger.error(f"[DataRequestListener] handle {channel} error: {e}")
            await self._push_response(user_id, channel, {"error": str(e)})

    async def _handle_pnl(self, user_id: str, params: dict):
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")
        platform = params.get("platform", "all")

        cache_key = f"dr:pnl:{user_id}:{start_date}:{end_date}:{platform}"
        cached = _cache_get(cache_key)
        if cached:
            await self._push_response(user_id, "pnl_daily", cached)
            return

        from app.core.security import create_access_token
        token = create_access_token({"sub": user_id})

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "http://127.0.0.1:8000/api/v1/pnl/daily",
                params={
                    "start_date": start_date,
                    "end_date": end_date,
                    "platform": platform,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                _cache_set(cache_key, data)
                await self._push_response(user_id, "pnl_daily", data)
            else:
                await self._push_response(
                    user_id, "pnl_daily", {"error": f"HTTP {resp.status_code}"}
                )

    async def _handle_fund_flow(self, user_id: str, params: dict):
        days = params.get("days", 30)

        cache_key = f"dr:ff:{user_id}:{days}"
        cached = _cache_get(cache_key)
        if cached:
            await self._push_response(user_id, "fund_flow", cached)
            return

        from app.core.security import create_access_token
        token = create_access_token({"sub": user_id})

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "http://127.0.0.1:8000/api/v1/accounts/me/fund-flow",
                params={"days": days},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                data["ok"] = True
                _cache_set(cache_key, data)
                await self._push_response(user_id, "fund_flow", data)
            else:
                await self._push_response(
                    user_id,
                    "fund_flow",
                    {"error": f"HTTP {resp.status_code}", "ok": False},
                )

    async def _push_response(self, user_id: str, msg_type: str, data: dict):
        from app.core.redis_client import redis_client as _rc
        if not _rc.client:
            return
        evt = {
            "user_id": user_id,
            "type": msg_type,
            "data": data,
            "ts": int(time.time() * 1000),
        }
        await _rc.client.publish("ws:user_event", json.dumps(evt))


data_request_listener = DataRequestListener()
