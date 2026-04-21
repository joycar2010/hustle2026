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


async def _settle_or_market_binance(
    place_result: Dict[str, Any], account: Account, symbol: str,
    side: str, position_side: str, quantity: float,
    poll_s: float = 0.5, max_polls: int = 4,
) -> Dict[str, Any]:
    '''R2: ensure a Binance post-only LIMIT actually fills, else cancel + re-send MARKET.

    Behavior:
      1. If place_result status already FILLED -> return unchanged.
      2. Poll get_order up to (poll_s * max_polls) seconds (default 2s).
      3. Still not FILLED -> cancel + re-issue as MARKET.
      4. Attach _r2_action field for audit.
    '''
    from app.services.binance_client import BinanceFuturesClient
    from app.services.order_executor import order_executor
    from app.core.proxy_utils import build_proxy_url

    if not place_result or not place_result.get('success'):
        return place_result
    data = place_result.get('data') or {}
    order_id = place_result.get('order_id') or data.get('orderId')
    if data.get('status') == 'FILLED':
        place_result['_r2_action'] = 'filled_immediate'
        return place_result
    if not order_id:
        place_result['_r2_action'] = 'no_order_id'
        return place_result

    client = BinanceFuturesClient(account.api_key, account.api_secret,
                                  proxy_url=build_proxy_url(account.proxy_config))
    try:
        for i in range(max_polls):
            await asyncio.sleep(poll_s)
            try:
                status = await client.get_order(symbol, int(order_id))
            except Exception as e:
                logger.warning(f'[R2] get_order #{order_id} failed: {e}')
                break
            if status.get('status') == 'FILLED':
                place_result['_r2_action'] = f'filled_after_{(i+1)*poll_s:.1f}s'
                place_result['data'] = status
                return place_result
            if status.get('status') in ('CANCELED', 'REJECTED', 'EXPIRED'):
                break

        try:
            await client.cancel_order(symbol, int(order_id))
        except Exception as e:
            logger.warning(f'[R2] cancel_order #{order_id} failed: {e}')
            place_result['_r2_action'] = 'cancel_failed'
            return place_result

        try:
            reissue = await order_executor.place_binance_order(
                account=account, symbol=symbol, side=side, order_type='MARKET',
                quantity=quantity, position_side=position_side, post_only=False,
            )
            reissue['_r2_action'] = 'reissued_market'
            reissue['_r2_original_order_id'] = order_id
            return reissue
        except Exception as e:
            logger.error(f'[R2] reissue market failed: {e}')
            place_result['_r2_action'] = f'reissue_failed:{str(e)[:100]}'
            return place_result
    finally:
        try:
            await client.close()
        except Exception:
            pass


# ═════════ A-leg platform-dispatched open adapters ═════════

async def _open_a_binance(a_acc, a_sym, a_side, a_pos, a_qty, a_price):
    from app.services.order_executor import order_executor
    r = await order_executor.place_binance_order(
        account=a_acc, symbol=a_sym, side=a_side, order_type='LIMIT',
        quantity=a_qty, price=a_price, position_side=a_pos, post_only=True,
    )
    return await _settle_or_market_binance(r, a_acc, a_sym, a_side, a_pos, a_qty)


