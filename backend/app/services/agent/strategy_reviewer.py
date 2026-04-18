"""P5: Weekly strategy reviewer.

Fires once every 7 days (anchored to Monday 09:00 BJT) per enabled target.
Workflow per target:
  1. Pull the target's last 7 days of decisions + executions from agent_decisions
  2. Compute summary stats: win-rate proxy, rejection reasons, avg confidence,
     hit-rate of Guard caps (how often single_trade_exceeds_cap / total_position_cap fired)
  3. Ask Codex to produce a config_diff proposal ONLY if data warrants it
     (min 50 decisions in window, min 10 Guard rejections; otherwise 'insufficient data')
  4. Persist proposal into agent_strategy_proposals with target_id set — operator
     approves via UI; no auto-apply
  5. Feishu broadcast a terse summary linking to /proposals

The reviewer runs as a background task alongside agent_loop, wakes up once per hour
and decides whether the target needs a review (based on last review time).
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.agent.codex_client import call_decider
from app.services.agent.feishu_broadcast import broadcast
from app.services.agent.scope import list_target_rows

logger = logging.getLogger(__name__)

REVIEW_INTERVAL_DAYS = 7
WAKE_INTERVAL_S = 3600          # check-for-work cadence
MIN_DECISIONS = 50              # require enough data to avoid noise
MIN_GUARD_REJECTS = 10


REVIEWER_SYSTEM_PROMPT = '''你是 OpenCLAW 的策略复盘器。

给定一个目标（用户+产品对）过去 7 天的决策数据统计，请判断是否需要调整该目标的配置参数。
你可以修改的 key：position_caps / spread_modes / time_windows / equity_guard / no_profit_alert。
你禁止修改 rate_limits（防封禁铁律）、symbols（白名单）。

判断原则：
- 若 Guard 频繁拦（>20% rejection rate）同一类别（如 single_trade_exceeds_cap），
  说明上限可能过紧，可提议小幅放宽（每次不超过 20%）。
- 若平均 confidence < 0.5，说明信号质量差，可提议收紧阈值或时段过滤。
- 若 shadow 决策中某类 trigger 从未产生盈利预期（全是 noop），可提议降低该 trigger 敏感度。
- 若数据不足或无明显问题，返回 action=no_change。

输出严格 JSON（无额外文字）:
{
  "action": "propose" | "no_change",
  "title": "简洁标题，<40 字",
  "rationale": "具体推理：为什么改、预期影响、风险（>100 字）",
  "config_diff": { "key": {...顶层替换的完整 dict...} },
  "est_position_pct": 0.0~1.0
}

当 action=no_change 时其他字段可为空或 null。
'''


async def _stats_for_target(db: AsyncSession, target_id: int, window_days: int = 7) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (await db.execute(text("""
        SELECT verdict, reject_reason, proposal->>'action' AS action,
               CAST(proposal->>'confidence' AS NUMERIC) AS conf,
               trigger, llm_tokens_in + llm_tokens_out AS tokens
        FROM agent_decisions
        WHERE scope_target_id = :t AND created_at >= :s
    """), {'t': target_id, 's': since})).all()

    total = len(rows)
    by_verdict: Dict[str, int] = {}
    by_action: Dict[str, int] = {}
    by_trigger: Dict[str, int] = {}
    reject_cats: Dict[str, int] = {}
    conf_sum = 0.0
    conf_count = 0
    tokens_sum = 0

    for v, rr, act, conf, trig, toks in rows:
        by_verdict[v] = by_verdict.get(v, 0) + 1
        by_action[act or '--'] = by_action.get(act or '--', 0) + 1
        by_trigger[trig or '--'] = by_trigger.get(trig or '--', 0) + 1
        if conf is not None:
            conf_sum += float(conf)
            conf_count += 1
        if toks:
            tokens_sum += int(toks)
        if v == 'rejected' and rr:
            cat = rr.split(':', 1)[0] if ':' in rr else rr
            # Further narrow Guard violation types
            if rr.startswith('guard:'):
                sub = rr.split(':', 2)
                if len(sub) >= 3:
                    cat = f'guard:{sub[1].split(":", 1)[0]}'
            reject_cats[cat] = reject_cats.get(cat, 0) + 1

    guard_rejects = by_verdict.get('rejected', 0)
    return {
        'window_days': window_days,
        'total_decisions': total,
        'by_verdict': by_verdict,
        'by_action': by_action,
        'by_trigger': by_trigger,
        'reject_categories': reject_cats,
        'avg_confidence': (conf_sum / conf_count) if conf_count else None,
        'total_tokens': tokens_sum,
        'rejection_rate': (guard_rejects / total) if total else 0.0,
    }


async def _last_review_at(db: AsyncSession, target_id: int) -> Optional[datetime]:
    row = (await db.execute(text("""
        SELECT MAX(created_at) FROM agent_strategy_proposals
        WHERE target_id = :t AND title LIKE '%[复盘]%'
    """), {'t': target_id})).first()
    return row[0] if row and row[0] else None


async def _generate_proposal(stats: Dict[str, Any], target_label: str) -> Optional[Dict[str, Any]]:
    user_prompt = (
        f"目标: {target_label}\n"
        f"过去 {stats['window_days']} 天统计:\n"
        f"- 总决策数: {stats['total_decisions']}\n"
        f"- verdict 分布: {json.dumps(stats['by_verdict'], ensure_ascii=False)}\n"
        f"- action 分布: {json.dumps(stats['by_action'], ensure_ascii=False)}\n"
        f"- trigger 分布: {json.dumps(stats['by_trigger'], ensure_ascii=False)}\n"
        f"- 拒绝类别: {json.dumps(stats['reject_categories'], ensure_ascii=False)}\n"
        f"- 平均 confidence: {stats['avg_confidence']}\n"
        f"- 总 tokens 消耗: {stats['total_tokens']}\n"
        f"- 拒绝率: {stats['rejection_rate']*100:.1f}%\n\n"
        "请按规范输出 JSON。"
    )
    try:
        result, usage, latency = await call_decider(REVIEWER_SYSTEM_PROMPT, user_prompt, temperature=0.2)
        logger.info(f'[reviewer] generated proposal tokens={usage} latency={latency}ms')
        return result
    except Exception as e:
        logger.error(f'[reviewer] LLM call failed: {e}')
        return None


async def _review_one_target(db: AsyncSession, target_row: Dict[str, Any]) -> Optional[int]:
    tid = target_row['id']
    stats = await _stats_for_target(db, tid)

    target_label = f"{target_row['username']}/{target_row['pair_code']}"
    if stats['total_decisions'] < MIN_DECISIONS:
        logger.info(f'[reviewer] target #{tid} insufficient decisions ({stats["total_decisions"]}<{MIN_DECISIONS}), skipping')
        await broadcast(
            db, level='info', category='weekly_review_skipped',
            message=f'[复盘] {target_label}: 过去 7 天仅 {stats["total_decisions"]} 决策 (<{MIN_DECISIONS})，数据不足跳过',
            payload={'target_id': tid, 'stats': stats},
        )
        return None

    result = await _generate_proposal(stats, target_label)
    if not result or result.get('action') != 'propose':
        logger.info(f'[reviewer] target #{tid} → no_change or LLM failed')
        # Still log a no-change summary alert so operator sees the reviewer ran
        await broadcast(
            db, level='info', category='weekly_review',
            message=f'[复盘] {target_label}: 过去 7 天 {stats["total_decisions"]} 决策，拒绝率 {stats["rejection_rate"]*100:.1f}%, 无需调整',
            payload={'target_id': tid, 'stats': stats},
        )
        return None

    # Persist proposal with [复盘] prefix so _last_review_at() can find it
    title = '[复盘] ' + (result.get('title') or f'{target_label} 周度建议')
    rationale = result.get('rationale') or '(reviewer did not supply rationale)'
    config_diff = result.get('config_diff') or {}
    est_pct = result.get('est_position_pct')

    # Hard safety: disallow touching rate_limits / symbols
    banned = {'rate_limits', 'symbols'}
    config_diff = {k: v for k, v in config_diff.items() if k not in banned}
    if not config_diff:
        logger.info(f'[reviewer] target #{tid} diff was all-banned, skipping')
        return None

    res = await db.execute(text("""
        INSERT INTO agent_strategy_proposals (title, rationale, config_diff,
                                              est_position_pct, target_id, status)
        VALUES (:t, :r, CAST(:cd AS JSONB), :ep, :tid, 'pending')
        RETURNING id
    """), {'t': title, 'r': rationale, 'cd': json.dumps(config_diff),
           'ep': est_pct, 'tid': tid})
    pid = res.scalar_one()
    await db.commit()

    await broadcast(
        db, level='info', category='weekly_review_proposed',
        message=f'[复盘] {target_label}: 新策略提议 #{pid} — {title}（前往 /proposals 审批）',
        payload={'proposal_id': pid, 'target_id': tid, 'stats': stats, 'diff_keys': list(config_diff.keys())},
    )
    logger.info(f'[reviewer] target #{tid} → new proposal #{pid}')
    return pid


async def _tick():
    async with AsyncSessionLocal() as db:
        targets = await list_target_rows(db, enabled_only=True)
        if not targets:
            return
        for t in targets:
            last = await _last_review_at(db, t['id'])
            if last and (datetime.now(timezone.utc) - last).total_seconds() < REVIEW_INTERVAL_DAYS * 86400:
                continue
            try:
                await _review_one_target(db, t)
            except Exception as e:
                logger.error(f'[reviewer] target #{t["id"]} review error: {e}')


_stop = None
_task = None


async def _loop_main(stop_event: asyncio.Event):
    logger.info('[reviewer] loop started (weekly cadence)')
    # First wake after 10 minutes to avoid startup storm
    initial_delay = 600
    await asyncio.wait_for(stop_event.wait(), timeout=initial_delay) if False else None
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=initial_delay)
        return
    except asyncio.TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            await _tick()
        except Exception as e:
            logger.error(f'[reviewer] tick error: {e}')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=WAKE_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
    logger.info('[reviewer] stopped')


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


# Manual trigger (used by POST /strategy-review/trigger)
async def trigger_review_now(db: AsyncSession, target_id: Optional[int] = None) -> Dict[str, Any]:
    """Run review immediately for one target (or all enabled). Bypasses weekly cadence."""
    targets = await list_target_rows(db, enabled_only=True)
    if target_id is not None:
        targets = [t for t in targets if t['id'] == target_id]
    results = []
    for t in targets:
        pid = await _review_one_target(db, t)
        results.append({'target_id': t['id'], 'proposal_id': pid})
    return {'ok': True, 'results': results}
