"""Event-driven agent loop.

Polls Go market service every 5s to push spread samples; in parallel runs
event triggers that fire decide() when:
  - spread crosses threshold (1.5, 1.8, 5.0)
  - 60s heartbeat (forces a noop-or-act recheck)
  - leg imbalance detected (handled by leg_monitor → triggers via shared queue)

Background task started on FastAPI startup. Cooldown: at most 1 decision
per 30s for the same trigger family to avoid LLM/cost runaway.
"""
import asyncio
import logging
import time
from typing import Dict
from app.core.database import AsyncSessionLocal
from app.services.agent.market_snapshot import fetch_spread, push_spread_sample, spread_30m_avg
from app.services.agent.codex_decider import decide
from app.services.agent import state as agent_state

logger = logging.getLogger(__name__)

_last_trigger_ts: Dict[str, float] = {}
COOLDOWN_S = 30
HEARTBEAT_S = 60
SPREAD_THRESHOLDS = [1.5, 1.8, 5.0]
_last_avg = 0.0


def _can_trigger(name: str) -> bool:
    now = time.time()
    if now - _last_trigger_ts.get(name, 0) < COOLDOWN_S:
        return False
    _last_trigger_ts[name] = now
    return True


async def _heartbeat_tick(db) -> None:
    from app.services.agent.scope import list_active_contexts
    targets = await list_active_contexts(db)
    if not targets:
        # No targets configured — single legacy decide for KPI continuity
        if _can_trigger('heartbeat:global'):
            await decide(db, trigger='heartbeat_60s')
        return
    for ctx in targets:
        key = f'heartbeat:{ctx.target_id}'
        if _can_trigger(key):
            await decide(db, trigger='heartbeat_60s', ctx=ctx)


async def _spread_threshold_tick(db) -> None:
    global _last_avg
    from app.services.agent.scope import list_active_contexts
    avg = spread_30m_avg()
    triggered_name = None
    for thr in SPREAD_THRESHOLDS:
        crossed_up = _last_avg < thr <= avg
        crossed_dn = _last_avg > -thr >= avg
        if crossed_up or crossed_dn:
            triggered_name = f'spread_cross_{thr if crossed_up else -thr}'
            break
    _last_avg = avg
    if not triggered_name:
        return
    targets = await list_active_contexts(db)
    if not targets:
        if _can_trigger(f'{triggered_name}:global'):
            await decide(db, trigger=triggered_name)
        return
    for ctx in targets:
        key = f'{triggered_name}:t{ctx.target_id}'
        if _can_trigger(key):
            await decide(db, trigger=triggered_name, ctx=ctx)


async def agent_loop_main(stop_event: asyncio.Event):
    logger.info('[agent_loop] OpenCLAW loop started')
    last_heartbeat = 0.0
    while not stop_event.is_set():
        try:
            # Per-pair spread sampling — iterate active targets, push to their window
            try:
                from app.services.agent.scope import list_active_contexts
                async with AsyncSessionLocal() as _db:
                    _active = await list_active_contexts(_db)
                if _active:
                    for _c in _active:
                        sp = await fetch_spread(_c.pair_code)
                        if sp:
                            push_spread_sample(sp.get('forward_entry_spread', 0.0), target_id=_c.target_id)
                else:
                    sp = await fetch_spread('XAU')
                    if sp:
                        push_spread_sample(sp.get('forward_entry_spread', 0.0))
            except Exception as _spread_err:
                logger.warning(f'[agent_loop] spread sample error: {_spread_err}')
            async with AsyncSessionLocal() as db:
                state = await agent_state.get_state(db)
                if state['kill_switch'] or state['mode'] == 'off':
                    pass  # collect samples but no decisions
                else:
                    await _spread_threshold_tick(db)
                    if time.time() - last_heartbeat > HEARTBEAT_S:
                        last_heartbeat = time.time()
                        await _heartbeat_tick(db)
        except Exception as e:
            logger.error(f'[agent_loop] tick error: {e}')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
    logger.info('[agent_loop] stopped')


_stop_event: asyncio.Event = None
_task: asyncio.Task = None


def start():
    global _stop_event, _task
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(agent_loop_main(_stop_event))
    logger.info('[agent_loop] task scheduled')


async def stop():
    global _stop_event, _task
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except asyncio.TimeoutError:
            _task.cancel()