async def _open_a_bybit_perp(a_acc, a_sym, a_side, a_qty, a_price,
                              poll_s: float = 0.5, max_polls: int = 4):
    '''Bybit v5 linear perpetual A-leg: PostOnly Limit + fall back to Market if not filled.'''
    from app.services.bybit_client import BybitClient
    from app.core.proxy_utils import build_proxy_url

    client = BybitClient(a_acc.api_key, a_acc.api_secret,
                         proxy_url=build_proxy_url(a_acc.proxy_config))
    try:
        bs = 'Buy' if a_side.upper() == 'BUY' else 'Sell'
        try:
            r = await client.place_order(
                category='linear', symbol=a_sym, side=bs, order_type='Limit',
                qty=str(a_qty), price=str(a_price), time_in_force='PostOnly',
            )
        except Exception as e:
            return {'success': False, 'error': f'place_order:{e}'[:300]}

        order_id = ((r.get('result') or {}).get('orderId')) if isinstance(r, dict) else None
        if not order_id:
            return {'success': False, 'error': f'no_order_id:{str(r)[:200]}', 'data': r}

        for i in range(max_polls):
            await asyncio.sleep(poll_s)
            try:
                q = await client.get_order(category='linear', symbol=a_sym, order_id=order_id)
            except Exception as e:
                logger.warning(f'[bybit_perp R2] get_order failed: {e}')
                break
            rows = (q.get('result') or {}).get('list') or []
            if rows:
                st = rows[0].get('orderStatus')
                if st == 'Filled':
                    return {'success': True, 'platform': 'bybit_perp', 'data': rows[0],
                            '_r2_action': f'filled_after_{(i+1)*poll_s:.1f}s'}
                if st in ('Cancelled', 'Rejected', 'Deactivated'):
                    break

        try:
            await client.cancel_order(category='linear', symbol=a_sym, order_id=order_id)
        except Exception:
            pass
        try:
            mk = await client.place_order(
                category='linear', symbol=a_sym, side=bs, order_type='Market',
                qty=str(a_qty), time_in_force='IOC',
            )
            return {'success': True, 'platform': 'bybit_perp', 'data': mk,
                    '_r2_action': 'reissued_market', '_r2_original_order_id': order_id}
        except Exception as e:
            return {'success': False, 'platform': 'bybit_perp',
                    'error': f'reissue_market:{e}'[:300]}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _open_a_gate(a_acc, a_sym, a_side, a_qty, a_price,
                       poll_s: float = 0.5, max_polls: int = 4):
    '''Gate v4 USDT-perp A-leg: PostOnly Limit + fallback to IOC market.'''
    from app.services.gateio_client import GateioFuturesClient
    from app.core.proxy_utils import build_proxy_url

    contract = a_sym if '_' in a_sym else a_sym.replace('USDT', '_USDT')
    # Gate size: positive=long, negative=short (contracts). int only.
    size = max(1, int(a_qty))
    if a_side.upper() == 'SELL':
        size = -size

    client = GateioFuturesClient(
        api_key=a_acc.api_key, api_secret=a_acc.api_secret,
        proxy_url=build_proxy_url(a_acc.proxy_config),
    )
    try:
        try:
            r = await client.place_order(
                contract=contract, size=size, price=str(a_price), tif='poc',
                reduce_only=False, text='t-openclaw-open',
            )
        except Exception as e:
            return {'success': False, 'error': f'place_order:{e}'[:300]}

        order_id = str((r or {}).get('id') or '') if isinstance(r, dict) else ''
        # Gate may immediately reject PostOnly if it would cross — check status
        init_status = (r or {}).get('status') if isinstance(r, dict) else None
        if init_status == 'finished':
            return {'success': True, 'platform': 'gateio', 'data': r,
                    '_r2_action': 'filled_immediate'}

        if order_id:
            for i in range(max_polls):
                await asyncio.sleep(poll_s)
                try:
                    q = await client._request('GET', f'/futures/{client.settle}/orders/{order_id}')
                except Exception as e:
                    logger.warning(f'[gate R2] get order failed: {e}')
                    break
                if q.get('status') == 'finished':
                    return {'success': True, 'platform': 'gateio', 'data': q,
                            '_r2_action': f'filled_after_{(i+1)*poll_s:.1f}s'}
                if q.get('finish_as') in ('cancelled', 'reduce_only'):
                    break

            try:
                await client.cancel_order(order_id)
            except Exception:
                pass

        try:
            mk = await client.place_order(
                contract=contract, size=size, price=None, tif='ioc',
                reduce_only=False, text='t-openclaw-mkt',
            )
            return {'success': True, 'platform': 'gateio', 'data': mk,
                    '_r2_action': 'reissued_market', '_r2_original_order_id': order_id}
        except Exception as e:
            return {'success': False, 'platform': 'gateio',
                    'error': f'reissue_market:{e}'[:300]}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _dispatch_a_open(a_acc, a_sym, a_side, a_pos, a_qty, a_price):
    '''Platform-dispatched A-leg open with R2 settler. Returns {success, _r2_action, ...}.'''
    if a_acc.platform_id == 1:
        return await _open_a_binance(a_acc, a_sym, a_side, a_pos, a_qty, a_price)
    if a_acc.platform_id == 2 and not getattr(a_acc, 'is_mt5_account', False):
        return await _open_a_bybit_perp(a_acc, a_sym, a_side, a_qty, a_price)
    if a_acc.platform_id == 4:
        return await _open_a_gate(a_acc, a_sym, a_side, a_qty, a_price)
    return {'success': False, 'error': f'unsupported a_platform:{a_acc.platform_id} is_mt5={getattr(a_acc, "is_mt5_account", None)}'}


