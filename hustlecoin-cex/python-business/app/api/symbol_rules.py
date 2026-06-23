from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.models import SymbolRule, GlobalRules
from app.db.schemas.symbol_rules import SymbolRuleUpdate, SymbolRuleResponse
from app.db.schemas.common import MessageResponse, PaginatedResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/symbol-rules", tags=["symbol-rules"])


def _get_global_rules(db: Session, user_id: int) -> GlobalRules:
    rules = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
    if not rules:
        rules = GlobalRules(user_id=user_id)
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


def _to_response(rule: SymbolRule, global_rules: GlobalRules) -> dict:
    return {
        "id": rule.id,
        "symbol": rule.symbol,
        "open_spread": rule.open_spread,
        "borrow_spread": rule.borrow_spread,
        "close_spread": rule.close_spread,
        "order_amount": rule.order_amount,
        "remove_spread": rule.remove_spread,
        "close_funding_ratio": rule.close_funding_ratio,
        "repay_funding_ratio": rule.repay_funding_ratio,
        "allow_remove": rule.allow_remove,
        "allow_repay": rule.allow_repay,
        "max_daily_interest_rate": rule.max_daily_interest_rate,
        "repay_spread": rule.repay_spread,
        "max_borrow_amount": rule.max_borrow_amount,
        "source": rule.source,
        "effective_open_spread": rule.open_spread if rule.open_spread is not None else global_rules.open_spread,
        "effective_borrow_spread": rule.borrow_spread if rule.borrow_spread is not None else getattr(global_rules, "borrow_spread", None),
        "effective_close_spread": rule.close_spread if rule.close_spread is not None else global_rules.close_spread,
        "effective_order_amount": rule.order_amount if rule.order_amount is not None else global_rules.order_amount,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


@router.get("/", response_model=PaginatedResponse[SymbolRuleResponse])
def list_symbol_rules(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = db.query(SymbolRule).filter(SymbolRule.user_id == user_id)
    if search:
        q = q.filter(SymbolRule.symbol.ilike(f"%{search.upper()}%"))
    total = q.count()
    rules = q.order_by(SymbolRule.symbol).offset((page - 1) * size).limit(size).all()
    global_rules = _get_global_rules(db, user_id)
    return {"items": [_to_response(r, global_rules) for r in rules], "total": total, "page": page, "page_size": size}


@router.get("/{symbol}", response_model=SymbolRuleResponse)
def get_symbol_rule(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = symbol.upper().strip()
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        rule = SymbolRule(user_id=user_id, symbol=symbol, source="custom")
        db.add(rule)
        db.commit()
        db.refresh(rule)
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.put("/{symbol}", response_model=SymbolRuleResponse)
def update_symbol_rule(symbol: str, data: SymbolRuleUpdate, request: Request, db: Session = Depends(get_db)):
    from decimal import Decimal
    user_id = get_current_user_id(request)
    symbol = symbol.upper().strip()
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        rule = SymbolRule(user_id=user_id, symbol=symbol, source="custom")
        db.add(rule)
        db.flush()

    update_data = data.model_dump(exclude_unset=True)
    explicitly_set_repay = "allow_repay" in update_data

    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.source = "custom"

    # C3: auto-disable repay when remove_spread < 0.5 (unless user explicitly set allow_repay)
    effective_remove = rule.remove_spread
    if effective_remove is None:
        global_rules = _get_global_rules(db, user_id)
        effective_remove = global_rules.remove_spread
    if effective_remove is not None and not explicitly_set_repay:
        if Decimal(str(effective_remove)) < Decimal("0.5"):
            rule.allow_repay = False
        elif not rule.allow_repay:
            rule.allow_repay = True

    db.commit()
    db.refresh(rule)
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.post("/{symbol}/reset", response_model=SymbolRuleResponse)
def reset_symbol_rule(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = symbol.upper().strip()
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"No rule for {symbol}")
    rule.open_spread = None
    rule.borrow_spread = None
    rule.close_spread = None
    rule.order_amount = None
    rule.remove_spread = None
    rule.close_funding_ratio = None
    rule.repay_funding_ratio = None
    rule.max_daily_interest_rate = None
    rule.repay_spread = None
    rule.max_borrow_amount = None
    rule.source = "global"
    db.commit()
    db.refresh(rule)
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.delete("/{symbol}", response_model=MessageResponse)
def delete_symbol_rule(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = symbol.upper().strip()
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"No rule for {symbol}")
    db.delete(rule)
    db.commit()
    return {"message": f"Symbol rule for {symbol} deleted"}
