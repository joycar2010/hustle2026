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
from app.services.pushed_symbols import (
    auto_global_rule_account_field,
    auto_global_rules_key,
)

router = APIRouter(prefix="/api/account-symbol-rules", tags=["account-symbol-rules"])


def _set_auto_global_account_marker(user_id: int, sub_account_id: int, symbol: str, *, enabled: bool) -> None:
    """Keep the automatic-push source marker in sync with account overrides.

    A plain ``SYMBOL`` hash member means every worker still inherits the
    automatic/global snapshot.  An account-scoped field opts only that
    worker out, so saving account 05 cannot unexpectedly change account 04.
    This is deliberately best effort: the database row remains authoritative
    and the worker's periodic reload is the fallback when Redis is unavailable.
    """
    try:
        import redis as _r
        from app.config import settings as _s

        rc = _r.from_url(_s.redis_url, decode_responses=True,
                         socket_connect_timeout=1, socket_timeout=1)
        field = auto_global_rule_account_field(sub_account_id, symbol)
        key = auto_global_rules_key(user_id)
        if enabled:
            rc.hset(key, field, "1")
        else:
            rc.hdel(key, field)
        rc.close()
    except Exception:
        # Marker state is advisory.  A committed DB rule is still loaded by
        # the worker; this avoids making a successful save depend on Redis.
        pass


def _has_explicit_account_override(data: dict) -> bool:
    """Return whether an account save contains a value that overrides global.

    Empty dialog rows send nulls to clear inherited fields.  ``is_enabled``
    remains an explicit account gate even when all numeric fields are cleared.
    """
    for field, value in data.items():
        if field == "is_enabled":
            return True
        if value is not None:
            return True
    return False


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
    # Keep the source marker account-scoped: a saved close/open threshold
    # opts only this worker out of automatic/global inheritance.
    _set_auto_global_account_marker(
        user_id,
        sub_account_id,
        sym,
        enabled=_has_explicit_account_override(data.model_dump(exclude_unset=True)),
    )
    _publish_rules_reload(user_id, clear_repayhold_symbol=sym)
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
    _set_auto_global_account_marker(user_id, sub_account_id, symbol.upper(), enabled=False)
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
        _set_auto_global_account_marker(user_id, sub_account_id, symbol.upper(), enabled=False)
        _publish_rules_reload(user_id)   # 0 秒通知引擎重载
    return {"message": f"Reset rule for {symbol.upper()} on account {sub_account_id}"}


@router.post("/batch")
def batch_upsert(data: BatchAccountSymbolRuleRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    updated = 0
    created = 0
    marker_updates: list[tuple[int, str, bool]] = []
    for item in data.items:
        sym = item.symbol.upper()
        payload = item.data.model_dump(exclude_unset=True)
        rule = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.user_id == user_id,
            AccountSymbolRule.sub_account_id == item.sub_account_id,
            AccountSymbolRule.symbol == sym,
        ).first()

        if rule:
            for field, value in payload.items():
                setattr(rule, field, value)
            updated += 1
        else:
            rule = AccountSymbolRule(
                user_id=user_id,
                sub_account_id=item.sub_account_id,
                symbol=sym,
                **payload,
            )
            db.add(rule)
            created += 1
        marker_updates.append((item.sub_account_id, sym, _has_explicit_account_override(payload)))

    db.commit()
    for sub_account_id, sym, enabled in marker_updates:
        _set_auto_global_account_marker(user_id, sub_account_id, sym, enabled=enabled)
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
