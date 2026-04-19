"""PUT /api/v1/users/openclaw-access — toggle auto.hustle2026.xyz login access.

When openclaw_enabled = true, the target user can log into auto.hustle2026.xyz
(OpenCLAW agent control panel) alongside super admin / system admin roles.

Only super admin / system admin may flip this flag.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.auth import get_current_user_id

logger = logging.getLogger(__name__)

ADMIN_ROLES = {'超级管理员', '系统管理员', 'super_admin', 'system_admin', 'admin'}


class OpenclawAccessReq(BaseModel):
    user_id: str
    enabled: bool


async def _require_admin(db: AsyncSession, user_id: str):
    row = (await db.execute(text(
        "SELECT role FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {'u': user_id})).first()
    if not row or row[0] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail='仅超管/系统管理员可设置智能体量化权限')


def make_router() -> APIRouter:
    r = APIRouter()

    @r.put('/openclaw-access', status_code=status.HTTP_200_OK)
    async def toggle_openclaw_access(
        req: OpenclawAccessReq,
        db: AsyncSession = Depends(get_db),
        operator_id: str = Depends(get_current_user_id),
    ):
        await _require_admin(db, operator_id)

        target = (await db.execute(text(
            "SELECT user_id, username FROM users WHERE user_id = CAST(:u AS UUID)"
        ), {'u': req.user_id})).first()
        if not target:
            raise HTTPException(status_code=404, detail='目标用户不存在')

        await db.execute(text("""
            UPDATE users SET openclaw_enabled = :e, update_time = NOW()
            WHERE user_id = CAST(:u AS UUID)
        """), {'e': req.enabled, 'u': req.user_id})
        await db.commit()

        logger.info(
            f'[openclaw-access] {target[1]} openclaw_enabled={req.enabled} '
            f'by operator={operator_id[:8]}'
        )
        return {'ok': True, 'user_id': req.user_id,
                'username': target[1], 'openclaw_enabled': req.enabled}

    return r
