"""服务心跳(coin engine:throughput 巡检模式的通用化)。

每个服务周期性 SET dcm:hb:<service> {ts,pid,host,extra} EX ttl。
外部看门狗/风控面读 dcm:hb:* 判停更——键消失即服务停更,无需依赖服务自报健康。
心跳写失败只告警日志,绝不让心跳异常拖垮业务循环。
"""
import asyncio
import json
import logging
import os
import socket
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, redis_url: str, service: str, interval_sec: int = 30, ttl_sec: int = 90):
        self.redis_url = redis_url
        self.service = service
        self.interval = interval_sec
        self.ttl = ttl_sec
        self._r: aioredis.Redis | None = None
        self.extra: dict = {}   # 业务方可随时更新(如吞吐计数),下一拍带出

    async def beat_once(self) -> bool:
        try:
            if self._r is None:
                self._r = aioredis.from_url(self.redis_url, decode_responses=True)
            payload = {"ts": int(time.time()), "pid": os.getpid(),
                       "host": socket.gethostname(), **self.extra}
            await self._r.set(f"dcm:hb:{self.service}", json.dumps(payload), ex=self.ttl)
            return True
        except Exception as e:
            logger.warning(f"heartbeat {self.service} failed: {e}")
            self._r = None  # 下拍重建连接
            return False

    async def run_forever(self):
        while True:
            await self.beat_once()
            await asyncio.sleep(self.interval)


def read_all_heartbeats(redis_url: str) -> dict[str, dict]:
    """同步读全部服务心跳(看门狗/巡检用)。"""
    import redis as redis_sync
    out: dict[str, dict] = {}
    try:
        r = redis_sync.from_url(redis_url, decode_responses=True)
        for k in r.scan_iter("dcm:hb:*", count=100):
            try:
                out[k.removeprefix("dcm:hb:")] = json.loads(r.get(k) or "{}")
            except Exception:
                out[k.removeprefix("dcm:hb:")] = {}
        r.close()
    except Exception as e:
        logger.warning(f"read_all_heartbeats failed: {e}")
    return out
