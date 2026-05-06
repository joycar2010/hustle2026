import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session

from app.db.models_ai import AiConfig, AiFaq, AiConversation, AiMessage
from app.db.session import get_db
from app.middleware.permissions import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/ai", tags=["admin-ai"])


# ─── Request schemas ───

class FaqRequest(BaseModel):
    question: str
    answer: str
    category: str = "general"
    sort_order: int = 0


class AiConfigRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    is_enabled: bool | None = None
    rate_limit_per_min: int | None = None


# ─── FAQ CRUD (unchanged) ───

@router.get("/faq")
def list_faq(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        items = db.query(AiFaq).order_by(AiFaq.sort_order, AiFaq.id).all()
        return [
            {
                "id": f.id,
                "question": f.question,
                "answer": f.answer,
                "category": f.category,
                "sort_order": f.sort_order,
                "is_active": f.is_active,
                "created_at": str(f.created_at) if f.created_at else None,
            }
            for f in items
        ]
    except Exception:
        return []


@router.post("/faq")
def create_faq(req: FaqRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    faq = AiFaq(
        question=req.question,
        answer=req.answer,
        category=req.category,
        sort_order=req.sort_order,
    )
    db.add(faq)
    db.commit()
    db.refresh(faq)
    return {"id": faq.id, "message": "FAQ created"}


@router.put("/faq/{faq_id}")
def update_faq(faq_id: int, req: FaqRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    faq = db.query(AiFaq).filter(AiFaq.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    faq.question = req.question
    faq.answer = req.answer
    faq.category = req.category
    faq.sort_order = req.sort_order
    db.commit()
    return {"message": "FAQ updated"}


@router.delete("/faq/{faq_id}")
def delete_faq(faq_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    faq = db.query(AiFaq).filter(AiFaq.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    db.delete(faq)
    db.commit()
    return {"message": "FAQ deleted"}


# ─── Per-site config ───

@router.get("/config")
def get_config(request: Request, db: Session = Depends(get_db), site: str = Query("default")):
    require_admin(request)
    try:
        config = db.query(AiConfig).filter(AiConfig.site == site).first()
        if not config:
            return {
                "id": 0,
                "site": site,
                "provider": "claude",
                "base_url": "",
                "model_name": "claude-sonnet-4-6",
                "temperature": 0.7,
                "max_tokens": 2000,
                "system_prompt": "",
                "is_enabled": False,
                "rate_limit_per_min": 10,
            }
        return {
            "id": config.id,
            "site": config.site,
            "provider": config.provider,
            "api_key": config.api_key or "",
            "base_url": config.base_url or "",
            "model_name": config.model_name,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "system_prompt": config.system_prompt or "",
            "is_enabled": config.is_enabled,
            "rate_limit_per_min": config.rate_limit_per_min or 10,
        }
    except Exception:
        return {
            "id": 0,
            "site": site,
            "provider": "claude",
            "base_url": "",
            "model_name": "claude-sonnet-4-6",
            "temperature": 0.7,
            "max_tokens": 2000,
            "system_prompt": "",
            "is_enabled": False,
            "rate_limit_per_min": 10,
        }


@router.put("/config")
def update_config(req: AiConfigRequest, request: Request, db: Session = Depends(get_db), site: str = Query("default")):
    require_admin(request)
    config = db.query(AiConfig).filter(AiConfig.site == site).first()
    if not config:
        config = AiConfig(site=site)
        db.add(config)

    if req.provider is not None:
        config.provider = req.provider
    if req.api_key is not None:
        config.api_key = req.api_key
    if req.base_url is not None:
        config.base_url = req.base_url.rstrip("/") if req.base_url else None
    if req.model_name is not None:
        config.model_name = req.model_name
    if req.temperature is not None:
        config.temperature = req.temperature
    if req.max_tokens is not None:
        config.max_tokens = req.max_tokens
    if req.system_prompt is not None:
        config.system_prompt = req.system_prompt
    if req.is_enabled is not None:
        config.is_enabled = req.is_enabled
    if req.rate_limit_per_min is not None:
        config.rate_limit_per_min = req.rate_limit_per_min

    db.commit()
    return {"message": "Config updated"}


# ─── Stats ───

@router.get("/stats")
def get_stats(request: Request, db: Session = Depends(get_db), site: str = Query(None)):
    require_admin(request)
    try:
        q_conv = db.query(AiConversation)
        q_msg = db.query(AiMessage).join(AiConversation, AiMessage.conversation_id == AiConversation.id)
        if site:
            q_conv = q_conv.filter(AiConversation.site == site)
            q_msg = q_msg.filter(AiConversation.site == site)

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_messages = q_msg.count()
        today_messages = q_msg.filter(AiMessage.created_at >= today_start).count()
        active_users = q_conv.filter(AiConversation.user_id.isnot(None)).distinct(AiConversation.user_id).count()
        total_tokens = db.query(func.coalesce(func.sum(AiConversation.token_used), 0))
        if site:
            total_tokens = total_tokens.filter(AiConversation.site == site)
        total_tokens = total_tokens.scalar()

        days_14 = []
        for i in range(13, -1, -1):
            day = (now - timedelta(days=i)).date()
            count = (
                db.query(func.count(AiMessage.id))
                .join(AiConversation, AiMessage.conversation_id == AiConversation.id)
                .filter(cast(AiMessage.created_at, Date) == day)
            )
            if site:
                count = count.filter(AiConversation.site == site)
            days_14.append({"date": str(day), "count": count.scalar() or 0})

        return {
            "total_messages": total_messages,
            "today_messages": today_messages,
            "active_users": active_users,
            "total_tokens": total_tokens,
            "daily_trend": days_14,
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {
            "total_messages": 0,
            "today_messages": 0,
            "active_users": 0,
            "total_tokens": 0,
            "daily_trend": [],
        }


# ─── Conversations ───

@router.get("/conversations")
def list_conversations(
    request: Request,
    db: Session = Depends(get_db),
    site: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(None),
):
    require_admin(request)
    q = db.query(AiConversation)
    if site:
        q = q.filter(AiConversation.site == site)
    if search:
        q = q.filter(AiConversation.title.ilike(f"%{search}%"))

    total = q.count()
    items = q.order_by(AiConversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": c.id,
                "site": c.site,
                "user_id": c.user_id,
                "session_id": c.session_id,
                "title": c.title or "",
                "message_count": c.message_count,
                "token_used": c.token_used,
                "created_at": str(c.created_at) if c.created_at else None,
                "updated_at": str(c.updated_at) if c.updated_at else None,
            }
            for c in items
        ],
    }


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    conv = db.query(AiConversation).filter(AiConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).order_by(AiMessage.id).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "token_count": m.token_count,
            "created_at": str(m.created_at) if m.created_at else None,
        }
        for m in msgs
    ]


# ─── Hot Questions ───

@router.get("/hot-questions")
def hot_questions(
    request: Request,
    db: Session = Depends(get_db),
    site: str = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    require_admin(request)
    try:
        q = (
            db.query(
                AiMessage.content,
                func.count(AiMessage.id).label("cnt"),
            )
            .join(AiConversation, AiMessage.conversation_id == AiConversation.id)
            .filter(AiMessage.role == "user")
        )
        if site:
            q = q.filter(AiConversation.site == site)

        rows = q.group_by(AiMessage.content).order_by(func.count(AiMessage.id).desc()).limit(limit).all()
        return [{"question": r[0][:200], "count": r[1]} for r in rows]
    except Exception:
        return []
