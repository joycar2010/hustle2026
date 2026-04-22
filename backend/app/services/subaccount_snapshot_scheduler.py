"""Daily NAV snapshot scheduler.

Runs in the background, wakes up at 00:05 Asia/Shanghai every day, and
iterates over every parent that has active sub-accounts, computing and
upserting that day's NAV snapshot into subscription_daily_nav.

The lazy upsert in get_parent_nav already covers most cases (anyone who
opens the app triggers a snapshot for that parent), but the scheduler
guarantees coverage for parents whose UI isn't opened that day — critical
for the historical chart accuracy.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.subaccount_nav import get_parent_nav, invalidate_parent_nav, _upsert_daily_snapshot

logger = logging.getLogger(__name__)
BJ = ZoneInfo("Asia/Shanghai")


def _seconds_until_next_run() -> float:
    """Time until next 00:05 Asia/Shanghai."""
    now = datetime.now(BJ)
    target = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


async def _snapshot_all_active_parents() -> int:
    """Snapshot every parent that currently has >= 1 active subscription."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT DISTINCT parent_user_id
            FROM sub_account_subscriptions
            WHERE status = 'active'
        """))).fetchall()
        parent_ids = [str(r[0]) for r in rows]

    written = 0
    for pid in parent_ids:
        try:
            # Force-refresh to avoid stale cached NAV on day boundary
            await invalidate_parent_nav(pid)
            async with AsyncSessionLocal() as db:
                snap = await get_parent_nav(db, pid, force=True)
                # get_parent_nav already does lazy upsert; tag as scheduled by redoing it
                if snap.total_shares > 0:
                    await _upsert_daily_snapshot(
                        db, pid,
                        snap.total_assets_usdt,
                        snap.total_shares - await _active_shares(db, pid),
                        await _active_shares(db, pid),
                        snap.nav_per_share,
                        source='scheduled',
                    )
                    written += 1
        except Exception as e:
            logger.error(f"[nav-scheduler] parent={pid} snapshot failed: {e}")
    return written


async def _active_shares(db, parent_user_id: str):
    from decimal import Decimal
    row = (await db.execute(text("""
        SELECT COALESCE(SUM(shares), 0)
        FROM sub_account_subscriptions
        WHERE parent_user_id = CAST(:u AS UUID) AND status = 'active'
    """), {"u": parent_user_id})).first()
    return Decimal(str(row[0] or 0))


async def daily_snapshot_loop() -> None:
    """Main scheduler loop. Logs each run; retries on failure with 5-min backoff."""
    logger.info("[nav-scheduler] daily snapshot loop started")
    while True:
        try:
            wait = _seconds_until_next_run()
            logger.info(f"[nav-scheduler] next run in {wait/3600:.2f}h")
            await asyncio.sleep(wait)
            written = await _snapshot_all_active_parents()
            logger.info(f"[nav-scheduler] daily snapshot run complete: {written} parents recorded")
        except asyncio.CancelledError:
            logger.info("[nav-scheduler] cancelled, exiting")
            return
        except Exception as e:
            logger.exception(f"[nav-scheduler] loop error: {e}")
            await asyncio.sleep(300)
