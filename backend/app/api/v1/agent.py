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


class AiDraftReq(BaseModel):
    message: str
    target_id: Optional[int] = None
    history: Optional[List[Dict[str, str]]] = None


CONFIG_SCHEMA_PROMPT = """你是 OpenCLAW 量化交易系统的配置助手。用户会用中文自然语言描述配置变更需求，你需要将其转化为精确的 config_diff JSON。

## 系统配置结构

当前系统有以下配置键（agent_active_config 表）：

1. **position_caps** — 持仓限额
   - single_trade_pct (float, 0~1): 单笔交易占总资金比例，如 0.10 = 10%
   - total_position_pct (float, 0~1): 总持仓占总资金比例上限
   - daily_volume_pct (float, 0~100): 日交易量占比上限

2. **rate_limits** — 频次限制
   - max_decisions_per_min (int): 每分钟最大决策数
   - max_trades_per_hour (int): 每小时最大交易数
   - cooldown_after_loss_s (int): 亏损后冷却秒数

3. **symbols** — 交易标的列表
   - (array of strings): 如 ["GBXAU", "XAUUSD"]

4. **spread_modes** — 点差模式
   - (object): 键为标的名，值为模式配置

5. **equity_guard** — 净资产守卫
   - warn_ratio (float, 0~1): 警告阈值
   - critical_ratio (float, 0~1): 危险阈值
   - force_reduce_ratio (float, 0~1): 强制减仓阈值
   - force_reduce_pct (float, 0~1): 强制减仓比例

6. **llm_settings** — LLM 设置
   - model (string): 模型名称
   - streaming (bool): 是否流式
   - balance_alert_threshold_cny (float): 余额告警阈值(元)

7. **rate_limits** — 频次限制（同上）

8. **time_windows** — 时间窗口
   - (object): 交易时段配置

9. **no_profit_alert** — 无盈利告警
   - (object): 告警相关阈值

10. **relay_stations** — 中转站配置（数组，不建议通过提案修改）

11. **chesspnt_auth** — 认证凭据（敏感，不建议通过提案修改）

12. **agent_scope** — 智能体作用域（不建议通过提案修改）

## 当前配置值

{current_config}

## 目标级覆盖

如果用户指定了特定目标（target），config_diff 会写入 agent_target_config 而非全局。
可用目标列表：
{targets_info}

## 输出要求

返回严格的 JSON（无注释，无 markdown 包裹）：
{{
  "title": "简短标题，20字以内",
  "rationale": "业务推理：为什么要改、预期收益、风险点",
  "config_diff": {{ ... }},
  "target_id": null 或目标ID数字,
  "warnings": ["可选的风险提示"],
  "est_position_pct": null 或 0~1 的浮点数
}}

config_diff 只包含需要变更的键和字段，不要包含未变更的部分。
如果用户描述不清或不合理，在 warnings 中说明，仍然尽量给出最接近的 diff。
如果涉及敏感配置（chesspnt_auth, relay_stations），在 warnings 中提示建议走专门管理界面。
"""


