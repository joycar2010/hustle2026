"""OpenCLAW agent API — control panel + execution triggers (P3.5).

RBAC: ALL endpoints require role ∈ {超级管理员, 系统管理员, super_admin, system_admin, admin}.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user_id
from app.core.database import get_db
from app.models.user import User
from app.services.agent import config_loader
from app.services.agent import state as agent_state
from app.services.agent.rate_buckets import RateBuckets

router = APIRouter()

ADMIN_ROLES = {'超级管理员', '系统管理员', 'super_admin', 'system_admin', 'admin'}

_redis = None


def _get_redis():
    global _redis
    if _redis is None:
        import redis.asyncio as redis
        _redis = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)
    return _redis


async def require_admin(db: AsyncSession = Depends(get_db),
                        user_id: str = Depends(get_current_user_id)) -> str:
    row = (await db.execute(text("SELECT role FROM users WHERE user_id = CAST(:u AS UUID)"),
                            {'u': user_id})).first()
    if not row or row[0] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail='OpenCLAW 控制台仅限超级管理员/系统管理员访问')
    return user_id


# ───── Read ─────

@router.get('/whoami')
async def whoami(db: AsyncSession = Depends(get_db),
                 user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    """Lightweight check used by frontend route guard."""
    row = (await db.execute(text("SELECT username, role FROM users WHERE user_id = CAST(:u AS UUID)"),
                            {'u': user_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail='user_not_found')
    return {'user_id': user_id, 'username': row[0], 'role': row[1],
            'is_admin': row[1] in ADMIN_ROLES}


@router.get('/status')
async def get_status(target_id: Optional[int] = Query(None),
                     db: AsyncSession = Depends(get_db),
                     user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    s = await agent_state.get_state(db)
    cfg = await config_loader.load_config(db)
    try:
        from app.services.agent.market_snapshot import collect_xau_positions_and_equity, daily_traded_volume, spread_30m_avg, fetch_conversion_factor
        from app.services.agent.scope import list_active_contexts
        ctx = None
        if target_id is not None:
            for c in await list_active_contexts(db):
                if c.target_id == target_id:
                    ctx = c
                    break
        eq = await collect_xau_positions_and_equity(db, ctx)
        vol = await daily_traded_volume(db, ctx)
        conv_factor = await fetch_conversion_factor(db, ctx)
        a_notional = abs(eq['a_size'])
        b_notional = abs(eq['b_size']) * conv_factor
        total_pos = (a_notional + b_notional) / 2
        position_ratio = (total_pos / eq['total_equity']) if eq['total_equity'] else 0
        daily_ratio = (vol / eq['total_equity']) if eq['total_equity'] else 0
        spread_avg = spread_30m_avg(target_id=(ctx.target_id if ctx else None))
    except Exception:
        position_ratio = daily_ratio = spread_avg = 0.0
        eq = {'total_equity': 0, 'a_equity': 0, 'b_equity': 0}

    return {
        'mode': s['mode'], 'kill_switch': s['kill_switch'],
        'shadow_started_at': s.get('shadow_started_at').isoformat() if s.get('shadow_started_at') else None,
        'last_decision_at': s.get('last_decision_at').isoformat() if s.get('last_decision_at') else None,
        'position_ratio': position_ratio, 'daily_volume_ratio': daily_ratio,
        'spread_30m_avg': spread_avg,
        'total_equity': eq['total_equity'], 'a_equity': eq['a_equity'], 'b_equity': eq['b_equity'],
        'config_version': len(cfg),
    }


@router.get('/llm-stats')
async def get_llm_stats(db: AsyncSession = Depends(get_db), user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Tokens used today + relay balance + selected model."""
    cfg = await config_loader.load_config(db)
    ls = cfg.get('llm_settings', {}) or {}

    # Today + lifetime token usage from agent_decisions
    rows = (await db.execute(text("""
        SELECT
          COALESCE(SUM(CASE WHEN created_at >= CURRENT_DATE THEN llm_tokens_in END), 0) AS today_in,
          COALESCE(SUM(CASE WHEN created_at >= CURRENT_DATE THEN llm_tokens_out END), 0) AS today_out,
          COALESCE(SUM(llm_tokens_in), 0) AS total_in,
          COALESCE(SUM(llm_tokens_out), 0) AS total_out,
          COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS today_calls,
          COUNT(*) AS total_calls
        FROM agent_decisions
    """))).first()

    from app.services.agent.balance_monitor import compute_balance
    balance = await compute_balance(db)

    return {
        'model': ls.get('model'),
        'streaming': ls.get('streaming', True),
        'available_models': ls.get('available_models', []),
        'tokens_today': {'in': int(rows[0]), 'out': int(rows[1]), 'total': int(rows[0]) + int(rows[1]), 'calls': int(rows[4])},
        'tokens_total': {'in': int(rows[2]), 'out': int(rows[3]), 'total': int(rows[2]) + int(rows[3]), 'calls': int(rows[5])},
        'balance': balance,
    }


