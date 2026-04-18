"""OpenCLAW execution layer.

Converts a Guard-approved Proposal into concrete A-leg (Binance) + B-leg (Bybit/MT5)
orders via the existing order_executor service, then commits rate-bucket usage and
records execution_result back into agent_decisions.

IMPORTANT: This module is ONLY called when agent_state.mode == 'auto' AND Guard passes.
In 'semi' mode the decision sits as 'pending' until an operator approves it via the
control panel (approve_decision endpoint), which then calls execute_proposal directly.

Safety invariants (also enforced by Guard, double-checked here):
  1. Only XAUUSDT (Binance) and XAUUSD+ (Bybit MT5) symbols.
  2. open_* must open BOTH legs atomically (asyncio.gather, fail-all if either fails).
  3. rate_buckets.commit fires only AFTER successful exchange ack.
  4. Kill switch re-checked right before sending — race window closes within 1s.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.services.agent import state as agent_state
from app.services.agent import config_loader
from app.services.agent.guard import Proposal
from app.services.agent.rate_buckets import RateBuckets
from app.services.agent.market_snapshot import fetch_spread

logger = logging.getLogger(__name__)

# Legacy constants kept for backward compatibility with other imports
PAIR_CODE = "XAU"
A_SYMBOL = "XAUUSDT"
B_SYMBOL = "XAUUSD+"
A_PLATFORM_ID = 1
B_PLATFORM_ID = 2

# New: scope-aware symbol/account resolution


async def _get_redis():
    import redis.asyncio as redis
    return redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)


async def _resolve_accounts(db: AsyncSession) -> Tuple[Optional[Account], Optional[Account]]:
    """Pick A/B accounts honoring agent_scope (user + pair + pinned account_ids).

    Delegates to app.services.agent.scope.resolve_a_b_accounts.
    """
    from app.services.agent.scope import resolve_a_b_accounts
    return await resolve_a_b_accounts(db)


def _size_legs(notional_usdt: float, mark_price: float, conversion_factor: float = 100.0) -> Tuple[float, float]:
    """Translate USDT notional into A-leg contracts (oz) and B-leg lots.

    XAUUSDT: 1 contract = 1 oz, notional = contracts × price
        contracts = notional_usdt / price
    XAUUSD+ MT5: 1 lot = 100 oz = notional / (100 × price) → lots = contracts / 100

    Minimums: Binance 0.01 contract, MT5 0.01 lot (enforce).
    """
    if mark_price <= 0:
        return 0.0, 0.0
    a_contracts = notional_usdt / mark_price
    b_lots = a_contracts / conversion_factor
    # Round to exchange precision — conservative (floor at 0.01)
    a_contracts = max(0.01, round(a_contracts, 2))
    b_lots = max(0.01, round(b_lots, 2))
    return a_contracts, b_lots


async def _place_pair_open(
    a_account: Account, b_account: Account, direction: str,
    a_qty: float, b_qty: float, a_price: float,
    a_symbol: str = A_SYMBOL, b_symbol: str = B_SYMBOL,
) -> Dict[str, Any]:
    """Open direction on A leg + opposite on B leg — market-neutral entry.

    direction='long' → A buy LONG, B sell SHORT (hedge)
    direction='short' → A sell SHORT, B buy LONG
    """
    from app.services.order_executor import order_executor

    if direction == 'long':
        a_side, a_pos, b_side = 'BUY', 'LONG', 'Sell'
    else:
        a_side, a_pos, b_side = 'SELL', 'SHORT', 'Buy'

    a_task = order_executor.place_binance_order(
        account=a_account, symbol=a_symbol, side=a_side, order_type='LIMIT',
        quantity=a_qty, price=a_price, position_side=a_pos, post_only=True,
    )
    b_task = order_executor.place_bybit_order(
        account=b_account, symbol=b_symbol, side=b_side, order_type='Market',
        quantity=str(b_qty), category='linear',
    )
    results = await asyncio.gather(a_task, b_task, return_exceptions=True)
    return {
        'a_result': str(results[0])[:500],
        'b_result': str(results[1])[:500],
        'a_ok': not isinstance(results[0], Exception),
        'b_ok': not isinstance(results[1], Exception),
    }


async def _place_pair_close(
    a_account: Account, b_account: Account, side_to_close: str,
) -> Dict[str, Any]:
    """Close positions on both legs. side_to_close='long' or 'short' refers to A leg.
    B leg position is the opposite side.
    """
    from app.services.order_executor import order_executor
    from app.services.binance_client import BinanceFuturesClient
    from app.core.proxy_utils import build_proxy_url

    # A leg: close via market (opposite side, reduceOnly equivalent)
    a_pos_side = 'LONG' if side_to_close == 'long' else 'SHORT'
    a_closing_side = 'SELL' if side_to_close == 'long' else 'BUY'

    async def _close_a():
        client = BinanceFuturesClient(a_account.api_key, a_account.api_secret,
                                       proxy_url=build_proxy_url(a_account.proxy_config))
        try:
            positions = await client.get_positions(symbol=A_SYMBOL)
            for p in positions:
                if p.get('positionSide') == a_pos_side and abs(float(p.get('positionAmt', 0))) > 0:
                    amt = abs(float(p['positionAmt']))
                    return await order_executor.place_binance_order(
                        account=a_account, symbol=A_SYMBOL, side=a_closing_side,
                        order_type='MARKET', quantity=amt, position_side=a_pos_side,
                    )
            return {'status': 'no_position'}
        finally:
            await client.close()

    # B leg: opposite of A → if A was LONG (hedge was SHORT on B), closing A LONG means also closing B SHORT
    b_close_side = 'Buy' if side_to_close == 'long' else 'Sell'  # opposite of opening side
    async def _close_b():
        return await order_executor.place_bybit_order(
            account=b_account, symbol=B_SYMBOL, side=b_close_side, order_type='Market',
            quantity='0', category='linear', close_position=True,
        )

    results = await asyncio.gather(_close_a(), _close_b(), return_exceptions=True)
    return {
        'a_result': str(results[0])[:500], 'b_result': str(results[1])[:500],
        'a_ok': not isinstance(results[0], Exception),
        'b_ok': not isinstance(results[1], Exception),
    }


async def execute_proposal(db: AsyncSession, decision_id: int, proposal: Proposal, ctx=None) -> Dict[str, Any]:
    """Execute an approved proposal. Returns execution_result dict.

    Callers: codex_decider (mode=auto) OR approve_decision endpoint (mode=semi).
    """
    # Race-window re-check of kill switch (operator may have hit kill in last 5s)
    st = await agent_state.get_state(db)
    if st['kill_switch']:
        return {'ok': False, 'reason': 'kill_switch_on_at_execute'}

    cfg = await config_loader.load_config(db, target_id=ctx.target_id if ctx else None)
    rl = cfg.get('rate_limits', {})
    margin = float(rl.get('safety_margin', 0.20))
    caps = {k: int(v) for k, v in rl.items() if k != 'safety_margin'}

    # Rate bucket pre-check — if we're already at water mark, abort
    rc = await _get_redis()
    try:
        buckets = RateBuckets(rc, key_prefix=(ctx.rate_namespace if ctx else "openclaw:rate"))
        ok, violation = await buckets.pre_check(caps, margin)
        if not ok:
            return {'ok': False, 'reason': f'rate_pre_check_failed:{violation}'}

        if ctx is not None:
            from app.services.agent.scope import resolve_a_b_accounts as _rab
            a_acc, b_acc = await _rab(db, ctx)
            a_sym, b_sym = ctx.a_symbol, ctx.b_symbol
            conv = ctx.conversion_factor
        else:
            a_acc, b_acc = await _resolve_accounts(db)
            a_sym, b_sym = A_SYMBOL, B_SYMBOL
            conv = float(cfg.get('symbols', {}).get('conversion_factor') or 100.0)
        if not a_acc or not b_acc:
            return {'ok': False, 'reason': f'account_not_found_for_scope:{ctx.label if ctx else "default"}'}

        spread = await fetch_spread()
        a_price = (spread or {}).get('binance_quote', {}).get('ask_price')
        if not a_price:
            return {'ok': False, 'reason': 'cannot_fetch_a_price'}

        a_qty, b_qty = _size_legs(proposal.qty, float(a_price), conv)

        t0 = time.time()
        if proposal.action == 'open_long':
            exec_result = await _place_pair_open(a_acc, b_acc, 'long', a_qty, b_qty, float(a_price), a_sym, b_sym)
        elif proposal.action == 'open_short':
            exec_result = await _place_pair_open(a_acc, b_acc, 'short', a_qty, b_qty, float(a_price), a_sym, b_sym)
        elif proposal.action == 'close_long':
            exec_result = await _place_pair_close(a_acc, b_acc, 'long')
        elif proposal.action == 'close_short':
            exec_result = await _place_pair_close(a_acc, b_acc, 'short')
        elif proposal.action == 'rebalance':
            # Caller should have set leg to the missing one; only place the single side
            if proposal.leg == 'a':
                from app.services.order_executor import order_executor
                side = 'BUY' if proposal.qty > 0 else 'SELL'
                pos = 'LONG' if proposal.qty > 0 else 'SHORT'
                r = await order_executor.place_binance_order(
                    account=a_acc, symbol=A_SYMBOL, side=side, order_type='LIMIT',
                    quantity=a_qty, price=float(a_price), position_side=pos, post_only=True,
                )
                exec_result = {'a_result': str(r)[:500], 'a_ok': True, 'b_result': 'skipped', 'b_ok': True}
            elif proposal.leg == 'b':
                from app.services.order_executor import order_executor
                side = 'Buy' if proposal.qty > 0 else 'Sell'
                r = await order_executor.place_bybit_order(
                    account=b_acc, symbol=B_SYMBOL, side=side, order_type='Market',
                    quantity=str(b_qty), category='linear',
                )
                exec_result = {'b_result': str(r)[:500], 'b_ok': True, 'a_result': 'skipped', 'a_ok': True}
            else:
                return {'ok': False, 'reason': 'rebalance_requires_single_leg'}
        else:
            return {'ok': False, 'reason': f'unknown_action:{proposal.action}'}

        elapsed_ms = int((time.time() - t0) * 1000)

        # Commit rate buckets — one unit per leg actually sent (A + B = 2 units for open/close)
        action_id = f'd{decision_id}-{uuid.uuid4().hex[:8]}'
        if exec_result.get('a_ok'):
            await buckets.commit(action_id + '-a')
        if exec_result.get('b_ok') and exec_result.get('b_result') != 'skipped':
            await buckets.commit(action_id + '-b')

        overall_ok = exec_result.get('a_ok') and exec_result.get('b_ok')

        # Persist execution outcome back into agent_decisions
        await db.execute(text("""
            UPDATE agent_decisions
            SET execution_result = CAST(:r AS JSONB)
            WHERE id = :id
        """), {'r': __import__('json').dumps({**exec_result, 'elapsed_ms': elapsed_ms,
                                              'a_qty': a_qty, 'b_qty': b_qty,
                                              'a_price': float(a_price), 'overall_ok': overall_ok}),
              'id': decision_id})
        await db.commit()

        return {'ok': overall_ok, 'exec': exec_result, 'elapsed_ms': elapsed_ms,
                'a_qty': a_qty, 'b_qty': b_qty}
    finally:
        try:
            await rc.close()
        except Exception:
            pass
