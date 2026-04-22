"""Dashboard stream — push user.accounts.{uid} to WS subscribers every 5s.

Philosophy:
- Only poll MT5/Binance/Bybit for users that actually have active subscribers.
- If nobody's watching, we save the network trip entirely.
"""
import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.models.user import User
from app.services import account_data_service
from app.websocket.stream_hub import stream_hub

logger = logging.getLogger(__name__)

TICK_S = 5
_stop_event: asyncio.Event = None
_task: asyncio.Task = None


async def _publish_for_user(user_id: str) -> None:
    """Fetch aggregated dashboard for one user and publish to channel."""
    channel = f"user.accounts.{user_id}"
    if stream_hub.subscriber_count(channel) == 0:
        return
    try:
        async with AsyncSessionLocal() as db:
            # Same logic as HTTP endpoint: admin => all accounts, else own
            ur = await db.execute(select(User).where(User.user_id == user_id))
            caller = ur.scalar_one_or_none()
            if caller is None:
                return
            ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
            is_admin = caller.role in ADMIN_ROLES
            if is_admin:
                r = await db.execute(select(Account))
            else:
                r = await db.execute(select(Account).where(Account.user_id == UUID(user_id)))
            accounts = [a for a in r.scalars().all() if a.is_active]
        if not accounts:
            await stream_hub.publish(channel, {"summary": {}, "accounts": [], "positions": []})
            return
        data = await account_data_service.get_aggregated_account_data(accounts)
        await stream_hub.publish(channel, data)
    except Exception as e:
        logger.debug(f'[dashboard_stream] {user_id}: {e}')


async def _tick():
    # Enumerate channels with subscribers
    chans = [c for c in list(stream_hub._subs.keys()) if c.startswith('user.accounts.')]
    if not chans:
        return
    user_ids = [c.rsplit('.', 1)[-1] for c in chans]
    await asyncio.gather(*[_publish_for_user(u) for u in user_ids], return_exceptions=True)


async def _loop_main(stop: asyncio.Event):
    logger.info('[dashboard_stream] started')
    while not stop.is_set():
        try:
            await _tick()
        except Exception as e:
            logger.error(f'[dashboard_stream] tick err: {e}')
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_S)
        except asyncio.TimeoutError:
            pass
    logger.info('[dashboard_stream] stopped')


def start():
    global _stop_event, _task
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_loop_main(_stop_event))


async def stop():
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except asyncio.TimeoutError:
            _task.cancel()