@router.post('/proposals/ai-draft')
async def ai_draft_proposal(req: AiDraftReq, db: AsyncSession = Depends(get_db),
                            user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Use LLM to convert natural language into a structured proposal draft."""
    import os, aiohttp, json as _json, logging
    log = logging.getLogger(__name__)

    cfg = await config_loader.load_config(db, force=True)
    ls = cfg.get('llm_settings', {}) or {}
    base = (os.getenv('OPENCLAW_LLM_BASE_URL') or '').rstrip('/')
    key = os.getenv('OPENCLAW_LLM_API_KEY', '')
    model = ls.get('model', '')

    if not base or not key or not model:
        raise HTTPException(status_code=400, detail='LLM 未配置（需要 OPENCLAW_LLM_BASE_URL, OPENCLAW_LLM_API_KEY 和 llm_settings.model）')

    # Build current config context (mask sensitive values)
    config_lines = []
    rows = (await db.execute(text("SELECT key, value FROM agent_active_config ORDER BY key"))).all()
    SENSITIVE_KEYS = {'chesspnt_auth', 'relay_sessions'}
    for row in rows:
        k, v = row[0], row[1]
        if k in SENSITIVE_KEYS:
            config_lines.append(f"- {k}: (敏感，已隐藏)")
        else:
            config_lines.append(f"- {k}: {_json.dumps(v, ensure_ascii=False)}")

    # Build targets info
    targets_rows = (await db.execute(text(
        "SELECT st.id, u.username, st.pair_code FROM agent_scope_targets st JOIN users u ON st.user_id = u.user_id WHERE st.enabled=true ORDER BY st.id"
    ))).all()
    targets_info = '\n'.join(f"  - ID {r[0]}: {r[1]}/{r[2]}" for r in targets_rows) or '(无目标)'

    system_prompt = CONFIG_SCHEMA_PROMPT.format(
        current_config='\n'.join(config_lines),
        targets_info=targets_info,
    )

    messages = [{'role': 'system', 'content': system_prompt}]
    if req.history:
        for h in req.history[-6:]:
            messages.append({'role': h.get('role', 'user'), 'content': h.get('content', '')})
    messages.append({'role': 'user', 'content': req.message})

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(
                f'{base}/v1/chat/completions',
                headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                json={
                    'model': model,
                    'messages': messages,
                    'max_tokens': 2000,
                    'temperature': 0.3,
                },
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.error(f'AI draft LLM error {resp.status}: {body[:500]}')
                    raise HTTPException(status_code=502, detail=f'LLM 调用失败: HTTP {resp.status}')
                data = await resp.json()
                content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f'LLM 网络错误: {e}')

    # Parse LLM response — try to extract JSON
    content = content.strip()
    if content.startswith('```'):
        lines = content.split('\n')
        lines = [l for l in lines if not l.startswith('```')]
        content = '\n'.join(lines).strip()

    try:
        draft = _json.loads(content)
    except _json.JSONDecodeError:
        import re as _re
        m = _re.search(r'\{[\s\S]*\}', content)
        if m:
            try:
                draft = _json.loads(m.group())
            except _json.JSONDecodeError:
                return {'ok': False, 'error': 'AI 返回的内容无法解析为 JSON', 'raw': content}
        else:
            return {'ok': False, 'error': 'AI 返回的内容无法解析为 JSON', 'raw': content}

    # Validate config_diff keys
    valid_keys = {r[0] for r in rows}
    warnings = list(draft.get('warnings', []) or [])
    if draft.get('config_diff'):
        bad_keys = [k for k in draft['config_diff'] if k not in valid_keys]
        if bad_keys:
            warnings.append(f'以下键不在当前配置中，可能无效: {", ".join(bad_keys)}')

    return {
        'ok': True,
        'draft': {
            'title': draft.get('title', ''),
            'rationale': draft.get('rationale', ''),
            'config_diff': draft.get('config_diff', {}),
            'target_id': draft.get('target_id') if draft.get('target_id') else req.target_id,
            'est_position_pct': draft.get('est_position_pct'),
            'warnings': warnings,
        },
        'ai_message': content,
    }


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
    if g.violations:
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


@router.get('/config-audit')
async def get_config_audit(db: AsyncSession = Depends(get_db),
                           user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Returns config with audit metadata (source_proposal_id, updated_at, updated_by)."""
    global_rows = (await db.execute(text(
        'SELECT key, value, source_proposal_id, updated_at, updated_by '
        'FROM agent_active_config ORDER BY key'
    ))).all()
    target_rows = (await db.execute(text(
        'SELECT target_id, key, value, source_proposal_id, updated_at, updated_by '
        'FROM agent_target_config ORDER BY target_id, key'
    ))).all()
    # Resolve target labels
    target_ids = list(set(r[0] for r in target_rows))
    target_labels = {}
    if target_ids:
        label_rows = (await db.execute(text(
            'SELECT st.id, u.username, st.pair_code '
            'FROM agent_scope_targets st JOIN users u ON st.user_id = u.user_id '
            'WHERE st.id = ANY(:ids)'
        ), {'ids': target_ids})).all()
        for lr in label_rows:
            target_labels[lr[0]] = f'{lr[1]}/{lr[2]}'
    return {
        'global': [{
            'key': r[0], 'value': r[1],
            'source_proposal_id': r[2],
            'updated_at': r[3].isoformat() if r[3] else None,
            'updated_by': str(r[4]) if r[4] else None,
        } for r in global_rows],
        'targets': [{
            'target_id': r[0], 'target_label': target_labels.get(r[0], f'#{r[0]}'),
            'key': r[1], 'value': r[2],
            'source_proposal_id': r[3],
            'updated_at': r[4].isoformat() if r[4] else None,
            'updated_by': str(r[5]) if r[5] else None,
        } for r in target_rows],
    }


# ─── Phase B: Dashboard aggregation APIs ─────────────────────────────

@router.get('/targets/comparison')
async def targets_comparison(db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Aggregate per-target KPIs for the comparison table and matrix cards."""
    targets = (await db.execute(text("""
        SELECT t.id, t.user_id, t.pair_code, t.enabled, t.priority,
               u.username,
               upa.account_a_id, upa.account_b_id
        FROM agent_scope_targets t
        JOIN users u ON u.user_id = t.user_id
        LEFT JOIN user_pair_accounts upa ON upa.user_id = t.user_id AND upa.pair_code = t.pair_code
        WHERE t.enabled = true
        ORDER BY t.priority DESC, t.id
    """))).all()

    result = []
    for t in targets:
        tid, uid, pair, enabled, priority, username, acc_a, acc_b = t

        # Decision stats 24h
        dstats = (await db.execute(text("""
            SELECT count(*) as total,
                   count(*) FILTER (WHERE verdict='executed') as executed,
                   count(*) FILTER (WHERE verdict='shadow') as shadow,
                   count(*) FILTER (WHERE verdict='rejected') as rejected,
                   avg((proposal->>'confidence')::float) as avg_conf,
                   max(created_at) as last_decision,
                   min(created_at) as first_decision
            FROM agent_decisions
            WHERE scope_target_id = :tid AND created_at > NOW() - INTERVAL '24 hours'
        """), {'tid': tid})).first()

        total = dstats[0] or 0
        executed = dstats[1] or 0
        shadow = dstats[2] or 0
        rejected = dstats[3] or 0
        avg_conf = float(dstats[4] or 0)
        last_decision = dstats[5].isoformat() if dstats[5] else None

        # Latest market snapshot for balance
        latest_snap = (await db.execute(text("""
            SELECT market_snapshot FROM agent_decisions
            WHERE scope_target_id = :tid AND market_snapshot IS NOT NULL
            ORDER BY id DESC LIMIT 1
        """), {'tid': tid})).scalar()

        a_size = 0
        b_size = 0
        conversion_factor = 1
        a_equity = 0
        b_equity = 0
        total_equity = 0
        if latest_snap and isinstance(latest_snap, dict):
            a_size = latest_snap.get('a_size', 0) or 0
            b_size = latest_snap.get('b_size', 0) or 0
            conversion_factor = latest_snap.get('conversion_factor', 1) or 1
            a_equity = latest_snap.get('a_equity', 0) or 0
            b_equity = latest_snap.get('b_equity', 0) or 0
            total_equity = latest_snap.get('total_equity', 0) or 0

        b_normalized = b_size * conversion_factor
        delta = abs(a_size - b_normalized)
        match_ratio = 0
        if a_size + b_normalized > 0:
            match_ratio = delta / ((a_size + b_normalized) / 2) if (a_size + b_normalized) > 0 else 0

        # Latest account snapshots for net assets
        net_a = 0
        net_b = 0
        margin_used_a = 0
        margin_avail_a = 0
        if acc_a:
            sa = (await db.execute(text("""
                SELECT net_assets, margin_used, margin_available FROM account_snapshots
                WHERE account_id = :aid ORDER BY timestamp DESC LIMIT 1
            """), {'aid': str(acc_a)})).first()
            if sa:
                net_a = float(sa[0] or 0)
                margin_used_a = float(sa[1] or 0)
                margin_avail_a = float(sa[2] or 0)
        if acc_b:
            sb = (await db.execute(text("""
                SELECT net_assets, margin_used, margin_available FROM account_snapshots
                WHERE account_id = :aid ORDER BY timestamp DESC LIMIT 1
            """), {'aid': str(acc_b)})).first()
            if sb:
                net_b = float(sb[0] or 0)

        # Daily PnL estimate from account_snapshots
        daily_pnl_est = 0
        margin_usage_pct = 0
        acc_ids_str = [str(a) for a in [acc_a, acc_b] if a]
        if acc_ids_str:
            dpnl = (await db.execute(text("""
                SELECT COALESCE(avg(daily_pnl), 0) FROM account_snapshots
                WHERE account_id = ANY(:aids) AND timestamp > NOW() - INTERVAL '24 hours'
            """), {'aids': acc_ids_str})).scalar()
            daily_pnl_est = round(float(dpnl or 0), 2)

            # Max drawdown 24h from net_assets series
            snap_rows = (await db.execute(text("""
                SELECT net_assets FROM account_snapshots
                WHERE account_id = ANY(:aids) AND timestamp > NOW() - INTERVAL '24 hours'
                ORDER BY timestamp
            """), {'aids': acc_ids_str})).all()
            peak = 0
            max_dd = 0
            for sr in snap_rows:
                val = float(sr[0] or 0)
                if val > peak:
                    peak = val
                if peak > 0:
                    dd = (peak - val) / peak * 100
                    if dd > max_dd:
                        max_dd = dd

            # Margin usage %
            total_margin = margin_used_a + margin_avail_a
            if total_margin > 0:
                margin_usage_pct = round(margin_used_a / total_margin * 100, 1)
        else:
            max_dd = 0

        # Decisions per hour
        freq_per_hour = round(total / 24, 2) if total else 0

        # Health score (0-100): composite of win rate, balance, latency
        exec_rate = (executed + shadow) / total * 100 if total else 50
        balance_score = max(0, 100 - match_ratio * 500)  # 20% mismatch = 0
        health = min(100, round((exec_rate * 0.5 + balance_score * 0.3 + avg_conf * 100 * 0.2)))

        # Alert level (enhanced)
        alert_level = 'normal'
        alert_reasons = []
        if match_ratio > 0.10:
            alert_level = 'critical'
            alert_reasons.append('持仓偏离>10%')
        elif match_ratio > 0.05:
            alert_level = 'warning'
            alert_reasons.append('持仓偏离>5%')
        if rejected / max(total, 1) > 0.7:
            if alert_level == 'normal':
                alert_level = 'warning'
            alert_reasons.append('拦截率>70%')
        if margin_usage_pct > 80:
            if alert_level == 'normal':
                alert_level = 'warning'
            alert_reasons.append('保证金使用>80%')
        if max_dd > 5:
            if alert_level != 'critical':
                alert_level = 'warning' if max_dd <= 10 else 'critical'
            alert_reasons.append(f'回撤{max_dd:.1f}%')

        result.append({
            'target_id': tid, 'user_id': str(uid), 'username': username,
            'pair_code': pair, 'priority': priority, 'enabled': enabled,
            'total_24h': total, 'executed_24h': executed, 'shadow_24h': shadow,
            'rejected_24h': rejected, 'avg_confidence': round(avg_conf, 3),
            'last_decision_at': last_decision,
            'freq_per_hour': freq_per_hour,
            'a_size': a_size, 'b_size': b_size, 'conversion_factor': conversion_factor,
            'match_deviation_pct': round(match_ratio * 100, 2),
            'a_equity': round(a_equity, 2), 'b_equity': round(b_equity, 2),
            'total_equity': round(total_equity, 2),
            'net_assets_a': round(net_a, 2), 'net_assets_b': round(net_b, 2),
            'net_assets_total': round(net_a + net_b, 2),
            'margin_used_a': round(margin_used_a, 2),
            'margin_available_a': round(margin_avail_a, 2),
            'health_score': health,
            'alert_level': alert_level,
            'account_a_id': str(acc_a) if acc_a else None,
            'account_b_id': str(acc_b) if acc_b else None,
            'daily_pnl_est': daily_pnl_est,
            'max_drawdown_24h': round(max_dd, 2),
            'margin_usage_pct': margin_usage_pct,
            'alert_reasons': alert_reasons,
        })

    # Sort: critical first, then warning, then by health ascending
    level_order = {'critical': 0, 'warning': 1, 'normal': 2}
    result.sort(key=lambda x: (level_order.get(x['alert_level'], 9), -x.get('net_assets_total', 0)))

    return {'items': result}


@router.get('/targets/{target_id}/equity-series')
async def target_equity_series(target_id: int,
                               window: str = Query('24h'),
                               db: AsyncSession = Depends(get_db),
                               user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Net asset time series for a target (A + B accounts combined)."""
    intervals = {'1h': '1 hour', '24h': '24 hours', '7d': '7 days', '30d': '30 days'}
    interval = intervals.get(window, '24 hours')
    bucket = '5 minutes' if window in ('1h', '24h') else '1 hour'

    # Get account IDs
    accs = (await db.execute(text("""
        SELECT upa.account_a_id, upa.account_b_id
        FROM agent_scope_targets t
        JOIN user_pair_accounts upa ON upa.user_id = t.user_id AND upa.pair_code = t.pair_code
        WHERE t.id = :tid
    """), {'tid': target_id})).first()
    if not accs:
        return {'series': [], 'max_drawdown_pct': 0}

    acc_a, acc_b = str(accs[0]) if accs[0] else None, str(accs[1]) if accs[1] else None
    acc_ids = [a for a in [acc_a, acc_b] if a]
    if not acc_ids:
        return {'series': [], 'max_drawdown_pct': 0}

    rows = (await db.execute(text(f"""
        SELECT date_trunc(:bucket, timestamp) as t,
               sum(net_assets) as combined_net,
               sum(margin_used) as combined_margin,
               sum(unrealized_pnl) as combined_pnl
        FROM account_snapshots
        WHERE account_id = ANY(:aids)
          AND timestamp > NOW() - INTERVAL '{interval}'
        GROUP BY t
        ORDER BY t
    """), {'bucket': bucket, 'aids': acc_ids})).all()

    series = []
    peak = 0
    max_dd = 0
    for r in rows:
        net = float(r[1] or 0)
        if net > peak:
            peak = net
        dd = (peak - net) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        series.append({
            'time': r[0].isoformat(),
            'net_assets': round(net, 2),
            'margin_used': round(float(r[2] or 0), 2),
            'unrealized_pnl': round(float(r[3] or 0), 2),
            'drawdown_pct': round(dd, 2),
        })

    return {'series': series, 'max_drawdown_pct': round(max_dd, 2), 'peak_net': round(peak, 2)}


@router.get('/targets/{target_id}/balance-series')
async def target_balance_series(target_id: int,
                                window: str = Query('24h'),
                                db: AsyncSession = Depends(get_db),
                                user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Position balance (A leg vs B leg) time series extracted from decision snapshots."""
    intervals = {'1h': '1 hour', '24h': '24 hours', '7d': '7 days', '30d': '30 days'}
    interval = intervals.get(window, '24 hours')

    rows = (await db.execute(text(f"""
        SELECT created_at,
               market_snapshot->>'a_size' as a_size,
               market_snapshot->>'b_size' as b_size,
               market_snapshot->>'conversion_factor' as cf,
               market_snapshot->>'a_equity' as a_eq,
               market_snapshot->>'b_equity' as b_eq
        FROM agent_decisions
        WHERE scope_target_id = :tid
          AND market_snapshot IS NOT NULL
          AND created_at > NOW() - INTERVAL '{interval}'
        ORDER BY created_at
    """), {'tid': target_id})).all()

    series = []
    for r in rows:
        a = float(r[1] or 0)
        b = float(r[2] or 0)
        cf = float(r[3] or 1) or 1
        b_norm = b * cf
        delta = a - b_norm
        series.append({
            'time': r[0].isoformat(),
            'a_size': a,
            'b_size': b,
            'b_normalized': round(b_norm, 4),
            'delta': round(delta, 4),
            'a_equity': round(float(r[4] or 0), 2),
            'b_equity': round(float(r[5] or 0), 2),
        })

    return {'series': series}


@router.get('/targets/{target_id}/fund-allocation')
async def target_fund_allocation(target_id: int,
                                 db: AsyncSession = Depends(get_db),
                                 user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Cross-platform fund allocation for a target."""
    accs = (await db.execute(text("""
        SELECT upa.account_a_id, upa.account_b_id
        FROM agent_scope_targets t
        JOIN user_pair_accounts upa ON upa.user_id = t.user_id AND upa.pair_code = t.pair_code
        WHERE t.id = :tid
    """), {'tid': target_id})).first()
    if not accs:
        return {'platforms': [], 'total_net': 0}

    platforms = []
    total_net = 0
    for acc_id, leg in [(accs[0], 'A'), (accs[1], 'B')]:
        if not acc_id:
            continue
        info = (await db.execute(text("""
            SELECT a.account_id, a.platform_id, p.platform_name, p.display_name, a.account_name, a.is_mt5_account
            FROM accounts a
            LEFT JOIN platforms p ON a.platform_id = p.platform_id
            WHERE a.account_id = :aid
        """), {'aid': str(acc_id)})).first()
        snap = (await db.execute(text("""
            SELECT net_assets, margin_used, margin_available, unrealized_pnl, total_assets
            FROM account_snapshots WHERE account_id = :aid ORDER BY timestamp DESC LIMIT 1
        """), {'aid': str(acc_id)})).first()
        if info and snap:
            net = float(snap[0] or 0)
            margin_used = float(snap[1] or 0)
            margin_avail = float(snap[2] or 0)
            total_net += net
            margin_total = margin_used + margin_avail
            platforms.append({
                'leg': leg,
                'platform': info[2] or f'platform_{info[1]}',
                'display_name': info[3] or info[2] or '',
                'account_name': info[4],
                'is_mt5': info[5],
                'net_assets': round(net, 2),
                'margin_used': round(margin_used, 2),
                'margin_available': round(margin_avail, 2),
                'margin_usage_pct': round(margin_used / margin_total * 100, 1) if margin_total > 0 else 0,
                'unrealized_pnl': round(float(snap[3] or 0), 2),
                'total_assets': round(float(snap[4] or 0), 2),
            })

    return {'platforms': platforms, 'total_net': round(total_net, 2)}


@router.get('/targets/{target_id}/pnl-series')
async def target_pnl_series(target_id: int,
                            window: str = Query('7d'),
                            db: AsyncSession = Depends(get_db),
                            user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Phase C scaffold: daily PnL series from account_snapshots daily_pnl + trades when available."""
    intervals = {'1h': '1 hour', '24h': '24 hours', '7d': '7 days', '30d': '30 days'}
    interval = intervals.get(window, '7 days')

    accs = (await db.execute(text("""
        SELECT upa.account_a_id, upa.account_b_id
        FROM agent_scope_targets t
        JOIN user_pair_accounts upa ON upa.user_id = t.user_id AND upa.pair_code = t.pair_code
        WHERE t.id = :tid
    """), {'tid': target_id})).first()
    if not accs:
        return {'series': [], 'total_pnl': 0, 'source': 'no_accounts'}

    acc_ids = [str(a) for a in [accs[0], accs[1]] if a]

    # Try trades table first (Phase C: will have data when system goes live)
    trade_count = (await db.execute(text("""
        SELECT count(*) FROM trades WHERE account_id = ANY(:aids)
    """), {'aids': acc_ids})).scalar()

    if trade_count and trade_count > 0:
        rows = (await db.execute(text(f"""
            SELECT date_trunc('day', timestamp) as d,
                   sum(realized_pnl) as day_pnl,
                   sum(fee) as day_fee,
                   count(*) as trade_count,
                   count(*) FILTER (WHERE realized_pnl > 0) as wins,
                   count(*) FILTER (WHERE realized_pnl <= 0) as losses
            FROM trades
            WHERE account_id = ANY(:aids) AND timestamp > NOW() - INTERVAL '{interval}'
            GROUP BY d ORDER BY d
        """), {'aids': acc_ids})).all()
        series = [{
            'date': r[0].isoformat()[:10],
            'pnl': round(float(r[1] or 0), 2),
            'fee': round(float(r[2] or 0), 2),
            'net_pnl': round(float(r[1] or 0) - float(r[2] or 0), 2),
            'trade_count': r[3],
            'win_rate': round(r[4] / max(r[3], 1) * 100, 1),
        } for r in rows]
        total_pnl = sum(s['net_pnl'] for s in series)
        return {'series': series, 'total_pnl': round(total_pnl, 2), 'source': 'trades'}

    # Fallback: daily_pnl from account_snapshots (less accurate but available)
    rows = (await db.execute(text(f"""
        SELECT date_trunc('day', timestamp) as d,
               avg(daily_pnl) as avg_daily_pnl,
               count(*) as snap_count
        FROM account_snapshots
        WHERE account_id = ANY(:aids) AND timestamp > NOW() - INTERVAL '{interval}'
        GROUP BY d ORDER BY d
    """), {'aids': acc_ids})).all()
    series = [{
        'date': r[0].isoformat()[:10],
        'pnl': round(float(r[1] or 0), 2),
        'fee': 0,
        'net_pnl': round(float(r[1] or 0), 2),
        'trade_count': 0,
        'win_rate': 0,
        'snap_count': r[2],
    } for r in rows]
    total_pnl = sum(s['net_pnl'] for s in series)
    return {'series': series, 'total_pnl': round(total_pnl, 2), 'source': 'snapshots_fallback'}


@router.get('/targets/{target_id}/confidence-trend')
async def target_confidence_trend(target_id: int,
                                  window: str = Query('7d'),
                                  db: AsyncSession = Depends(get_db),
                                  user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Daily confidence and verdict distribution trend for decision quality charts."""
    intervals = {'1h': '1 hour', '24h': '24 hours', '7d': '7 days', '30d': '30 days'}
    interval = intervals.get(window, '7 days')
    rows = (await db.execute(text(f"""
        SELECT date_trunc('day', created_at) as d,
               avg((proposal->>'confidence')::float) as avg_conf,
               count(*) as total,
               count(*) FILTER (WHERE verdict='executed') as executed,
               count(*) FILTER (WHERE verdict='shadow') as shadow,
               count(*) FILTER (WHERE verdict='rejected') as rejected,
               avg(llm_latency_ms) as avg_latency
        FROM agent_decisions
        WHERE scope_target_id = :tid AND created_at > NOW() - INTERVAL '{interval}'
        GROUP BY d ORDER BY d
    """), {'tid': target_id})).all()

    series = [{
        'date': r[0].isoformat()[:10],
        'avg_confidence': round(float(r[1] or 0), 3),
        'total': r[2],
        'executed': r[3], 'shadow': r[4], 'rejected': r[5],
        'exec_rate': round((r[3] + r[4]) / max(r[2], 1) * 100, 1),
        'avg_latency_ms': round(float(r[6] or 0), 0),
    } for r in rows]
    return {'series': series}


@router.get('/alerts/active')
async def active_alerts(db: AsyncSession = Depends(get_db),
                        user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Recent alerts for dashboard badges."""
    rows = (await db.execute(text("""
        SELECT id, level, category, message, created_at, ack_at
        FROM agent_alerts
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY id DESC LIMIT 100
    """))).all()
    items = [{
        'id': r[0], 'level': r[1], 'category': r[2], 'message': r[3],
        'created_at': r[4].isoformat() if r[4] else None,
        'acked': r[5] is not None,
    } for r in rows]
    unacked = len([i for i in items if not i['acked']])
    by_level = {}
    for i in items:
        by_level[i['level']] = by_level.get(i['level'], 0) + 1
    return {'items': items, 'unacked_count': unacked, 'by_level': by_level}


# ───── Infrastructure Monitoring APIs (Batch 2) ─────


@router.get("/llm-latency-series")
async def llm_latency_series(
    window: str = Query("7d"),
    bucket: str = Query("hour", description="hour | day"),
    target_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """LLM latency time series for infrastructure chart."""
    secs = _resolve_window_seconds(window)
    bucket_unit = "hour" if bucket == "hour" else "day"

    where = ["d.created_at >= NOW() - make_interval(secs => :secs)", "d.llm_latency_ms IS NOT NULL"]
    params: Dict[str, Any] = {"secs": secs}
    if target_id is not None:
        where.append("d.scope_target_id = :tid")
        params["tid"] = target_id
    where_sql = " AND ".join(where)

    rows = (await db.execute(text(f"""
        WITH bucket AS (
            SELECT date_trunc(:bunit, d.created_at) AS t,
                   AVG(d.llm_latency_ms)::int AS avg_ms,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY d.llm_latency_ms)::int AS p50,
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY d.llm_latency_ms)::int AS p95,
                   PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY d.llm_latency_ms)::int AS p99,
                   MIN(d.llm_latency_ms)::int AS min_ms,
                   MAX(d.llm_latency_ms)::int AS max_ms,
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
               COALESCE(b.avg_ms, 0), COALESCE(b.p50, 0), COALESCE(b.p95, 0),
               COALESCE(b.p99, 0), COALESCE(b.min_ms, 0), COALESCE(b.max_ms, 0),
               COALESCE(b.calls, 0)
        FROM spine s LEFT JOIN bucket b ON b.t = s.t
        ORDER BY s.t
    """), {**params, "bunit": bucket_unit})).all()

    return {
        "window": window,
        "bucket": bucket_unit,
        "series": [
            {
                "time": r[0].isoformat(),
                "avg_ms": int(r[1]), "p50": int(r[2]), "p95": int(r[3]),
                "p99": int(r[4]), "min_ms": int(r[5]), "max_ms": int(r[6]),
                "calls": int(r[7]),
            }
            for r in rows
        ],
    }


@router.get("/token-usage-series")
async def token_usage_series(
    window: str = Query("7d"),
    bucket: str = Query("hour", description="hour | day"),
    target_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Token consumption trend (in/out/cost) for infrastructure chart."""
    secs = _resolve_window_seconds(window)
    bucket_unit = "hour" if bucket == "hour" else "day"

    ls_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'llm_settings'"
    ))).first()
    ls = (ls_row[0] if ls_row else None) or {}
    rate = float(ls.get("usd_to_cny_rate") or 7.3)

    where = ["d.created_at >= NOW() - make_interval(secs => :secs)"]
    params: Dict[str, Any] = {"secs": secs}
    if target_id is not None:
        where.append("d.scope_target_id = :tid")
        params["tid"] = target_id
    where_sql = " AND ".join(where)

    rows = (await db.execute(text(f"""
        WITH bucket AS (
            SELECT date_trunc(:bunit, d.created_at) AS t,
                   COALESCE(SUM(d.llm_tokens_in), 0) AS tin,
                   COALESCE(SUM(d.llm_tokens_out), 0) AS tout,
                   COUNT(*) AS calls,
                   COALESCE(AVG(d.llm_latency_ms), 0)::int AS avg_latency
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
               COALESCE(b.tin, 0), COALESCE(b.tout, 0),
               COALESCE(b.calls, 0), COALESCE(b.avg_latency, 0)
        FROM spine s LEFT JOIN bucket b ON b.t = s.t
        ORDER BY s.t
    """), {**params, "bunit": bucket_unit})).all()

    PRICE_IN_PER_M = 0.5
    PRICE_OUT_PER_M = 1.5
    series = []
    cumulative_in = 0
    cumulative_out = 0
    for r in rows:
        tin, tout = int(r[1]), int(r[2])
        cumulative_in += tin
        cumulative_out += tout
        usd = (tin / 1e6) * PRICE_IN_PER_M + (tout / 1e6) * PRICE_OUT_PER_M
        series.append({
            "time": r[0].isoformat(),
            "tokens_in": tin,
            "tokens_out": tout,
            "tokens_total": tin + tout,
            "cumulative_in": cumulative_in,
            "cumulative_out": cumulative_out,
            "calls": int(r[3]),
            "avg_latency_ms": int(r[4]),
            "cost_usd": round(usd, 4),
            "cost_cny": round(usd * rate, 4),
        })
    return {
        "window": window,
        "bucket": bucket_unit,
        "usd_to_cny_rate": rate,
        "totals": {
            "tokens_in": cumulative_in,
            "tokens_out": cumulative_out,
            "cost_usd": round((cumulative_in / 1e6) * PRICE_IN_PER_M + (cumulative_out / 1e6) * PRICE_OUT_PER_M, 4),
        },
        "series": series,
    }


