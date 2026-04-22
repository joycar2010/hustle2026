"""Site status: announcements + maintenance mode.

Endpoints:
  GET  /api/v1/site-status                            — public, used by all 3 frontends
  GET  /api/v1/announcements                          — admin list (incl. inactive/expired)
  POST /api/v1/announcements                          — admin create
  PUT  /api/v1/announcements/{id}                     — admin update
  DELETE /api/v1/announcements/{id}                   — admin delete
  POST /api/v1/maintenance/toggle                     — admin enable/disable maintenance

Stream channel: site.status — published whenever announcements/maintenance change.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.auth import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_ROLES = {'超级管理员', '系统管理员', 'super_admin', 'system_admin', 'admin', 'operator'}


async def _require_admin(db: AsyncSession, user_id: str):
    row = (await db.execute(text(
        "SELECT role FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {'u': user_id})).first()
    if not row or row[0] not in ADMIN_ROLES:
        raise HTTPException(403, '仅管理员可操作')


# ─────────── Schemas ───────────
class AnnouncementCreate(BaseModel):
    title: str = Field(..., max_length=200)
    content: str
    level: str = 'info'
    is_active: bool = True
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    level: Optional[str] = None
    is_active: Optional[bool] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class MaintenanceToggle(BaseModel):
    on: bool
    reason: Optional[str] = None
    scheduled_resume_at: Optional[datetime] = None


# ─────────── Helpers ───────────
async def _publish_site_status(db: AsyncSession):
    try:
        from app.websocket.stream_hub import stream_hub
        snap = await _get_site_status_snapshot(db)
        await stream_hub.publish('site.status', snap)
    except Exception as e:
        logger.debug(f'[site_status] publish failed: {e}')


async def _get_site_status_snapshot(db: AsyncSession) -> dict:
    # Active announcements (now within window)
    rows = (await db.execute(text(
        "SELECT id, title, content, level, start_at, end_at "
        "FROM system_announcements "
        "WHERE is_active = true "
        "  AND (start_at IS NULL OR start_at <= NOW()) "
        "  AND (end_at IS NULL OR end_at >= NOW()) "
        "ORDER BY created_at DESC"
    ))).fetchall()
    announcements = [{
        'id': str(r[0]), 'title': r[1], 'content': r[2], 'level': r[3],
        'start_at': r[4].isoformat() if r[4] else None,
        'end_at': r[5].isoformat() if r[5] else None,
    } for r in rows]
    m = (await db.execute(text(
        "SELECT is_active, reason, started_at, scheduled_resume_at FROM system_maintenance_state WHERE id=1"
    ))).first()
    maintenance = {
        'is_active': bool(m[0]) if m else False,
        'reason': m[1] if m else None,
        'started_at': m[2].isoformat() if m and m[2] else None,
        'scheduled_resume_at': m[3].isoformat() if m and m[3] else None,
    }
    return {'announcements': announcements, 'maintenance': maintenance}


# ─────────── Public ───────────
@router.get('/site-status')
async def get_site_status(db: AsyncSession = Depends(get_db)):
    """Public endpoint — used by go/www/admin frontends as initial snapshot
    before WS subscription kicks in."""
    return await _get_site_status_snapshot(db)


# ─────────── Admin: announcements CRUD ───────────
@router.get('/announcements')
async def list_announcements(
    include_inactive: bool = True,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _require_admin(db, user_id)
    sql = (
        "SELECT id, title, content, level, is_active, start_at, end_at, "
        "       created_by, created_at, updated_at "
        "FROM system_announcements "
    )
    if not include_inactive:
        sql += "WHERE is_active = true "
    sql += "ORDER BY created_at DESC LIMIT 200"
    rows = (await db.execute(text(sql))).fetchall()
    return {'items': [{
        'id': str(r[0]), 'title': r[1], 'content': r[2], 'level': r[3],
        'is_active': r[4],
        'start_at': r[5].isoformat() if r[5] else None,
        'end_at': r[6].isoformat() if r[6] else None,
        'created_by': str(r[7]) if r[7] else None,
        'created_at': r[8].isoformat() if r[8] else None,
        'updated_at': r[9].isoformat() if r[9] else None,
    } for r in rows]}


@router.post('/announcements', status_code=201)
async def create_announcement(
    req: AnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _require_admin(db, user_id)
    row = (await db.execute(text(
        "INSERT INTO system_announcements (title, content, level, is_active, start_at, end_at, created_by) "
        "VALUES (:t,:c,:l,:a,:s,:e,CAST(:u AS UUID)) RETURNING id"
    ), {'t': req.title, 'c': req.content, 'l': req.level, 'a': req.is_active,
        's': req.start_at, 'e': req.end_at, 'u': user_id})).first()
    await db.commit()
    await _publish_site_status(db)
    return {'ok': True, 'id': str(row[0])}


@router.put('/announcements/{ann_id}')
async def update_announcement(
    ann_id: UUID,
    req: AnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _require_admin(db, user_id)
    fields = {k: v for k, v in req.dict(exclude_unset=True).items()}
    if not fields:
        return {'ok': True, 'updated': 0}
    sets = ', '.join(f"{k}=:{k}" for k in fields)
    fields['id'] = str(ann_id)
    await db.execute(text(
        f"UPDATE system_announcements SET {sets}, updated_at=NOW() WHERE id=CAST(:id AS UUID)"
    ), fields)
    await db.commit()
    await _publish_site_status(db)
    return {'ok': True}


@router.delete('/announcements/{ann_id}', status_code=204)
async def delete_announcement(
    ann_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _require_admin(db, user_id)
    await db.execute(text("DELETE FROM system_announcements WHERE id=CAST(:i AS UUID)"),
                     {'i': str(ann_id)})
    await db.commit()
    await _publish_site_status(db)


# ─────────── Admin: maintenance toggle ───────────
@router.post('/maintenance/toggle')
async def toggle_maintenance(
    req: MaintenanceToggle,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _require_admin(db, user_id)
    if req.on:
        await db.execute(text(
            "UPDATE system_maintenance_state SET is_active=true, reason=:r, "
            "started_at=NOW(), scheduled_resume_at=:s, activated_by=CAST(:u AS UUID), updated_at=NOW() "
            "WHERE id=1"
        ), {'r': req.reason or '', 's': req.scheduled_resume_at, 'u': user_id})
    else:
        await db.execute(text(
            "UPDATE system_maintenance_state SET is_active=false, reason=NULL, "
            "started_at=NULL, scheduled_resume_at=NULL, updated_at=NOW() WHERE id=1"
        ))
    await db.commit()
    await _publish_site_status(db)
    return {'ok': True, 'maintenance_active': req.on}


@router.get('/maintenance/state')
async def get_maintenance_state(db: AsyncSession = Depends(get_db)):
    snap = await _get_site_status_snapshot(db)
    return snap['maintenance']
