from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import GlobalRules
from app.db.models_auth import User
from app.db.schemas.global_rules import GlobalRulesUpdate, GlobalRulesResponse
from app.db.session import get_db
from app.middleware.permissions import require_admin

router = APIRouter(prefix="/api/admin/global-rules", tags=["admin-global-rules"])


@router.get("/")
def get_system_rules(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rules = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).first()
    if not rules:
        rules = GlobalRules(user_id=None)
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return _rules_to_dict(rules)


@router.put("/")
def update_system_rules(data: GlobalRulesUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    rules = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).first()
    if not rules:
        rules = GlobalRules(user_id=None)
        db.add(rules)

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(rules, field, value)
    db.commit()
    db.refresh(rules)

    return _rules_to_dict(rules)


@router.post("/broadcast")
def broadcast_rules(request: Request, db: Session = Depends(get_db)):
    """Copy system default rules to all users."""
    require_admin(request)

    system_rules = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).first()
    if not system_rules:
        raise HTTPException(status_code=400, detail="No system default rules configured")

    users = db.query(User).filter(User.is_active == True).all()
    updated = 0
    fields = [
        "auto_push_spread", "remove_spread", "open_spread", "close_spread",
        "order_amount", "close_funding_ratio", "repay_funding_ratio",
        "borrow_delay_sec", "confirm_delay_sec", "confirm_skip_spread",
        "repay_ban_minutes", "interest_filter", "max_loss_per_position",
        "circuit_breaker_spread_pct", "circuit_breaker_pause_sec",
        "max_daily_interest_rate", "repay_spread", "max_positions",
        "auto_start_on_boot", "futures_liquidation_threshold",
    ]

    for u in users:
        user_rules = db.query(GlobalRules).filter(GlobalRules.user_id == u.id).first()
        if not user_rules:
            user_rules = GlobalRules(user_id=u.id)
            db.add(user_rules)
        for f in fields:
            setattr(user_rules, f, getattr(system_rules, f))
        updated += 1

    db.commit()
    return {"message": f"Rules broadcast to {updated} users", "updated": updated}


@router.get("/users")
def list_user_rules(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    users = db.query(User).filter(User.is_active == True).order_by(User.id).all()
    result = []
    for u in users:
        rules = db.query(GlobalRules).filter(GlobalRules.user_id == u.id).first()
        if rules:
            d = _rules_to_dict(rules)
            d["username"] = u.username
            result.append(d)
    return result


def _rules_to_dict(r: GlobalRules) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "auto_push_spread": str(r.auto_push_spread),
        "remove_spread": str(r.remove_spread),
        "open_spread": str(r.open_spread),
        "close_spread": str(r.close_spread),
        "order_amount": str(r.order_amount),
        "close_funding_ratio": str(r.close_funding_ratio),
        "repay_funding_ratio": str(r.repay_funding_ratio),
        "borrow_delay_sec": r.borrow_delay_sec,
        "confirm_delay_sec": r.confirm_delay_sec,
        "confirm_skip_spread": str(r.confirm_skip_spread),
        "repay_ban_minutes": r.repay_ban_minutes,
        "interest_filter": str(r.interest_filter),
        "max_loss_per_position": str(r.max_loss_per_position) if r.max_loss_per_position else None,
        "circuit_breaker_spread_pct": str(r.circuit_breaker_spread_pct) if r.circuit_breaker_spread_pct else None,
        "circuit_breaker_pause_sec": r.circuit_breaker_pause_sec,
        "max_daily_interest_rate": str(r.max_daily_interest_rate) if r.max_daily_interest_rate else None,
        "repay_spread": str(r.repay_spread) if r.repay_spread else None,
        "max_positions": r.max_positions,
        "auto_start_on_boot": r.auto_start_on_boot,
        "futures_liquidation_threshold": str(r.futures_liquidation_threshold) if r.futures_liquidation_threshold else None,
        "updated_at": str(r.updated_at) if r.updated_at else None,
    }
