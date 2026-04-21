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