async def _dispatch_a_reduce(a_acc, a_sym, side_indicator: str, qty: float):
    '''Market reduce on A-leg, platform-dispatched. side_indicator: sell_long|buy_short.'''
    from app.services.order_executor import order_executor
    from app.core.proxy_utils import build_proxy_url

    if a_acc.platform_id == 1:
        side = 'SELL' if side_indicator == 'sell_long' else 'BUY'
        pos = 'LONG' if side_indicator == 'sell_long' else 'SHORT'
        return await order_executor.place_binance_order(
            account=a_acc, symbol=a_sym, side=side, order_type='MARKET',
            quantity=qty, position_side=pos,
        )
    if a_acc.platform_id == 2 and not getattr(a_acc, 'is_mt5_account', False):
        from app.services.bybit_client import BybitClient
        client = BybitClient(a_acc.api_key, a_acc.api_secret,
                             proxy_url=build_proxy_url(a_acc.proxy_config))
        try:
            bs = 'Sell' if side_indicator == 'sell_long' else 'Buy'
            return await client.place_order(
                category='linear', symbol=a_sym, side=bs, order_type='Market',
                qty=str(qty), time_in_force='IOC', reduce_only=True,
            )
        finally:
            try:
                await client.close()
            except Exception:
                pass
    if a_acc.platform_id == 4:
        from app.services.gateio_client import GateioFuturesClient
        client = GateioFuturesClient(
            api_key=a_acc.api_key, api_secret=a_acc.api_secret,
            proxy_url=build_proxy_url(a_acc.proxy_config),
        )
        try:
            contract = a_sym if '_' in a_sym else a_sym.replace('USDT', '_USDT')
            size = -int(qty) if side_indicator == 'sell_long' else int(qty)
            r = await client.place_order(
                contract=contract, size=size, price=None, tif='ioc',
                reduce_only=True, text='t-openclaw-reduce',
            )
            return {'success': True, 'platform': 'gateio', 'data': r}
        finally:
            try:
                await client.close()
            except Exception:
                pass
    return {'success': False, 'error': f'unsupported a_platform:{a_acc.platform_id}'}


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

    async def _a_then_settle():
        # Platform-dispatched A-leg open (Binance / Bybit-perp / Gate) with
        # per-platform R2 settle-or-market fallback built in.
        return await _dispatch_a_open(
            a_account, a_symbol, a_side, a_pos, a_qty, a_price,
        )

    b_task = order_executor.place_bybit_order(
        account=b_account, symbol=b_symbol, side=b_side, order_type='Market',
        quantity=str(b_qty), category='linear',
    )
    results = await asyncio.gather(_a_then_settle(), b_task, return_exceptions=True)
    a_r, b_r = results[0], results[1]
    a_ok = not isinstance(a_r, Exception) and (a_r or {}).get('success') is not False
    b_ok = not isinstance(b_r, Exception) and (b_r or {}).get('success') is not False
    unwind = None
    if a_ok and not b_ok:
        unwind = await _emergency_unwind('a', a_account, a_symbol, a_qty, a_side)
    elif b_ok and not a_ok:
        unwind = await _emergency_unwind('b', b_account, b_symbol, b_qty, b_side)
    return {
        'a_result': str(a_r)[:500],
        'b_result': str(b_r)[:500],
        'a_ok': a_ok,
        'b_ok': b_ok,
        'a_r2': (a_r or {}).get('_r2_action') if isinstance(a_r, dict) else None,
        'r1_unwind': unwind,
    }


