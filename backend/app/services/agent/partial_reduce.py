"""Smart partial position reduction.

Used by equity_fsm forced reduce: cut open positions by reduce_pct,
chunked into N market orders spaced chunk_interval seconds apart, on BOTH
legs simultaneously (preserve market-neutral hedge).

Direction inferred from current net positions:
  a_size > 0 (LONG)  → SELL on A, BUY on B (B was hedged short)
  a_size < 0 (SHORT) → BUY on A, SELL on B
If a_size == 0 (flat A) but b_size != 0 → close only B to fully exit hedge.

Logs each chunk to agent_decisions with trigger='forced_reduce_chunk'.
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def execute_partial_reduce(
    db: AsyncSession,
    parent_decision_id: int,
    reduce_pct: float = 0.30,
    chunks: int = 5,
    chunk_interval_s: float = 30.0,
) -> Dict[str, Any]:
    """Reduce current XAU positions by reduce_pct over N chunks @ chunk_interval_s spacing."""
    from app.services.agent.market_snapshot import collect_xau_positions_and_equity, fetch_conversion_factor
    from app.services.agent.executor import _resolve_accounts, A_SYMBOL, B_SYMBOL
    from app.services.order_executor import order_executor
    from app.services.agent.feishu_broadcast import broadcast

    a_acc, b_acc = await _resolve_accounts(db)
    if not a_acc or not b_acc:
        return {'ok': False, 'reason': 'account_not_found'}

    eq = await collect_xau_positions_and_equity(db)
    a_size, b_size = eq['a_size'], eq['b_size']
    conv = await fetch_conversion_factor(db)

    if abs(a_size) < 0.01 and abs(b_size) < 0.01:
        return {'ok': True, 'reason': 'no_position_nothing_to_reduce'}

    # Total reduction targets
    a_target_total = abs(a_size) * reduce_pct
    b_target_total = abs(b_size) * reduce_pct
    a_per_chunk = round(a_target_total / chunks, 2)
    b_per_chunk = round(b_target_total / chunks, 2)
    if a_per_chunk < 0.01 and b_per_chunk < 0.01:
        return {'ok': False, 'reason': f'chunk_size_below_min:a={a_per_chunk},b={b_per_chunk}'}
    a_per_chunk = max(0.01, a_per_chunk)
    b_per_chunk = max(0.01, b_per_chunk)

    # Direction: opposite of current net side
    a_side, a_pos_side = ('SELL', 'LONG') if a_size > 0 else ('BUY', 'SHORT')
    b_side = 'Buy' if b_size > 0 else 'Sell'  # opposite to close

    logger.warning(
        f'[partial_reduce] start parent={parent_decision_id} pct={reduce_pct} '
        f'chunks={chunks} a_per={a_per_chunk} b_per={b_per_chunk}'
    )

    chunk_results: List[Dict[str, Any]] = []
    for i in range(chunks):
        t0 = time.time()
        a_task = order_executor.place_binance_order(
            account=a_acc, symbol=A_SYMBOL, side=a_side, order_type='MARKET',
            quantity=a_per_chunk, position_side=a_pos_side,
        ) if abs(a_size) >= 0.01 else _noop()
        b_task = order_executor.place_bybit_order(
            account=b_acc, symbol=B_SYMBOL, side=b_side, order_type='Market',
            quantity=str(b_per_chunk), category='linear', close_position=False,
        ) if abs(b_size) >= 0.01 else _noop()

        results = await asyncio.gather(a_task, b_task, return_exceptions=True)
        chunk = {
            'chunk': i + 1, 'elapsed_ms': int((time.time() - t0) * 1000),
            'a_result': str(results[0])[:300], 'b_result': str(results[1])[:300],
            'a_ok': not isinstance(results[0], Exception),
            'b_ok': not isinstance(results[1], Exception),
        }
        chunk_results.append(chunk)

        # Per-chunk audit row
        await db.execute(text("""
            INSERT INTO agent_decisions (trigger, market_snapshot, proposal, verdict, reject_reason)
            VALUES ('forced_reduce_chunk', '{}', CAST(:p AS JSONB), 'executed', :rr)
        """), {
            'p': __import__('json').dumps({'parent_decision_id': parent_decision_id,
                                           'chunk': i + 1, 'a_qty': a_per_chunk,
                                           'b_qty': b_per_chunk}),
            'rr': f'parent={parent_decision_id};chunk={i+1}/{chunks}',
        })
        await db.commit()

        if i < chunks - 1:
            await asyncio.sleep(chunk_interval_s)

    a_ok_count = sum(1 for c in chunk_results if c['a_ok'])
    b_ok_count = sum(1 for c in chunk_results if c['b_ok'])

    await broadcast(
        db, level='warn', category='partial_reduce_done',
        message=f'分批减仓完成 | 减幅 {reduce_pct*100:.0f}% | A: {a_ok_count}/{chunks} 成功 | B: {b_ok_count}/{chunks} 成功',
        payload={'parent_decision_id': parent_decision_id, 'chunks': chunk_results},
    )

    return {
        'ok': a_ok_count + b_ok_count > 0,
        'chunks': chunk_results,
        'a_ok_count': a_ok_count, 'b_ok_count': b_ok_count,
        'reduce_pct': reduce_pct,
    }


async def _noop():
    return {'status': 'skipped'}
