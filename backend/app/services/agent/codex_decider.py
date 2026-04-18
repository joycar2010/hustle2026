"""OpenCLAW orchestrator: snapshot → LLM → Guard → log → (shadow/execute).

A single decide() call:
  1. Build MarketState from live sources
  2. Call Codex with (system_prompt, user_prompt with snapshot)
  3. Parse JSON → Proposal
  4. Run Guard (deterministic rules)
  5. Determine verdict:
       - kill_switch ON              → 'rejected' (kill)
       - mode = off                  → 'rejected' (off)
       - mode = shadow               → 'shadow'    (log, no action)
       - mode = semi  + needs_approval → 'pending' (await operator)
       - mode = semi/auto + Guard ok → 'executed' (P2: actually trade)
       - Guard violations            → 'rejected'
  6. Persist to agent_decisions; broadcast to Feishu when significant.

In P1 the 'executed' branch logs only; actual order routing wires in P2.
"""
import json
import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from dataclasses import asdict

from app.services.agent import config_loader, state as agent_state
from app.services.agent.system_prompt import OPENCLAW_SYSTEM_PROMPT
from app.services.agent.market_snapshot import build_snapshot, snapshot_to_user_prompt
from app.services.agent.codex_client import call_decider
from app.services.agent.guard import Proposal, run_guard, GuardResult
from app.services.agent.feishu_broadcast import broadcast

logger = logging.getLogger(__name__)


async def decide(db: AsyncSession, trigger: str, ctx=None, force_log: bool = True) -> Dict[str, Any]:
    snap = await build_snapshot(db, ctx)
    if not snap:
        logger.warning('[decider] cannot build snapshot, skipping')
        return {'verdict': 'skipped', 'reason': 'no_snapshot'}

    state = await agent_state.get_state(db)
    cfg = await config_loader.load_config(db, target_id=ctx.target_id if ctx else None)
    mode = state['mode']
    kill = state['kill_switch']

    user_prompt = snapshot_to_user_prompt(snap)
    proposal_json: Optional[Dict[str, Any]] = None
    usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    latency_ms = 0
    llm_error: Optional[str] = None

    try:
        proposal_json, usage, latency_ms = await call_decider(OPENCLAW_SYSTEM_PROMPT, user_prompt, db=db)
    except Exception as e:
        llm_error = str(e)[:500]
        logger.error(f'[decider] LLM call failed: {llm_error}')

    if not proposal_json:
        verdict = 'rejected'
        reject_reason = f'llm_failed:{llm_error}' if llm_error else 'llm_returned_no_json'
        proposal_dict = {}
    else:
        try:
            p = Proposal(
                action=proposal_json.get('action', 'noop'),
                leg=proposal_json.get('leg', 'both'),
                qty=float(proposal_json.get('qty', 0)),
                reason=proposal_json.get('reason', ''),
                trigger=proposal_json.get('trigger', trigger),
                confidence=float(proposal_json.get('confidence', 0)),
                is_rebalance_补腿=bool(proposal_json.get('is_rebalance_补腿', False)),
            )
        except (ValueError, TypeError) as e:
            verdict = 'rejected'
            reject_reason = f'bad_proposal_format:{e}'
            proposal_dict = proposal_json
        else:
            proposal_dict = asdict(p)
            guard_result: GuardResult = run_guard(p, snap, cfg)

            if kill:
                verdict = 'rejected'
                reject_reason = 'kill_switch_on'
            elif mode == 'off':
                verdict = 'rejected'
                reject_reason = 'mode_off'
            elif not guard_result.ok:
                verdict = 'rejected'
                reject_reason = 'guard:' + ';'.join(guard_result.violations)
            elif p.action == 'noop':
                verdict = 'shadow' if mode == 'shadow' else 'executed'
                reject_reason = None
            elif mode == 'shadow':
                verdict = 'shadow'
                reject_reason = None
            elif mode == 'semi':
                # P1: all non-noop in semi → pending operator approval
                verdict = 'pending'
                reject_reason = None
            else:  # auto — P2 execution layer active
                verdict = 'executed'
                reject_reason = None
                # Execution happens AFTER the initial INSERT below (needs decision_id)

    snapshot_dict = asdict(snap)
    res = await db.execute(text('''
        INSERT INTO agent_decisions
          (trigger, market_snapshot, proposal, verdict, reject_reason,
           llm_tokens_in, llm_tokens_out, llm_latency_ms,
           scope_user_id, scope_pair_code, scope_target_id)
        VALUES (:tr, CAST(:ms AS JSONB), CAST(:pp AS JSONB), :v, :rr,
                :ti, :to, :lt,
                CAST(:sui AS UUID), :spc, :stid)
        RETURNING id
    '''), {
        'tr': trigger,
        'ms': json.dumps(snapshot_dict, default=str),
        'pp': json.dumps(proposal_dict, default=str),
        'v': verdict,
        'rr': reject_reason,
        'ti': usage['prompt_tokens'],
        'to': usage['completion_tokens'],
        'lt': latency_ms,
        'sui': ctx.user_id if ctx else None,
        'spc': ctx.pair_code if ctx else None,
        'stid': ctx.target_id if ctx else None,
    })
    decision_id = res.scalar_one()
    await db.execute(text('UPDATE agent_state SET last_decision_at=NOW() WHERE id=1'))
    await db.commit()

    # In auto mode with an actionable verdict, fire the execution layer
    if verdict == 'executed' and proposal_dict.get('action', 'noop') != 'noop':
        try:
            from app.services.agent.executor import execute_proposal as _exec
            _ = await _exec(db, decision_id, p, ctx=ctx)
        except Exception as e:
            logger.error(f'[decider] executor raised: {e}')
            await db.execute(text("""UPDATE agent_decisions SET verdict='rejected', reject_reason=:r WHERE id=:id"""),
                             {'r': f'executor_error:{str(e)[:200]}', 'id': decision_id})
            await db.commit()
            verdict = 'rejected'
            reject_reason = 'executor_error'

    # Broadcast significant events to Feishu
    is_action = proposal_dict.get('action', 'noop') not in ('noop', '')
    if verdict in ('rejected', 'pending') and is_action:
        await broadcast(db, level='warn' if verdict == 'rejected' else 'info',
                        category='decision_' + verdict,
                        message=f'[{ctx.label if ctx else "global"}] 决策#{decision_id} {verdict}: action={proposal_dict.get("action")} leg={proposal_dict.get("leg")} qty={proposal_dict.get("qty")}'
                                + (f' | {reject_reason}' if reject_reason else ''),
                        payload={'decision_id': decision_id, 'trigger': trigger})
    elif verdict == 'shadow' and is_action:
        await broadcast(db, level='info', category='shadow_decision',
                        message=f'[Shadow][{ctx.label if ctx else "global"}] 决策#{decision_id} 提议 {proposal_dict.get("action")} leg={proposal_dict.get("leg")} qty={proposal_dict.get("qty")}（未执行）',
                        payload={'decision_id': decision_id, 'trigger': trigger})

    logger.info(f'[decider] decision#{decision_id} verdict={verdict} action={proposal_dict.get("action")} latency={latency_ms}ms tokens={usage["total_tokens"]}')

    return {
        'decision_id': decision_id,
        'verdict': verdict,
        'reject_reason': reject_reason,
        'proposal': proposal_dict,
        'usage': usage,
        'latency_ms': latency_ms,
    }
