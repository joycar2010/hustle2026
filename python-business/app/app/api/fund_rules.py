from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import FundRules
from app.db.schemas.fund_rules import FundRulesUpdate, FundRulesResponse
from app.db.session import get_db

router = APIRouter(prefix="/api/fund-rules", tags=["fund-rules"])


def _get_or_create(db: Session) -> FundRules:
    rules = db.query(FundRules).first()
    if not rules:
        rules = FundRules()
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


@router.get("/", response_model=FundRulesResponse)
def get_fund_rules(db: Session = Depends(get_db)):
    return _get_or_create(db)


@router.put("/", response_model=FundRulesResponse)
def update_fund_rules(data: FundRulesUpdate, db: Session = Depends(get_db)):
    rules = _get_or_create(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rules, field, value)
    db.commit()
    db.refresh(rules)
    return rules
