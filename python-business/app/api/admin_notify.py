import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models import FeishuConfig
from app.db.session import get_db
from app.middleware.permissions import require_admin

router = APIRouter(prefix="/api/admin/notifications", tags=["admin-notify"])


class FeishuConfigUpdate(BaseModel):
    webhook_url: str | None = None
    secret_key: str | None = None
    alert_interval_sec: int | None = None


@router.get("/feishu-config")
def get_feishu_config(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    configs = db.query(FeishuConfig).all()
    return [
        {
            "id": c.id,
            "user_id": c.user_id,
            "webhook_url": c.webhook_url,
            "secret_key": c.secret_key or "",
            "alert_interval_sec": c.alert_interval_sec,
            "is_global": c.user_id is None,
        }
        for c in configs
    ]


@router.put("/feishu-config")
def update_feishu_config(req: FeishuConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    config = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    if not config:
        config = FeishuConfig(user_id=None)
        db.add(config)

    if req.webhook_url is not None:
        config.webhook_url = req.webhook_url
    if req.secret_key is not None:
        config.secret_key = req.secret_key
    if req.alert_interval_sec is not None:
        config.alert_interval_sec = req.alert_interval_sec

    db.commit()
    db.refresh(config)
    return {"message": "Config updated", "id": config.id}


@router.post("/feishu-test")
def test_feishu(request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    config = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    if not config or not config.webhook_url:
        raise HTTPException(status_code=400, detail="Feishu webhook not configured")

    try:
        resp = httpx.post(
            config.webhook_url,
            json={
                "msg_type": "text",
                "content": {"text": "[HustleCoin Admin] 测试消息 - 飞书通知连接正常"},
            },
            timeout=10,
        )
        return {"status": "sent", "response_code": resp.status_code, "body": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/templates")
def list_templates(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        from app.db.models_notify import NotificationTemplate
        templates = db.query(NotificationTemplate).order_by(NotificationTemplate.id).all()
        return [
            {
                "id": t.id,
                "template_name": t.template_name,
                "category": t.category,
                "title_template": t.title_template,
                "content_template": t.content_template,
                "enable_feishu": t.enable_feishu,
                "enable_email": t.enable_email,
                "priority": t.priority,
                "cooldown_seconds": t.cooldown_seconds,
                "is_enabled": t.is_enabled,
            }
            for t in templates
        ]
    except Exception:
        return []


@router.put("/templates/{template_id}")
def update_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        from app.db.models_notify import NotificationTemplate
        t = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
        if not t:
            raise HTTPException(status_code=404, detail="Template not found")
        import json
        body = json.loads(request._body.decode()) if hasattr(request, '_body') else {}
        for key in ("template_name", "title_template", "content_template", "category"):
            if key in body:
                setattr(t, key, body[key])
        for key in ("enable_feishu", "enable_email", "is_enabled"):
            if key in body:
                setattr(t, key, body[key])
        for key in ("priority", "cooldown_seconds"):
            if key in body:
                setattr(t, key, body[key])
        db.commit()
        return {"message": "Template updated"}
    except HTTPException:
        raise
    except Exception:
        return {"message": "Templates not available yet"}


@router.get("/logs")
def list_logs(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    require_admin(request)
    try:
        from app.db.models_notify import NotificationLog
        total = db.query(func.count(NotificationLog.id)).scalar() or 0
        logs = db.query(NotificationLog).order_by(NotificationLog.id.desc()).offset((page - 1) * size).limit(size).all()
        return {
            "items": [
                {
                    "id": l.id,
                    "template_name": l.template_name,
                    "channel": l.channel,
                    "recipient": l.recipient,
                    "status": l.status,
                    "content_preview": (l.content or "")[:100],
                    "created_at": str(l.created_at) if l.created_at else None,
                }
                for l in logs
            ],
            "total": total,
            "page": page,
            "size": size,
        }
    except Exception:
        return {"items": [], "total": 0, "page": page, "size": size}
