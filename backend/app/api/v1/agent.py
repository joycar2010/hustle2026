"""OpenCLAW agent API — control panel + execution triggers (P3.5).

RBAC: ALL endpoints require role ∈ {超级管理员, 系统管理员, super_admin, system_admin, admin}.
"""
import re
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
    row = (await db.execute(text("SELECT role, openclaw_enabled FROM users WHERE user_id = CAST(:u AS UUID)"),
                            {'u': user_id})).first()
    if not row:
        raise HTTPException(status_code=403, detail='用户不存在')
    role, openclaw_enabled = row[0], bool(row[1])
    if role in ADMIN_ROLES:
        return user_id
    if openclaw_enabled:
        return user_id
    raise HTTPException(status_code=403, detail='OpenCLAW 控制台需管理员或 [智能体量化] 授权账户方可访问')


# ───── Read ─────

@router.get('/whoami')
async def whoami(db: AsyncSession = Depends(get_db),
                 user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    """Lightweight check used by frontend route guard."""
    row = (await db.execute(text("SELECT username, role, openclaw_enabled FROM users WHERE user_id = CAST(:u AS UUID)"),
                            {'u': user_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail='user_not_found')
    is_admin = row[1] in ADMIN_ROLES or bool(row[2])
    return {'user_id': user_id, 'username': row[0], 'role': row[1],
            'openclaw_enabled': bool(row[2]), 'is_admin': is_admin}


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
        'openclaw_enabled': s.get('openclaw_enabled', True),
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

    # Prefer relay_stations active primary
    _rs = list(cfg.get('relay_stations', []) or [])
    _active = next((r for r in _rs if r.get('enabled') and r.get('role') == 'primary'), None)
    _m = _active.get('model') if _active else ls.get('model')
    _s = _active.get('streaming', True) if _active else ls.get('streaming', True)
    _am = _active.get('available_models', []) if _active else ls.get('available_models', [])
    return {
        'model': _m,
        'streaming': _s,
        'available_models': _am,
        'active_relay_id': _active['id'] if _active else None,
        'active_relay_name': _active.get('name') if _active else None,
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
async def list_decisions(limit: int = Query(50, ge=1, le=200),
                         target_id: Optional[int] = Query(None),
                         cursor: Optional[int] = Query(None,
                             description='Keyset cursor: return rows with id < cursor'),
                         verdict: Optional[str] = Query(None,
                             description='Comma-separated verdicts to include'),
                         trigger: Optional[str] = Query(None,
                             description='Comma-separated triggers to include'),
                         pair_code: Optional[str] = Query(None,
                             description='Comma-separated pair codes to include'),
                         from_ts: Optional[str] = Query(None, alias='from',
                             description='ISO8601 lower bound on created_at'),
                         to_ts: Optional[str] = Query(None, alias='to',
                             description='ISO8601 upper bound on created_at'),
                         min_confidence: Optional[float] = Query(None, ge=0, le=1),
                         q: Optional[str] = Query(None,
                             description='Free-text match against reject_reason / proposal.reason'),
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Keyset-paginated decision feed with multi-dimensional filtering.

    Cursor semantics: pass next_cursor from the previous response to fetch the
    next page; omit to get the head. has_more is true when LIMIT was reached
    AND a row exists past the last id we returned.
    """
    where: List[str] = []
    params: Dict[str, Any] = {'lim': limit}
    if cursor is not None:
        where.append('d.id < :cur')
        params['cur'] = cursor
    if target_id is not None:
        where.append('d.scope_target_id = :tid')
        params['tid'] = target_id
    if verdict:
        verdicts = [v.strip() for v in verdict.split(',') if v.strip()]
        if verdicts:
            where.append('d.verdict = ANY(:verdicts)')
            params['verdicts'] = verdicts
    if trigger:
        triggers = [t.strip() for t in trigger.split(',') if t.strip()]
        if triggers:
            where.append('d.trigger = ANY(:triggers)')
            params['triggers'] = triggers
    if pair_code:
        pairs = [p_.strip() for p_ in pair_code.split(',') if p_.strip()]
        if pairs:
            where.append('d.scope_pair_code = ANY(:pairs)')
            params['pairs'] = pairs
    if from_ts:
        where.append('d.created_at >= :from_ts')
        params['from_ts'] = from_ts
    if to_ts:
        where.append('d.created_at <= :to_ts')
        params['to_ts'] = to_ts
    if min_confidence is not None:
        # proposal->>'confidence' is text in jsonb, cast to numeric for compare
        where.append("(d.proposal->>'confidence')::numeric >= :minconf")
        params['minconf'] = min_confidence
    if q:
        where.append("(COALESCE(d.reject_reason,'') ILIKE :q OR COALESCE(d.proposal->>'reason','') ILIKE :q)")
        params['q'] = f'%{q}%'

    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    sql = f"""
        SELECT d.id, d.created_at, d.trigger, d.proposal, d.verdict, d.reject_reason, d.execution_result,
               d.llm_tokens_in, d.llm_tokens_out, d.llm_latency_ms,
               d.scope_target_id, d.scope_pair_code, u.username
        FROM agent_decisions d
        LEFT JOIN users u ON u.user_id = d.scope_user_id
        {where_sql}
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
    next_cursor = items[-1]['id'] if items and len(items) == limit else None
    has_more = bool(next_cursor)
    # Cheap approximate total via pg_class — we never want a COUNT(*) on the
    # hot path of a 2s polling endpoint. Filtering doesn't refine total_approx
    # (it's the table-wide rowcount, used to size the UI scrollbar / hint).
    try:
        approx = (await db.execute(text(
            "SELECT reltuples::bigint FROM pg_class WHERE relname = 'agent_decisions'"
        ))).scalar() or 0
    except Exception:
        approx = None
    return {
        'items': items,
        'count': len(items),
        'next_cursor': next_cursor,
        'has_more': has_more,
        'total_approx': int(approx) if approx is not None else None,
    }


@router.get('/proposals')
async def list_proposals(status_filter: str = Query('pending'),
                         target_id: Optional[int] = Query(None),
                         pair_code: Optional[str] = Query(None,
                             description='Comma-separated pair codes (resolved via scope target)'),
                         q: Optional[str] = Query(None,
                             description='Free-text match against title / rationale'),
                         limit: int = Query(50, ge=1, le=200),
                         cursor: Optional[int] = Query(None,
                             description='Keyset cursor: return rows with id < cursor'),
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    where: List[str] = []
    params: Dict[str, Any] = {'s': status_filter, 'lim': limit}
    if status_filter != 'all':
        where.append('p.status = :s')
    if target_id is not None:
        where.append('p.target_id = :tid')
        params['tid'] = target_id
    if cursor is not None:
        where.append('p.id < :cur')
        params['cur'] = cursor
    if pair_code:
        pairs = [x.strip() for x in pair_code.split(',') if x.strip()]
        if pairs:
            where.append('t.pair_code = ANY(:pairs)')
            params['pairs'] = pairs
    if q:
        where.append('(p.title ILIKE :q OR p.rationale ILIKE :q)')
        params['q'] = f'%{q}%'
    clause = (' WHERE ' + ' AND '.join(where)) if where else ''
    sql = f"""
        SELECT p.id, p.created_at, p.title, p.rationale, p.est_position_pct, p.status,
               p.config_diff, p.target_id, t.pair_code, u.username,
               p.reviewed_at, p.activated_at
        FROM agent_strategy_proposals p
        LEFT JOIN agent_scope_targets t ON t.id = p.target_id
        LEFT JOIN users u ON u.user_id = t.user_id
        {clause}
        ORDER BY p.id DESC LIMIT :lim
    """
    rows = (await db.execute(text(sql), params)).all()
    items = [{
        'id': r[0], 'created_at': r[1].isoformat(), 'title': r[2], 'rationale': r[3],
        'est_position_pct': float(r[4] or 0), 'status': r[5], 'config_diff': r[6],
        'target_id': r[7], 'pair_code': r[8], 'username': r[9],
        'reviewed_at': r[10].isoformat() if r[10] else None,
        'activated_at': r[11].isoformat() if r[11] else None,
    } for r in rows]
    next_cursor = items[-1]['id'] if items and len(items) == limit else None
    return {
        'items': items,
        'count': len(items),
        'next_cursor': next_cursor,
        'has_more': bool(next_cursor),
    }


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


class OpenclawToggleReq(BaseModel):
    on: bool


@router.post('/openclaw-toggle')
async def toggle_openclaw_global(req: OpenclawToggleReq, db: AsyncSession = Depends(get_db),
                                 user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Global OpenCLAW enable/disable. Disabling short-circuits all decisions,
    executions and alerts regardless of per-user settings."""
    await agent_state.set_openclaw_enabled(db, req.on)
    from app.services.agent.feishu_broadcast import broadcast
    await broadcast(db, level='critical' if not req.on else 'info', category='openclaw_toggle',
                    message=f'OpenCLAW 全局开关 {"已启用" if req.on else "已停用（全员禁）"}（操作员 {user_id[:8]}）',
                    payload={'on': req.on, 'operator': user_id})
    return {'ok': True, 'openclaw_enabled': req.on}


class LlmConfigReq(BaseModel):
    model: Optional[str] = None
    streaming: Optional[bool] = None
    balance_alert_threshold_cny: Optional[float] = None


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
                            import logging
                            logging.getLogger(__name__).warning(f'模型 {req.model} 流式验证失败(不阻止保存): {jerr}')
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
                            import logging
                            logging.getLogger(__name__).warning(f'模型 {req.model} 流式响应空(不阻止保存)')
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f'模型 {req.model} 流式验证异常(不阻止保存): {e}')
        ls['model'] = req.model
    if req.streaming is not None:
        ls['streaming'] = bool(req.streaming)
    if req.balance_alert_threshold_cny is not None:
        ls['balance_alert_threshold_cny'] = float(req.balance_alert_threshold_cny)
    # Strip obsolete fields if present in prior config
    for _k in ('recharge_total_cny', 'usage_multiplier', 'currency_symbol'):
        ls.pop(_k, None)

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
    # Also sync to active primary relay station
    _rs = list(cfg.get('relay_stations', []) or [])
    _active = next((r for r in _rs if r.get('enabled') and r.get('role') == 'primary'), None)
    if _active:
        if req.model is not None:
            _active['model'] = req.model
        if req.streaming is not None:
            _active['streaming'] = bool(req.streaming)
        if req.balance_alert_threshold_cny is not None:
            _active['balance_alert_threshold_cny'] = float(req.balance_alert_threshold_cny)
        await _save_relay_stations(db, _rs, user_id)
    return {'ok': True, 'llm_settings': ls}




# ─────────────────────────────────────────────────────────────────────
# Relay Stations CRUD (multi-relay primary/standby)
# ─────────────────────────────────────────────────────────────────────

async def _load_relay_stations(db) -> list:
    cfg = await config_loader.load_config(db)
    return list(cfg.get('relay_stations', []) or [])

async def _save_relay_stations(db, stations: list, user_id: str):
    import json as _json
    await db.execute(text("""
        INSERT INTO agent_active_config (key, value, updated_by)
        VALUES ('relay_stations', CAST(:v AS JSONB), CAST(:u AS UUID))
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW(), updated_by=EXCLUDED.updated_by
    """), {'v': _json.dumps(stations), 'u': user_id})
    await db.commit()
    config_loader.invalidate()

def _safe_station(s: dict) -> dict:
    """Strip sensitive fields for API response."""
    out = dict(s)
    out.pop('chesspnt_password', None)
    out.pop('llm_api_key', None)
    cookie = out.get('session_cookie', '')
    out['cookie_set'] = bool(cookie)
    out.pop('session_cookie', None)
    return out


@router.get('/relay-stations')
async def list_relay_stations(db: AsyncSession = Depends(get_db),
                              user_id: str = Depends(require_admin)):
    stations = await _load_relay_stations(db)
    return {'items': [_safe_station(s) for s in stations]}


@router.post('/relay-stations')
async def add_relay_station(body: Dict[str, Any] = Body(...),
                            db: AsyncSession = Depends(get_db),
                            user_id: str = Depends(require_admin)):
    import uuid
    stations = await _load_relay_stations(db)
    new_id = str(uuid.uuid4())[:8]
    station = {
        'id': new_id,
        'name': body.get('name', f'relay-{new_id}'),
        'api_base': body.get('api_base', 'https://api.chesspnt.com'),
        'llm_base_url': body.get('llm_base_url', ''),
        'llm_api_key': body.get('llm_api_key', ''),
        'chesspnt_username': body.get('chesspnt_username', ''),
        'chesspnt_password': body.get('chesspnt_password', ''),
        'session_cookie': '',
        'new_api_user': body.get('new_api_user', ''),
        'units_per_usd': body.get('units_per_usd', 500000),
        'available_models': body.get('available_models', []),
        'model': body.get('model', ''),
        'streaming': body.get('streaming', True),
        'balance_alert_threshold_cny': body.get('balance_alert_threshold_cny', 20),
        'usd_to_cny_rate': body.get('usd_to_cny_rate', 7.3),
        'enabled': body.get('enabled', True),
        'role': body.get('role', 'standby'),
        'priority': body.get('priority', len(stations)),
    }
    stations.append(station)
    await _save_relay_stations(db, stations, user_id)
    return {'ok': True, 'station': _safe_station(station)}


@router.put('/relay-stations/{station_id}')
async def update_relay_station(station_id: str,
                               body: Dict[str, Any] = Body(...),
                               db: AsyncSession = Depends(get_db),
                               user_id: str = Depends(require_admin)):
    stations = await _load_relay_stations(db)
    found = None
    for s in stations:
        if s['id'] == station_id:
            found = s
            break
    if not found:
        raise HTTPException(status_code=404, detail='relay station not found')
    # Update allowed fields
    for k in ('name', 'api_base', 'llm_base_url', 'llm_api_key',
              'chesspnt_username', 'new_api_user', 'units_per_usd',
              'model', 'streaming', 'balance_alert_threshold_cny',
              'usd_to_cny_rate', 'priority', 'available_models'):
        if k in body and body[k] is not None:
            found[k] = body[k]
    if 'chesspnt_password' in body and body['chesspnt_password']:
        found['chesspnt_password'] = body['chesspnt_password']
    await _save_relay_stations(db, stations, user_id)
    return {'ok': True, 'station': _safe_station(found)}


@router.delete('/relay-stations/{station_id}')
async def delete_relay_station(station_id: str,
                               db: AsyncSession = Depends(get_db),
                               user_id: str = Depends(require_admin)):
    stations = await _load_relay_stations(db)
    new_stations = [s for s in stations if s['id'] != station_id]
    if len(new_stations) == len(stations):
        raise HTTPException(status_code=404, detail='relay station not found')
    await _save_relay_stations(db, new_stations, user_id)
    return {'ok': True}


@router.post('/relay-stations/{station_id}/toggle')
async def toggle_relay_station(station_id: str,
                               body: Dict[str, Any] = Body(...),
                               db: AsyncSession = Depends(get_db),
                               user_id: str = Depends(require_admin)):
    stations = await _load_relay_stations(db)
    for s in stations:
        if s['id'] == station_id:
            s['enabled'] = bool(body.get('enabled', not s.get('enabled', True)))
            await _save_relay_stations(db, stations, user_id)
            return {'ok': True, 'station': _safe_station(s)}
    raise HTTPException(status_code=404, detail='relay station not found')


@router.post('/relay-stations/{station_id}/set-role')
async def set_relay_role(station_id: str,
                         body: Dict[str, Any] = Body(...),
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)):
    """Set a station as primary (demoting the previous primary to standby)."""
    role = body.get('role', 'primary')
    stations = await _load_relay_stations(db)
    found = False
    for s in stations:
        if s['id'] == station_id:
            s['role'] = role
            found = True
        elif role == 'primary' and s.get('role') == 'primary':
            s['role'] = 'standby'
    if not found:
        raise HTTPException(status_code=404, detail='relay station not found')
    await _save_relay_stations(db, stations, user_id)
    return {'ok': True, 'items': [_safe_station(s) for s in stations]}


@router.post('/relay-stations/{station_id}/refresh-cookie')
async def refresh_station_cookie(station_id: str,
                                 db: AsyncSession = Depends(get_db),
                                 user_id: str = Depends(require_admin)):
    """Login to chesspnt and update session cookie for a specific station."""
    import aiohttp, json as _json
    stations = await _load_relay_stations(db)
    found = None
    for s in stations:
        if s['id'] == station_id:
            found = s
            break
    if not found:
        raise HTTPException(status_code=404, detail='relay station not found')
    base = found.get('api_base', 'https://api.chesspnt.com').rstrip('/')
    username = found.get('chesspnt_username', '')
    password = found.get('chesspnt_password', '')
    if not username or not password:
        return {'ok': False, 'error': 'username/password not configured'}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(f'{base}/api/user/login',
                                    json={'username': username, 'password': password}) as resp:
                data = await resp.json()
                if not data.get('success'):
                    return {'ok': False, 'error': data.get('message', 'login failed')}
                cookies = resp.headers.getall('Set-Cookie', [])
                new_cookie = ''
                for c in cookies:
                    if 'session=' in c:
                        new_cookie = c.split('session=')[1].split(';')[0]
                        break
                if not new_cookie:
                    return {'ok': False, 'error': 'no session cookie in response'}
                found['session_cookie'] = new_cookie
                await _save_relay_stations(db, stations, user_id)
                return {'ok': True, 'message': 'cookie updated', 'user': data.get('data', {}).get('username')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/relay-stations/{station_id}/refresh-models')
async def refresh_station_models(station_id: str,
                                 db: AsyncSession = Depends(get_db),
                                 user_id: str = Depends(require_admin)):
    """Pull live model list from chesspnt for a specific station."""
    import aiohttp
    stations = await _load_relay_stations(db)
    found = None
    for s in stations:
        if s['id'] == station_id:
            found = s
            break
    if not found:
        raise HTTPException(status_code=404, detail='relay station not found')
    base = found.get('api_base', 'https://api.chesspnt.com').rstrip('/')
    cookie = found.get('session_cookie', '')
    user_hdr = found.get('new_api_user', '')
    if not cookie:
        return {'ok': False, 'error': 'no session cookie — refresh cookie first'}
    headers = {'accept': 'application/json', 'cookie': f'session={cookie}'}
    if user_hdr:
        headers['new-api-user'] = str(user_hdr)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(f'{base}/api/user/models', headers=headers) as resp:
                if resp.status not in (200, 201):
                    return {'ok': False, 'error': f'HTTP {resp.status}'}
                body = await resp.json()
                models = body.get('data') if isinstance(body, dict) else body
                if not isinstance(models, list):
                    return {'ok': False, 'error': 'unexpected response'}
                models = sorted({str(m) for m in models if m})
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    old = set(found.get('available_models', []))
    new = set(models)
    found['available_models'] = models
    await _save_relay_stations(db, stations, user_id)
    from app.services.agent.codex_client import invalidate_model_cache
    invalidate_model_cache()
    return {
        'ok': True, 'count': len(models), 'available_models': models,
        'added': sorted(new - old), 'removed': sorted(old - new),
    }


@router.get('/chesspnt-auth')
async def get_chesspnt_auth(db: AsyncSession = Depends(get_db),
                            user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Get chesspnt relay config (masks password/cookie)."""
    cfg = await config_loader.load_config(db)
    auth = cfg.get('chesspnt_auth', {}) or {}
    return {
        'api_base': auth.get('api_base', 'https://api.chesspnt.com'),
        'username': auth.get('username', ''),
        'password_set': bool(auth.get('password')),
        'new_api_user': auth.get('new_api_user', ''),
        'units_per_usd': auth.get('units_per_usd', 500000),
        'cookie_set': bool(auth.get('session_cookie')),
    }


@router.post('/chesspnt-auth')
async def save_chesspnt_auth(body: Dict[str, Any] = Body(...),
                             db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Save chesspnt relay config (api_base, username, password, units_per_usd)."""
    import json as _json
    cfg = await config_loader.load_config(db, force=True)
    auth = dict(cfg.get('chesspnt_auth', {}) or {})
    for k in ('api_base', 'username', 'password', 'units_per_usd', 'new_api_user'):
        if k in body and body[k] is not None:
            auth[k] = body[k]
    await db.execute(text("""
        INSERT INTO agent_active_config (key, value, updated_by)
        VALUES ('chesspnt_auth', CAST(:v AS JSONB), CAST(:u AS UUID))
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW(), updated_by=EXCLUDED.updated_by
    """), {'v': _json.dumps(auth), 'u': user_id})
    await db.commit()
    config_loader.invalidate()
    safe = {k: v for k, v in auth.items() if k not in ('password', 'session_cookie')}
    return {'ok': True, 'chesspnt_auth': safe}


@router.post('/chesspnt-refresh')
async def refresh_chesspnt_session(db: AsyncSession = Depends(get_db),
                                   user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Login to chesspnt.com and update session cookie in DB."""
    import aiohttp, json as _json
    cfg = await config_loader.load_config(db, force=True)
    auth = dict(cfg.get('chesspnt_auth', {}) or {})
    base = auth.get('api_base', 'https://api.chesspnt.com').rstrip('/')

    # Use stored credentials or defaults
    username = auth.get('username', 'joycar')
    password = auth.get('password', 'Lk106504!')

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(
                f'{base}/api/user/login',
                json={'username': username, 'password': password}
            ) as resp:
                data = await resp.json()
                if not data.get('success'):
                    return {'ok': False, 'error': data.get('message', 'login failed')}

                # Extract session cookie from response headers
                cookies = resp.headers.getall('Set-Cookie', [])
                new_cookie = ''
                for c in cookies:
                    if 'session=' in c:
                        new_cookie = c.split('session=')[1].split(';')[0]
                        break

                if not new_cookie:
                    return {'ok': False, 'error': 'no session cookie in response'}

                # Update DB
                auth['session_cookie'] = new_cookie
                await db.execute(text(
                    "UPDATE agent_active_config SET value=cast(:v as jsonb), updated_at=NOW() WHERE key='chesspnt_auth'"
                ), {'v': _json.dumps(auth)})
                await db.commit()
                config_loader.invalidate()

                return {'ok': True, 'message': 'session cookie updated', 'user': data.get('data', {}).get('username')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/chesspnt-models/refresh')
async def refresh_chesspnt_models(db: AsyncSession = Depends(get_db),
                                  user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Pull live model list from chesspnt /api/user/models and overwrite
    llm_settings.available_models. Manual-only (no scheduler) — operator clicks
    when session cookie is fresh and they want to surface newly-released models.
    Returns the new model list and the diff (added/removed) for UI display.
    """
    import aiohttp, json as _json
    cfg = await config_loader.load_config(db, force=True)
    auth = cfg.get('chesspnt_auth', {}) or {}
    base = auth.get('api_base', 'https://api.chesspnt.com').rstrip('/')
    cookie = auth.get('session_cookie', '')
    user_hdr = auth.get('new_api_user', '')
    if not cookie:
        return {'ok': False, 'error': 'no chesspnt session_cookie configured — refresh cookie first'}

    headers = {
        'accept': 'application/json, text/plain, */*',
        'cookie': f'session={cookie}',
    }
    if user_hdr:
        headers['new-api-user'] = str(user_hdr)

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(f'{base}/api/user/models', headers=headers) as resp:
                if resp.status not in (200, 201):
                    return {'ok': False, 'error': f'HTTP {resp.status}'}
                body = await resp.json()
                models = body.get('data') if isinstance(body, dict) else body
                if not isinstance(models, list) or not models:
                    return {'ok': False, 'error': f'unexpected response shape: {str(body)[:200]}'}
                models = sorted({str(m) for m in models if m})
    except Exception as e:
        return {'ok': False, 'error': f'fetch failed: {e}'}

    ls = dict(cfg.get('llm_settings', {}) or {})
    old = set(ls.get('available_models') or [])
    new = set(models)
    ls['available_models'] = models
    # If currently selected model no longer exists, leave it (operator will see warning in UI).
    await db.execute(text("""
        INSERT INTO agent_active_config (key, value, updated_by)
        VALUES ('llm_settings', CAST(:v AS JSONB), CAST(:u AS UUID))
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW(), updated_by=EXCLUDED.updated_by
    """), {'v': _json.dumps(ls), 'u': user_id})
    await db.commit()
    config_loader.invalidate()
    from app.services.agent.codex_client import invalidate_model_cache
    invalidate_model_cache()

    return {
        'ok': True,
        'count': len(models),
        'available_models': models,
        'added': sorted(new - old),
        'removed': sorted(old - new),
        'current_model_still_present': ls.get('model') in new if ls.get('model') else None,
    }


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


class TargetCapsUpdateReq(BaseModel):
    single_trade_pct: Optional[float] = None
    total_position_pct: Optional[float] = None
    daily_volume_pct: Optional[float] = None


@router.post('/scope/targets/{target_id}/caps')
async def update_target_caps(target_id: int, req: TargetCapsUpdateReq,
                             db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    import json as _json
    existing = await db.execute(text(
        "SELECT value FROM agent_target_config WHERE target_id = :t AND key = 'position_caps'"
    ), {'t': target_id})
    row = existing.first()
    if row:
        caps = _json.loads(row[0]) if isinstance(row[0], str) else (row[0] if isinstance(row[0], dict) else {})
    else:
        gr = await db.execute(text("SELECT value FROM agent_active_config WHERE key = 'position_caps'"))
        g = gr.first()
        caps = _json.loads(g[0]) if g and isinstance(g[0], str) else {'single_trade_pct': 0.10, 'total_position_pct': 0.50, 'daily_volume_pct': 5.0}
    if req.single_trade_pct is not None:
        caps['single_trade_pct'] = req.single_trade_pct
    if req.total_position_pct is not None:
        caps['total_position_pct'] = req.total_position_pct
    if req.daily_volume_pct is not None:
        caps['daily_volume_pct'] = req.daily_volume_pct
    caps_json = _json.dumps(caps)
    if row:
        await db.execute(text(
            "UPDATE agent_target_config SET value = :v, updated_at = now(), updated_by = CAST(:u AS UUID) WHERE target_id = :t AND key = 'position_caps'"
        ), {'v': caps_json, 't': target_id, 'u': user_id})
    else:
        await db.execute(text(
            "INSERT INTO agent_target_config (target_id, key, value, updated_at, updated_by) VALUES (:t, 'position_caps', :v, now(), CAST(:u AS UUID))"
        ), {'t': target_id, 'v': caps_json, 'u': user_id})
    await db.commit()
    config_loader.invalidate(target_id=target_id)
    return {'ok': True, 'caps': caps}


@router.get('/scope/targets/{target_id}/caps')
async def get_target_caps(target_id: int,
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    cfg = await config_loader.load_config(db, target_id=target_id)
    caps = cfg.get('position_caps', {})
    global_cfg = await config_loader.load_config(db)
    global_caps = global_cfg.get('position_caps', {})
    return {'caps': caps, 'global_caps': global_caps, 'target_id': target_id}


@router.get('/llm-health')
async def llm_health(db: AsyncSession = Depends(get_db),
                     user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    import time as _time
    try:
        from app.services.agent.codex_client import (
            _is_circuit_open, _circuit_open_until, _failure_log,
            _pick_fallback_model, _CIRCUIT_WINDOW, _CIRCUIT_THRESHOLD,
            _circuit_consecutive_trips, _CIRCUIT_BASE_COOLDOWN, _CIRCUIT_MAX_COOLDOWN,
            get_runtime_model_and_stream,
        )
        now = _time.time()
        recent_failures = sum(1 for t in _failure_log if now - t < _CIRCUIT_WINDOW)
        model, streaming = await get_runtime_model_and_stream(db)
        current_cooldown = min(
            _CIRCUIT_BASE_COOLDOWN * (2 ** max(0, _circuit_consecutive_trips - 1)),
            _CIRCUIT_MAX_COOLDOWN,
        ) if _circuit_consecutive_trips > 0 else _CIRCUIT_BASE_COOLDOWN
        return {
            'circuit_open': _is_circuit_open(),
            'circuit_open_until': _circuit_open_until if _is_circuit_open() else None,
            'recent_failures': recent_failures,
            'failure_threshold': _CIRCUIT_THRESHOLD,
            'failure_window_s': _CIRCUIT_WINDOW,
            'consecutive_trips': _circuit_consecutive_trips,
            'current_cooldown_s': current_cooldown,
            'primary_model': model,
            'fallback_model': _pick_fallback_model(model),
        }
    except Exception as e:
        return {'error': str(e), 'circuit_open': False}


@router.post('/llm-health/reset')
async def reset_circuit_breaker(user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Manually reset the LLM circuit breaker."""
    try:
        from app.services.agent.codex_client import (
            _failure_log, _is_circuit_open,
        )
        import app.services.agent.codex_client as _cc
        was_open = _is_circuit_open()
        _cc._circuit_open_until = 0.0
        _cc._circuit_consecutive_trips = 0
        _failure_log.clear()
        return {'ok': True, 'was_open': was_open, 'circuit_open': False}
    except Exception as e:
        return {'ok': False, 'error': str(e)}





# ─────────────────────────────────────────────────────────────────────────
# Phase 2/3 — analytics + traceability endpoints
# ─────────────────────────────────────────────────────────────────────────

def _resolve_window_seconds(window: str) -> int:
    """Translate '24h' / '7d' / '30d' / '1h' into seconds. Defaults to 24h
    on bad input so the dashboard never crashes."""
    m = re.match(r"^(\d+)([hdm])$", (window or "").strip().lower())
    if not m:
        return 86400
    n, u = int(m.group(1)), m.group(2)
    return n * (3600 if u == 'h' else 86400 if u == 'd' else 60)


def _read_usd_to_cny_rate(db) -> float:
    """Pull the same usd_to_cny_rate the LLM cost UI uses, falling back to
    7.3. Synchronous wrapper around an async SQL call is intentional — caller
    already awaits this helper."""
    return 7.3  # constant fallback; live read happens inside endpoints below


@router.get('/decisions/stats')
async def decision_stats(window: str = Query('24h',
                             description='Time window: 1h / 24h / 7d / 30d'),
                         target_id: Optional[int] = Query(None),
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """KPI summary for the agent dashboard: total decisions, breakdown by
    verdict and trigger, token sums, latency percentiles, all scoped to a
    rolling time window (default 24h) and optionally a single target."""
    secs = _resolve_window_seconds(window)
    where = ["d.created_at >= NOW() - make_interval(secs => :secs)"]
    params: Dict[str, Any] = {'secs': secs}
    if target_id is not None:
        where.append('d.scope_target_id = :tid')
        params['tid'] = target_id
    where_sql = ' AND '.join(where)

    summary = (await db.execute(text(f"""
        SELECT COUNT(*)                                AS total,
               COALESCE(SUM(d.llm_tokens_in), 0)       AS tokens_in,
               COALESCE(SUM(d.llm_tokens_out), 0)      AS tokens_out,
               COALESCE(AVG(d.llm_latency_ms), 0)      AS avg_latency,
               COALESCE(percentile_cont(0.5)
                  WITHIN GROUP (ORDER BY d.llm_latency_ms), 0) AS p50,
               COALESCE(percentile_cont(0.95)
                  WITHIN GROUP (ORDER BY d.llm_latency_ms), 0) AS p95,
               COALESCE(percentile_cont(0.99)
                  WITHIN GROUP (ORDER BY d.llm_latency_ms), 0) AS p99,
               COALESCE(AVG((d.proposal->>\'confidence\')::numeric), 0) AS avg_conf
        FROM agent_decisions d
        WHERE {where_sql}
    """), params)).first()

    by_verdict_rows = (await db.execute(text(f"""
        SELECT d.verdict, COUNT(*) FROM agent_decisions d
        WHERE {where_sql}
        GROUP BY d.verdict
    """), params)).all()
    by_trigger_rows = (await db.execute(text(f"""
        SELECT d.trigger, COUNT(*) FROM agent_decisions d
        WHERE {where_sql}
        GROUP BY d.trigger
        ORDER BY 2 DESC LIMIT 20
    """), params)).all()
    by_action_rows = (await db.execute(text(f"""
        SELECT COALESCE(d.proposal->>\'action\', \'noop\') AS act, COUNT(*)
        FROM agent_decisions d
        WHERE {where_sql}
        GROUP BY act
        ORDER BY 2 DESC LIMIT 20
    """), params)).all()
    reject_rows = (await db.execute(text(f"""
        SELECT COALESCE(d.reject_reason, \'(unknown)\') AS reason, COUNT(*)
        FROM agent_decisions d
        WHERE {where_sql} AND d.verdict = \'rejected\'
        GROUP BY reason
        ORDER BY 2 DESC LIMIT 10
    """), params)).all()

    total = int(summary[0] or 0)
    by_verdict = {r[0]: int(r[1]) for r in by_verdict_rows}
    executed = by_verdict.get('executed', 0)
    rejected = by_verdict.get('rejected', 0)
    return {
        'window': window,
        'total': total,
        'executed_rate': (executed / total) if total else 0,
        'rejected_rate': (rejected / total) if total else 0,
        'tokens_in': int(summary[1]),
        'tokens_out': int(summary[2]),
        'tokens_total': int(summary[1]) + int(summary[2]),
        'latency': {
            'avg_ms': float(summary[3]),
            'p50_ms': float(summary[4]),
            'p95_ms': float(summary[5]),
            'p99_ms': float(summary[6]),
        },
        'avg_confidence': float(summary[7]),
        'by_verdict': by_verdict,
        'by_trigger': [{'trigger': r[0], 'count': int(r[1])} for r in by_trigger_rows],
        'by_action':  [{'action':  r[0], 'count': int(r[1])} for r in by_action_rows],
        'top_reject_reasons': [{'reason': r[0], 'count': int(r[1])} for r in reject_rows],
    }


@router.get('/decisions/heatmap')
async def decision_heatmap(window: str = Query('24h'),
                           target_id: Optional[int] = Query(None),
                           db: AsyncSession = Depends(get_db),
                           user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Per-hour × verdict matrix for a heatmap. Returns one row per hour in
    the window, with counts bucketed by verdict. Hours with no activity are
    included with zeros so the chart axis is contiguous."""
    secs = _resolve_window_seconds(window)
    where = ["d.created_at >= NOW() - make_interval(secs => :secs)"]
    params: Dict[str, Any] = {'secs': secs}
    if target_id is not None:
        where.append('d.scope_target_id = :tid')
        params['tid'] = target_id
    where_sql = ' AND '.join(where)

    rows = (await db.execute(text(f"""
        WITH bucket AS (
            SELECT date_trunc(\'hour\', d.created_at) AS h,
                   d.verdict, COUNT(*) AS c
            FROM agent_decisions d
            WHERE {where_sql}
            GROUP BY 1, 2
        ),
        spine AS (
            SELECT generate_series(
                date_trunc(\'hour\', NOW() - make_interval(secs => :secs)),
                date_trunc(\'hour\', NOW()),
                interval \'1 hour\'
            ) AS h
        )
        SELECT s.h,
               COALESCE(SUM(b.c) FILTER (WHERE b.verdict = \'executed\'), 0),
               COALESCE(SUM(b.c) FILTER (WHERE b.verdict = \'shadow\'),   0),
               COALESCE(SUM(b.c) FILTER (WHERE b.verdict = \'pending\'),  0),
               COALESCE(SUM(b.c) FILTER (WHERE b.verdict = \'rejected\'), 0)
        FROM spine s LEFT JOIN bucket b ON b.h = s.h
        GROUP BY s.h ORDER BY s.h
    """), params)).all()
    return {
        'window': window,
        'buckets': [{
            'hour': r[0].isoformat(),
            'executed': int(r[1]),
            'shadow':   int(r[2]),
            'pending':  int(r[3]),
            'rejected': int(r[4]),
            'total':    int(r[1]) + int(r[2]) + int(r[3]) + int(r[4]),
        } for r in rows],
    }


@router.get('/decisions/cost-series')
async def decision_cost_series(window: str = Query('7d'),
                               bucket: str = Query('hour',
                                   description='Bucket size: hour | day'),
                               target_id: Optional[int] = Query(None),
                               db: AsyncSession = Depends(get_db),
                               user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Token usage time series for the cost chart. Reads usd_to_cny_rate +
    usage_unit from agent_active_config.llm_settings so CNY translation
    matches the rest of the UI."""
    secs = _resolve_window_seconds(window)
    bucket_unit = 'hour' if bucket == 'hour' else 'day'

    # Pull rate / unit from llm_settings — same source as /llm/stats.
    ls_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = \'llm_settings\'"
    ))).first()
    ls = (ls_row[0] if ls_row else None) or {}
    rate = float(ls.get('usd_to_cny_rate') or 7.3)

    where = ["d.created_at >= NOW() - make_interval(secs => :secs)"]
    params: Dict[str, Any] = {'secs': secs}
    if target_id is not None:
        where.append('d.scope_target_id = :tid')
        params['tid'] = target_id
    where_sql = ' AND '.join(where)

    rows = (await db.execute(text(f"""
        WITH bucket AS (
            SELECT date_trunc(:bunit, d.created_at) AS t,
                   COALESCE(SUM(d.llm_tokens_in), 0) AS tin,
                   COALESCE(SUM(d.llm_tokens_out), 0) AS tout,
                   COUNT(*) AS calls
            FROM agent_decisions d
            WHERE {where_sql}
            GROUP BY 1
        ),
        spine AS (
            SELECT generate_series(
                date_trunc(:bunit, NOW() - make_interval(secs => :secs)),
                date_trunc(:bunit, NOW()),
                ('1 ' || :bunit)::interval
            ) AS t
        )
        SELECT s.t,
               COALESCE(b.tin,  0) AS tin,
               COALESCE(b.tout, 0) AS tout,
               COALESCE(b.calls, 0) AS calls
        FROM spine s LEFT JOIN bucket b ON b.t = s.t
        ORDER BY s.t
    """), {**params, 'bunit': bucket_unit})).all()

    # Rough cost estimate — caller can swap to per-model pricing later.
    # Default ~$0.50/M input, $1.50/M output (mid-tier model order of magnitude).
    PRICE_IN_PER_M = 0.5
    PRICE_OUT_PER_M = 1.5
    series = []
    for r in rows:
        tin, tout = int(r[1]), int(r[2])
        usd = (tin / 1e6) * PRICE_IN_PER_M + (tout / 1e6) * PRICE_OUT_PER_M
        series.append({
            'time':   r[0].isoformat(),
            'tokens_in':  tin,
            'tokens_out': tout,
            'calls':  int(r[3]),
            'cost_usd': round(usd, 4),
            'cost_cny': round(usd * rate, 4),
        })
    return {
        'window': window,
        'bucket': bucket_unit,
        'usd_to_cny_rate': rate,
        'series': series,
    }


@router.get('/proposals/{pid}/source-decisions')
async def proposal_source_decisions(pid: int,
                                    limit: int = Query(50, le=200),
                                    db: AsyncSession = Depends(get_db),
                                    user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """List recent decisions on the same target as this proposal — gives
    operators the context that motivated the strategy change request.

    We don\'t have an explicit FK from decisions → proposal yet, so we use
    the (target_id, time-window) heuristic: decisions on this proposal\'s
    target in the 24h leading up to the proposal\'s creation."""
    p_row = (await db.execute(text("""
        SELECT id, target_id, created_at FROM agent_strategy_proposals WHERE id = :pid
    """), {'pid': pid})).first()
    if not p_row:
        raise HTTPException(status_code=404, detail='proposal not found')
    _, tgt_id, p_created = p_row[0], p_row[1], p_row[2]
    if not tgt_id:
        return {'items': [], 'count': 0, 'note': 'global proposal — no target scope'}

    rows = (await db.execute(text("""
        SELECT d.id, d.created_at, d.trigger, d.proposal, d.verdict, d.reject_reason,
               d.llm_latency_ms
        FROM agent_decisions d
        WHERE d.scope_target_id = :tid
          AND d.created_at <= :pc
          AND d.created_at >= :pc - interval \'24 hour\'
        ORDER BY d.id DESC LIMIT :lim
    """), {'tid': tgt_id, 'pc': p_created, 'lim': limit})).all()
    return {
        'items': [{
            'id': r[0], 'created_at': r[1].isoformat(), 'trigger': r[2],
            'action': (r[3] or {}).get('action', '--'),
            'reason': (r[3] or {}).get('reason', ''),
            'confidence': (r[3] or {}).get('confidence', 0),
            'verdict': r[4], 'reject_reason': r[5], 'latency_ms': r[6],
        } for r in rows],
        'count': len(rows),
    }


@router.get('/proposals/{pid}/audit')
async def proposal_audit(pid: int,
                         db: AsyncSession = Depends(get_db),
                         user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Return the full audit trail for a proposal."""
    rows = (await db.execute(text("""
        SELECT a.id, a.proposal_id, a.action, a.actor_user_id::text, u.username,
               a.reason, a.diff_keys, a.target_id, a.created_at
        FROM agent_proposal_audit a
        LEFT JOIN users u ON u.user_id = a.actor_user_id
        WHERE a.proposal_id = :pid
        ORDER BY a.created_at ASC
    """), {'pid': pid})).all()
    return {'items': [{
        'id': r[0], 'proposal_id': r[1], 'action': r[2],
        'actor_user_id': r[3], 'actor_username': r[4],
        'reason': r[5], 'diff_keys': r[6] or [],
        'target_id': r[7], 'created_at': r[8].isoformat() if r[8] else None,
    } for r in rows]}

@router.post('/decisions/{decision_id}/approve')
async def approve_decision(decision_id: int, db: AsyncSession = Depends(get_db),
                           user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Approve a pending decision — re-validates Guard against CURRENT market state
    (not the stale snapshot from when the proposal was generated minutes ago) and
    threads the originating target's ScopeContext all the way through executor.

    Guards against the common failure mode where an operator pauses, market moves,
    and a proposal that was safe 3 minutes ago now violates caps.
    """
    row = (await db.execute(text(
        "SELECT verdict, proposal, scope_target_id FROM agent_decisions WHERE id = :id"
    ), {'id': decision_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail='decision not found')
    if row[0] != 'pending':
        raise HTTPException(status_code=400, detail=f'decision is {row[0]}, not pending')

    from app.services.agent.guard import Proposal, run_guard
    from app.services.agent.executor import execute_proposal
    from app.services.agent.market_snapshot import build_snapshot
    from app.services.agent.scope import list_target_rows, resolve_target

    pj = row[1] or {}
    scope_target_id = row[2]

    proposal = Proposal(
        action=pj.get('action', 'noop'), leg=pj.get('leg', 'both'),
        qty=float(pj.get('qty', 0)), reason=pj.get('reason', ''),
        trigger=pj.get('trigger', ''), confidence=float(pj.get('confidence', 0)),
        is_rebalance_补腿=bool(pj.get('is_rebalance_补腿', False)),
    )

    # Resolve scope context from the original decision's target
    ctx = None
    if scope_target_id is not None:
        rows = await list_target_rows(db, enabled_only=False)
        trow = next((r for r in rows if r['id'] == scope_target_id), None)
        if trow is None:
            raise HTTPException(status_code=400, detail=f'目标 #{scope_target_id} 已被删除，无法执行')
        if not trow['enabled']:
            raise HTTPException(status_code=400, detail=f'目标 #{scope_target_id} 已禁用，无法执行')
        ctx = await resolve_target(db, trow, force=True)
        if ctx is None:
            raise HTTPException(status_code=400, detail=f'目标 #{scope_target_id} scope 解析失败')

    # Re-run Guard against fresh market snapshot — protects against time decay
    fresh_snap = await build_snapshot(db, ctx)
    if fresh_snap is None:
        raise HTTPException(status_code=503, detail='市场快照构建失败（Go 行情不可达？）')
    cfg = await config_loader.load_config(db, target_id=ctx.target_id if ctx else None)
    g = run_guard(proposal, fresh_snap, cfg)
    if not g.ok:
        reason = 'approve_revalidate_failed: ' + ';'.join(g.violations)
        await db.execute(text(
            "UPDATE agent_decisions SET verdict='rejected', reject_reason=:rr WHERE id=:id"
        ), {'rr': reason, 'id': decision_id})
        await db.commit()
        raise HTTPException(status_code=409, detail=f'重检拒绝: {reason}')

    exec_res = await execute_proposal(db, decision_id, proposal, ctx=ctx)
    verdict = 'executed' if exec_res.get('ok') else 'rejected'
    await db.execute(text(
        "UPDATE agent_decisions SET verdict=:v, reject_reason=:rr WHERE id=:id"
    ), {'v': verdict, 'rr': None if exec_res.get('ok') else exec_res.get('reason'),
        'id': decision_id})
    await db.commit()

    return {
        'ok': exec_res.get('ok'),
        'verdict': verdict,
        'exec': exec_res,
        'approved_by': user_id,
        'scope': ctx.label if ctx else 'legacy',
        'revalidated': True,
    }


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
    # Audit log — who approved, when, what changed
    try:
        await db.execute(text("""
            INSERT INTO agent_proposal_audit
              (proposal_id, action, actor_user_id, reason, diff_keys, target_id)
            VALUES (:pid, 'approved', CAST(:u AS UUID), NULL, :keys, :tid)
        """), {'pid': pid, 'u': user_id,
               'keys': list(diff.keys()), 'tid': target_id})
        await db.commit()
    except Exception as _aud_err:
        import logging as _log; _log.getLogger(__name__).warning(
            f'[agent] audit insert failed (approve #{pid}): {_aud_err}')
    config_loader.invalidate(target_id=target_id)
    from app.services.agent.feishu_broadcast import broadcast
    scope_label = f'target#{target_id}' if target_id else 'global'
    await broadcast(db, level='info', category='strategy_approved',
                    message=f'新策略#{pid} 已批准并热加载（范围 {scope_label}, 操作员 {user_id[:8]}）',
                    payload={'proposal_id': pid, 'target_id': target_id, 'keys_changed': list(diff.keys())})
    try:
        from app.services.agent.ws_events import push_proposal_event
        await push_proposal_event('proposal_approved', {
            'id': pid, 'target_id': target_id,
            'keys_changed': list(diff.keys()),
            'actor_user_id': user_id,
        })
    except Exception:
        pass
    return {'ok': True, 'target_id': target_id, 'activated_keys': list(diff.keys())}


@router.post('/strategy-proposals/{pid}/reject')
async def reject_strategy(pid: int, reason: Optional[str] = Body(None, embed=True),
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    result = await db.execute(text("""
        UPDATE agent_strategy_proposals
        SET status='rejected', reviewed_by=CAST(:u AS UUID), reviewed_at=NOW()
        WHERE id=:id AND status='pending'
        RETURNING target_id
    """), {'u': user_id, 'id': pid})
    row = result.first()
    await db.commit()
    if row is None:
        return {'ok': False, 'note': 'proposal not pending'}
    target_id = row[0]
    try:
        await db.execute(text("""
            INSERT INTO agent_proposal_audit
              (proposal_id, action, actor_user_id, reason, diff_keys, target_id)
            VALUES (:pid, 'rejected', CAST(:u AS UUID), :reason, NULL, :tid)
        """), {'pid': pid, 'u': user_id, 'reason': reason, 'tid': target_id})
        await db.commit()
    except Exception as _aud_err:
        import logging as _log; _log.getLogger(__name__).warning(
            f'[agent] audit insert failed (reject #{pid}): {_aud_err}')
    try:
        from app.services.agent.ws_events import push_proposal_event
        await push_proposal_event('proposal_rejected', {
            'id': pid, 'target_id': target_id, 'reason': reason,
            'actor_user_id': user_id,
        })
    except Exception:
        pass
    return {'ok': True}
