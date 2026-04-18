"""Feishu broadcast wrapper for agent alerts and Shadow-mode decisions.

Reuses existing FeishuService (app_id/app_secret based) and sends to all
admin/operator users that have feishu_open_id set.

All sends also persist into agent_alerts table.
"""
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

LEVEL_PREFIX = {
    'info':     '[OpenCLAW · INFO] ',
    'warn':     '[OpenCLAW · 警告] ',
    'danger':   '[OpenCLAW · 危险] ',
    'critical': '[OpenCLAW · 紧急] ',
}


async def _list_recipients(db: AsyncSession):
    rows = (await db.execute(text('''
        SELECT user_id, username, feishu_open_id FROM users
        WHERE feishu_open_id IS NOT NULL AND feishu_open_id <> ''
    '''))).all()
    return rows


async def broadcast(
    db: AsyncSession,
    *,
    level: str = 'info',
    category: str,
    message: str,
    payload: Optional[dict] = None,
    ack_required: bool = False,
) -> int:
    """Send to all eligible operators; log to agent_alerts.

    Returns the new agent_alerts.id.
    """
    full = LEVEL_PREFIX.get(level, '[OpenCLAW] ') + message
    sent_count = 0
    sent_ok = False
    try:
        from app.services.feishu_service import get_feishu_service
        feishu = get_feishu_service()
        if feishu:
            for r in await _list_recipients(db):
                try:
                    res = await feishu.send_text_message(receive_id=r[2], content=full)
                    if res.get('success'):
                        sent_count += 1
                        sent_ok = True
                except Exception as e:
                    logger.warning(f'[feishu] send to {r[1]} failed: {e}')
    except Exception as e:
        logger.error(f'[feishu] init failed: {e}')

    res = await db.execute(text('''
        INSERT INTO agent_alerts (level, category, message, payload, feishu_sent, ack_required)
        VALUES (:lv, :cat, :msg, CAST(:pl AS JSONB), :ok, :ack)
        RETURNING id
    '''), {
        'lv': level, 'cat': category, 'msg': message,
        'pl': __import__('json').dumps(payload or {}),
        'ok': sent_ok, 'ack': ack_required,
    })
    new_id = res.scalar_one()
    await db.commit()
    logger.info(f'[OpenCLAW alert#{new_id}] {level}/{category}: {message} (feishu sent={sent_count})')
    return new_id