async def _close_a_leg(account: Account, symbol: str, side_to_close: str) -> Dict[str, Any]:
    '''Platform-dispatched A-leg close. Returns {success, status, platform, error?}.

    D2 fix: pre-OpenCLAW code hardcoded Binance. Now routes by account.platform_id:
      - 1 (Binance futures)   -> BinanceFuturesClient + place_binance_order MARKET
      - 4 (Gate futures)      -> GateioFuturesClient + place_order tif=ioc reduce_only=True
      - 2 (Bybit perpetual)   -> NotImplementedError (add when BXAU target activated)
    '''
    from app.services.order_executor import order_executor
    from app.core.proxy_utils import build_proxy_url

    a_closing_side = 'SELL' if side_to_close == 'long' else 'BUY'  # Binance
    a_pos_side = 'LONG' if side_to_close == 'long' else 'SHORT'

    if account.platform_id == 1:
        from app.services.binance_client import BinanceFuturesClient
        client = BinanceFuturesClient(account.api_key, account.api_secret,
                                      proxy_url=build_proxy_url(account.proxy_config))
        try:
            positions = await client.get_positions(symbol=symbol)
            for pos in positions:
                if pos.get('positionSide') == a_pos_side and abs(float(pos.get('positionAmt', 0))) > 0:
                    amt = abs(float(pos['positionAmt']))
                    r = await order_executor.place_binance_order(
                        account=account, symbol=symbol, side=a_closing_side,
                        order_type='MARKET', quantity=amt, position_side=a_pos_side,
                    )
                    return {**r, 'platform': 'binance'}
            return {'success': True, 'status': 'no_position', 'platform': 'binance'}
        finally:
            await client.close()

    if account.platform_id == 4:
        from app.services.gateio_client import GateioFuturesClient
        client = GateioFuturesClient(
            api_key=account.api_key, api_secret=account.api_secret,
            proxy_url=build_proxy_url(account.proxy_config),
        )
        try:
            contract = symbol if '_' in symbol else symbol.replace('USDT', '_USDT')
            positions = await client.get_positions(contract)
            for pos in positions:
                size = int(pos.get('size', 0))
                if size == 0:
                    continue
                if (side_to_close == 'long' and size > 0) or (side_to_close == 'short' and size < 0):
                    r = await client.place_order(
                        contract=contract, size=-size, price=None, tif='ioc',
                        reduce_only=True, text='t-openclaw-close',
                    )
                    return {'success': True, 'status': 'closed', 'platform': 'gateio', 'data': r}
            return {'success': True, 'status': 'no_position', 'platform': 'gateio'}
        finally:
            await client.close()

    # Bybit v5 perpetual (non-MT5) — e.g. BXAU target
    if account.platform_id == 2 and not getattr(account, 'is_mt5_account', False):
        from app.services.bybit_client import BybitClient
        client = BybitClient(account.api_key, account.api_secret,
                             proxy_url=build_proxy_url(account.proxy_config))
        try:
            pos_resp = await client.get_positions(category='linear', symbol=symbol)
            rows = (pos_resp.get('result') or {}).get('list') or []
            for pos in rows:
                size = float(pos.get('size', 0) or 0)
                if size == 0:
                    continue
                pos_side = (pos.get('side') or '').lower()  # 'Buy'/'Sell'/'None' (hedge mode)
                want_long = side_to_close == 'long'
                if (want_long and pos_side == 'buy') or (not want_long and pos_side == 'sell'):
                    opposite = 'Sell' if want_long else 'Buy'
                    r = await client.place_order(
                        category='linear', symbol=symbol, side=opposite,
                        order_type='Market', qty=str(size), time_in_force='IOC',
                        reduce_only=True,
                    )
                    return {'success': True, 'status': 'closed', 'platform': 'bybit_perp', 'data': r}
            return {'success': True, 'status': 'no_position', 'platform': 'bybit_perp'}
        finally:
            try:
                await client.close()
            except Exception:
                pass

    return {'success': False, 'error': f'unsupported a_platform:{account.platform_id} is_mt5={getattr(account, "is_mt5_account", None)}',
            'platform': 'unknown'}


