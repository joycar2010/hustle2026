from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.models import AccountSymbolRule, SymbolRule, GlobalRules, SubAccount
from app.db.schemas.symbol_rules import SymbolRuleUpdate, SymbolRuleResponse
from app.db.schemas.common import MessageResponse, PaginatedResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services.rule_hysteresis import remove_hierarchy_has_conflict
from app.services.rule_reload import clear_user_borrow_failures
from app.services.pushed_symbols import (
    auto_global_rules_key,
    manual_push_marker_key,
)
from engine.config_loader import DEFAULT_GLOBAL
from engine.thresholds import push_remove_conflict

router = APIRouter(prefix="/api/symbol-rules", tags=["symbol-rules"])


def _norm_symbol(symbol: str) -> str:
    """è§„èŒƒåŒ–äº¤æ˜“å¯¹:å¤§å†™åŽ»ç©ºæ ¼ + è¡¥å…¨ USDT åŽç¼€(æœ¬ç³»ç»Ÿå…¨ä¸º USDT æ°¸ç»­å¯¹)ã€‚
    æ ¹é™¤ã€Œè£¸å¸ç§åã€è§„åˆ™(å¦‚ 'FIL')â€”â€” å‰ç«¯/å¼•æ“Žéƒ½æŒ‰å…¨å 'FILUSDT' æŸ¥ç‚¹å·®/è¡Œæƒ…/è§„åˆ™,è£¸é”®ä¼šå»ºå‡º
    å¯¹ä¸ä¸Šçš„ç©ºç™½è¡Œ(å®žæµ‹ AXL/FIDA/FIL å…­åˆ—å…¨ç©ºæ ¹å› )ã€‚å·²å¸¦ USDT çš„ä¸åŠ¨ã€‚"""
    s = (symbol or "").upper().strip()
    if s and not s.endswith("USDT"):
        s += "USDT"
    return s


def _canonical_symbol_key(symbol: str | None) -> str:
    """Return the same canonical key used by account-rule and worker code."""
    value = str(symbol or "").strip().upper()
    if value and not value.endswith("USDT"):
        value += "USDT"
    return value


def _publish_rules_reload(user_id: int):
    """äº‹ä»¶é©±åŠ¨ 0 ç§’è§„åˆ™çƒ­é‡è½½:ä¿å­˜/é‡ç½®/åˆ é™¤å•ä¸€è§„åˆ™åŽç«‹å³é€šçŸ¥è¯¥ user çš„ worker é‡è¯»è§„åˆ™
    (worker è®¢é˜… rules:reload:{uid})ã€‚å¤±è´¥é™é»˜,ä¸é˜»æ–­ä¿å­˜(ä¸»å¾ªçŽ¯ 3s è½®è¯¢ä»å…œåº•)ã€‚"""
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.publish(f"rules:reload:{user_id}", "1")
        rc.close()
    except Exception:
        pass


def _clear_auto_global_rule_source(user_id: int, symbol: str) -> None:
    """A saved single-symbol rule opts out of automatic global inheritance."""
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.hdel(auto_global_rules_key(user_id), symbol)
        rc.close()
    except Exception:
        # Rule persistence remains authoritative; a Worker retry will pick up
        # the database change once the control-plane marker is reachable.
        pass


