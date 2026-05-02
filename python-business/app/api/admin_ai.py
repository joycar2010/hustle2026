from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.permissions import require_admin

router = APIRouter(prefix="/api/admin/ai", tags=["admin-ai"])


class FaqRequest(BaseModel):
    question: str
    answer: str
    category: str = "general"
    sort_order: int = 0


class AiConfigRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    is_enabled: bool | None = None


@router.get("/faq")
def list_faq(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        from app.db.models_ai import AiFaq
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
    from app.db.models_ai import AiFaq
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
    from app.db.models_ai import AiFaq
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
    from app.db.models_ai import AiFaq
    faq = db.query(AiFaq).filter(AiFaq.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    db.delete(faq)
    db.commit()
    return {"message": "FAQ deleted"}


@router.get("/config")
def get_config(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        from app.db.models_ai import AiConfig
        config = db.query(AiConfig).first()
        if not config:
            return {
                "id": 0,
                "provider": "claude",
                "model_name": "claude-sonnet-4-6",
                "temperature": 0.7,
                "max_tokens": 2000,
                "system_prompt": "",
                "is_enabled": False,
            }
        return {
            "id": config.id,
            "provider": config.provider,
            "model_name": config.model_name,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "system_prompt": config.system_prompt or "",
            "is_enabled": config.is_enabled,
        }
    except Exception:
        return {
            "id": 0,
            "provider": "claude",
            "model_name": "claude-sonnet-4-6",
            "temperature": 0.7,
            "max_tokens": 2000,
            "system_prompt": "",
            "is_enabled": False,
        }


@router.put("/config")
def update_config(req: AiConfigRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    from app.db.models_ai import AiConfig
    config = db.query(AiConfig).first()
    if not config:
        config = AiConfig()
        db.add(config)

    if req.provider is not None:
        config.provider = req.provider
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

    db.commit()
    return {"message": "Config updated"}
