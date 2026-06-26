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

    # 系统规则变更后立即通知所有活跃用户的 worker 热重载,不等 30s 轮询周期
    _publish_system_rules_reload(db)

    return _rules_to_dict(rules)


def _publish_system_rules_reload(db: Session):
    """系统后端规则(NULL 行)保存后,向所有活跃用户的引擎发布 rules:reload 信号。
    symbol_rules.py 保存后发单用户信号,系统规则影响全员所以需广播。失败静默不阻断保存。"""
    try:
        import redis as _r
        from app.config import settings as _s
        from app.db.models_auth import User
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        users = db.query(User.id).filter(User.is_active == True).all()
        for (uid,) in users:
            rc.publish(f"rules:reload:{uid}", "system")
        rc.close()
    except Exception:
        pass


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
        "auto_push_spread", "remove_spread", "borrow_spread", "open_spread", "close_spread",
        "order_amount", "close_funding_ratio", "repay_funding_ratio",
        "borrow_delay_sec", "confirm_delay_sec", "confirm_skip_spread",
        "repay_ban_minutes", "interest_filter", "max_loss_per_position",
        "repay_spread", "max_positions", "auto_start_on_boot",
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
        "borrow_spread": str(r.borrow_spread) if r.borrow_spread is not None else None,
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
        # 系统后端规则字段(黄框)
        "follow_type": getattr(r, "follow_type", None) or "market",
        "slippage_pct": str(r.slippage_pct) if getattr(r, "slippage_pct", None) is not None else None,
        "stabilize_sec": str(r.stabilize_sec) if getattr(r, "stabilize_sec", None) is not None else None,
        "tier_ratios": getattr(r, "tier_ratios", None) or "",
        "borrow_rate_per_sec": str(r.borrow_rate_per_sec) if getattr(r, "borrow_rate_per_sec", None) is not None else None,
        "borrow_via_otoco": bool(getattr(r, "borrow_via_otoco", False)),
        "borrow_mode": getattr(r, "borrow_mode", None),
        "otoco_legs": getattr(r, "otoco_legs", 2),
        "multi_max_accounts_per_symbol": getattr(r, "multi_max_accounts_per_symbol", 3),
        "hedge_via_master": bool(getattr(r, "hedge_via_master", False)),
        "max_spread_pct": str(r.max_spread_pct) if getattr(r, "max_spread_pct", None) is not None else None,
        "min_volume_24h": str(r.min_volume_24h) if getattr(r, "min_volume_24h", None) is not None else None,
        "min_volume_24h_futures": str(r.min_volume_24h_futures) if getattr(r, "min_volume_24h_futures", None) is not None else None,
        "block_risky_open": bool(getattr(r, "block_risky_open", False)),
        "filter_duration_ms": getattr(r, "filter_duration_ms", 0),
        "min_borrow_usdt": str(r.min_borrow_usdt) if getattr(r, "min_borrow_usdt", None) is not None else None,
        "collateral_ratio": str(r.collateral_ratio) if getattr(r, "collateral_ratio", None) is not None else None,
        "removed_cooldown_minutes": getattr(r, "removed_cooldown_minutes", 0),
        "open_spread_buffer": str(r.open_spread_buffer) if getattr(r, "open_spread_buffer", None) is not None else None,
        "taker_fee_spot": str(r.taker_fee_spot) if getattr(r, "taker_fee_spot", None) is not None else None,
        "taker_fee_futures": str(r.taker_fee_futures) if getattr(r, "taker_fee_futures", None) is not None else None,
        "spread_stale_sec": getattr(r, "spread_stale_sec", None),
        "updated_at": str(r.updated_at) if r.updated_at else None,
    }
