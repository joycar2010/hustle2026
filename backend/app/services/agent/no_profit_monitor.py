"""12-hour no-profit monitor.

Per operator's iron rule:
  '单笔交易多空双方总收益出现12小时未盈利通知飞书提醒'

Implementation:
  - Find oldest open XAU position (across A and B legs) by querying exchange position
    open_time via account_data_service.
  - Compute combined unrealized PnL = sum(unrealized_pnl across A leg + B leg positions).
  - If oldest position > 12h AND combined unrealized PnL <= 0 → emit alert.
  - Dedup: don't re-alert within 12h for the same intervention episode.
    Key by combined position fingerprint (rounded a_size + b_size).

Background: 60s tick. Cheap (uses existing account_data_service 60s cache).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.agent.feishu_broadcast import broadcast

logger = logging.getLogger(__name__)

NO_PROFIT_THRESHOLD_HOURS = 12
TICK_INTERVAL_S = 60



_last_alert_ts: float = 0.0
_last_fingerprint: str = ''


async def _aggregate_oldest_pos_and_pnl(db: AsyncSession) -> Tuple[Optional[datetime], float, float, float]:
    """Return (oldest_open_time, combined_unrealized_pnl, a_size, b_size) across all active targets."""
    from app.services.account_service import account_data_service
    from app.models.account import Account
    from app.services.agent.scope import list_active_contexts

    contexts = await list_active_contexts(db)
    accs = (await db.execute(select(Account).where(Account.is_active == True))).scalars().all()
    if not accs or not contexts:
        return None, 0.0, 0.0, 0.0

    agg = await account_data_service.get_aggregated_account_data(list(accs))

    in_scope_aids = set()
    for ctx in contexts:
        for a in accs:
            if ctx.is_scope_match_account(a):
                in_scope_aids.add(str(a.account_id))

    oldest_ms: Optional[int] = None
    combined_pnl = 0.0
    a_size = b_size = 0.0

    for acc_data in agg.get('accounts', []):
        pid = acc_data.get('platform_id')
        aid = str(acc_data.get('account_id', ''))
        if aid not in in_scope_aids:
            continue

        for pos in acc_data.get('positions', []):
            sym = (pos.get('symbol') or '').upper()
            matched = False
            is_a_leg = False
            for ctx in contexts:
                a_prefix = ctx.a_symbol.upper()[:6]
                b_prefix = ctx.b_symbol.upper()[:6]
                if pid == ctx.a_platform_id and sym.startswith(a_prefix):
                    matched = True
                    is_a_leg = True
                    break
                if pid == ctx.b_platform_id and (sym.startswith(b_prefix) or sym.startswith(a_prefix)):
                    matched = True
                    is_a_leg = False
                    break
            if not matched:
                continue

            size = float(pos.get('size', 0) or 0)
            upnl = float(pos.get('unrealized_pnl', 0) or 0)
            combined_pnl += upnl
            if is_a_leg:
                a_size += size if pos.get('side', '').upper() in ('LONG', 'BUY') else -size
            else:
                b_size += size if pos.get('side', '').upper() in ('LONG', 'BUY') else -size

            ot = pos.get('open_time') or pos.get('updateTime') or pos.get('time')
            if ot:
                try:
                    ot_ms = int(ot)
                    if ot_ms < 1e12:
                        ot_ms *= 1000
                    if oldest_ms is None or ot_ms < oldest_ms:
                        oldest_ms = ot_ms
                except (ValueError, TypeError):
                    pass

    oldest_dt = datetime.fromtimestamp(oldest_ms / 1000, tz=timezone.utc) if oldest_ms else None
    return oldest_dt, combined_pnl, a_size, b_size


async def _tick():
    global _last_alert_ts, _last_fingerprint
    async with AsyncSessionLocal() as db:
        oldest, pnl, a, b = await _aggregate_oldest_pos_and_pnl(db)
        if not oldest or (abs(a) < 0.01 and abs(b) < 0.01):
            return
        age_h = (datetime.now(timezone.utc) - oldest).total_seconds() / 3600.0
        if age_h < NO_PROFIT_THRESHOLD_HOURS:
            return
        if pnl > 0:
            return

        fingerprint = f'a={round(a, 2)};b={round(b, 2)}'
        now = time.time()
        # Dedup window = 12h from last alert if fingerprint matches
        if fingerprint == _last_fingerprint and (now - _last_alert_ts) < 12 * 3600:
            return

        _last_alert_ts = now
        _last_fingerprint = fingerprint
        await broadcast(
            db, level='warn', category='no_profit_12h',
            message=f'持仓 {age_h:.1f}h 未盈利 | A={a} B={b} | 合并浮亏 {pnl:.2f} USDT — 请评估是否离场',
            payload={'age_h': age_h, 'combined_pnl': pnl, 'a_size': a, 'b_size': b,
                     'oldest_open_time': oldest.isoformat()},
        )


_stop = None
_task = None


async def _loop_main(stop_event: asyncio.Event):
    logger.info('[no_profit_monitor] loop started')
    while not stop_event.is_set():
        try:
            await _tick()
        except Exception as e:
            logger.error(f'[no_profit_monitor] tick error: {e}')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
    logger.info('[no_profit_monitor] stopped')


def start():
    global _stop, _task
    if _task and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_loop_main(_stop))


async def stop():
    global _stop, _task
    if _stop:
        _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except asyncio.TimeoutError:
            _task.cancel()
