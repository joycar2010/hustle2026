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

class FundViewAccessReq(BaseModel):
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


    @r.put('/fund-view-access', status_code=status.HTTP_200_OK)
    async def toggle_fund_view_access(
        req: FundViewAccessReq,
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
            UPDATE users SET fund_view_enabled = :e, update_time = NOW()
            WHERE user_id = CAST(:u AS UUID)
        """), {'e': req.enabled, 'u': req.user_id})
        await db.commit()

        logger.info(
            f'[fund-view-access] {target[1]} fund_view_enabled={req.enabled} '
            f'by operator={operator_id[:8]}'
        )
        return {'ok': True, 'user_id': req.user_id,
                'username': target[1], 'fund_view_enabled': req.enabled}

    class FeishuLookupReq(BaseModel):
        mobile: str

    @r.post('/feishu-lookup', status_code=status.HTTP_200_OK)
    async def feishu_lookup(
        req: FeishuLookupReq,
        db: AsyncSession = Depends(get_db),
        operator_id: str = Depends(get_current_user_id),
    ):
        """Resolve a mobile number to a Feishu open_id via the bound app.

        Used by admin UI 'get Feishu ID' button. Requires admin role.
        """
        await _require_admin(db, operator_id)
        mobile = (req.mobile or '').strip()
        if not mobile:
            raise HTTPException(status_code=400, detail='手机号不能为空')

        from app.services.feishu_service import get_feishu_service
        feishu = get_feishu_service()
        if feishu is None:
            raise HTTPException(status_code=503, detail='飞书服务未配置，请先在系统管理-通知服务中填入 App ID/Secret')

        try:
            result = await feishu.get_user_by_mobile(mobile)
        except Exception as e:
            logger.exception('[feishu-lookup] lookup failed')
            raise HTTPException(status_code=502, detail=f'飞书 API 调用异常: {e}')

        if not result.get('success'):
            raise HTTPException(status_code=404,
                                detail=result.get('error') or '未查到该手机号的飞书用户')
        user = result.get('user') or {}
        open_id = user.get('open_id') or user.get('openid')
        union_id = user.get('union_id')
        return {
            'ok': True,
            'mobile': mobile,
            # Expose both snake_case (feishu_*) and short (open_id/union_id)
            # variants so any frontend version can bind directly.
            'open_id': open_id,
            'union_id': union_id,
            'feishu_open_id': open_id,
            'feishu_union_id': union_id,
            'user_id': user.get('user_id'),
            'name': user.get('name'),
            'raw': user,
        }

    return r
