"""Per-user shared MASTER-account futures client (hedge_via_master mode).

子账户现货空 + 主账户合约多:借币/现货留在各子账户 key,合约对冲腿统一用主账户 key。
每个 user 只建一个 client 实例,5 个 worker 共享 —— 单 client 信号量天然限并发,
lot 缓存/UID 权重单点,per-symbol 锁(挂在 client 上)串行化共享净仓的开/平。

失败语义:主账户未配置 / key 为空 / 双向持仓模式 → 返回 None(负缓存 60s),
调用方必须把对应动作留在原状态等待重试,绝不能回退到子账户 key 打合约。
"""
import asyncio
import logging
import time

from coincore.models import MasterAccount
from coincore.db import SessionLocal
from engine.trading.binance_trading import BinanceTradingClient

logger = logging.getLogger(__name__)

_clients: dict[int, BinanceTradingClient] = {}
_failed_at: dict[int, float] = {}     # 负缓存: 上次创建失败时间
_FAIL_TTL = 60.0
_init_locks: dict[int, asyncio.Lock] = {}   # per-key,避免跨 user 串行
_closed = False                              # close_all 后拒绝重建(停机竞态防护)


def _load_master(user_id: int | None) -> MasterAccount | None:
    db = SessionLocal()
    try:
        m = None
        if user_id is not None:
            m = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
        if not m:
            # upsert 历史上不写 user_id —— 兜底取 NULL 行/唯一行
            m = (db.query(MasterAccount).filter(MasterAccount.user_id.is_(None)).first()
                 or db.query(MasterAccount).first())
        return m
    finally:
        db.close()


async def get_master_futures_client(user_id: int | None) -> BinanceTradingClient | None:
    """共享 master 合约 client(进程级生命周期,懒加载)。不可用返回 None。"""
    if _closed:
        return None
    key = user_id or 0
    client = _clients.get(key)
    if client is not None:
        return client
    if time.monotonic() - _failed_at.get(key, -_FAIL_TTL) < _FAIL_TTL:
        return None
    lock = _init_locks.setdefault(key, asyncio.Lock())
    async with lock:
        client = _clients.get(key)
        if client is not None:
            return client
        # 锁内复检负缓存: 失败风暴时排队 waiter 不再逐个重试整套初始化
        if _closed or time.monotonic() - _failed_at.get(key, -_FAIL_TTL) < _FAIL_TTL:
            return None
        m = await asyncio.to_thread(_load_master, user_id)
        if not m or not m.api_key or not m.api_secret:
            logger.warning(f"hedge_via_master: master account not configured (user={user_id})")
            _failed_at[key] = time.monotonic()
            return None
        # metrics 用保留负 key,与子账户 id 区分
        client = BinanceTradingClient(m.api_key, m.api_secret, sub_account_id=-(key or 1))
        await client.__aenter__()
        try:
            dual = await client.get_position_mode()
            if dual:
                logger.error(
                    "hedge_via_master: master account is in DUAL position mode (双向持仓); "
                    "engine orders carry no positionSide — switch the master to one-way mode first. "
                    "Hedging disabled until then."
                )
                await client.__aexit__(None, None, None)
                _failed_at[key] = time.monotonic()
                return None
        except Exception as e:
            logger.warning(f"hedge_via_master: position-mode check failed ({e}); refusing master client")
            await client.__aexit__(None, None, None)
            _failed_at[key] = time.monotonic()
            return None
        _clients[key] = client
        logger.info(f"hedge_via_master: master futures client ready (user={user_id}, one-way mode)")
        return client


async def close_all():
    global _closed
    _closed = True
    for key, client in list(_clients.items()):
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
        _clients.pop(key, None)