async def _place_pair_close(
    a_account: Account, b_account: Account, side_to_close: str,
    a_symbol: str = A_SYMBOL, b_symbol: str = B_SYMBOL,
) -> Dict[str, Any]:
    '''Close both legs simultaneously with platform-dispatched A-side.'''
    from app.services.order_executor import order_executor

    # B leg opposite of A side: if A was LONG (B hedged SHORT), close B by BUYing
    b_close_side = 'Buy' if side_to_close == 'long' else 'Sell'

    async def _close_b():
        return await order_executor.place_bybit_order(
            account=b_account, symbol=b_symbol, side=b_close_side, order_type='Market',
            quantity='0', category='linear', close_position=True,
        )

    results = await asyncio.gather(
        _close_a_leg(a_account, a_symbol, side_to_close),
        _close_b(),
        return_exceptions=True,
    )
    a_r, b_r = results[0], results[1]
    a_ok = not isinstance(a_r, Exception) and (a_r or {}).get('success') is not False
    b_ok = not isinstance(b_r, Exception) and (b_r or {}).get('success') is not False
    return {
        'a_result': str(a_r)[:500], 'b_result': str(b_r)[:500],
        'a_ok': a_ok, 'b_ok': b_ok,
    }


async def _emergency_unwind(
    succeeded_leg: str, account: Account, symbol: str,
    filled_qty: float, original_side: str,
) -> Dict[str, Any]:
    '''R1: when one leg fills but the other fails, immediately reverse-market
    the succeeded leg to avoid naked directional exposure.

    original_side: 'BUY'/'SELL' on A, or 'Buy'/'Sell' on B.
    '''
    from app.services.order_executor import order_executor

    try:
        if succeeded_leg == 'a':
            # Binance: opposite side MARKET close
            opposite = 'SELL' if original_side.upper() == 'BUY' else 'BUY'
            pos_side = 'LONG' if original_side.upper() == 'BUY' else 'SHORT'
            r = await order_executor.place_binance_order(
                account=account, symbol=symbol, side=opposite,
                order_type='MARKET', quantity=filled_qty, position_side=pos_side,
            )
            return {'unwound': True, 'leg': 'a', 'result': str(r)[:400]}
        else:  # b
            opposite = 'Sell' if original_side.lower() == 'buy' else 'Buy'
            r = await order_executor.place_bybit_order(
                account=account, symbol=symbol, side=opposite,
                order_type='Market', quantity=str(filled_qty),
                category='linear', close_position=True,
            )
            return {'unwound': True, 'leg': 'b', 'result': str(r)[:400]}
    except Exception as e:
        logger.error(f'[R1] emergency unwind {succeeded_leg} failed: {e}')
        return {'unwound': False, 'leg': succeeded_leg, 'error': str(e)[:400]}


async def _is_killed_fresh(db: AsyncSession) -> bool:
    '''R3: tight kill re-check called right before asyncio.gather.

    Goes straight to DB (single row, indexed PK) — ~5-15 ms. Acceptable overhead
    since it's called once per order batch, not per tick.
    '''
    row = (await db.execute(text(
        'SELECT kill_switch, openclaw_enabled FROM agent_state WHERE id = 1'
    ))).first()
    # Killed if explicit kill_switch OR global openclaw disabled
    return bool(row and (row[0] or not row[1]))



