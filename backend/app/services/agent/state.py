"""AgentState helpers — single-row table with mode/kill switch/global enable."""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def get_state(db: AsyncSession) -> dict:
    row = (await db.execute(text(
        'SELECT mode, kill_switch, shadow_started_at, last_decision_at, config, openclaw_enabled FROM agent_state WHERE id=1'
    ))).first()
    if not row:
        return {'mode': 'shadow', 'kill_switch': False, 'openclaw_enabled': True}
    return {'mode': row[0], 'kill_switch': row[1], 'shadow_started_at': row[2],
            'last_decision_at': row[3], 'config': row[4] or {},
            'openclaw_enabled': bool(row[5])}


async def set_mode(db: AsyncSession, mode: str) -> None:
    assert mode in ('off', 'shadow', 'semi', 'auto'), f'bad mode {mode}'
    await db.execute(text('UPDATE agent_state SET mode=:m, updated_at=NOW() WHERE id=1'), {'m': mode})
    await db.commit()


async def set_kill_switch(db: AsyncSession, on: bool) -> None:
    await db.execute(text('UPDATE agent_state SET kill_switch=:k, updated_at=NOW() WHERE id=1'), {'k': on})
    await db.commit()


async def set_openclaw_enabled(db: AsyncSession, on: bool) -> None:
    await db.execute(text('UPDATE agent_state SET openclaw_enabled=:k, updated_at=NOW() WHERE id=1'), {'k': on})
    await db.commit()


async def is_openclaw_globally_enabled(db: AsyncSession) -> bool:
    row = (await db.execute(text('SELECT openclaw_enabled FROM agent_state WHERE id=1'))).first()
    return bool(row and row[0])


async def is_executing_allowed(db: AsyncSession) -> bool:
    s = await get_state(db)
    if s['kill_switch'] or not s.get('openclaw_enabled', True):
        return False
    return s['mode'] in ('semi', 'auto')