def _manual_push_active(user_id: int, symbol: str) -> bool:
    """Return whether a symbol is currently protected by an explicit push."""
    try:
        import redis as _redis
        from app.config import settings

        client = _redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            return bool(client.get(manual_push_marker_key(user_id, symbol)))
        finally:
            client.close()
    except Exception:
        # Validation must remain fail-closed when the control-plane marker is
        # unavailable; automatic pushes still require a valid hysteresis pair.
        return False


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
        "open_order_amount": rule.open_order_amount,
        "remove_spread": rule.remove_spread,
        "close_funding_ratio": rule.close_funding_ratio,
        "repay_funding_ratio": rule.repay_funding_ratio,
        "allow_remove": rule.allow_remove,
        "allow_repay": rule.allow_repay,
        "max_daily_interest_rate": rule.max_daily_interest_rate,
        "repay_spread": rule.repay_spread,
        "max_borrow_amount": rule.max_borrow_amount,
        "slippage_pct": rule.slippage_pct,
        "follow_type": rule.follow_type,
        "note": rule.note,
        "source": rule.source,
        "has_account_override": False,
        "effective_open_spread": rule.open_spread if rule.open_spread is not None else global_rules.open_spread,
        "effective_borrow_spread": rule.borrow_spread if rule.borrow_spread is not None else getattr(global_rules, "borrow_spread", None),
        "effective_close_spread": rule.close_spread if rule.close_spread is not None else global_rules.close_spread,
        "effective_order_amount": rule.order_amount if rule.order_amount is not None else global_rules.order_amount,
        "effective_open_order_amount": (
            rule.open_order_amount
            if rule.open_order_amount is not None
            else (
                global_rules.open_order_amount
                if getattr(global_rules, "open_order_amount", None) is not None
                else global_rules.order_amount
            )
        ),
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
    # The dashboard's compact source badge must include account-symbol
    # overrides.  A symbol-level row can be an empty/global placeholder while
    # one account still has an explicit close spread, amount, or cap.  The
    # worker already applies that account rule; expose the same fact to the UI
    # so it cannot incorrectly show “通用规则”.
    account_symbols = {
        _canonical_symbol_key(row[0])
        for row in db.query(AccountSymbolRule.symbol)
        .filter(AccountSymbolRule.user_id == user_id)
        .filter(or_(
            AccountSymbolRule.open_spread.isnot(None),
            AccountSymbolRule.borrow_spread.isnot(None),
            AccountSymbolRule.close_spread.isnot(None),
            AccountSymbolRule.order_amount.isnot(None),
            AccountSymbolRule.open_order_amount.isnot(None),
            AccountSymbolRule.max_borrow_amount.isnot(None),
            AccountSymbolRule.remove_spread.isnot(None),
            AccountSymbolRule.close_funding_ratio.isnot(None),
            AccountSymbolRule.repay_funding_ratio.isnot(None),
            AccountSymbolRule.repay_spread.isnot(None),
            AccountSymbolRule.max_daily_interest_rate.isnot(None),
        ))
        .all()
    }
    items = []
    for rule in rules:
        item = _to_response(rule, global_rules)
        if _canonical_symbol_key(rule.symbol) in account_symbols:
            item["source"] = "custom"
            item["has_account_override"] = True
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": size}