@router.get("/alerts/circuit-breaker-timeline")
async def circuit_breaker_timeline(
    window: str = Query("30d"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Circuit breaker event timeline filtered from agent_alerts."""
    secs = _resolve_window_seconds(window)
    rows = (await db.execute(text("""
        SELECT id, level, message, created_at, ack_at
        FROM agent_alerts
        WHERE category = 'circuit_breaker'
          AND created_at >= NOW() - make_interval(secs => :secs)
        ORDER BY id DESC
        LIMIT 200
    """), {"secs": secs})).all()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "level": r[1],
            "message": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "acked": r[4] is not None,
            "ack_at": r[4].isoformat() if r[4] else None,
        })

    by_level = {}
    for i in items:
        by_level[i["level"]] = by_level.get(i["level"], 0) + 1

    return {
        "window": window,
        "total": len(items),
        "by_level": by_level,
        "items": items,
    }


@router.get("/intervention-stats")
async def intervention_stats(
    window: str = Query("30d"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """30-day aggregated intervention statistics."""
    secs = _resolve_window_seconds(window)

    summary = (await db.execute(text("""
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE state = 'RESOLVED') AS resolved,
          COUNT(*) FILTER (WHERE state = 'FORCED_REDUCE') AS forced_reduce,
          COUNT(*) FILTER (WHERE state = 'ESCALATING') AS escalating,
          COUNT(*) FILTER (WHERE state = 'WARNING') AS warning,
          COUNT(*) FILTER (WHERE resolved_at IS NULL) AS active,
          AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - triggered_at)))::int AS avg_duration_s,
          AVG(equity_ratio) AS avg_equity_ratio,
          MIN(equity_ratio) AS min_equity_ratio
        FROM equity_intervention_log
        WHERE triggered_at >= NOW() - make_interval(secs => :secs)
    """), {"secs": secs})).first()

    daily = (await db.execute(text("""
        SELECT date_trunc('day', triggered_at)::date AS day,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE state = 'FORCED_REDUCE') AS forced,
               AVG(equity_ratio) AS avg_ratio
        FROM equity_intervention_log
        WHERE triggered_at >= NOW() - make_interval(secs => :secs)
        GROUP BY 1 ORDER BY 1
    """), {"secs": secs})).all()

    return {
        "window": window,
        "summary": {
            "total": int(summary[0] or 0),
            "resolved": int(summary[1] or 0),
            "forced_reduce": int(summary[2] or 0),
            "escalating": int(summary[3] or 0),
            "warning": int(summary[4] or 0),
            "active": int(summary[5] or 0),
            "avg_duration_s": int(summary[6] or 0),
            "avg_equity_ratio": round(float(summary[7] or 0), 4),
            "min_equity_ratio": round(float(summary[8] or 0), 4),
        },
        "daily": [
            {
                "date": str(r[0]),
                "total": int(r[1]),
                "forced_reduce": int(r[2]),
                "avg_equity_ratio": round(float(r[3] or 0), 4),
            }
            for r in daily
        ],
    }


# ───── Batch 3: Equity / Exposure / Confidence APIs ─────


@router.get("/equity/snapshot-series")
async def equity_snapshot_series(
    window: str = Query("7d"),
    bucket: str = Query("hour", description="hour | day"),
    account_id: Optional[str] = Query(None),
    platform_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Historical net-asset time series from account_snapshots,
    grouped by platform for cross-platform overlay."""
    secs = _resolve_window_seconds(window)
    bucket_unit = "hour" if bucket == "hour" else "day"

    where = ["s.timestamp >= NOW() - make_interval(secs => :secs)"]
    params: Dict[str, Any] = {"secs": secs}
    if account_id:
        where.append("s.account_id = :aid::uuid")
        params["aid"] = account_id
    if platform_id is not None:
        where.append("a.platform_id = :pid")
        params["pid"] = platform_id
    where_sql = " AND ".join(where)

    sql = """
        SELECT date_trunc(:bunit, s.timestamp) AS t,
               p.platform_name,
               a.platform_id,
               AVG(s.net_assets)        AS avg_net,
               AVG(s.total_assets)      AS avg_total,
               AVG(s.unrealized_pnl)    AS avg_upnl,
               AVG(s.daily_pnl)         AS avg_daily_pnl,
               AVG(s.margin_used)       AS avg_margin,
               COUNT(*)                 AS samples
        FROM account_snapshots s
        JOIN accounts a ON s.account_id = a.account_id
        JOIN platforms p ON a.platform_id = p.platform_id
        WHERE """ + where_sql + """
        GROUP BY 1, 2, 3
        ORDER BY 1, 3
    """
    rows = (await db.execute(text(sql), {**params, "bunit": bucket_unit})).all()

    by_platform = {}
    for r in rows:
        pname = r[1]
        if pname not in by_platform:
            by_platform[pname] = {"platform_id": int(r[2]), "series": []}
        by_platform[pname]["series"].append({
            "time": r[0].isoformat(),
            "net_assets": round(float(r[3] or 0), 2),
            "total_assets": round(float(r[4] or 0), 2),
            "unrealized_pnl": round(float(r[5] or 0), 2),
            "daily_pnl": round(float(r[6] or 0), 2),
            "margin_used": round(float(r[7] or 0), 2),
            "samples": int(r[8]),
        })

    # Combined cross-platform total
    agg_sql = """
        SELECT t, SUM(avg_net) AS total_net, SUM(avg_upnl) AS total_upnl
        FROM (
            SELECT date_trunc(:bunit, s.timestamp) AS t,
                   s.account_id,
                   AVG(s.net_assets) AS avg_net,
                   AVG(s.unrealized_pnl) AS avg_upnl
            FROM account_snapshots s
            JOIN accounts a ON s.account_id = a.account_id
            WHERE """ + where_sql + """
            GROUP BY 1, s.account_id
        ) sub
        GROUP BY 1 ORDER BY 1
    """
    agg_rows = (await db.execute(text(agg_sql), {**params, "bunit": bucket_unit})).all()
    combined = [{
        "time": r[0].isoformat(),
        "total_net_assets": round(float(r[1] or 0), 2),
        "total_unrealized_pnl": round(float(r[2] or 0), 2),
    } for r in agg_rows]

    return {
        "window": window,
        "bucket": bucket_unit,
        "platforms": by_platform,
        "combined": combined,
    }


