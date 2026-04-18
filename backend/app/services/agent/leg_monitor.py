"""Single-leg detection background task.

Polls position state every 5s, computes |a_size - b_size * conversion| > 1
→ inserts leg_imbalance_log row + emits Feishu alert + pushes a 補腿 proposal
to Codex (highest priority).
"""
import asyncio
import logging
from typing import Optional
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _read_positions(db) -> Optional[dict]:
    """Aggregate XAU positions across whitelisted A/B accounts."""
    # TODO P1: read from existing position cache; placeholder returns None
    return None


async def _alert_imbalance(a_size: float, b_size: float, delta: float):
    logger.warning(f'[LEG_MONITOR] imbalance a={a_size} b={b_size} delta={delta}')
    # TODO P2: feishu webhook


async def leg_monitor_loop(interval: float = 5.0, stop_event: Optional[asyncio.Event] = None):
    logger.info('[LEG_MONITOR] started')
    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            async with AsyncSessionLocal() as db:
                pos = await _read_positions(db)
                if pos:
                    delta = abs(pos['a_size'] - pos['b_size'] * pos['conversion'])
                    if delta > 1.0:
                        await db.execute(text('''
                            INSERT INTO leg_imbalance_log (a_size, b_size, delta, conversion_factor)
                            VALUES (:a, :b, :d, :c)
                        '''), {'a': pos['a_size'], 'b': pos['b_size'], 'd': delta, 'c': pos['conversion']})
                        await db.commit()
                        await _alert_imbalance(pos['a_size'], pos['b_size'], delta)
        except Exception as e:
            logger.error(f'[LEG_MONITOR] error: {e}')
        await asyncio.sleep(interval)
