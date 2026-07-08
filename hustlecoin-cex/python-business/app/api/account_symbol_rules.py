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


def _publish_rules_reload(user_id: int, clear_repayhold_symbol: str = None):
    """事件驱动 0 秒规则热重载:保存/删除逐账户单一规则后立即通知该 user 的 worker 重读规则
    (worker 订阅 rules:reload:{uid})。失败静默,不阻断保存(主循环 3s 轮询仍兜底)。
    clear_repayhold_symbol: 保存该币规则=显式再武装 → 清「还币暂停」标记允许立即重借。
    (此前只有批量行 symbol_rules PUT 清标记,用户在逐账户行填 -1 清不掉,还币后要干等30分钟)"""
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.publish(f"rules:reload:{user_id}", "1")
        if clear_repayhold_symbol:
            rc.delete(f"engine:{user_id}:repayhold:{clear_repayhold_symbol.upper()}")
        rc.close()
    except Exception:
        pass


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
    _publish_rules_reload(user_id, clear_repayhold_symbol=sym)   # 0 秒重载 + 清还币暂停标记
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
    _publish_rules_reload(user_id)   # 0 秒通知引擎重载
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
        _publish_rules_reload(user_id)   # 0 秒通知引擎重载
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
    _publish_rules_reload(user_id)   # 0 秒通知引擎重载
    # 批量保存涉及的每个币都视为显式再武装,逐一清还币暂停标记
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        for _sym in {it.symbol.upper() for it in data.items}:
            rc.delete(f"engine:{user_id}:repayhold:{_sym}")
        rc.close()
    except Exception:
        pass
    return {"message": f"Batch complete: {created} created, {updated} updated"}