@router.get("/equity/realtime")
async def equity_realtime(
    target_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Realtime cross-platform equity via collect_xau_positions_and_equity.
    Designed for frontend polling (15-30s interval)."""
    from app.services.agent.market_snapshot import collect_xau_positions_and_equity, fetch_conversion_factor
    from app.services.agent.scope import list_active_contexts
    import time

    t0 = time.time()
    contexts = await list_active_contexts(db)
    results = []

    if target_id is not None:
        ctx = next((c for c in contexts if c.target_id == target_id), None)
        if not ctx:
            raise HTTPException(404, "target not found")
        eq = await collect_xau_positions_and_equity(db, ctx)
        conv = await fetch_conversion_factor(db, ctx)
        results.append({
            "target_id": ctx.target_id,
            "pair_code": ctx.pair_code,
            "label": ctx.label,
            "a_size": eq["a_size"], "b_size": eq["b_size"],
            "a_equity": eq.get("a_equity", 0), "b_equity": eq.get("b_equity", 0),
            "total_equity": eq.get("total_equity", 0),
            "delta": eq["a_size"] - eq["b_size"] * conv,
            "conversion_factor": conv,
        })
    else:
        for ctx in contexts:
            try:
                eq = await collect_xau_positions_and_equity(db, ctx)
                conv = await fetch_conversion_factor(db, ctx)
                results.append({
                    "target_id": ctx.target_id,
                    "pair_code": ctx.pair_code,
                    "label": ctx.label,
                    "a_size": eq["a_size"], "b_size": eq["b_size"],
                    "a_equity": eq.get("a_equity", 0), "b_equity": eq.get("b_equity", 0),
                    "total_equity": eq.get("total_equity", 0),
                    "delta": eq["a_size"] - eq["b_size"] * conv,
                    "conversion_factor": conv,
                })
            except Exception as e:
                results.append({
                    "target_id": ctx.target_id,
                    "pair_code": ctx.pair_code,
                    "label": ctx.label,
                    "error": str(e),
                })

    total_equity = sum(r.get("total_equity", 0) for r in results if "error" not in r)
    total_delta = sum(r.get("delta", 0) for r in results if "error" not in r)

    return {
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "elapsed_ms": int((time.time() - t0) * 1000),
        "targets": results,
        "aggregated": {
            "total_equity": total_equity,
            "total_delta": total_delta,
            "target_count": len([r for r in results if "error" not in r]),
        },
    }


@router.get("/equity/exposure")
async def equity_exposure(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Cross-platform exposure breakdown — latest snapshot per account
    grouped by platform, for the exposure pie/bar chart."""
    rows = (await db.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (s.account_id)
                   s.account_id, s.net_assets, s.total_assets,
                   s.unrealized_pnl, s.margin_used, s.total_position,
                   s.timestamp,
                   a.platform_id, a.account_name,
                   p.platform_name
            FROM account_snapshots s
            JOIN accounts a ON s.account_id = a.account_id
            JOIN platforms p ON a.platform_id = p.platform_id
            WHERE s.timestamp >= NOW() - INTERVAL '2 hours'
            ORDER BY s.account_id, s.timestamp DESC
        )
        SELECT * FROM latest ORDER BY platform_id, account_name
    """))).all()

    accounts = []
    by_platform = {}
    for r in rows:
        entry = {
            "account_id": str(r[0]),
            "net_assets": round(float(r[1] or 0), 2),
            "total_assets": round(float(r[2] or 0), 2),
            "unrealized_pnl": round(float(r[3] or 0), 2),
            "margin_used": round(float(r[4] or 0), 2),
            "total_position": round(float(r[5] or 0), 4),
            "snapshot_at": r[6].isoformat() if r[6] else None,
            "platform_id": int(r[7]),
            "account_name": r[8],
            "platform_name": r[9],
        }
        accounts.append(entry)
        pname = r[9]
        if pname not in by_platform:
            by_platform[pname] = {"platform_id": int(r[7]), "net_assets": 0, "margin_used": 0, "accounts": 0}
        by_platform[pname]["net_assets"] += entry["net_assets"]
        by_platform[pname]["margin_used"] += entry["margin_used"]
        by_platform[pname]["accounts"] += 1

    total_net = sum(a["net_assets"] for a in accounts)
    for p in by_platform.values():
        p["net_assets"] = round(p["net_assets"], 2)
        p["margin_used"] = round(p["margin_used"], 2)
        p["pct"] = round(p["net_assets"] / total_net * 100, 1) if total_net else 0

    return {
        "total_net_assets": round(total_net, 2),
        "total_accounts": len(accounts),
        "by_platform": by_platform,
        "accounts": accounts,
    }


@router.get("/decisions/confidence-distribution")
async def confidence_distribution(
    window: str = Query("7d"),
    target_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Confidence score distribution histogram + stats per target."""
    secs = _resolve_window_seconds(window)

    where = ["d.created_at >= NOW() - make_interval(secs => :secs)",
             "d.proposal IS NOT NULL"]
    params: Dict[str, Any] = {"secs": secs}
    if target_id is not None:
        where.append("d.scope_target_id = :tid")
        params["tid"] = target_id
    where_sql = " AND ".join(where)

    # Histogram: 10 bins from 0.0 to 1.0
    hist_sql = """
        SELECT
            width_bucket((d.proposal->>'confidence')::float, 0, 1.001, 10) AS bin,
            COUNT(*) AS cnt,
            d.verdict
        FROM agent_decisions d
        WHERE """ + where_sql + """
          AND d.proposal->>'confidence' IS NOT NULL
        GROUP BY 1, 3
        ORDER BY 1
    """
    hist_rows = (await db.execute(text(hist_sql), params)).all()

    bins = []
    for b in range(1, 11):
        lo = round((b - 1) * 0.1, 1)
        hi = round(b * 0.1, 1)
        label = f"{lo:.1f}-{hi:.1f}"
        row_data = {"bin": b, "range": label, "total": 0}
        for r in hist_rows:
            if r[0] == b:
                row_data["total"] += int(r[1])
                row_data[r[2] or "unknown"] = int(r[1])
        bins.append(row_data)

    # Per-target stats
    target_sql = """
        SELECT d.scope_target_id,
               COUNT(*) AS total,
               AVG((d.proposal->>'confidence')::float) AS avg_conf,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (d.proposal->>'confidence')::float) AS median_conf,
               MIN((d.proposal->>'confidence')::float) AS min_conf,
               MAX((d.proposal->>'confidence')::float) AS max_conf,
               STDDEV((d.proposal->>'confidence')::float) AS stddev_conf
        FROM agent_decisions d
        WHERE """ + where_sql + """
          AND d.proposal->>'confidence' IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """
    target_rows = (await db.execute(text(target_sql), params)).all()
    by_target = [{
        "target_id": r[0],
        "total": int(r[1]),
        "avg": round(float(r[2] or 0), 3),
        "median": round(float(r[3] or 0), 3),
        "min": round(float(r[4] or 0), 3),
        "max": round(float(r[5] or 0), 3),
        "stddev": round(float(r[6] or 0), 3),
    } for r in target_rows]

    # Confidence vs verdict correlation
    corr_sql = """
        SELECT d.verdict,
               COUNT(*) AS cnt,
               AVG((d.proposal->>'confidence')::float) AS avg_conf
        FROM agent_decisions d
        WHERE """ + where_sql + """
          AND d.proposal->>'confidence' IS NOT NULL
        GROUP BY 1
    """
    corr_rows = (await db.execute(text(corr_sql), params)).all()
    by_verdict = {r[0]: {"count": int(r[1]), "avg_confidence": round(float(r[2] or 0), 3)} for r in corr_rows}

    return {
        "window": window,
        "target_id": target_id,
        "histogram": bins,
        "by_target": by_target,
        "by_verdict": by_verdict,
    }


# ───── Batch 4: Daily Cost Paginated + CSV Export ─────



@router.get("/decisions/cost-daily")
async def decision_cost_daily(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    window: str = Query("30d"),
    fmt: str = Query("json", description="json | csv"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
):
    """Daily token cost from chesspnt relay logs, grouped by date.
    Fetches ALL models used on the primary relay."""
    import aiohttp, datetime as _dt
    from collections import defaultdict

    cfg_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'relay_stations'"
    ))).scalar()
    stations = cfg_row if isinstance(cfg_row, list) else []
    active = next((r for r in stations if r.get('enabled') and r.get('role') == 'primary'), None)
    if not active:
        raise HTTPException(400, "no active primary relay station")

    base = active.get('api_base', 'https://api.chesspnt.com').rstrip('/')
    cookie = active.get('session_cookie', '')
    new_api_user = str(active.get('new_api_user', ''))
    units_per_usd = float(active.get('units_per_usd', 500000))

    headers = {
        'accept': 'application/json, text/plain, */*',
        'cookie': f'session={cookie}',
    }
    if new_api_user:
        headers['new-api-user'] = new_api_user

    secs = _resolve_window_seconds(window)
    start_ts = int((_dt.datetime.utcnow() - _dt.timedelta(seconds=secs)).timestamp())
    now_ts = int(_time_mod.time())

    daily: Dict[str, Dict] = defaultdict(lambda: {
        'calls': 0, 'tokens_in': 0, 'tokens_out': 0, 'quota': 0,
    })

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120)
        ) as session:
            pg = 0
            while pg < 200:
                params = {
                    'p': str(pg), 'page_size': '100',
                    'start_timestamp': str(start_ts),
                    'end_timestamp': str(now_ts),
                }
                async with session.get(
                    f'{base}/api/log/self', headers=headers, params=params
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if not data.get('success'):
                        break
                    items = data.get('data', {}).get('items', [])
                    total_records = data.get('data', {}).get('total', 0)
                    for item in items:
                        ts = item.get('created_at', 0)
                        day = _dt.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d') if ts else 'unknown'
                        d = daily[day]
                        d['calls'] += 1
                        d['tokens_in'] += item.get('prompt_tokens', 0)
                        d['tokens_out'] += item.get('completion_tokens', 0)
                        d['quota'] += item.get('quota', 0)
                    if not items or (pg + 1) * 100 >= total_records:
                        break
                    pg += 1
    except Exception:
        pass

    all_items = []
    for day in sorted(daily.keys(), reverse=True):
        d = daily[day]
        usd = d['quota'] / units_per_usd if units_per_usd else 0
        all_items.append({
            'date': day,
            'calls': d['calls'],
            'tokens_in': d['tokens_in'],
            'tokens_out': d['tokens_out'],
            'tokens_total': d['tokens_in'] + d['tokens_out'],
            'cost_usd': round(usd, 4),
        })

    total_days = len(all_items)
    total_pages = max(1, -(-total_days // page_size))

    if fmt == "csv":
        import io, csv as _csv
        from fastapi.responses import StreamingResponse
        buf = io.StringIO()
        buf.write('﻿')
        w = _csv.writer(buf)
        w.writerow(["日期", "调用次数", "Tokens_In", "Tokens_Out", "Tokens_Total", "费用USD"])
        for it in all_items:
            w.writerow([it["date"], it["calls"], it["tokens_in"], it["tokens_out"],
                        it["tokens_total"], it["cost_usd"]])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=token_cost_daily.csv"},
        )

    offset = (page - 1) * page_size
    paged = all_items[offset:offset + page_size]

    return {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "total_days": total_days,
        "items": paged,
    }


# ───── Relay Cost Summary (chesspnt real-time, model-filtered) ─────

import time as _time_mod

_relay_cost_cache: Dict[str, Any] = {}
_relay_cost_cache_ts: float = 0


@router.get("/relay/cost-summary")
async def relay_cost_summary(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Real-time token cost for the active primary relay model only.
    Aggregates quota from chesspnt /api/log/self filtered by model_name.
    Cached 120s."""
    import aiohttp, datetime as _dt

    global _relay_cost_cache, _relay_cost_cache_ts
    now = _time_mod.time()
    if _relay_cost_cache and now - _relay_cost_cache_ts < 120:
        return _relay_cost_cache

    cfg_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'relay_stations'"
    ))).scalar()
    stations = cfg_row if isinstance(cfg_row, list) else []
    active = next((r for r in stations if r.get('enabled') and r.get('role') == 'primary'), None)
    if not active:
        return {"error": "no active primary relay station"}

    base = active.get('api_base', 'https://api.chesspnt.com').rstrip('/')
    cookie = active.get('session_cookie', '')
    new_api_user = str(active.get('new_api_user', ''))
    units_per_usd = float(active.get('units_per_usd', 500000))
    usd_to_cny = float(active.get('usd_to_cny_rate', 7.3))
    model_name = active.get('model', '')

    if not cookie:
        return {"error": "no session cookie configured"}
    if not model_name:
        return {"error": "no model configured on primary relay"}

    headers = {
        'accept': 'application/json, text/plain, */*',
        'cookie': f'session={cookie}',
    }
    if new_api_user:
        headers['new-api-user'] = new_api_user

    utc_today = _dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ts = int(utc_today.timestamp())
    now_ts = int(_time_mod.time())

    async def sum_pages(session, start_ts, end_ts, max_pages=100):
        total_quota = 0
        total_calls = 0
        total_records = 0
        page = 0
        while page < max_pages:
            p = {'p': str(page), 'page_size': '100', 'model_name': model_name}
            if start_ts:
                p['start_timestamp'] = str(start_ts)
            if end_ts:
                p['end_timestamp'] = str(end_ts)
            async with session.get(f'{base}/api/log/self', headers=headers, params=p) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data.get('success'):
                    break
                items = data.get('data', {}).get('items', [])
                total_records = data.get('data', {}).get('total', 0)
                for item in items:
                    total_quota += item.get('quota', 0)
                    total_calls += 1
                if not items or (page + 1) * 100 >= total_records:
                    break
                page += 1
        usd = total_quota / units_per_usd if units_per_usd else 0
        return {
            'quota_units': total_quota,
            'cost_usd': round(usd, 4),
            'cost_cny': round(usd * usd_to_cny, 2),
            'calls': total_calls,
            'total_records': total_records,
            'complete': total_calls >= total_records,
        }

    today = {"quota_units": 0, "cost_usd": 0, "cost_cny": 0, "calls": 0}
    cumulative = {"quota_units": 0, "cost_usd": 0, "cost_cny": 0, "calls": 0}
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120)
        ) as session:
            import asyncio as _aio
            today, cumulative = await _aio.gather(
                sum_pages(session, today_ts, now_ts, max_pages=50),
                sum_pages(session, 0, now_ts, max_pages=100),
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[relay-cost] error: {e}')

    result = {
        "today": today,
        "cumulative": cumulative,
        "units_per_usd": units_per_usd,
        "usd_to_cny_rate": usd_to_cny,
        "relay_name": active.get('name', ''),
        "model": model_name,
        "cached_at": _dt.datetime.utcnow().isoformat() + "Z",
    }
    _relay_cost_cache = result
    _relay_cost_cache_ts = now
    return result


# ───── Hustle AI Chat Assistant ─────

HUSTLE_SYSTEM_PROMPT_AUTO = """你是 Hustle，OpenCLAW 量化智能体控制台的 AI 客服助手。你的任务是用简洁、准确的中文回答用户关于控制台使用操作的问题。

## 控制台概览
OpenCLAW 是一个量化交易智能体管理平台，包含以下模块：

### 1. 实时监控 (Dashboard)
- 顶部导航栏：显示当前模型、今日tokens消耗、今日消费金额、钱包余额、运行模式(Shadow/半自动/全自动)
- 目标卡片：每个交易目标显示实时净值、持仓大小、Delta差值、最近决策
- 持仓对比：A端/B端持仓对比，展示跨平台仓位差异
- 警报区域：未确认警报会在导航栏显示红色角标，点击可查看和确认

### 2. 决策流 (Decisions)
- 展示智能体的每一次决策记录，包含时间、目标、verdict(判定)、置信度
- Verdict 类型：execute(执行交易)、skip(跳过)、shadow(影子模式记录)、rejected(被风控拒绝)
- 可按目标、verdict类型、时间范围筛选
- 每条决策可展开查看详细的 proposal(提议)内容和 reasoning(推理过程)
- 置信度分布图表帮助分析决策质量

### 3. 提议中心 (Proposals)
- 用于修改智能体配置的提案审批系统
- 新建提议：可手动填写 JSON config_diff，或使用 AI 对话生成
- AI 对话生成：用自然语言描述想修改的配置，AI 自动生成结构化提案
- 提议状态：pending(待审批) → approved(已批准)/rejected(已拒绝)
- 审批后自动写入 agent_active_config，config_loader 5秒 TTL 热加载生效
- config_diff 展示旧值→新值对比（红色删除线→绿色新值）
- 支持全局配置和目标级配置的修改

### 4. 风控中心 (RiskControl)
- 目标管理：启用/禁用交易目标，配置交易对
- 持仓限额(position_caps)：设置各目标的最大持仓量
- 频次限制(rate_limits)：max_decisions_per_min(默认10)、max_trades_per_hour(默认30)、cooldown_after_loss_s(默认120秒)
- 权益保护(equity_guard)：warn_ratio(0.90)、critical_ratio(0.80)、force_reduce_ratio(0.70)
- 干预日志：查看权益保护触发的历史记录

### 5. 基础设施 (Infrastructure)
- 中转站管理：配置 LLM API 中转站(chesspnt等)，主站/备用站切换
- LLM 健康状态：模型名称、延迟、熔断器状态
- Token 消费统计：今日/累计 tokens、今日/累计消费金额
- 每日消费明细表：按天统计消费，支持分页和 CSV 导出
- 生效配置审计：只读查看当前所有生效的配置项，修改需走提案流程

### 6. 登录与权限
- 需要超级管理员或系统管理员角色才能访问
- 具有 openclaw_enabled 权限的用户也可访问
- JWT token 认证，存储在 localStorage

## 回答规则
1. 只回答控制台使用操作相关的问题
2. 不透露任何 API key、密码、session cookie 等敏感信息
3. 如果用户问非操作相关的问题，礼貌告知你只负责使用操作指导
4. 回答简洁明了，必要时用列表或步骤说明
5. 使用中文回答"""


class ChatReq(BaseModel):
    message: str
    site: str = "auto"


@router.post("/chat")
async def hustle_chat(req: ChatReq, request: Request,
                      db: AsyncSession = Depends(get_db),
                      user_id: str = Depends(require_admin)):
    """Hustle AI chat — SSE streaming response."""
    import aiohttp, json as _json, logging
    from starlette.responses import StreamingResponse
    log = logging.getLogger(__name__)

    # Load chat config from DB
    _chat_cfg_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'hustle_chat_config'"
    ))).scalar()
    _chat_cfg = _chat_cfg_row if isinstance(_chat_cfg_row, dict) else {}
    _enabled_sites = _chat_cfg.get('enabled_sites', ['auto'])
    _rate_limit = _chat_cfg.get('rate_limit', 20)

    if req.site not in _enabled_sites:
        raise HTTPException(403, "AI 客服已关闭")

    # Rate limit from DB config
    cnt = (await db.execute(text("""
        SELECT COUNT(*) FROM hustle_chat_messages
        WHERE user_id = CAST(:uid AS UUID) AND site = :site AND role = 'user'
          AND created_at >= NOW() - INTERVAL '1 hour'
    """), {"uid": user_id, "site": req.site})).scalar()
    if cnt >= _rate_limit:
        raise HTTPException(429, f"每小时最多提问 {_rate_limit} 次，请稍后再试")

    # Load recent history (last 10 messages)
    history_rows = (await db.execute(text("""
        SELECT role, content FROM (
            SELECT role, content, created_at FROM hustle_chat_messages
            WHERE user_id = CAST(:uid AS UUID) AND site = :site
            ORDER BY created_at DESC LIMIT 10
        ) sub ORDER BY created_at ASC
    """), {"uid": user_id, "site": req.site})).all()

    # Get relay config
    cfg_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'relay_stations'"
    ))).scalar()
    stations = cfg_row if isinstance(cfg_row, list) else []
    active = next((r for r in stations if r.get('enabled') and r.get('role') == 'primary'), None)
    if not active:
        raise HTTPException(503, "LLM 未配置")

    base = (active.get('llm_base_url') or '').rstrip('/')
    key = active.get('llm_api_key', '')
    model = active.get('model', 'gpt-5.4')
    if not base or not key:
        raise HTTPException(503, "LLM 未配置")

    # Build messages
    _db_prompts = _chat_cfg.get('system_prompts', {})
    _site_prompt = _db_prompts.get(req.site, '') if _db_prompts.get(req.site) else HUSTLE_SYSTEM_PROMPT_AUTO
    messages = [{"role": "system", "content": _site_prompt}]
    for row in history_rows:
        messages.append({"role": row[0], "content": row[1]})
    messages.append({"role": "user", "content": req.message})

    # Save user message first
    await db.execute(text("""
        INSERT INTO hustle_chat_messages (user_id, site, role, content)
        VALUES (CAST(:uid AS UUID), :site, 'user', :content)
    """), {"uid": user_id, "site": req.site, "content": req.message})
    await db.commit()

    async def event_stream():
        full_response = []
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)
            ) as session:
                async with session.post(
                    f'{base}/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': model,
                        'messages': messages,
                        'stream': True,
                        'max_tokens': 1500,
                        'temperature': 0.5,
                    },
                ) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        log.error(f'[hustle-chat] LLM {resp.status}: {err[:300]}')
                        yield f"data: {_json.dumps({'error': f'LLM 调用失败: HTTP {resp.status}'})}\n\n"
                        return

                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode('utf-8', errors='ignore')
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if not line or not line.startswith('data:'):
                                continue
                            payload = line[5:].strip()
                            if payload == '[DONE]':
                                yield "data: [DONE]\n\n"
                                break
                            try:
                                obj = _json.loads(payload)
                                choices = obj.get('choices') or []
                                if not choices:
                                    continue
                                delta = choices[0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    full_response.append(content)
                                    yield f"data: {_json.dumps({'content': content})}\n\n"
                            except (ValueError, KeyError, IndexError):
                                continue
        except Exception as e:
            log.error(f'[hustle-chat] stream error: {e}')
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"
        finally:
            # Save assistant response
            if full_response:
                try:
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as db2:
                        await db2.execute(text("""
                            INSERT INTO hustle_chat_messages (user_id, site, role, content)
                            VALUES (CAST(:uid AS UUID), :site, 'assistant', :content)
                        """), {"uid": user_id, "site": req.site, "content": ''.join(full_response)})
                        await db2.commit()
                except Exception as e2:
                    log.error(f'[hustle-chat] save response error: {e2}')

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/history")
async def chat_history(
    site: str = Query("auto"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Load chat history for the Hustle assistant."""
    rows = (await db.execute(text("""
        SELECT id, role, content, created_at FROM hustle_chat_messages
        WHERE user_id = CAST(:uid AS UUID) AND site = :site
        ORDER BY created_at DESC LIMIT 50
    """), {"uid": user_id, "site": site})).all()

    # Count remaining quota
    cnt = (await db.execute(text("""
        SELECT COUNT(*) FROM hustle_chat_messages
        WHERE user_id = CAST(:uid AS UUID) AND site = :site AND role = 'user'
          AND created_at >= NOW() - INTERVAL '1 hour'
    """), {"uid": user_id, "site": site})).scalar()

    messages = [
        {"id": r[0], "role": r[1], "content": r[2], "time": r[3].isoformat() if r[3] else None}
        for r in reversed(rows)
    ]
    _hcfg = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'hustle_chat_config'"
    ))).scalar()
    _hlimit = _hcfg.get('rate_limit', 20) if isinstance(_hcfg, dict) else 20
    return {"messages": messages, "remaining": max(0, _hlimit - int(cnt or 0))}



