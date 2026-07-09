"""Redis 总线契约(coin 生产验证模式,新键空间):

- snapshot_publish: HSET 快照哈希 + PUBLISH 键名(消费者收通知后回读哈希取最新值,天然去重合并)
- publish: 纯事件广播
- push_command / pop_command: 命令队列 rpush + TTL(队列积压不无限膨胀,消费者 lpop)

服务间只允许经此总线与配置表耦合,禁止同步 HTTP 互调。
"""
import json
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self, redis_url: str):
        self._url = redis_url
        self._r: aioredis.Redis | None = None

    def _redis(self) -> aioredis.Redis:
        if self._r is None:
            self._r = aioredis.from_url(self._url, decode_responses=True)
        return self._r

    async def publish(self, channel: str, payload: dict) -> bool:
        try:
            await self._redis().publish(channel, json.dumps(payload, ensure_ascii=False))
            return True
        except Exception as e:
            logger.warning(f"bus publish {channel} failed: {e}")
            return False

    async def snapshot_publish(self, hash_key: str, field: str, payload: dict,
                               channel: str | None = None) -> bool:
        """HSET hash_key field=json + PUBLISH channel field(channel 缺省 = hash_key:updates)。"""
        try:
            r = self._redis()
            pipe = r.pipeline(transaction=True)
            pipe.hset(hash_key, field, json.dumps(payload, ensure_ascii=False))
            pipe.publish(channel or f"{hash_key}:updates", field)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"bus snapshot {hash_key}/{field} failed: {e}")
            return False

    async def push_command(self, queue: str, payload: dict, ttl: int = 120) -> bool:
        """命令入队(rpush+expire)。TTL 防积压:消费者死亡时队列自动过期,不回放陈旧命令。"""
        try:
            r = self._redis()
            pipe = r.pipeline(transaction=True)
            pipe.rpush(queue, json.dumps(payload, ensure_ascii=False))
            pipe.expire(queue, ttl)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"bus push_command {queue} failed: {e}")
            return False

    async def pop_command(self, queue: str) -> dict | None:
        try:
            raw = await self._redis().lpop(queue)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"bus pop_command {queue} failed: {e}")
            return None

    async def close(self):
        if self._r is not None:
            try:
                await self._r.aclose()
            except Exception:
                pass
            self._r = None
