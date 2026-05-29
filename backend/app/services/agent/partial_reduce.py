"""D4 (partial_reduce): accept ctx, use ctx.a_symbol/b_symbol + platform dispatch for A leg.

If ctx is None, falls back to legacy scan (best-effort on first enabled target).
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _noop():
    return {'status': 'skipped'}


async def _place_a_reduce_chunk(a_acc, a_symbol, side_indicator: str, qty: float) -> Dict[str, Any]:
    """Delegates to executor._dispatch_a_reduce for platform-aware reduce."""
    from app.services.agent.executor import _dispatch_a_reduce
    return await _dispatch_a_reduce(a_acc, a_symbol, side_indicator, qty)


async def execute_partial_reduce(
    db: AsyncSession,
    parent_decision_id: int,
    reduce_pct: float = 0.30,
    chunks: int = 5,
    chunk_interval_s: float = 30.0,
    ctx=None,
) -> Dict[str, Any]:
    """D4: reduce current positions by reduce_pct over N chunks with platform-aware A-leg."""
    # ── GATEWAY GUARD: must check mode/kill_switch before executing real trades ──
    try:
        from app.services.trading_gateway import is_trading_allowed
        gw = await is_trading_allowed(caller="partial_reduce")
        if not gw.allowed:
            logger.warning(f"[partial_reduce] BLOCKED by gateway: {gw.reason}")
            return {"success": False, "blocked": True, "reason": gw.reason,
                    "a_ok_count": 0, "b_ok_count": 0}
    except Exception as _gw_err:
        logger.error(f"[partial_reduce] gateway check FAILED: {_gw_err} — ABORTING for safety")
        return {"success": False, "blocked": True, "reason": f"gateway error: {_gw_err}",
                "a_ok_count": 0, "b_ok_count": 0}

    from app.services.agent.market_snapshot import collect_xau_positions_and_equity, fetch_conversion_factor
    from app.services.order_executor import order_executor
    from app.services.agent.feishu_broadcast import broadcast
    from app.services.agent.scope import list_active_contexts, resolve_a_b_accounts

    # Resolve ctx if not given — pick first enabled target (best-effort)
    if ctx is None:
        ctxs = await list_active_contexts(db)
        ctx = ctxs[0] if ctxs else None
    if ctx is None:
        return {'ok': False, 'reason': 'no_active_scope_target'}

    a_acc, b_acc = await resolve_a_b_accounts(db, ctx)
    if not a_acc or not b_acc:
        return {'ok': False, 'reason': f'account_not_found_for_scope:{ctx.label}'}

    eq = await collect_xau_positions_and_equity(db, ctx)
    a_size, b_size = eq['a_size'], eq['b_size']
    conv = ctx.conversion_factor
    a_symbol, b_symbol = ctx.a_symbol, ctx.b_symbol

    if abs(a_size) < 0.01 and abs(b_size) < 0.01:
        return {'ok': True, 'reason': 'no_position_nothing_to_reduce'}

    a_target_total = abs(a_size) * reduce_pct
    b_target_total = abs(b_size) * reduce_pct
    a_per_chunk = max(0.01, round(a_target_total / chunks, 2))
    b_per_chunk = max(0.01, round(b_target_total / chunks, 2))

    # Direction indicators
    a_indicator = 'sell_long' if a_size > 0 else 'buy_short'
    b_side = 'Buy' if b_size > 0 else 'Sell'  # opposite to close B

    logger.warning(
        f'[partial_reduce] start parent={parent_decision_id} scope={ctx.label} '
        f'pct={reduce_pct} chunks={chunks} a_per={a_per_chunk} b_per={b_per_chunk}'
    )

    chunk_results: List[Dict[str, Any]] = []
    for i in range(chunks):
        t0 = time.time()
        a_task = (_place_a_reduce_chunk(a_acc, a_symbol, a_indicator, a_per_chunk)
                  if abs(a_size) >= 0.01 else _noop())
        b_task = (order_executor.place_bybit_order(
                      account=b_acc, symbol=b_symbol, side=b_side, order_type='Market',
                      quantity=str(b_per_chunk), category='linear', close_position=False)
                  if abs(b_size) >= 0.01 else _noop())

        results = await asyncio.gather(a_task, b_task, return_exceptions=True)
        chunk = {
            'chunk': i + 1, 'elapsed_ms': int((time.time() - t0) * 1000),
            'a_result': str(results[0])[:300], 'b_result': str(results[1])[:300],
            'a_ok': not isinstance(results[0], Exception),
            'b_ok': not isinstance(results[1], Exception),
        }
        chunk_results.append(chunk)

        await db.execute(text("""
            INSERT INTO agent_decisions
              (trigger, market_snapshot, proposal, verdict, reject_reason,
               scope_user_id, scope_pair_code, scope_target_id)
            VALUES ('forced_reduce_chunk', '{}', CAST(:p AS JSONB), 'executed', :rr,
                    CAST(:su AS UUID), :sp, :st)
        """), {
            'p': __import__('json').dumps({
                'parent_decision_id': parent_decision_id,
                'chunk': i + 1, 'a_qty': a_per_chunk, 'b_qty': b_per_chunk,
                'scope': ctx.label,
            }),
            'rr': f'parent={parent_decision_id};chunk={i+1}/{chunks};scope={ctx.label}',
            'su': ctx.user_id, 'sp': ctx.pair_code, 'st': ctx.target_id,
        })
        await db.commit()

        if i < chunks - 1:
            await asyncio.sleep(chunk_interval_s)

    a_ok_count = sum(1 for c in chunk_results if c['a_ok'])
    b_ok_count = sum(1 for c in chunk_results if c['b_ok'])

    await broadcast(
        db, level='warn', category='partial_reduce_done',
        message=f'[{ctx.label}] 分批减仓完成 | 减幅 {reduce_pct*100:.0f}% | A: {a_ok_count}/{chunks} | B: {b_ok_count}/{chunks}',
        payload={'parent_decision_id': parent_decision_id, 'scope': ctx.label, 'chunks': chunk_results},
    )

    # R6: invalidate account cache so next Guard tick sees reduced positions
    try:
        from app.services.account_service import account_data_service
        account_data_service.invalidate_cache(str(a_acc.account_id))
        account_data_service.invalidate_cache(str(b_acc.account_id))
    except Exception:
        pass

    return {
        'ok': a_ok_count + b_ok_count > 0,
        'chunks': chunk_results,
        'a_ok_count': a_ok_count, 'b_ok_count': b_ok_count,
        'reduce_pct': reduce_pct,
        'scope': ctx.label,
    }
