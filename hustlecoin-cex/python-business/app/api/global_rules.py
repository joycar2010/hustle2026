from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import GlobalRules
from app.db.schemas.global_rules import GlobalRulesUpdate, GlobalRulesResponse
from app.db.session import get_db

router = APIRouter(prefix="/api/global-rules", tags=["global-rules"])


def _get_or_create(db: Session) -> GlobalRules:
    rules = db.query(GlobalRules).first()
    if not rules:
        rules = GlobalRules()
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


@router.get("/", response_model=GlobalRulesResponse)
def get_global_rules(db: Session = Depends(get_db)):
    return _get_or_create(db)


@router.put("/", response_model=GlobalRulesResponse)
def update_global_rules(data: GlobalRulesUpdate, db: Session = Depends(get_db)):
    rules = _get_or_create(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rules, field, value)
    db.commit()
    db.refresh(rules)
    return rules
