"""AgentState helpers — single-row table with mode/kill switch."""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def get_state(db: AsyncSession) -> dict:
    row = (await db.execute(text(
        'SELECT mode, kill_switch, shadow_started_at, last_decision_at, config FROM agent_state WHERE id=1'
    ))).first()
    if not row:
        return {'mode': 'shadow', 'kill_switch': False}
    return {'mode': row[0], 'kill_switch': row[1], 'shadow_started_at': row[2],
            'last_decision_at': row[3], 'config': row[4] or {}}


async def set_mode(db: AsyncSession, mode: str) -> None:
    assert mode in ('off', 'shadow', 'semi', 'auto'), f'bad mode {mode}'
    await db.execute(text('UPDATE agent_state SET mode=:m, updated_at=NOW() WHERE id=1'), {'m': mode})
    await db.commit()


async def set_kill_switch(db: AsyncSession, on: bool) -> None:
    await db.execute(text('UPDATE agent_state SET kill_switch=:k, updated_at=NOW() WHERE id=1'), {'k': on})
    await db.commit()


async def is_executing_allowed(db: AsyncSession) -> bool:
    s = await get_state(db)
    if s['kill_switch']:
        return False
    return s['mode'] in ('semi', 'auto')
