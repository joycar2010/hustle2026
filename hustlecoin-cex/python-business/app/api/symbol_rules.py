from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.models import SymbolRule, GlobalRules
from app.db.schemas.symbol_rules import SymbolRuleUpdate, SymbolRuleResponse
from app.db.schemas.common import MessageResponse, PaginatedResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/symbol-rules", tags=["symbol-rules"])


def _norm_symbol(symbol: str) -> str:
    """规范化交易对:大写去空格 + 补全 USDT 后缀(本系统全为 USDT 永续对)。
    根除「裸币种名」规则(如 'FIL')—— 前端/引擎都按全名 'FILUSDT' 查点差/行情/规则,裸键会建出
    对不上的空白行(实测 AXL/FIDA/FIL 六列全空根因)。已带 USDT 的不动。"""
    s = (symbol or "").upper().strip()
    if s and not s.endswith("USDT"):
        s += "USDT"
    return s


def _publish_rules_reload(user_id: int):
    """事件驱动 0 秒规则热重载:保存/重置/删除单一规则后立即通知该 user 的 worker 重读规则
    (worker 订阅 rules:reload:{uid})。失败静默,不阻断保存(主循环 3s 轮询仍兜底)。"""
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.publish(f"rules:reload:{user_id}", "1")
        rc.close()
    except Exception:
        pass


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
    symbol = _norm_symbol(symbol)
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id,
        SymbolRule.symbol == symbol,
    ).first()
    if not rule:
        # 不再为"查看"落库空壳 custom 行(否则该币永久误显"单一规则"、被前端并集钉在面板上清不掉)。
        # 返回 404,前端 SymbolRuleDialog 自动用全局规则兜底(已有逻辑,比构造临时对象更安全)。
        raise HTTPException(status_code=404, detail=f"No custom rule for {symbol}")
    global_rules = _get_global_rules(db, user_id)
    return _to_response(rule, global_rules)


@router.put("/{symbol}", response_model=SymbolRuleResponse)
def update_symbol_rule(symbol: str, data: SymbolRuleUpdate, request: Request, db: Session = Depends(get_db)):
    from decimal import Decimal
    user_id = get_current_user_id(request)
    symbol = _norm_symbol(symbol)
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
    remove_spread_changed = "remove_spread" in update_data  # 本次是否显式改了 remove_spread

    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.source = "custom"

    # C3: remove_spread<0.5 时自动联动关闭 allow_repay —— 仅在【本次请求显式修改 remove_spread】时才重算。
    # 解耦(问题3):此前无条件用 rule.remove_spread(已存在值)判定,导致"只改 close_spread(平点差)保存"
    # 也会因旧 remove_spread<0.5 把 allow_repay 翻成 False → 引擎 _is_repay_allowed 拦截 → 设平点差却永不平仓。
    # 现改为:不碰 remove_spread / 不显式给 allow_repay 的保存,一律不动 allow_repay。
    if remove_spread_changed and not explicitly_set_repay:
        effective_remove = rule.remove_spread
        if effective_remove is None:
            global_rules = _get_global_rules(db, user_id)
            effective_remove = global_rules.remove_spread
        if effective_remove is not None:
            if Decimal(str(effective_remove)) < Decimal("0.5"):
                rule.allow_repay = False
            elif not rule.allow_repay:
                rule.allow_repay = True

    db.commit()
    db.refresh(rule)
    _publish_rules_reload(user_id)   # 0 秒通知引擎重载
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
    rule.remove_spread = None
    rule.close_funding_ratio = None
    rule.repay_funding_ratio = None
    rule.max_daily_interest_rate = None
    rule.repay_spread = None
    rule.max_borrow_amount = None
    rule.source = "global"
    db.commit()
    db.refresh(rule)
    _publish_rules_reload(user_id)   # 0 秒通知引擎重载
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
    db.delete(rule)
    db.commit()
    _publish_rules_reload(user_id)   # 0 秒通知引擎重载
    return {"message": f"Symbol rule for {symbol} deleted"}
