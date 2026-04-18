"""Net-equity drawdown FSM.

Implements the operator's iron rule:
  When single-side equity < 25% of total equity (e.g. one leg blew up):
    1. Send Feishu alert immediately (state → WARNING)
    2. Repeat alert 3 times within ~5 minutes
    3. If equity ratio still bad after 20 minutes (state → ESCALATING)
    4. After 30 minutes total, AUTO-REDUCE positions by 30%
       UNLESS operator hits the ack button on the Feishu card
       (POST /api/v1/agent/equity-ack)

State persisted in equity_intervention_log; one active row per (account_id) at a time.
Background task runs every 60s.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.agent import config_loader
from app.services.agent.feishu_broadcast import broadcast

logger = logging.getLogger(__name__)


async def _open_intervention(db: AsyncSession, account_id, equity_ratio: float) -> int:
    res = await db.execute(text("""
        INSERT INTO equity_intervention_log (account_id, state, equity_ratio, details)
        VALUES (:a, 'WARNING', :r, CAST(:d AS JSONB))
        RETURNING id
    """), {'a': account_id, 'r': equity_ratio,
           'd': __import__('json').dumps({'opened_at': datetime.now(timezone.utc).isoformat()})})
    new_id = res.scalar_one()
    await db.commit()
    return new_id


async def _get_active(db: AsyncSession, account_id) -> Optional[dict]:
    row = (await db.execute(text("""
        SELECT id, state, equity_ratio, triggered_at, ack_by, forced_reduce_pct, details
        FROM equity_intervention_log
        WHERE account_id = :a AND resolved_at IS NULL
        ORDER BY id DESC LIMIT 1
    """), {'a': account_id})).first()
    if not row:
        return None
    return {'id': row[0], 'state': row[1], 'equity_ratio': float(row[2] or 0),
            'triggered_at': row[3], 'ack_by': row[4], 'forced_reduce_pct': row[5],
            'details': row[6] or {}}


async def _set_state(db: AsyncSession, intervention_id: int, state: str, **fields):
    sets = ['state = :s']
    params = {'i': intervention_id, 's': state}
    if 'equity_ratio' in fields:
        sets.append('equity_ratio = :r')
        params['r'] = fields['equity_ratio']
    if 'forced_reduce_pct' in fields:
        sets.append('forced_reduce_pct = :p')
        params['p'] = fields['forced_reduce_pct']
    if 'resolved' in fields and fields['resolved']:
        sets.append('resolved_at = NOW()')
    if 'ack_by' in fields:
        sets.append('ack_by = :ab')
        params['ab'] = fields['ack_by']
    sql = f"UPDATE equity_intervention_log SET {', '.join(sets)} WHERE id = :i"
    await db.execute(text(sql), params)
    await db.commit()


async def acknowledge(db: AsyncSession, account_id, ack_by) -> bool:
    """Operator confirms situation is normal — cancels pending forced reduce.

    Called by POST /api/v1/agent/equity-ack (with auth).
    """
    active = await _get_active(db, account_id)
    if not active:
        return False
    await _set_state(db, active['id'], 'RESOLVED', resolved=True, ack_by=ack_by)
    await broadcast(db, level='info', category='equity_ack',
                    message=f'操作员确认 — 账户 {str(account_id)[:8]} 净资产告警已解除（不强减）',
                    payload={'intervention_id': active['id']})
    return True


async def _execute_forced_reduce(db: AsyncSession, account_id, current_pct: float) -> dict:
    """P2.5: smart partial reduce — 30% of current position over 5 chunks, both legs symmetric.

    Direction inferred from current net positions; preserves market neutrality.
    Audit: parent row (trigger=forced_reduce) + 5 child rows (trigger=forced_reduce_chunk).
    """
    from app.services.agent.partial_reduce import execute_partial_reduce

    logger.warning(f'[equity_fsm] FORCED_REDUCE start account={account_id} pct={current_pct*100:.0f}%')

    res = await db.execute(text("""
        INSERT INTO agent_decisions (trigger, market_snapshot, proposal, verdict, reject_reason)
        VALUES ('forced_reduce', '{}', CAST(:p AS JSONB), 'executed', 'auto_reduce_by_fsm')
        RETURNING id
    """), {'p': __import__('json').dumps({
        'action': 'partial_reduce', 'leg': 'both', 'qty': 0,
        'reason': f'forced_reduce {current_pct*100:.0f}% (5-chunk smart partial)',
        'reduce_pct': current_pct,
    })})
    decision_id = res.scalar_one()
    await db.commit()

    exec_res = await execute_partial_reduce(
        db, parent_decision_id=decision_id,
        reduce_pct=current_pct, chunks=5, chunk_interval_s=30.0,
    )

    await broadcast(db, level='critical', category='forced_reduce_done',
                    message=f'强制减仓 {current_pct*100:.0f}% 完成 | 账户 {str(account_id)[:8]} | A: {exec_res.get("a_ok_count", 0)}/5 | B: {exec_res.get("b_ok_count", 0)}/5',
                    payload={'parent_decision_id': decision_id, 'exec': exec_res})
    return exec_res


async def _per_account_check(db: AsyncSession, account_id, equity_ratio: float, cfg: dict):
    """Run one tick for one account."""
    eq_cfg = cfg.get('equity_guard', {})
    floor = float(eq_cfg.get('single_side_floor', 0.25))
    escalate_min = int(eq_cfg.get('escalate_minutes', 20))
    forced_min = int(eq_cfg.get('forced_reduce_minutes', 30))
    forced_pct = float(eq_cfg.get('forced_reduce_pct', 0.30))

    active = await _get_active(db, account_id)
    is_below = equity_ratio < floor

    if not active and is_below:
        intervention_id = await _open_intervention(db, account_id, equity_ratio)
        for i in range(3):
            await broadcast(db, level='danger', category='equity_warning',
                            message=f'净资产告警 #{i+1}/3 | 账户 {str(account_id)[:8]} 单边占比 {equity_ratio*100:.1f}% < {floor*100:.0f}%',
                            payload={'intervention_id': intervention_id, 'equity_ratio': equity_ratio},
                            ack_required=True)
            await asyncio.sleep(2)
        return

    if not active:
        return  # no active intervention, equity normal

    age_min = (datetime.now(timezone.utc) - active['triggered_at']).total_seconds() / 60.0
    if not is_below:
        await _set_state(db, active['id'], 'RESOLVED', resolved=True, equity_ratio=equity_ratio)
        await broadcast(db, level='info', category='equity_resolved',
                        message=f'净资产恢复 | 账户 {str(account_id)[:8]} 占比回升至 {equity_ratio*100:.1f}%',
                        payload={'intervention_id': active['id']})
        return

    if active['state'] == 'WARNING' and age_min >= escalate_min:
        await _set_state(db, active['id'], 'ESCALATING', equity_ratio=equity_ratio)
        await broadcast(db, level='danger', category='equity_escalating',
                        message=f'净资产持续低位 {age_min:.0f} 分钟 | 账户 {str(account_id)[:8]} | 再过 {forced_min - age_min:.0f} 分钟将自动减仓 30%（操作员可 ack 取消）',
                        payload={'intervention_id': active['id'], 'equity_ratio': equity_ratio},
                        ack_required=True)
        return

    if active['state'] in ('WARNING', 'ESCALATING') and age_min >= forced_min and active['ack_by'] is None:
        await _set_state(db, active['id'], 'FORCED_REDUCE', equity_ratio=equity_ratio,
                         forced_reduce_pct=forced_pct)
        await _execute_forced_reduce(db, account_id, forced_pct)
        await _set_state(db, active['id'], 'RESOLVED', resolved=True)


async def _tick():
    """One FSM tick: check all whitelisted active accounts."""
    async with AsyncSessionLocal() as db:
        cfg = await config_loader.load_config(db)

        # Build per-account equity ratio: equity / total across A+B legs of same user
        # For P2 simplicity: aggregate per platform, treat A side and B side as the two "sides"
        from app.services.agent.market_snapshot import collect_xau_positions_and_equity
        eq = await collect_xau_positions_and_equity(db)
        total = eq['total_equity']
        if total <= 0:
            return
        # Skip when there are no XAU positions to protect — equity imbalance without
        # exposure is just an unused hedge wallet, not a risk event.
        if abs(eq['a_size']) < 0.01 and abs(eq['b_size']) < 0.01:
            return
        a_ratio = eq['a_equity'] / total if total else 1.0
        b_ratio = eq['b_equity'] / total if total else 1.0

        # Use synthetic IDs for aggregate-side checks
        from uuid import UUID
        SYNTHETIC_A = UUID('00000000-0000-0000-0000-000000000001')
        SYNTHETIC_B = UUID('00000000-0000-0000-0000-000000000002')
        await _per_account_check(db, SYNTHETIC_A, a_ratio, cfg)
        await _per_account_check(db, SYNTHETIC_B, b_ratio, cfg)


_stop = None
_task = None


async def _loop_main(stop_event: asyncio.Event):
    logger.info('[equity_fsm] loop started')
    while not stop_event.is_set():
        try:
            await _tick()
        except Exception as e:
            logger.error(f'[equity_fsm] tick error: {e}')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info('[equity_fsm] stopped')


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
