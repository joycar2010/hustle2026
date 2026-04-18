"""6-window rolling rate limiter on Redis sorted sets.

Anti-ban contract:
  10m ≤ 50, 30m ≤ 120, 1h ≤ 300, 6h ≤ 1000, 12h ≤ 1500, 24h ≤ 2000.
A safety_margin (default 20%) is applied internally → effective caps are tighter
than the exchange limits, leaving headroom for retries and partial fills.

Two-phase: pre_check() returns ok/violation; on actual order send, commit() persists
the count. If commit is skipped, the entry auto-expires (timestamp passes window).
"""
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import redis.asyncio as redis

WINDOWS_SEC: Dict[str, int] = {
    '10m': 600, '30m': 1800, '1h': 3600,
    '6h': 21600, '12h': 43200, '24h': 86400,
}


@dataclass
class BucketUsage:
    window: str
    used: int
    cap: int
    effective_cap: int  # cap * (1 - safety_margin)


class RateBuckets:
    def __init__(self, redis_client: redis.Redis, key_prefix: str = 'openclaw:rate'):
        self.r = redis_client
        self.prefix = key_prefix

    def _key(self, window: str) -> str:
        return f'{self.prefix}:{window}'

    async def usage(self, caps: Dict[str, int], safety_margin: float = 0.20) -> List[BucketUsage]:
        now_ms = int(time.time() * 1000)
        out: List[BucketUsage] = []
        for win, sec in WINDOWS_SEC.items():
            cap = int(caps.get(win, 0))
            if not cap:
                continue
            cutoff = now_ms - sec * 1000
            await self.r.zremrangebyscore(self._key(win), 0, cutoff)
            used = await self.r.zcard(self._key(win))
            eff = int(cap * (1.0 - safety_margin))
            out.append(BucketUsage(window=win, used=used, cap=cap, effective_cap=eff))
        return out

    async def pre_check(self, caps: Dict[str, int], safety_margin: float = 0.20) -> Tuple[bool, Optional[str]]:
        for u in await self.usage(caps, safety_margin):
            if u.used + 1 > u.effective_cap:
                return False, f'rate_limit_{u.window}: {u.used}/{u.effective_cap} (cap {u.cap})'
        return True, None

    async def commit(self, action_id: str) -> None:
        """Persist 1 unit into all 6 windows. action_id is the unique member."""
        now_ms = int(time.time() * 1000)
        pipe = self.r.pipeline()
        for win in WINDOWS_SEC:
            pipe.zadd(self._key(win), {action_id: now_ms})
        await pipe.execute()