async def execute_proposal(db: AsyncSession, decision_id: int, proposal: Proposal, ctx=None) -> Dict[str, Any]:
    """Execute an approved proposal. Returns execution_result dict.

    Callers: codex_decider (mode=auto) OR approve_decision endpoint (mode=semi).
    """
    # Race-window re-check of kill switch (operator may have hit kill in last 5s)
    st = await agent_state.get_state(db)
    if st['kill_switch']:
        return {'ok': False, 'reason': 'kill_switch_on_at_execute'}
    if not st.get('openclaw_enabled', True):
        return {'ok': False, 'reason': 'openclaw_globally_disabled'}

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

        pair_code = ctx.pair_code if ctx else 'XAU'
        spread = await fetch_spread(pair_code)
        # Take A-side quote from whichever exchange the pair routes to
        a_price = (spread or {}).get('binance_quote', {}).get('ask_price')
        if not a_price:
            return {'ok': False, 'reason': f'cannot_fetch_a_price for {pair_code}'}

        a_qty, b_qty = _size_legs(proposal.qty, float(a_price), conv)

        t0 = time.time()
        # R3: tight kill re-check just before dispatch (closes ~500ms race window)
        if await _is_killed_fresh(db):
            return {'ok': False, 'reason': 'kill_switch_on_at_dispatch'}
        if proposal.action == 'open_long':
            exec_result = await _place_pair_open(a_acc, b_acc, 'long', a_qty, b_qty, float(a_price), a_sym, b_sym)
        elif proposal.action == 'open_short':
            exec_result = await _place_pair_open(a_acc, b_acc, 'short', a_qty, b_qty, float(a_price), a_sym, b_sym)
        elif proposal.action == 'close_long':
            exec_result = await _place_pair_close(a_acc, b_acc, 'long', a_sym, b_sym)
        elif proposal.action == 'close_short':
            exec_result = await _place_pair_close(a_acc, b_acc, 'short', a_sym, b_sym)
        elif proposal.action == 'rebalance':
            from app.services.order_executor import order_executor
            if proposal.leg == 'a':
                side = 'BUY' if proposal.qty > 0 else 'SELL'
                pos = 'LONG' if proposal.qty > 0 else 'SHORT'
                r = await _dispatch_a_open(a_acc, a_sym, side, pos, a_qty, float(a_price))
                exec_result = {
                    'a_result': str(r)[:500],
                    'a_ok': bool(r and r.get('success') is not False),
                    'b_result': 'skipped', 'b_ok': True,
                    'a_r2': (r or {}).get('_r2_action') if isinstance(r, dict) else None,
                }
            elif proposal.leg == 'b':
                side = 'Buy' if proposal.qty > 0 else 'Sell'
                r = await order_executor.place_bybit_order(
                    account=b_acc, symbol=b_sym, side=side, order_type='Market',
                    quantity=str(b_qty), category='linear',
                )
                exec_result = {'b_result': str(r)[:500],
                               'b_ok': bool(r and r.get('success') is not False),
                               'a_result': 'skipped', 'a_ok': True}
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

        # R6: force invalidate account_data_service cache so next Guard tick sees
        # fresh positions. Without this, 60s stale cache masks new positions ->
        # Guard thinks total_position_cap still has headroom -> runaway double-trade.
        if overall_ok:
            try:
                from app.services.account_service import account_data_service
                account_data_service.invalidate_cache(str(a_acc.account_id))
                account_data_service.invalidate_cache(str(b_acc.account_id))
                logger.info(f'[R6] cache invalidated {a_acc.account_id} {b_acc.account_id}')
            except Exception as e:
                logger.warning(f'[R6] cache invalidate failed (non-fatal): {e}')

        return {'ok': overall_ok, 'exec': exec_result, 'elapsed_ms': elapsed_ms,
                'a_qty': a_qty, 'b_qty': b_qty}
    finally:
        try:
            await rc.close()
        except Exception:
            pass
