from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.models_auth import AuditLog
from app.db.session import get_db
from app.middleware.permissions import require_admin

router = APIRouter(prefix="/api/admin/audit-logs", tags=["admin-audit"])


@router.get("")
def list_audit_logs(
    request: Request,
    user_id: int = Query(None),
    user: str = Query(None),
    action: str = Query(None),
    resource: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    require_admin(request)

    q = db.query(AuditLog)
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    if user:
        q = q.filter(AuditLog.user.ilike(f"%{user}%"))
    if action:
        q = q.filter(AuditLog.action == action.upper())
    if resource:
        q = q.filter(AuditLog.resource.ilike(f"%{resource}%"))
    if start_date:
        q = q.filter(AuditLog.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(AuditLog.created_at <= datetime.fromisoformat(end_date))

    total = q.count()
    logs = q.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size).all()

    return {
        "items": [
            {
                "id": log.id,
                "user": log.user,
                "user_id": log.user_id,
                "action": log.action,
                "resource": log.resource,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": str(log.created_at) if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "size": size,
    }
