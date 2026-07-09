"""全局告警节流(Redis 令牌桶,跨进程/跨服务生效)。

同一 key 在 interval_sec 窗口内最多放行 max_count 条。放行 True,抑制 False。
Redis 异常 fail-open(返回 True)——绝不因节流本身吞掉告警。interval_sec<=0 视为不节流。
键前缀 dcm:throttle: ,与 coin 的 notif:throttle: 键空间隔离,互不吞噪。
"""
import redis as redis_sync


def throttle_ok(redis_url: str, key: str, interval_sec: int, max_count: int) -> bool:
    try:
        interval_sec = int(interval_sec or 0)
        max_count = max(1, int(max_count or 1))
    except (TypeError, ValueError):
        return True
    if interval_sec <= 0:
        return True
    try:
        r = redis_sync.from_url(redis_url, decode_responses=True)
        k = f"dcm:throttle:{key}"
        n = r.incr(k)
        if n == 1:
            r.expire(k, interval_sec)
        r.close()
        return n <= max_count
    except Exception:
        return True
