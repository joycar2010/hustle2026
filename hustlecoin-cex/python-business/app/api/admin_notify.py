import json
import logging

import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.db.models import FeishuConfig
from app.db.models_auth import User
from app.db.models_notify import NotificationTemplate, NotificationLog, EmailConfig
from app.db.session import get_db
from app.middleware.permissions import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/notifications", tags=["admin-notify"])

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


# ─── Feishu Config ───

class FeishuConfigUpdate(BaseModel):
    webhook_url: str | None = None
    secret_key: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    alert_interval_sec: int | None = None
    alert_count: int | None = None
    margin_rate_alert: float | None = None
    leverage_risk_alert: float | None = None
    enable_transfer_fail_alert: bool | None = None
    enable_new_borrow_alert: bool | None = None


@router.get("/feishu-config")
def get_feishu_config(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = (
        db.query(FeishuConfig, User.username)
        .outerjoin(User, FeishuConfig.user_id == User.id)
        .all()
    )
    return [
        {
            "id": c.id,
            "user_id": c.user_id,
            "username": username,
            "webhook_url": c.webhook_url or "",
            "secret_key": c.secret_key or "",
            "app_id": getattr(c, "app_id", "") or "",
            "app_secret": "****" if getattr(c, "app_secret", "") else "",
            "alert_interval_sec": c.alert_interval_sec,
            "alert_count": c.alert_count,
            "margin_rate_alert": float(c.margin_rate_alert) if c.margin_rate_alert else 30,
            "leverage_risk_alert": float(c.leverage_risk_alert) if c.leverage_risk_alert else 1.3,
            "enable_transfer_fail_alert": c.enable_transfer_fail_alert,
            "enable_new_borrow_alert": c.enable_new_borrow_alert,
            "is_global": c.user_id is None,
        }
        for c, username in rows
    ]


@router.put("/feishu-config")
def update_feishu_config(req: FeishuConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    config = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    if not config:
        config = FeishuConfig(user_id=None)
        db.add(config)

    for field in ("webhook_url", "secret_key", "alert_interval_sec", "alert_count",
                  "margin_rate_alert", "leverage_risk_alert",
                  "enable_transfer_fail_alert", "enable_new_borrow_alert"):
        val = getattr(req, field)
        if val is not None:
            setattr(config, field, val)

    if req.app_id is not None:
        config.app_id = req.app_id
    if req.app_secret is not None and req.app_secret != "****":
        config.app_secret = req.app_secret

    db.commit()
    db.refresh(config)
    return {"message": "Config updated", "id": config.id}


@router.put("/feishu-config/user/{user_id}")
def update_user_feishu_config(user_id: int, req: FeishuConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    config = db.query(FeishuConfig).filter(FeishuConfig.user_id == user_id).first()
    if not config:
        config = FeishuConfig(user_id=user_id)
        db.add(config)

    for field in ("webhook_url", "secret_key", "alert_interval_sec", "alert_count",
                  "margin_rate_alert", "leverage_risk_alert",
                  "enable_transfer_fail_alert", "enable_new_borrow_alert"):
        val = getattr(req, field)
        if val is not None:
            setattr(config, field, val)

    if req.app_id is not None:
        config.app_id = req.app_id
    if req.app_secret is not None and req.app_secret != "****":
        config.app_secret = req.app_secret

    db.commit()
    db.refresh(config)
    return {"message": "User config updated", "id": config.id}


@router.delete("/feishu-config/user/{user_id}")
def delete_user_feishu_config(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    config = db.query(FeishuConfig).filter(FeishuConfig.user_id == user_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="该用户无独立配置")
    db.delete(config)
    db.commit()
    return {"message": "User config deleted, falling back to global"}


def _get_tenant_token(app_id: str, app_secret: str) -> dict:
    """Get Feishu tenant_access_token using app credentials."""
    resp = httpx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        return {"ok": False, "error": data.get("msg", "unknown error")}
    return {
        "ok": True,
        "token": data["tenant_access_token"],
        "expire": data.get("expire", 7200),
    }


def _resolve_phone_to_open_id(token: str, phone: str) -> dict:
    """Resolve phone number to open_id via Feishu contacts API."""
    if not phone.startswith("+"):
        phone = "+86" + phone
    resp = httpx.post(
        "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id",
        params={"user_id_type": "open_id"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"mobiles": [phone]},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        return {"ok": False, "error": data.get("msg", "API error")}
    user_list = data.get("data", {}).get("user_list", [])
    if not user_list or not user_list[0].get("user_id"):
        return {"ok": False, "error": f"未找到手机号 {phone} 对应的飞书用户"}
    return {"ok": True, "open_id": user_list[0]["user_id"]}


@router.get("/feishu-status")
def get_feishu_status(request: Request, db: Session = Depends(get_db)):
    """Check Feishu Open API connection by fetching a tenant_access_token."""
    require_admin(request)
    config = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    if not config or not getattr(config, "app_id", ""):
        return {"connected": False, "error": "飞书 App ID 未配置", "token_expires_at": None}

    result = _get_tenant_token(config.app_id, config.app_secret or "")
    if result["ok"]:
        import datetime
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=result["expire"])
        return {"connected": True, "token_expires_at": expires_at.isoformat(), "error": None}
    return {"connected": False, "error": result["error"], "token_expires_at": None}


@router.post("/feishu-test")
def test_feishu(request: Request, recipient: str = Query("", description="open_id or phone"), db: Session = Depends(get_db)):
    require_admin(request)
    config = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    if not config:
        raise HTTPException(status_code=400, detail="飞书未配置")

    app_id = getattr(config, "app_id", "") or ""
    app_secret_val = getattr(config, "app_secret", "") or ""

    if app_id and app_secret_val:
        token_result = _get_tenant_token(app_id, app_secret_val)
        if not token_result["ok"]:
            return {"status": "error", "detail": f"获取Token失败: {token_result['error']}"}
        token = token_result["token"]

        receive_id = recipient or ""
        if not receive_id:
            return {"status": "error", "detail": "请选择测试接收人"}

        if receive_id.startswith("ou_"):
            receive_id_type = "open_id"
        elif "@" in receive_id:
            receive_id_type = "email"
        elif receive_id.replace("+", "").isdigit():
            lookup = _resolve_phone_to_open_id(token, receive_id)
            if not lookup["ok"]:
                return {"status": "error", "detail": lookup["error"]}
            receive_id = lookup["open_id"]
            receive_id_type = "open_id"
        else:
            receive_id_type = "open_id"

        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "🧪 测试消息"}, "template": "blue"},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**这是一条测试消息**\n\n飞书通知服务配置成功！\n\n测试时间：{now_str}"}},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "🔔 HustleCoin 量化系统"}]},
            ],
        }
        try:
            resp = httpx.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card)},
                timeout=10,
            )
            body = resp.json()
            ok = body.get("code") == 0
            db.add(NotificationLog(template_name="测试消息", channel="feishu",
                                   status="sent" if ok else "failed",
                                   content=f"Open API test → {receive_id}"))
            db.commit()
            if ok:
                return {"status": "sent", "message_id": body.get("data", {}).get("message_id")}
            return {"status": "error", "detail": body.get("msg", "unknown")}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    if not config.webhook_url:
        raise HTTPException(status_code=400, detail="飞书 Webhook URL 和 App ID 均未配置")
    try:
        resp = httpx.post(
            config.webhook_url,
            json={"msg_type": "text", "content": {"text": "[HustleCoin Admin] 测试消息 - 飞书通知连接正常"}},
            timeout=10,
        )
        db.add(NotificationLog(template_name="测试消息", channel="feishu",
                               status="sent" if resp.status_code == 200 else "failed",
                               content="飞书通知连接测试 (webhook)"))
        db.commit()
        return {"status": "sent", "response_code": resp.status_code, "body": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ─── Email Config ───

class EmailConfigUpdate(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    use_ssl: bool | None = None
    is_enabled: bool | None = None


@router.get("/email-config")
def get_email_config(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cfg = db.query(EmailConfig).first()
    if not cfg:
        return {"smtp_host": "", "smtp_port": 465, "smtp_user": "", "smtp_password": "",
                "smtp_from": "", "use_ssl": True, "is_enabled": False}
    return {
        "smtp_host": cfg.smtp_host or "",
        "smtp_port": cfg.smtp_port,
        "smtp_user": cfg.smtp_user or "",
        "smtp_password": "****" if cfg.smtp_password else "",
        "smtp_from": cfg.smtp_from or "",
        "use_ssl": cfg.use_ssl,
        "is_enabled": cfg.is_enabled,
    }


@router.put("/email-config")
def update_email_config(req: EmailConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cfg = db.query(EmailConfig).first()
    if not cfg:
        cfg = EmailConfig()
        db.add(cfg)

    for field in ("smtp_host", "smtp_port", "smtp_user", "smtp_from", "use_ssl", "is_enabled"):
        val = getattr(req, field)
        if val is not None:
            setattr(cfg, field, val)
    if req.smtp_password is not None and req.smtp_password != "****":
        cfg.smtp_password = req.smtp_password

    db.commit()
    return {"message": "Email config updated"}


@router.post("/email-test")
def test_email(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    from engine.notify.email_sender import email_sender
    email_sender._last_reload = 0
    cfg = db.query(EmailConfig).first()
    if not cfg or not cfg.is_enabled or not cfg.smtp_host:
        raise HTTPException(status_code=400, detail="邮件服务未配置或未启用")

    to = cfg.smtp_from or cfg.smtp_user
    ok = email_sender.send(to, "[HustleCoin] 测试邮件", "邮件通知连接正常。")
    db.add(NotificationLog(template_name="测试邮件", channel="email",
                           recipient=to, status="sent" if ok else "failed",
                           content="邮件通知连接测试"))
    db.commit()
    return {"status": "sent" if ok else "failed"}


# ─── Templates ───

class TemplateUpdate(BaseModel):
    template_name: str | None = None
    category: str | None = None
    title_template: str | None = None
    content_template: str | None = None
    enable_feishu: bool | None = None
    enable_email: bool | None = None
    enable_marquee: bool | None = None
    priority: int | None = None
    cooldown_seconds: int | None = None
    marquee_color: str | None = None
    marquee_blink: bool | None = None
    sound_key: str | None = None
    is_enabled: bool | None = None


@router.get("/templates")
def list_templates(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
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
            "enable_marquee": getattr(t, "enable_marquee", True),
            "priority": t.priority,
            "cooldown_seconds": t.cooldown_seconds,
            "marquee_color": getattr(t, "marquee_color", "#3b82f6"),
            "marquee_blink": getattr(t, "marquee_blink", False),
            "sound_key": getattr(t, "sound_key", "none"),
            "is_enabled": t.is_enabled,
        }
        for t in templates
    ]


@router.put("/templates/{template_id}")
def update_template(template_id: int, req: TemplateUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    t = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    for field in ("template_name", "category", "title_template", "content_template",
                  "enable_feishu", "enable_email", "enable_marquee",
                  "priority", "cooldown_seconds",
                  "marquee_color", "marquee_blink", "sound_key", "is_enabled"):
        val = getattr(req, field)
        if val is not None:
            setattr(t, field, val)

    db.commit()
    return {"message": "Template updated"}


@router.post("/templates")
def create_template(req: TemplateUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    t = NotificationTemplate(
        template_name=req.template_name or "新模板",
        category=req.category or "system",
        title_template=req.title_template or "",
        content_template=req.content_template or "",
        enable_feishu=req.enable_feishu if req.enable_feishu is not None else True,
        enable_email=req.enable_email if req.enable_email is not None else False,
        enable_marquee=req.enable_marquee if req.enable_marquee is not None else True,
        priority=req.priority or 2,
        cooldown_seconds=req.cooldown_seconds or 60,
        marquee_color=req.marquee_color or "#3b82f6",
        marquee_blink=req.marquee_blink if req.marquee_blink is not None else False,
        sound_key=req.sound_key or "none",
        is_enabled=req.is_enabled if req.is_enabled is not None else True,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"message": "Template created", "id": t.id}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    t = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(t)
    db.commit()
    return {"message": "Template deleted"}


@router.post("/templates/{template_id}/test")
def test_template(template_id: int, request: Request, recipient: str = Query("", description="feishu open_id of target user"), db: Session = Depends(get_db)):
    require_admin(request)
    t = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")

    import datetime
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sample_vars = {
        "account": "hustle-测试",
        "symbol": "BTCUSDT",
        "amount": "100.00",
        "spread": "0.35%",
        "price": "98765.43",
        "time": now_str,
    }
    title = t.title_template or t.template_name
    content = t.content_template or f"模板 [{t.template_name}] 测试消息"
    for k, v in sample_vars.items():
        title = title.replace("{{" + k + "}}", v).replace("{" + k + "}", v)
        content = content.replace("{{" + k + "}}", v).replace("{" + k + "}", v)

    results = {}

    if getattr(t, "enable_feishu", False):
        fc = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
        app_id = (fc.app_id if fc and fc.app_id else "") or ""
        app_secret_val = (fc.app_secret if fc and fc.app_secret else "") or ""
        if app_id and app_secret_val:
            token_result = _get_tenant_token(app_id, app_secret_val)
            if token_result["ok"]:
                if not recipient:
                    results["feishu"] = "skipped: 未选择接收用户"
                else:
                    card = {
                        "config": {"wide_screen_mode": True},
                        "header": {"title": {"tag": "plain_text", "content": f"🧪 {title}"}, "template": "blue"},
                        "elements": [
                            {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                            {"tag": "hr"},
                            {"tag": "note", "elements": [
                                {"tag": "plain_text", "content": f"模板测试 · {t.category} · P{t.priority} · {now_str}"}
                            ]},
                        ],
                    }
                    try:
                        resp = httpx.post(
                            "https://open.feishu.cn/open-apis/im/v1/messages",
                            params={"receive_id_type": "open_id"},
                            headers={"Authorization": f"Bearer {token_result['token']}", "Content-Type": "application/json"},
                            json={"receive_id": recipient, "msg_type": "interactive", "content": json.dumps(card)},
                            timeout=10,
                        )
                        body = resp.json()
                        ok = body.get("code") == 0
                        results["feishu"] = "sent" if ok else f"failed: {body.get('msg', 'unknown')}"
                        db.add(NotificationLog(template_name=t.template_name, channel="feishu",
                                               recipient=recipient, status="sent" if ok else "failed",
                                               content=f"模板测试: {title}"))
                    except Exception as e:
                        results["feishu"] = f"error: {e}"
            else:
                results["feishu"] = f"token_error: {token_result.get('error')}"
        elif fc and fc.webhook_url:
            try:
                resp = httpx.post(fc.webhook_url,
                                  json={"msg_type": "text", "content": {"text": f"[模板测试] {title}\n{content}"}},
                                  timeout=10)
                results["feishu"] = "sent" if resp.status_code == 200 else f"failed: HTTP {resp.status_code}"
                db.add(NotificationLog(template_name=t.template_name, channel="feishu",
                                       status="sent" if resp.status_code == 200 else "failed",
                                       content=f"模板测试(webhook): {title}"))
            except Exception as e:
                results["feishu"] = f"error: {e}"
        else:
            results["feishu"] = "skipped: 飞书未配置"

    if getattr(t, "enable_email", False):
        try:
            from engine.notify.email_sender import email_sender
            email_sender._last_reload = 0
            cfg = db.query(EmailConfig).first()
            if cfg and cfg.is_enabled and cfg.smtp_host:
                to = cfg.smtp_from or cfg.smtp_user
                ok = email_sender.send(to, f"[模板测试] {title}", content)
                results["email"] = "sent" if ok else "failed"
                db.add(NotificationLog(template_name=t.template_name, channel="email",
                                       recipient=to, status="sent" if ok else "failed",
                                       content=f"模板测试: {title}"))
            else:
                results["email"] = "skipped: 邮件未配置或未启用"
        except Exception as e:
            results["email"] = f"error: {e}"

    if getattr(t, "enable_marquee", False):
        try:
            r = _get_redis()
            payload = {
                "title": title,
                "content": content,
                "priority": t.priority,
                "color": getattr(t, "marquee_color", "#3b82f6"),
                "blink": getattr(t, "marquee_blink", False),
                "sound": getattr(t, "sound_key", "none"),
            }
            r.publish("notification:broadcast", json.dumps(payload))
            results["marquee"] = "sent"
            db.add(NotificationLog(template_name=t.template_name, channel="marquee",
                                   status="sent", content=f"模板测试: {title}"))
        except Exception as e:
            results["marquee"] = f"error: {e}"

    db.commit()
    return {"template": t.template_name, "channels": results}


# ─── Site Notification (Marquee Broadcast) ───

class BroadcastRequest(BaseModel):
    title: str
    content: str
    priority: int = 2
    color: str = "#3b82f6"
    blink: bool = False
    sound: str = "none"


@router.post("/broadcast")
def broadcast_notification(req: BroadcastRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    payload = {
        "title": req.title,
        "content": req.content,
        "priority": req.priority,
        "color": req.color,
        "blink": req.blink,
        "sound": req.sound,
    }
    try:
        r = _get_redis()
        r.publish("notification:broadcast", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Redis broadcast failed: {e}")
        raise HTTPException(status_code=500, detail="广播失败")

    db.add(NotificationLog(template_name=req.title, channel="marquee",
                           status="sent", content=req.content))
    db.commit()
    return {"message": "Notification broadcasted"}


@router.get("/recent-marquee")
def recent_marquee(request: Request, limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    """admin 后台内置跑马灯数据源:近 24h 的 marquee 广播(含 API 文档变动等告警)。"""
    require_admin(request)
    import datetime
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    logs = (db.query(NotificationLog)
            .filter(NotificationLog.channel == "marquee", NotificationLog.status == "sent",
                    NotificationLog.created_at >= since)
            .order_by(NotificationLog.id.desc()).limit(limit).all())
    return {
        "items": [
            {
                "id": l.id,
                "title": l.template_name,
                "content": l.content or "",
                "created_at": str(l.created_at) if l.created_at else None,
            }
            for l in logs
        ]
    }


# ─── Logs ───

@router.get("/logs")
def list_logs(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    channel: str | None = None,
    status: str | None = None,
    template_name: str | None = None,
    db: Session = Depends(get_db),
):
    require_admin(request)
    q = db.query(NotificationLog)
    if channel:
        q = q.filter(NotificationLog.channel == channel)
    if status:
        q = q.filter(NotificationLog.status == status)
    if template_name:
        q = q.filter(NotificationLog.template_name.ilike(f"%{template_name}%"))

    total = q.count()
    logs = q.order_by(NotificationLog.id.desc()).offset((page - 1) * size).limit(size).all()
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


# ─── Sound presets (no DB, static list) ───

SOUND_PRESETS = [
    {"key": "none", "label": "无声音"},
    {"key": "ding", "label": "叮 (开仓)"},
    {"key": "success", "label": "成功 (平仓)"},
    {"key": "alert", "label": "警报 (风控)"},
    {"key": "error", "label": "错误 (异常)"},
    {"key": "chime", "label": "铃声 (通知)"},
]


@router.get("/sounds")
def list_sounds(request: Request):
    require_admin(request)
    return SOUND_PRESETS
