import logging
from decimal import Decimal

import redis.asyncio as aioredis

from app.config import settings
from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient

logger = logging.getLogger(__name__)

TRANSFER_TYPES = {
    ("futures", "margin"): "UMFUTURE_MARGIN",
    ("spot", "margin"): "MAIN_MARGIN",
    ("margin", "spot"): "MARGIN_MAIN",
    ("margin", "futures"): "MARGIN_UMFUTURE",
    ("spot", "futures"): "MAIN_UMFUTURE",
    ("futures", "spot"): "UMFUTURE_MAIN",
}

_lock_redis: aioredis.Redis | None = None
TRANSFER_LOCK_TTL = 30


async def _get_lock_redis() -> aioredis.Redis:
    global _lock_redis
    if _lock_redis is None:
        _lock_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _lock_redis


async def _acquire_transfer_lock(account_key: str) -> bool:
    r = await _get_lock_redis()
    return await r.set(f"transfer_lock:{account_key}", "1", nx=True, ex=TRANSFER_LOCK_TTL)


async def _release_transfer_lock(account_key: str):
    r = await _get_lock_redis()
    await r.delete(f"transfer_lock:{account_key}")


async def ensure_margin_balance(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    required_amount: Decimal,
    account_key: str = "default",
):
    lock_key = account_key
    acquired = await _acquire_transfer_lock(lock_key)
    if not acquired:
        logger.warning(f"Transfer lock contention for {lock_key}, skipping")
        return False

    try:
        margin_info = await client.get_margin_account()
        usdt_free = Decimal("0")
        for asset in margin_info.get("userAssets", []):
            if asset["asset"] == "USDT":
                usdt_free = Decimal(str(asset.get("free", "0")))
                break

        if usdt_free >= required_amount:
            return True

        deficit = required_amount - usdt_free
        transfer_amount = min(deficit, rules.single_transfer_amount)

        order = rules.transfer_order.split(",")
        for source in order:
            source = source.strip()
            if source == "margin":
                continue
            key = (source, "margin")
            transfer_type = TRANSFER_TYPES.get(key)
            if not transfer_type:
                continue
            try:
                await client.transfer(transfer_type, "USDT", transfer_amount)
                logger.info(f"Transferred {transfer_amount} USDT from {source} to margin")
                return True
            except Exception as e:
                logger.warning(f"Transfer from {source} failed: {e}")
                continue

        return False
    finally:
        await _release_transfer_lock(lock_key)
