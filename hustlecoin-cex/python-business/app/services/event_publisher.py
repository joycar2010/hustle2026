import json
import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def publish_position_update(position_data: dict):
    try:
        r = await _get_redis()
        await r.publish("position:updates", json.dumps(position_data))
    except Exception as e:
        logger.warning(f"Failed to publish position update: {e}")


async def publish_worker_status(worker_data: dict):
    try:
        r = await _get_redis()
        await r.publish("worker:status", json.dumps(worker_data))
    except Exception as e:
        logger.warning(f"Failed to publish worker status: {e}")
