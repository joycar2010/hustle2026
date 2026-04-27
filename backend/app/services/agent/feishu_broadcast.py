"""Feishu broadcast wrapper for agent (OpenCLAW) alerts.

This module is now a thin compatibility shim over ``alert_bus.AlertBus``.
All de-dup, fan-out (Feishu / WebSocket / DB persist) and recipient filtering
happen inside the bus.

Behaviour:
    - When ``owner_user_id`` is provided → the alert is targeted at THAT user
      (their popup + their Feishu) — no longer broadcast to every admin.
      This is the per-user routing requested in the architecture review.

    - When ``owner_user_id`` is omitted (legacy callers) → falls back to
      broadcasting to all admin/operator users with a Feishu binding, which
      preserves the original behaviour for system-wide alerts that don't
      belong to a single trader.

Returns the inserted agent_alerts.id (or 0 if dedup suppressed it).
"""
import logging
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.alert_bus import alert_bus, AlertEvent

logger = logging.getLogger(__name__)

LEVEL_PREFIX = {
    'info':     '[OpenCLAW · INFO] ',
    'warn':     '[OpenCLAW · 警告] ',
    'danger':   '[OpenCLAW · 危险] ',
    'critical': '[OpenCLAW · 紧急] ',
}


async def broadcast(
    db: AsyncSession,
    *,
    level: str = 'info',
    category: str,
    message: str,
    payload: Optional[dict] = None,
    ack_required: bool = False,
    owner_user_id: Optional[str] = None,
    pair_code: str = "",
    cooldown_s: int = 60,
) -> int:
    """Emit an OpenCLAW alert through the unified AlertBus."""
    # kill_switch guard: during emergency halt, suppress all non-essential
    # OpenCLAW alerts. System meta-events (kill_switch / mode_change) and
    # critical-level fatal events (e.g. forced_reduce_done) always pass.
    ALWAYS_PASS_CATEGORIES = {'kill_switch', 'mode_change', 'openclaw_toggle'}
    if level != 'critical' and category not in ALWAYS_PASS_CATEGORIES:
        try:
            from app.services.agent import state as _agent_state
            _st = await _agent_state.get_state(db)
            if (_st.get('kill_switch') or _st.get('mode') == 'off'
                    or not _st.get('openclaw_enabled', True)):
                logger.info(
                    f"[OpenCLAW] alert suppressed (system halted): "
                    f"level={level} category={category}"
                )
                return 0
        except Exception as _ge:
            # Guard failure must not break the alert path — fall through.
            logger.debug(f"[OpenCLAW] kill_switch guard check failed: {_ge}")

    title = LEVEL_PREFIX.get(level, '[OpenCLAW] ').strip(' ')
    event = AlertEvent(
        user_id=owner_user_id or "",
        template_key=f"openclaw:{category}",
        title=title,
        message=message,
        pair_code=pair_code,
        severity=level,
        cooldown_s=cooldown_s,
        payload=payload or {},
        ack_required=ack_required,
        # System-wide OpenCLAW operational events (no owner) are admin-only.
        # Traders should never see OpenCLAW toggle/kill_switch/mode_change popups.
        admin_only=(not owner_user_id),
    )
    delivered = await alert_bus.emit(event)
    if not delivered:
        return 0  # Suppressed by dedup — no agent_alerts row written.

    # Recover the row id we just inserted (best-effort; only used by callers
    # that wanted an ack handle. Not load-bearing.)
    try:
        row = (await db.execute(text(
            "SELECT id FROM agent_alerts ORDER BY id DESC LIMIT 1"
        ))).first()
        return int(row[0]) if row else 0
    except Exception:
        return 0


async def broadcast_approval_request(
    db,
    *,
    decision_id: int,
    proposal: dict,
    snapshot: dict,
    violations: list,
    target_label: str = 'global',
    owner_user_id: str = None,
) -> int:
    """Send a Feishu card for an escalated (pending) Guard decision.

    The card contains decision details, market context, violation list,
    and deep-link URLs for one-click approve / reject in the auto frontend.
    """
    action = proposal.get('action', '?')
    leg = proposal.get('leg', '?')
    qty = proposal.get('qty', 0)
    reason = proposal.get('reason', '')
    conf = proposal.get('confidence', 0)

    spread = snapshot.get('spread_30m_avg', '?')
    funding = snapshot.get('funding_rate', '?')
    equity = snapshot.get('equity_usdt', '?')
    pos_dir = snapshot.get('position_direction', '?')

    viol_text = '\n'.join(f'  • {v}' for v in violations) or '无'

    base_url = 'https://auto.hustle2026.xyz/decisions'
    approve_url = f'{base_url}?action=approve&id={decision_id}'
    reject_url = f'{base_url}?action=reject&id={decision_id}'

    msg = (
        f'**🔔 Guard 升级审批 · 决策 #{decision_id}**\n'
        f'目标: {target_label}\n'
        f'---\n'
        f'**提议**: {action} | leg={leg} | qty={qty}\n'
        f'置信度: {conf} | 原因: {reason}\n'
        f'---\n'
        f'**市场快照**: 点差={spread} | 资金费={funding} | 权益={equity} | 方向={pos_dir}\n'
        f'---\n'
        f'**Guard 软违规**:\n{viol_text}\n'
        f'---\n'
        f'⏱ **15分钟内未操作将自动拒绝**\n\n'
        f'✅ [点击批准]({approve_url})\n'
        f'❌ [点击拒绝]({reject_url})'
    )

    return await broadcast(
        db,
        level='warn',
        category='guard_escalation',
        message=msg,
        payload={
            'decision_id': decision_id,
            'action': action,
            'violations': violations,
        },
        ack_required=True,
        owner_user_id=owner_user_id,
        cooldown_s=0,
    )
