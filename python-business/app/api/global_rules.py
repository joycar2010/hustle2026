from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.models import GlobalRules
from app.db.schemas.global_rules import GlobalRulesUpdate, GlobalRulesResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/global-rules", tags=["global-rules"])


def _get_or_create(db: Session, user_id: int) -> GlobalRules:
    rules = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
    if not rules:
        rules = GlobalRules(user_id=user_id)
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


@router.get("/", response_model=GlobalRulesResponse)
def get_global_rules(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    return _get_or_create(db, user_id)


@router.put("/", response_model=GlobalRulesResponse)
def update_global_rules(data: GlobalRulesUpdate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    rules = _get_or_create(db, user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rules, field, value)
    db.commit()
    db.refresh(rules)
    return rules
