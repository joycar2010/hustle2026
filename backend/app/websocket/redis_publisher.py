"""Redis publisher for forwarding WS events to Go hub"""
import json
import logging
import asyncio
from typing import Any, Dict

logger = logging.getLogger(__name__)

_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings
            _redis_client = await aioredis.from_url(settings.REDIS_URL)
        except Exception as e:
            logger.warning(f"[RedisPublisher] Failed to connect: {e}")
            return None
    return _redis_client


async def publish(channel: str, msg_type: str, data: Any):
    """Publish a message to a Redis channel for Go hub to forward to WS clients."""
    rdb = await _get_redis()
    if rdb is None:
        return
    try:
        payload = json.dumps({"type": msg_type, "data": data})
        await rdb.publish(channel, payload)
    except Exception as e:
        logger.warning(f"[RedisPublisher] publish error on {channel}: {e}")


async def broadcast_market_data(spread_data: dict):
    await publish("ws:market_data", "market_data", spread_data)


async def broadcast_account_balance(data: dict):
    await publish("ws:account_balance", "account_balance", data)


async def broadcast_risk_metrics(data: dict):
    await publish("ws:risk_metrics", "risk_metrics", data)


async def broadcast_strategy_status(data: dict):
    await publish("ws:broadcast", "strategy_status", data)


async def broadcast_position_snapshot(data: dict):
    await publish("ws:broadcast", "position_snapshot", data)


async def broadcast_order_update(user_id: str, data: dict):
    await publish("ws:order_update", "order_update", {"user_id": user_id, **data})


async def broadcast_position_update(data: dict):
    await publish("ws:position_update", "position_update", data)
