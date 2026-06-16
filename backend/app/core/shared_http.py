"""共享 httpx.AsyncClient 单例(20260616).

根因: 多个后台任务(PositionStreamer 每秒×9桥、mt5_sync 每10s×9、各 Streamer)用
`async with httpx.AsyncClient()` 模式每次新建客户端, 每次都触发 CPU 密集的
`load_ssl_context_verify`(读CA证书构建SSL上下文)在事件循环线程上同步执行 →
事件循环被反复阻塞 → 全站策略循环间歇停摆数分钟(进度条/触发评估卡顿)。

修法: 全进程复用一个惰性初始化的 AsyncClient — SSL 上下文只构建一次、连接池复用。
单次调用的超时用 `client.get(url, timeout=X)` 覆盖, 不影响复用。
"""
import httpx
from typing import Optional

_shared_client: Optional[httpx.AsyncClient] = None


def get_shared_async_client() -> httpx.AsyncClient:
    """返回全进程共享的 AsyncClient(惰性创建). 默认超时 5s, 单次可覆盖."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
        )
    return _shared_client


async def close_shared_async_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        try:
            await _shared_client.aclose()
        except Exception:
            pass
    _shared_client = None
