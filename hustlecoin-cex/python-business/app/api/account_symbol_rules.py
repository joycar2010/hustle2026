from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import AccountSymbolRule
from app.db.session import get_db
from app.db.schemas.account_symbol_rule import (
    AccountSymbolRuleUpsert,
    AccountSymbolRuleResponse,
    BatchAccountSymbolRuleRequest,
)
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/account-symbol-rules", tags=["account-symbol-rules"])


@router.get("/{sub_account_id}", response_model=list[AccountSymbolRuleResponse])
def list_rules(sub_account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    return db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.sub_account_id == sub_account_id,
    ).order_by(AccountSymbolRule.symbol).all()


@router.get("/{sub_account_id}/{symbol}", response_model=AccountSymbolRuleResponse)
def get_rule(sub_account_id: int, symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    rule = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.sub_account_id == sub_account_id,
        AccountSymbolRule.symbol == symbol.upper(),
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/{sub_account_id}/{symbol}", response_model=AccountSymbolRuleResponse)
def upsert_rule(
    sub_account_id: int,
    symbol: str,
    data: AccountSymbolRuleUpsert,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    sym = symbol.upper()
    rule = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.sub_account_id == sub_account_id,
        AccountSymbolRule.symbol == sym,
    ).first()

    if rule:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
    else:
        rule = AccountSymbolRule(
            user_id=user_id,
            sub_account_id=sub_account_id,
            symbol=sym,
            **data.model_dump(exclude_unset=True),
        )
        db.add(rule)

    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{sub_account_id}/{symbol}")
def delete_rule(sub_account_id: int, symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    rule = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.sub_account_id == sub_account_id,
        AccountSymbolRule.symbol == symbol.upper(),
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"message": f"Deleted rule for {symbol.upper()} on account {sub_account_id}"}


@router.post("/{sub_account_id}/{symbol}/reset")
def reset_rule(sub_account_id: int, symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    rule = db.query(AccountSymbolRule).filter(
        AccountSymbolRule.user_id == user_id,
        AccountSymbolRule.sub_account_id == sub_account_id,
        AccountSymbolRule.symbol == symbol.upper(),
    ).first()
    if rule:
        db.delete(rule)
        db.commit()
    return {"message": f"Reset rule for {symbol.upper()} on account {sub_account_id}"}


@router.post("/batch")
def batch_upsert(data: BatchAccountSymbolRuleRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    updated = 0
    created = 0
    for item in data.items:
        sym = item.symbol.upper()
        rule = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.user_id == user_id,
            AccountSymbolRule.sub_account_id == item.sub_account_id,
            AccountSymbolRule.symbol == sym,
        ).first()

        if rule:
            for field, value in item.data.model_dump(exclude_unset=True).items():
                setattr(rule, field, value)
            updated += 1
        else:
            rule = AccountSymbolRule(
                user_id=user_id,
                sub_account_id=item.sub_account_id,
                symbol=sym,
                **item.data.model_dump(exclude_unset=True),
            )
            db.add(rule)
            created += 1

    db.commit()
    return {"message": f"Batch complete: {created} created, {updated} updated"}