@router.delete("/chat/messages/{message_id}")
async def delete_chat_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Delete a single chat message (user can only delete own messages)."""
    result = await db.execute(text("""
        DELETE FROM hustle_chat_messages
        WHERE id = :mid AND user_id = CAST(:uid AS UUID)
        RETURNING id
    """), {"mid": message_id, "uid": user_id})
    deleted = result.scalar()
    if not deleted:
        raise HTTPException(404, "\u6d88\u606f\u4e0d\u5b58\u5728\u6216\u65e0\u6743\u5220\u9664")
    await db.commit()
    return {"ok": True, "deleted_id": deleted}


@router.delete("/chat/history")
async def clear_chat_history(
    site: str = Query("auto"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Clear all chat history for the current user on this site."""
    result = await db.execute(text("""
        DELETE FROM hustle_chat_messages
        WHERE user_id = CAST(:uid AS UUID) AND site = :site
    """), {"uid": user_id, "site": site})
    await db.commit()
    return {"ok": True, "deleted_count": result.rowcount}


# ───── Hustle AI Chat Admin APIs ─────


@router.get("/chat/admin/stats")
async def chat_admin_stats(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """AI chat admin stats: usage, users, cost."""
    import aiohttp, datetime as _dt

    # Message counts
    total = (await db.execute(text(
        "SELECT COUNT(*) FROM hustle_chat_messages WHERE role='user'"
    ))).scalar() or 0

    today_start = _dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = (await db.execute(text(
        "SELECT COUNT(*) FROM hustle_chat_messages WHERE role='user' AND created_at >= :ts"
    ), {"ts": today_start})).scalar() or 0

    # Unique users
    unique_users = (await db.execute(text(
        "SELECT COUNT(DISTINCT user_id) FROM hustle_chat_messages"
    ))).scalar() or 0

    # Messages by site
    by_site = (await db.execute(text(
        "SELECT site, COUNT(*) FROM hustle_chat_messages WHERE role='user' GROUP BY site"
    ))).all()
    sites = {r[0]: int(r[1]) for r in by_site}

    # Daily trend (last 14 days)
    daily = (await db.execute(text("""
        SELECT date_trunc('day', created_at)::date AS day, COUNT(*) AS cnt
        FROM hustle_chat_messages WHERE role='user'
          AND created_at >= NOW() - INTERVAL '14 days'
        GROUP BY 1 ORDER BY 1
    """))).all()
    daily_trend = [{"date": str(r[0]), "count": int(r[1])} for r in daily]

    # Token cost from chesspnt: filter by token_name containing chat or all
    # We track chat cost by counting tokens in/out from chat messages
    total_tokens = (await db.execute(text(
        "SELECT COUNT(*) FROM hustle_chat_messages"
    ))).scalar() or 0

    # Estimate cost: count assistant messages tokens (rough: 1 char ≈ 1.5 tokens for Chinese)
    assistant_chars = (await db.execute(text(
        "SELECT COALESCE(SUM(LENGTH(content)), 0) FROM hustle_chat_messages WHERE role='assistant'"
    ))).scalar() or 0
    user_chars = (await db.execute(text(
        "SELECT COALESCE(SUM(LENGTH(content)), 0) FROM hustle_chat_messages WHERE role='user'"
    ))).scalar() or 0

    # Real cost: use chesspnt relay pricing
    # system_prompt ~1500 chars × 1.5 = ~2250 tokens input per call
    # user history ~500 chars avg = ~750 tokens
    # total input per call ≈ 3000 tokens + user message
    # output ≈ assistant chars × 1.5 tokens
    est_input_tokens = int(user_chars * 1.5) + int(total * 3000)  # system prompt overhead
    est_output_tokens = int(assistant_chars * 1.5)

    # Get relay pricing
    cfg_row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'relay_stations'"
    ))).scalar()
    stations = cfg_row if isinstance(cfg_row, list) else []
    active = next((r for r in stations if r.get('enabled') and r.get('role') == 'primary'), None)
    units_per_usd = float(active.get('units_per_usd', 500000)) if active else 500000
    model = active.get('model', 'gpt-5.4') if active else 'gpt-5.4'

    # gpt-5.4 pricing from chesspnt: model_ratio=1.25, group_ratio=0.3, completion_ratio=6
    model_ratio = 1.25
    group_ratio = 0.3
    comp_ratio = 6
    input_quota = est_input_tokens * model_ratio * group_ratio
    output_quota = est_output_tokens * model_ratio * group_ratio * comp_ratio
    total_quota = input_quota + output_quota
    cost_usd = total_quota / units_per_usd

    return {
        "total_messages": int(total),
        "today_messages": int(today_count),
        "unique_users": int(unique_users),
        "by_site": sites,
        "daily_trend": daily_trend,
        "total_messages_all": int(total_tokens),
        "estimated_cost": {
            "input_tokens": est_input_tokens,
            "output_tokens": est_output_tokens,
            "total_quota_units": round(total_quota),
            "cost_usd": round(cost_usd, 4),
            "model": model,
        },
    }


