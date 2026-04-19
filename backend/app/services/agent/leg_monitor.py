"""R5 Single-leg detection — real implementation.

Polls every 5s across every enabled scope target:
  1. Fetch positions + equity via scope-aware market_snapshot
  2. delta = a_size - b_size * conversion_factor  (oz-equivalent)
  3. |delta| > threshold (default 1 oz) → open (or update) a leg_imbalance_log row
  4. Emit Feishu alert once per new imbalance event (dedup by active row)
  5. When imbalance persists > resolve_grace_s without natural resolution, log a
     CRITICAL audit for operator attention

Does NOT auto-trigger rebalance orders — that call is reserved for Codex (which
evaluates direction and size in context). We surface the signal; Codex's next
decide() picks it up from the market state (a_size/b_size) and proposes rebalance.

Config (from agent_active_config):
  leg_imbalance: {threshold_oz: 1.0, resolve_grace_seconds: 900}
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_OZ = 1.0
DEFAULT_RESOLVE_GRACE_S = 900


async def _get_active_row(db: AsyncSession, target_id: int) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text("""
        SELECT id, a_size, b_size, delta, detected_at
        FROM leg_imbalance_log
        WHERE resolved_at IS NULL AND conversion_factor IS NOT NULL
          AND resolution IS NULL
          AND (resolution = 'target=' || :tid OR resolution IS NULL)
        ORDER BY id DESC LIMIT 1
    """), {'tid': str(target_id)})).first()
    if not row:
        return None
    return {'id': row[0], 'a_size': float(row[1] or 0), 'b_size': float(row[2] or 0),
            'delta': float(row[3] or 0), 'detected_at': row[4]}


async def _check_target(db: AsyncSession, ctx, threshold: float) -> None:
    from app.services.agent.market_snapshot import collect_xau_positions_and_equity
    from app.services.agent.feishu_broadcast import broadcast

    eq = await collect_xau_positions_and_equity(db, ctx)
    a_size = eq['a_size']
    b_size = eq['b_size']
    delta = a_size - b_size * ctx.conversion_factor
    abs_delta = abs(delta)

    # Find the most recent UNRESOLVED row attributed to this target (by resolution tag)
    active = (await db.execute(text("""
        SELECT id, delta, detected_at FROM leg_imbalance_log
        WHERE resolved_at IS NULL AND resolution = :tag
        ORDER BY id DESC LIMIT 1
    """), {'tag': f'target={ctx.target_id}'})).first()

    if abs_delta <= threshold:
        # No imbalance → resolve any active row
        if active:
            await db.execute(text("""
                UPDATE leg_imbalance_log SET resolved_at = NOW()
                WHERE id = :i
            """), {'i': active[0]})
            await db.commit()
            await broadcast(
                db, level='info', category='leg_resolved',
                message=f'[{ctx.label}] 双腿配平恢复 | delta={delta:.2f} oz (< {threshold})',
                payload={'target_id': ctx.target_id, 'delta': delta,
                         'a_size': a_size, 'b_size': b_size},
            )
        return

    # Imbalance above threshold
    if not active:
        # Open new row + fire alert
        res = await db.execute(text("""
            INSERT INTO leg_imbalance_log
              (a_size, b_size, delta, conversion_factor, resolution)
            VALUES (:a, :b, :d, :c, :tag)
            RETURNING id
        """), {'a': a_size, 'b': b_size, 'd': delta,
               'c': ctx.conversion_factor, 'tag': f'target={ctx.target_id}'})
        new_id = res.scalar_one()
        await db.commit()
        await broadcast(
            db, level='warn', category='leg_imbalance',
            message=(f'[{ctx.label}] 单腿失衡告警 | A={a_size:.2f} B={b_size:.2f}·{ctx.conversion_factor} '
                     f'delta={delta:+.2f} oz (>{threshold}) — 下一次 Codex 决策仅允许 rebalance 补腿'),
            payload={'target_id': ctx.target_id, 'leg_imbalance_id': new_id,
                     'a_size': a_size, 'b_size': b_size, 'delta': delta},
            ack_required=True,
        )
        return

    # Existing imbalance row — check if exceeded grace window
    age_s = (datetime.now(timezone.utc) - active[2]).total_seconds()
    if age_s > DEFAULT_RESOLVE_GRACE_S:
        # Update delta + emit escalation (once per grace expiry)
        await db.execute(text("""
            UPDATE leg_imbalance_log SET delta = :d WHERE id = :i
        """), {'d': delta, 'i': active[0]})
        await db.commit()
        # Only re-alert if delta grew by >20% since last alert (avoid spam)
        prev_delta = abs(float(active[1] or 0))
        if abs_delta > prev_delta * 1.2 or abs_delta > prev_delta + 0.5:
            await broadcast(
                db, level='danger', category='leg_imbalance_escalated',
                message=(f'[{ctx.label}] 单腿失衡持续 {age_s/60:.0f} 分钟未修复 | '
                         f'delta 从 {prev_delta:.2f} 恶化到 {abs_delta:.2f} oz'),
                payload={'target_id': ctx.target_id, 'leg_imbalance_id': active[0],
                         'prev_delta': prev_delta, 'delta': delta, 'age_s': age_s},
                ack_required=True,
            )


async def leg_monitor_loop(interval: float = 5.0, stop_event: Optional[asyncio.Event] = None):
    from app.services.agent.scope import list_active_contexts
    from app.services.agent import config_loader

    logger.info('[LEG_MONITOR] started (per-target real impl)')
    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            async with AsyncSessionLocal() as db:
                cfg = await config_loader.load_config(db)
                threshold = float(cfg.get('leg_imbalance', {}).get('threshold_oz',
                                  DEFAULT_THRESHOLD_OZ) or DEFAULT_THRESHOLD_OZ)
                ctxs = await list_active_contexts(db)
                for ctx in ctxs:
                    try:
                        await _check_target(db, ctx, threshold)
                    except Exception as e:
                        logger.error(f'[LEG_MONITOR] check target #{ctx.target_id} failed: {e}')
        except Exception as e:
            logger.error(f'[LEG_MONITOR] tick error: {e}')
        await asyncio.sleep(interval)


# ───── Async start / stop for FastAPI lifespan ─────
_stop: Optional[asyncio.Event] = None
_task: Optional[asyncio.Task] = None


def start(interval: float = 5.0):
    global _stop, _task
    if _task and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(leg_monitor_loop(interval=interval, stop_event=_stop))
    logger.info('[LEG_MONITOR] task scheduled')


async def stop():
    global _stop, _task
    if _stop:
        _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except asyncio.TimeoutError:
            _task.cancel()