@router.get('/leg-balance')
async def get_leg_balance(target_id: Optional[int] = Query(None),
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    try:
        from app.services.agent.market_snapshot import collect_xau_positions_and_equity, fetch_conversion_factor
        from app.services.agent.scope import list_active_contexts
        ctx = None
        if target_id is not None:
            for c in await list_active_contexts(db):
                if c.target_id == target_id:
                    ctx = c
                    break
        eq = await collect_xau_positions_and_equity(db, ctx)
        conv = await fetch_conversion_factor(db, ctx)
        delta = eq['a_size'] - eq['b_size'] * conv
        return {
            'a_size': eq['a_size'], 'b_size': eq['b_size'],
            'delta': delta, 'conversion_factor': conv,
            'a_symbol': ctx.a_symbol if ctx else 'XAUUSDT',
            'b_symbol': ctx.b_symbol if ctx else 'XAUUSD+',
            'a_platform_id': ctx.a_platform_id if ctx else 1,
            'b_platform_id': ctx.b_platform_id if ctx else 2,
            'pair_code': ctx.pair_code if ctx else None,
            'target_label': ctx.label if ctx else '全部聚合',
        }
    except Exception as e:
        return {'a_size': 0, 'b_size': 0, 'delta': 0, 'conversion_factor': 1, 'error': str(e)}


@router.get('/rate-buckets')
async def get_rate_buckets(target_id: Optional[int] = Query(None),
                           db: AsyncSession = Depends(get_db),
                           user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    cfg = await config_loader.load_config(db, target_id=target_id)
    rl = cfg.get('rate_limits', {})
    margin = float(rl.get('safety_margin', 0.20))
    caps = {k: int(v) for k, v in rl.items() if k != 'safety_margin'}
    prefix = f'openclaw:rate:t{target_id}' if target_id is not None else 'openclaw:rate'
    rb = RateBuckets(_get_redis(), key_prefix=prefix)
    usage = await rb.usage(caps, margin)
    return {'safety_margin': margin, 'scope_key_prefix': prefix, 'buckets': [
        {'window': u.window, 'used': u.used, 'cap': u.cap, 'effective_cap': u.effective_cap}
        for u in usage
    ]}


@router.get('/decisions')
async def list_decisions(limit: int = Query(50, le=200),
                         target_id: Optional[int] = Query(None),
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    where = ""
    params = {'lim': limit}
    if target_id is not None:
        where = "WHERE d.scope_target_id = :tid"
        params['tid'] = target_id
    sql = f"""
        SELECT d.id, d.created_at, d.trigger, d.proposal, d.verdict, d.reject_reason, d.execution_result,
               d.llm_tokens_in, d.llm_tokens_out, d.llm_latency_ms,
               d.scope_target_id, d.scope_pair_code, u.username
        FROM agent_decisions d
        LEFT JOIN users u ON u.user_id = d.scope_user_id
        {where}
        ORDER BY d.id DESC LIMIT :lim
    """
    rows = (await db.execute(text(sql), params)).all()
    items = [{
        'id': r[0], 'created_at': r[1].isoformat(), 'trigger': r[2],
        'action': (r[3] or {}).get('action', '--'),
        'leg': (r[3] or {}).get('leg', '--'),
        'qty': (r[3] or {}).get('qty', 0),
        'reason': (r[3] or {}).get('reason', ''),
        'confidence': (r[3] or {}).get('confidence', 0),
        'verdict': r[4], 'reject_reason': r[5], 'execution_result': r[6],
        'tokens_in': r[7], 'tokens_out': r[8], 'latency_ms': r[9],
        'target_id': r[10], 'pair_code': r[11], 'username': r[12],
    } for r in rows]
    return {'items': items, 'count': len(items)}


@router.get('/proposals')
async def list_proposals(status_filter: str = Query('pending'),
                         target_id: Optional[int] = Query(None),
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    where = []
    params = {'s': status_filter}
    if status_filter != 'all':
        where.append("p.status = :s")
    if target_id is not None:
        where.append("p.target_id = :tid")
        params['tid'] = target_id
    clause = (' WHERE ' + ' AND '.join(where)) if where else ''
    sql = f"""
        SELECT p.id, p.created_at, p.title, p.rationale, p.est_position_pct, p.status,
               p.config_diff, p.target_id, t.pair_code, u.username
        FROM agent_strategy_proposals p
        LEFT JOIN agent_scope_targets t ON t.id = p.target_id
        LEFT JOIN users u ON u.user_id = t.user_id
        {clause}
        ORDER BY p.id DESC LIMIT 50
    """
    rows = (await db.execute(text(sql), params)).all()
    return {'items': [{
        'id': r[0], 'created_at': r[1].isoformat(), 'title': r[2], 'rationale': r[3],
        'est_position_pct': float(r[4] or 0), 'status': r[5], 'config_diff': r[6],
        'target_id': r[7], 'pair_code': r[8], 'username': r[9],
    } for r in rows]}


class ProposalCreateReq(BaseModel):
    title: str
    rationale: str
    config_diff: Dict[str, Any]
    est_position_pct: Optional[float] = None
    target_id: Optional[int] = None


@router.post('/proposals')
async def create_proposal(req: ProposalCreateReq, db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Manually create a strategy proposal (admin tool)."""
    import json as _json
    res = await db.execute(text("""
        INSERT INTO agent_strategy_proposals (title, rationale, config_diff,
                                              est_position_pct, target_id, status)
        VALUES (:t, :r, CAST(:cd AS JSONB), :ep, :tid, 'pending')
        RETURNING id
    """), {
        't': req.title, 'r': req.rationale,
        'cd': _json.dumps(req.config_diff),
        'ep': req.est_position_pct, 'tid': req.target_id,
    })
    new_id = res.scalar_one()
    await db.commit()
    return {'ok': True, 'proposal_id': new_id}


@router.get('/config')
async def get_config(db: AsyncSession = Depends(get_db), user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    return await config_loader.load_config(db, force=True)


@router.get('/equity-interventions')
async def list_equity_interventions(db: AsyncSession = Depends(get_db),
                                    user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT id, account_id, state, equity_ratio, triggered_at, resolved_at, forced_reduce_pct, ack_by
        FROM equity_intervention_log ORDER BY id DESC LIMIT 30
    """))).all()
    return {'items': [{
        'id': r[0], 'account_id': str(r[1]), 'state': r[2],
        'equity_ratio': float(r[3] or 0),
        'triggered_at': r[4].isoformat() if r[4] else None,
        'resolved_at': r[5].isoformat() if r[5] else None,
        'forced_reduce_pct': float(r[6] or 0) if r[6] else None,
        'ack_by': str(r[7]) if r[7] else None,
    } for r in rows]}


@router.get('/scope-options')
async def get_scope_options(db: AsyncSession = Depends(get_db),
                            user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Lists candidate users (traders) and pair codes for scope selector."""
    users = (await db.execute(text("""
        SELECT user_id, username, role FROM users
        WHERE role IN ('交易员', 'trader', 'admin', '超级管理员', '系统管理员')
        ORDER BY username
    """))).all()
    pairs = (await db.execute(text("""
        SELECT pair_code FROM hedging_pairs WHERE is_active = true ORDER BY pair_code
    """))).all()
    cfg = await config_loader.load_config(db)
    scope = cfg.get('agent_scope', {}) or {}
    return {
        'users': [{'user_id': str(r[0]), 'username': r[1], 'role': r[2]} for r in users],
        'pair_codes': [r[0] for r in pairs],
        'current_scope': scope,
    }


# ───── Control ─────

class ModeReq(BaseModel):
    mode: str


@router.post('/mode')
async def set_mode(req: ModeReq, db: AsyncSession = Depends(get_db),
                   user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    if req.mode not in ('off', 'shadow', 'semi', 'auto'):
        raise HTTPException(status_code=400, detail=f'bad mode {req.mode}')
    await agent_state.set_mode(db, req.mode)
    from app.services.agent.feishu_broadcast import broadcast
    await broadcast(db, level='info', category='mode_change',
                    message=f'运行模式切换为 {req.mode}（操作员 {user_id[:8]}）',
                    payload={'mode': req.mode, 'operator': user_id})
    return {'ok': True, 'mode': req.mode}


class KillReq(BaseModel):
    on: bool


@router.post('/kill')
async def toggle_kill(req: KillReq, db: AsyncSession = Depends(get_db),
                      user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    await agent_state.set_kill_switch(db, req.on)
    from app.services.agent.feishu_broadcast import broadcast
    await broadcast(db, level='critical' if req.on else 'info', category='kill_switch',
                    message=f'Kill switch {"已开启" if req.on else "已关闭"}（操作员 {user_id[:8]}）',
                    payload={'on': req.on, 'operator': user_id})
    return {'ok': True, 'kill_switch': req.on}


class LlmConfigReq(BaseModel):
    model: Optional[str] = None
    streaming: Optional[bool] = None
    recharge_total_cny: Optional[float] = None
    balance_alert_threshold_cny: Optional[float] = None
    usage_multiplier: Optional[float] = None
    currency_symbol: Optional[str] = None


@router.post('/llm-config')
async def set_llm_config(req: LlmConfigReq, db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    cfg = await config_loader.load_config(db, force=True)
    ls = dict(cfg.get('llm_settings', {}) or {})
    available = ls.get('available_models') or []
    if req.model is not None:
        if available and req.model not in available:
            raise HTTPException(status_code=400, detail=f'model {req.model} not in available_models')
        # Streaming dry-run: match production decider path exactly
        import os, aiohttp, json as _json
        base = (os.getenv('OPENCLAW_LLM_BASE_URL') or '').rstrip('/')
        key = os.getenv('OPENCLAW_LLM_API_KEY', '')
        if base and key:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as hs:
                    async with hs.post(
                        f'{base}/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'content-type': 'application/json'},
                        data=_json.dumps({
                            'model': req.model,
                            'messages': [{'role': 'user', 'content': 'ping'}],
                            'max_tokens': 1,
                            'stream': True,
                            'stream_options': {'include_usage': True},
                        }),
                    ) as resp:
                        if resp.status != 200:
                            body = (await resp.text())[:400]
                            try:
                                jerr = _json.loads(body).get('error', {}).get('message', body)
                            except Exception:
                                jerr = body
                            raise HTTPException(status_code=400,
                                detail=f'模型 {req.model} 流式验证失败: {jerr}')
                        # Drain SSE: ensure we get at least one well-formed event
                        got_event = False
                        async for chunk in resp.content.iter_chunked(1024):
                            if not chunk:
                                continue
                            text_chunk = chunk.decode('utf-8', errors='ignore')
                            if text_chunk.strip().startswith('data:'):
                                got_event = True
                                break
                        if not got_event:
                            raise HTTPException(status_code=400,
                                detail=f'模型 {req.model} 流式响应空')
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400,
                    detail=f'模型 {req.model} 流式验证异常: {str(e)[:200]}')
        ls['model'] = req.model
    if req.streaming is not None:
        ls['streaming'] = bool(req.streaming)
    if req.recharge_total_cny is not None:
        ls['recharge_total_cny'] = float(req.recharge_total_cny)
    if req.balance_alert_threshold_cny is not None:
        ls['balance_alert_threshold_cny'] = float(req.balance_alert_threshold_cny)
    if req.usage_multiplier is not None:
        ls['usage_multiplier'] = float(req.usage_multiplier)
    if req.currency_symbol is not None:
        ls['currency_symbol'] = str(req.currency_symbol)[:5]

    import json as _json
    await db.execute(text("""
        INSERT INTO agent_active_config (key, value, updated_by)
        VALUES ('llm_settings', CAST(:v AS JSONB), CAST(:u AS UUID))
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW(), updated_by=EXCLUDED.updated_by
    """), {'v': _json.dumps(ls), 'u': user_id})
    await db.commit()
    config_loader.invalidate()
    from app.services.agent.codex_client import invalidate_model_cache
    invalidate_model_cache()
    return {'ok': True, 'llm_settings': ls}


# ───── Weekly strategy reviewer (P5) ─────

class ReviewTriggerReq(BaseModel):
    target_id: Optional[int] = None


@router.post('/strategy-review/trigger')
async def trigger_strategy_review(req: ReviewTriggerReq, db: AsyncSession = Depends(get_db),
                                  user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Run weekly-style review immediately for one target (or all enabled)."""
    from app.services.agent.strategy_reviewer import trigger_review_now
    return await trigger_review_now(db, req.target_id)


# ───── Multi-target scope CRUD (P4.0) ─────

class ScopeTargetReq(BaseModel):
    user_id: str
    pair_code: str
    priority: Optional[int] = 0


@router.get('/scope/targets')
async def list_scope_targets(db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    from app.services.agent.scope import list_target_rows
    rows = await list_target_rows(db, enabled_only=False)
    return {'items': rows, 'count': len(rows)}


@router.post('/scope/targets')
async def create_scope_target(req: ScopeTargetReq, db: AsyncSession = Depends(get_db),
                              user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    from app.services.agent.scope import create_target
    tid = await create_target(db, req.user_id, req.pair_code, req.priority or 0)
    from app.services.agent.feishu_broadcast import broadcast
    await broadcast(db, level='info', category='scope_target_added',
                    message=f'新增作用域目标 #{tid}: user={req.user_id[:8]} pair={req.pair_code}',
                    payload={'target_id': tid, 'user_id': req.user_id, 'pair_code': req.pair_code})
    return {'ok': True, 'target_id': tid}


@router.delete('/scope/targets/{target_id}')
async def delete_scope_target(target_id: int, db: AsyncSession = Depends(get_db),
                              user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    from app.services.agent.scope import delete_target
    ok = await delete_target(db, target_id)
    return {'ok': ok}


class ToggleReq(BaseModel):
    enabled: bool


@router.post('/scope/targets/{target_id}/toggle')
async def toggle_scope_target(target_id: int, req: ToggleReq,
                              db: AsyncSession = Depends(get_db),
                              user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    from app.services.agent.scope import toggle_target
    ok = await toggle_target(db, target_id, req.enabled)
    return {'ok': ok, 'enabled': req.enabled}


@router.post('/decisions/{decision_id}/approve')
async def approve_decision(decision_id: int, db: AsyncSession = Depends(get_db),
                           user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    row = (await db.execute(text("""
        SELECT verdict, proposal FROM agent_decisions WHERE id = :id
    """), {'id': decision_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail='decision not found')
    if row[0] != 'pending':
        raise HTTPException(status_code=400, detail=f'decision is {row[0]}, not pending')

    from app.services.agent.guard import Proposal
    from app.services.agent.executor import execute_proposal
    pj = row[1] or {}
    p = Proposal(
        action=pj.get('action', 'noop'), leg=pj.get('leg', 'both'),
        qty=float(pj.get('qty', 0)), reason=pj.get('reason', ''),
        trigger=pj.get('trigger', ''), confidence=float(pj.get('confidence', 0)),
        is_rebalance_补腿=bool(pj.get('is_rebalance_补腿', False)),
    )
    exec_res = await execute_proposal(db, decision_id, p)
    verdict = 'executed' if exec_res.get('ok') else 'rejected'
    await db.execute(text("""
        UPDATE agent_decisions SET verdict = :v, reject_reason = :rr WHERE id = :id
    """), {'v': verdict, 'rr': None if exec_res.get('ok') else exec_res.get('reason'), 'id': decision_id})
    await db.commit()
    return {'ok': exec_res.get('ok'), 'verdict': verdict, 'exec': exec_res, 'approved_by': user_id}


@router.post('/decisions/{decision_id}/reject')
async def reject_decision(decision_id: int, reason: Optional[str] = Body(None, embed=True),
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    row = (await db.execute(text("SELECT verdict FROM agent_decisions WHERE id=:id"), {'id': decision_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail='decision not found')
    if row[0] != 'pending':
        raise HTTPException(status_code=400, detail=f'decision is {row[0]}, not pending')
    await db.execute(text("""
        UPDATE agent_decisions SET verdict='rejected', reject_reason=:r WHERE id=:id
    """), {'r': reason or f'operator_reject_by_{user_id[:8]}', 'id': decision_id})
    await db.commit()
    return {'ok': True}


class EquityAckReq(BaseModel):
    account_id: Optional[str] = None


@router.post('/equity-ack')
async def equity_ack(req: EquityAckReq, db: AsyncSession = Depends(get_db),
                     user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    from app.services.agent.equity_fsm import acknowledge
    if req.account_id:
        ok = await acknowledge(db, UUID(req.account_id), UUID(user_id))
        return {'ok': ok, 'account_id': req.account_id}
    results = {}
    for synth in ['00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002']:
        results[synth] = await acknowledge(db, UUID(synth), UUID(user_id))
    return {'ok': any(results.values()), 'results': results}


@router.post('/strategy-proposals/{pid}/approve')
async def approve_strategy(pid: int, db: AsyncSession = Depends(get_db),
                           user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    row = (await db.execute(text("SELECT status, config_diff, target_id FROM agent_strategy_proposals WHERE id=:id"),
                            {'id': pid})).first()
    if not row:
        raise HTTPException(status_code=404, detail='proposal not found')
    if row[0] != 'pending':
        raise HTTPException(status_code=400, detail=f'proposal is {row[0]}')
    diff = row[1] or {}
    target_id = row[2]
    import json as _json
    for key, value in diff.items():
        if target_id is not None:
            await db.execute(text("""
                INSERT INTO agent_target_config (target_id, key, value, source_proposal_id, updated_by)
                VALUES (:tid, :k, CAST(:v AS JSONB), :pid, CAST(:u AS UUID))
                ON CONFLICT (target_id, key) DO UPDATE SET value=EXCLUDED.value,
                  source_proposal_id=EXCLUDED.source_proposal_id,
                  updated_at=NOW(), updated_by=EXCLUDED.updated_by
            """), {'tid': target_id, 'k': key, 'v': _json.dumps(value), 'pid': pid, 'u': user_id})
        else:
            await db.execute(text("""
                INSERT INTO agent_active_config (key, value, source_proposal_id, updated_by)
                VALUES (:k, CAST(:v AS JSONB), :pid, CAST(:u AS UUID))
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, source_proposal_id=EXCLUDED.source_proposal_id,
                  updated_at=NOW(), updated_by=EXCLUDED.updated_by
            """), {'k': key, 'v': _json.dumps(value), 'pid': pid, 'u': user_id})
    await db.execute(text("""
        UPDATE agent_strategy_proposals
        SET status='approved', reviewed_by=CAST(:u AS UUID), reviewed_at=NOW(), activated_at=NOW()
        WHERE id=:id
    """), {'u': user_id, 'id': pid})
    await db.commit()
    config_loader.invalidate(target_id=target_id)
    from app.services.agent.feishu_broadcast import broadcast
    scope_label = f'target#{target_id}' if target_id else 'global'
    await broadcast(db, level='info', category='strategy_approved',
                    message=f'新策略#{pid} 已批准并热加载（范围 {scope_label}, 操作员 {user_id[:8]}）',
                    payload={'proposal_id': pid, 'target_id': target_id, 'keys_changed': list(diff.keys())})
    return {'ok': True, 'target_id': target_id, 'activated_keys': list(diff.keys())}


@router.post('/strategy-proposals/{pid}/reject')
async def reject_strategy(pid: int, reason: Optional[str] = Body(None, embed=True),
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    await db.execute(text("""
        UPDATE agent_strategy_proposals
        SET status='rejected', reviewed_by=CAST(:u AS UUID), reviewed_at=NOW()
        WHERE id=:id AND status='pending'
    """), {'u': user_id, 'id': pid})
    await db.commit()
    return {'ok': True}
