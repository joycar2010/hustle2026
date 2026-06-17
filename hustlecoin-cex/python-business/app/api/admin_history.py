"""Admin 跨用户历史查询(平仓历史 + 执行流水)。

与 coin 端 /api/engine/positions/history 同口径(净PnL = realized_pnl + 累计资金费 − 累计利息),
但去掉 get_current_user_id 锁定、增加 user_id 维度,走 require_admin 跨用户读。
admin 端点独立挂载,绝不复用 coin 的用户隔离路径。
"""
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models import SubAccount
from app.db.models_auth import User
from app.db.session import get_db
from app.middleware.permissions import require_admin
from engine.models import Position, TradeLog

router = APIRouter(prefix="/api/admin/history", tags=["admin-history"])


def _username_map(db: Session) -> dict[int, str]:
    return {u.id: u.username for u in db.query(User.id, User.username).all()}


def _account_note_map(db: Session, account_ids: set[int]) -> dict[int, str]:
    if not account_ids:
        return {}
    rows = db.query(SubAccount.id, SubAccount.note).filter(SubAccount.id.in_(account_ids)).all()
    return {r.id: r.note for r in rows}


def _parse_start(s: str | None):
    return datetime.fromisoformat(s) if s else None


def _parse_end_exclusive(s: str | None):
    """end_date 含当日全天:date-only(午夜)→ +1 天用 < 比较,避免漏掉当天交易。"""
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        dt = dt + timedelta(days=1)
    return dt


@router.get("/closed")
def closed_history(
    request: Request,
    user_id: int = Query(None),
    sub_account_id: int = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    require_admin(request)

    q = db.query(Position).filter(Position.status == "CLOSED")
    if user_id is not None:
        q = q.filter(Position.user_id == user_id)
    if sub_account_id is not None:
        q = q.filter(Position.sub_account_id == sub_account_id)
    start = _parse_start(start_date)
    end = _parse_end_exclusive(end_date)
    if start is not None:
        q = q.filter(Position.closed_at >= start)
    if end is not None:
        q = q.filter(Position.closed_at < end)

    # 汇总走 DB 聚合(不拉进内存),与 coin /history 同口径
    ids_subq = q.with_entities(Position.id)
    total_pnl = Decimal(str(db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.id.in_(ids_subq)).scalar()))
    total_funding = Decimal(str(db.query(func.coalesce(func.sum(Position.cumulative_funding_fee), 0)).filter(
        Position.id.in_(ids_subq)).scalar()))
    total_interest = Decimal(str(db.query(func.coalesce(func.sum(Position.cumulative_interest), 0)).filter(
        Position.id.in_(ids_subq)).scalar()))
    count = q.count()

    rows = q.order_by(Position.closed_at.desc()).offset((page - 1) * size).limit(size).all()

    unames = _username_map(db)
    notes = _account_note_map(db, {p.sub_account_id for p in rows})

    positions = []
    for p in rows:
        positions.append({
            "id": p.id,
            "user_id": p.user_id,
            "username": unames.get(p.user_id) if p.user_id is not None else None,
            "symbol": p.symbol,
            "sub_account_id": p.sub_account_id,
            "account_note": notes.get(p.sub_account_id),
            "borrow_qty": str(p.borrow_qty) if p.borrow_qty is not None else None,
            "open_spread": str(p.open_spread) if p.open_spread is not None else None,
            "close_spread": str(p.close_spread) if p.close_spread is not None else None,
            "realized_pnl": str(p.realized_pnl) if p.realized_pnl is not None else None,
            "cumulative_funding_fee": str(p.cumulative_funding_fee) if p.cumulative_funding_fee is not None else None,
            "cumulative_interest": str(p.cumulative_interest) if p.cumulative_interest is not None else None,
            "open_usdt_amount": str(p.open_usdt_amount) if p.open_usdt_amount is not None else None,
            "opened_at": str(p.opened_at) if p.opened_at else None,
            "closed_at": str(p.closed_at) if p.closed_at else None,
        })

    return {
        "positions": positions,
        "total_pnl": str(total_pnl),
        "total_funding_fee": str(total_funding),
        "total_interest": str(total_interest),
        "net_pnl": str(total_pnl + total_funding - total_interest),
        "count": count,
    }


@router.get("/trade-logs")
def trade_logs(
    request: Request,
    position_id: int = Query(None),
    user_id: int = Query(None),
    sub_account_id: int = Query(None),
    symbol: str = Query(None),
    action: str = Query(None),
    status: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """跨用户执行流水。position_id 用于平仓历史下钻;其余筛选用于 P1b 排障。"""
    require_admin(request)

    q = db.query(TradeLog)
    if position_id is not None:
        q = q.filter(TradeLog.position_id == position_id)
    if user_id is not None:
        q = q.filter(TradeLog.user_id == user_id)
    if sub_account_id is not None:
        q = q.filter(TradeLog.sub_account_id == sub_account_id)
    if symbol:
        q = q.filter(TradeLog.symbol == symbol.upper())
    if action:
        q = q.filter(TradeLog.action == action)
    if status:
        q = q.filter(TradeLog.status == status)
    start = _parse_start(start_date)
    end = _parse_end_exclusive(end_date)
    if start is not None:
        q = q.filter(TradeLog.created_at >= start)
    if end is not None:
        q = q.filter(TradeLog.created_at < end)

    count = q.count()
    rows = q.order_by(TradeLog.created_at.desc()).offset((page - 1) * size).limit(size).all()

    unames = _username_map(db)
    notes = _account_note_map(db, {r.sub_account_id for r in rows})

    logs = []
    for t in rows:
        logs.append({
            "id": t.id,
            "position_id": t.position_id,
            "user_id": t.user_id,
            "username": unames.get(t.user_id) if t.user_id is not None else None,
            "sub_account_id": t.sub_account_id,
            "account_note": notes.get(t.sub_account_id),
            "action": t.action,
            "symbol": t.symbol,
            "side": t.side,
            "quantity": str(t.quantity) if t.quantity is not None else None,
            "price": str(t.price) if t.price is not None else None,
            "order_id": t.order_id,
            "status": t.status,
            "error_message": t.error_message,
            "latency_ms": t.latency_ms,
            "created_at": str(t.created_at) if t.created_at else None,
        })

    return {"logs": logs, "count": count}