@router.get("/{symbol}", response_model=SymbolRuleResponse)
def get_symbol_rule(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = _norm_symbol(symbol)
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        # ä¸å†ä¸º"æŸ¥çœ‹"è½åº“ç©ºå£³ custom è¡Œ(å¦åˆ™è¯¥å¸æ°¸ä¹…è¯¯æ˜¾"å•ä¸€è§„åˆ™"ã€è¢«å‰ç«¯å¹¶é›†é’‰åœ¨é¢æ¿ä¸Šæ¸…ä¸æŽ‰)ã€‚
        # è¿”å›ž 404,å‰ç«¯ SymbolRuleDialog è‡ªåŠ¨ç”¨å…¨å±€è§„åˆ™å…œåº•(å·²æœ‰é€»è¾‘,æ¯”æž„é€ ä¸´æ—¶å¯¹è±¡æ›´å®‰å…¨)ã€‚
        raise HTTPException(status_code=404, detail=f"No custom rule for {symbol}")
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.put("/{symbol}", response_model=SymbolRuleResponse)
def update_symbol_rule(symbol: str, data: SymbolRuleUpdate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = _norm_symbol(symbol)
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        rule_was_new = True
        rule = SymbolRule(user_id=user_id, symbol=symbol, source="custom")
        db.add(rule)
        db.flush()
    else:
        rule_was_new = False

    update_data = data.model_dump(exclude_unset=True)
    global_row = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
    auto_push = getattr(
        global_row, "auto_push_spread", DEFAULT_GLOBAL.auto_push_spread
    )
    final_allow_remove = update_data.get(
        "allow_remove", getattr(rule, "allow_remove", True)
    )
    effective_remove = update_data.get(
        "remove_spread", getattr(rule, "remove_spread", None)
    )
    if effective_remove is None:
        effective_remove = getattr(
            global_row, "remove_spread", DEFAULT_GLOBAL.remove_spread
        )
    # Only a removal-line or allow/remove transition can create a new
    # hysteresis conflict.  The dialog sends all columns on a dirty row, so an
    # unrelated borrow/open edit must not be blocked by a legacy remove line.
    remove_changed = (
        "remove_spread" in update_data
        and (
            rule_was_new
            or update_data.get("remove_spread") != getattr(rule, "remove_spread", None)
        )
    )
    allow_remove_changed = (
        "allow_remove" in update_data
        and (
            rule_was_new
            or update_data.get("allow_remove") != getattr(rule, "allow_remove", None)
        )
    )
    if final_allow_remove is not False and (remove_changed or allow_remove_changed):
        remove_lines = [effective_remove]
        account_rows = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.user_id == user_id,
            AccountSymbolRule.symbol.in_([symbol, symbol.removesuffix("USDT")]),
        ).all()
        remove_lines.extend(
            row.remove_spread if row.remove_spread is not None else effective_remove
            for row in account_rows
            if getattr(row, "is_enabled", True) is not False
        )
        if (
            any(push_remove_conflict(auto_push, line) for line in remove_lines)
            and not _manual_push_active(user_id, symbol)
        ):
            raise HTTPException(
                status_code=422,
                detail="ç‚¹å·®ä¸è¶³ç§»é™¤å¿…é¡»ä½ŽäºŽè‡ªåŠ¨æŽ¨é€ç‚¹å·®ï¼Œæ‰èƒ½å½¢æˆç¨³å®šè¿Ÿæ»žåŒºé—´",
            )
    explicitly_set_repay = "allow_repay" in update_data
    remove_spread_changed = "remove_spread" in update_data  # æœ¬æ¬¡æ˜¯å¦æ˜¾å¼æ”¹äº† remove_spread

    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.source = "custom"

    # ``allow_repay`` is an explicit debt-repayment control.  Do not derive or
    # mutate it from ``remove_spread``: a removal threshold change must never
    # silently disable repayment (or the preceding OPEN close lifecycle).

    db.commit()
    db.refresh(rule)
    _clear_auto_global_rule_source(user_id, symbol)
    _publish_rules_reload(user_id)   # 0 ç§’é€šçŸ¥å¼•æ“Žé‡è½½
    try:
        # ä¿å­˜è¯¥å¸è§„åˆ™=æ˜¾å¼å†æ­¦è£… â†’ æ¸…æ—§å‚æ•°ä¸‹çš„è¿˜å¸æš‚åœ/å€Ÿå¸å¤±è´¥æ ‡è®°,
        # å…è®¸å¼•æ“Žç«‹å³æŒ‰æ–°é˜ˆå€¼å’Œé‡‘é¢ä¸Šé™é‡æ–°è¯„ä¼°ã€‚
        import redis as _rr
        from app.config import settings as _ss
        _rc = _rr.from_url(_ss.redis_url, decode_responses=True)
        _rc.delete(f"engine:{user_id}:repayhold:{symbol}")
        owned_account_ids = tuple(
            row[0]
            for row in db.query(SubAccount.id).filter(
                SubAccount.user_id == user_id
            ).all()
        )
        clear_user_borrow_failures(
            _rc,
            user_id=user_id,
            symbol=symbol,
            owned_account_ids=owned_account_ids,
        )
        _rc.close()
    except Exception:
        pass
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.post("/{symbol}/reset", response_model=SymbolRuleResponse)
def reset_symbol_rule(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = _norm_symbol(symbol)
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
    rule.open_order_amount = None
    rule.remove_spread = None
    rule.close_funding_ratio = None
    rule.repay_funding_ratio = None
    rule.max_daily_interest_rate = None
    rule.repay_spread = None
    rule.max_borrow_amount = None
    rule.source = "global"
    db.commit()
    db.refresh(rule)
    _clear_auto_global_rule_source(user_id, symbol)
    _publish_rules_reload(user_id)   # 0 ç§’é€šçŸ¥å¼•æ“Žé‡è½½
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.delete("/{symbol}", response_model=MessageResponse)
def delete_symbol_rule(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = _norm_symbol(symbol)
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"No rule for {symbol}")
    global_rules = _get_global_rules(db, user_id)
    if remove_hierarchy_has_conflict(
        db,
        user_id,
        auto_push_spread=global_rules.auto_push_spread,
        global_remove_spread=global_rules.remove_spread,
        exclude_symbol_rule_ids=(rule.id,),
        only_symbols=(symbol,),
    ):
        raise HTTPException(
            status_code=422,
            detail="\u70b9\u5dee\u4e0d\u8db3\u79fb\u9664\u5fc5\u987b\u4f4e\u4e8e\u81ea\u52a8\u63a8\u9001\u70b9\u5dee\uff0c\u624d\u80fd\u5f62\u6210\u7a33\u5b9a\u8fdf\u6ede\u533a\u95f4",
        )
    db.delete(rule)
    db.commit()
    _clear_auto_global_rule_source(user_id, symbol)
    _publish_rules_reload(user_id)   # 0 ç§’é€šçŸ¥å¼•æ“Žé‡è½½
    return {"message": f"Symbol rule for {symbol} deleted"}

