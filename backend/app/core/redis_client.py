"""
Redis client configuration and connection management
"""
import redis.asyncio as redis
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client wrapper for caching and pub/sub"""

    def __init__(self):
        self.client: redis.Redis = None
        self.pubsub = None

    async def connect(self):
        """Connect to Redis server"""
        try:
            self.client = await redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            await self.client.ping()
            logger.info("✓ Connected to Redis")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Continuing without Redis.")
            self.client = None

    async def disconnect(self):
        """Disconnect from Redis server"""
        if self.client:
            await self.client.close()
            logger.info("Disconnected from Redis")

    async def get(self, key: str):
        """Get value from Redis"""
        if not self.client:
            return None
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None

    async def set(self, key: str, value: str, ex: int = None):
        """Set value in Redis with optional expiration"""
        if not self.client:
            return False
        try:
            await self.client.set(key, value, ex=ex)
            return True
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            return False

    async def delete(self, key: str):
        """Delete key from Redis"""
        if not self.client:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")
            return False

    async def publish(self, channel: str, message: str):
        """Publish message to Redis channel"""
        if not self.client:
            return False
        try:
            await self.client.publish(channel, message)
            return True
        except Exception as e:
            logger.error(f"Redis PUBLISH error: {e}")
            return False


# Global Redis client instance
redis_client = RedisClient()
