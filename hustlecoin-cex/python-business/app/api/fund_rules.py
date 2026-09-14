from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.models import FundRules
from app.db.schemas.fund_rules import FundRulesUpdate, FundRulesResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/fund-rules", tags=["fund-rules"])


def _get_or_create(db: Session, user_id: int) -> FundRules:
    """按登录用户取/建本用户的资金规则行(用户隔离;缺则用默认值建)。"""
    rules = db.query(FundRules).filter(FundRules.user_id == user_id).first()
    if not rules:
        rules = FundRules(user_id=user_id)
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


@router.get("/", response_model=FundRulesResponse)
def get_fund_rules(request: Request, db: Session = Depends(get_db)):
    return _get_or_create(db, get_current_user_id(request))


@router.put("/", response_model=FundRulesResponse)
def update_fund_rules(data: FundRulesUpdate, request: Request, db: Session = Depends(get_db)):
    rules = _get_or_create(db, get_current_user_id(request))
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rules, field, value)
    db.commit()
    db.refresh(rules)
    return rules
