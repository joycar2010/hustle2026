from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.models import GlobalRules
from app.db.schemas.global_rules import GlobalRulesUpdate, GlobalRulesResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/global-rules", tags=["global-rules"])


def _get_or_create(db: Session, user_id: int) -> GlobalRules:
    """按登录用户取/建本用户的全局规则行。多行表必须 user 作用域,
    避免无序 .first() 漂行(读/存与引擎 config_loader(user_id) 命中同一行)。"""
    rules = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
    if not rules:
        rules = GlobalRules(user_id=user_id)
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


@router.get("/", response_model=GlobalRulesResponse)
def get_global_rules(request: Request, db: Session = Depends(get_db)):
    rules = _get_or_create(db, get_current_user_id(request))
    # spread_stale_sec 是系统全局字段(NULL 行主管,admin「系统后端规则」配),overlay 给前端 /spreads 用
    sysrow = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).order_by(GlobalRules.id).first()
    if sysrow is not None and getattr(sysrow, "spread_stale_sec", None) is not None:
        rules.spread_stale_sec = sysrow.spread_stale_sec   # 仅内存 overlay(GET 不 commit)
    return rules


@router.put("/", response_model=GlobalRulesResponse)
def update_global_rules(data: GlobalRulesUpdate, request: Request, db: Session = Depends(get_db)):
    rules = _get_or_create(db, get_current_user_id(request))
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rules, field, value)
    db.commit()
    db.refresh(rules)
    return rules