@router.get("/chat/admin/conversations")
async def chat_admin_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    site: str = Query("auto"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """List all chat conversations grouped by user."""
    # Get unique users with message counts
    rows = (await db.execute(text("""
        SELECT m.user_id, u.username,
               COUNT(*) FILTER (WHERE m.role = 'user') AS user_msgs,
               COUNT(*) AS total_msgs,
               MAX(m.created_at) AS last_active
        FROM hustle_chat_messages m
        JOIN users u ON m.user_id = u.user_id
        WHERE m.site = :site
        GROUP BY m.user_id, u.username
        ORDER BY last_active DESC
        LIMIT :lim OFFSET :off
    """), {"site": site, "lim": page_size, "off": (page - 1) * page_size})).all()

    cnt = (await db.execute(text(
        "SELECT COUNT(DISTINCT user_id) FROM hustle_chat_messages WHERE site = :site"
    ), {"site": site})).scalar() or 0

    return {
        "page": page,
        "total": int(cnt),
        "total_pages": max(1, -(-int(cnt) // page_size)),
        "conversations": [{
            "user_id": str(r[0]),
            "username": r[1],
            "user_messages": int(r[2]),
            "total_messages": int(r[3]),
            "last_active": r[4].isoformat() if r[4] else None,
        } for r in rows],
    }


@router.get("/chat/admin/messages")
async def chat_admin_messages(
    target_user_id: str = Query(...),
    site: str = Query("auto"),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """View a specific user's chat messages."""
    rows = (await db.execute(text("""
        SELECT id, role, content, created_at FROM hustle_chat_messages
        WHERE user_id = CAST(:uid AS UUID) AND site = :site
        ORDER BY created_at DESC LIMIT 100
    """), {"uid": target_user_id, "site": site})).all()

    return {
        "messages": [{
            "id": r[0], "role": r[1], "content": r[2],
            "time": r[3].isoformat() if r[3] else None,
        } for r in reversed(rows)],
    }



# ───── Hustle AI Chat Admin: Config + Hot Questions ─────


@router.get("/chat/admin/config")
async def chat_admin_config(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Get AI chat config: system prompt, enabled sites, rate limit."""
    row = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'hustle_chat_config'"
    ))).scalar()
    if row and isinstance(row, dict):
        return row
    # defaults
    return {
        "enabled_sites": ["auto"],
        "rate_limit": 20,
        "system_prompts": {"auto": ""},
    }


@router.put("/chat/admin/config")
async def chat_admin_config_update(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Update AI chat config."""
    import json as _json
    body = await request.json()

    # Validate
    allowed_keys = {"enabled_sites", "rate_limit", "system_prompts"}
    cfg = {}
    if "enabled_sites" in body:
        cfg["enabled_sites"] = body["enabled_sites"]
    if "rate_limit" in body:
        cfg["rate_limit"] = max(1, min(100, int(body["rate_limit"])))
    if "system_prompts" in body:
        cfg["system_prompts"] = body["system_prompts"]

    # Merge with existing
    existing = (await db.execute(text(
        "SELECT value FROM agent_active_config WHERE key = 'hustle_chat_config'"
    ))).scalar()
    if existing and isinstance(existing, dict):
        existing.update(cfg)
        cfg = existing
    else:
        cfg.setdefault("enabled_sites", ["auto"])
        cfg.setdefault("rate_limit", 20)
        cfg.setdefault("system_prompts", {"auto": ""})

    # Upsert
    await db.execute(text("""
        INSERT INTO agent_active_config (key, value)
        VALUES ('hustle_chat_config', :val::jsonb)
        ON CONFLICT (key) DO UPDATE SET value = :val::jsonb
    """), {"val": _json.dumps(cfg)})
    await db.commit()

    return {"ok": True, "config": cfg}


@router.get("/chat/admin/hot-questions")
async def chat_admin_hot_questions(
    site: str = Query("auto"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Top 10 most asked questions (by content similarity — simple exact match)."""
    rows = (await db.execute(text("""
        SELECT content, COUNT(*) AS cnt
        FROM hustle_chat_messages
        WHERE role = 'user' AND site = :site
        GROUP BY content
        ORDER BY cnt DESC, MAX(created_at) DESC
        LIMIT 10
    """), {"site": site})).all()
    return {
        "questions": [{"content": r[0], "count": int(r[1])} for r in rows],
    }


# ──────────────────────────────────────────────────────────────────────
# Guard Time-Window Rules CRUD
# ──────────────────────────────────────────────────────────────────────

@router.get('/guard-rules')
async def get_guard_rules(db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    """Return current Guard time_rules configuration."""
    row = (await db.execute(text(
        "SELECT value::text FROM agent_active_config WHERE key = 'time_rules'"
    ))).first()
    if not row:
        return {}
    import json as _json
    return _json.loads(row[0])


@router.put('/guard-rules')
async def update_guard_rules(rules: Dict[str, Any] = Body(...),
                             db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, str]:
    """Update Guard time_rules configuration. Takes effect within 5s (config_loader TTL)."""
    import json as _json
    from app.services.agent.config_loader import invalidate as _invalidate_config
    await db.execute(text("""
        INSERT INTO agent_active_config (key, value, updated_by)
        VALUES ('time_rules', cast(:v as jsonb), :uid)
        ON CONFLICT (key) DO UPDATE SET value = cast(:v as jsonb), updated_at = NOW(), updated_by = :uid
    """), {'v': _json.dumps(rules), 'uid': user_id})
    await db.commit()
    _invalidate_config()
    return {'status': 'ok', 'message': 'Guard rules updated, effective within 5s'}
