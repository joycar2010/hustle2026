from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.db.session import get_db
from engine.models import Position, TradeLog, EngineState
from engine.schemas import (
    PositionResponse, TradeLogResponse, EngineStateResponse,
    PositionSummary, DashboardResponse,
)

router = APIRouter(prefix="/api/engine", tags=["engine"])


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(
    sub_account_id: int = Query(None),
    status: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Position)
    if sub_account_id:
        q = q.filter(Position.sub_account_id == sub_account_id)
    if status:
        q = q.filter(Position.status == status.upper())
    if symbol:
        q = q.filter(Position.symbol == symbol.upper())
    q = q.order_by(Position.id.desc())
    return q.offset((page - 1) * size).limit(size).all()


@router.get("/positions/summary", response_model=PositionSummary)
def positions_summary(db: Session = Depends(get_db)):
    total_open = db.query(Position).filter(Position.status == "OPEN").count()
    total_closed = db.query(Position).filter(Position.status == "CLOSED").count()
    total_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.status == "CLOSED"
    ).scalar()
    return {
        "total_open": total_open,
        "total_closed": total_closed,
        "total_pnl": Decimal(str(total_pnl)),
    }


@router.get("/positions/{position_id}", response_model=PositionResponse)
def get_position(position_id: int, db: Session = Depends(get_db)):
    pos = db.query(Position).get(position_id)
    if not pos:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Position not found")
    return pos


@router.get("/trade-logs", response_model=list[TradeLogResponse])
def list_trade_logs(
    sub_account_id: int = Query(None),
    action: str = Query(None),
    position_id: int = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(TradeLog)
    if sub_account_id:
        q = q.filter(TradeLog.sub_account_id == sub_account_id)
    if action:
        q = q.filter(TradeLog.action == action.upper())
    if position_id:
        q = q.filter(TradeLog.position_id == position_id)
    q = q.order_by(TradeLog.id.desc())
    return q.offset((page - 1) * size).limit(size).all()


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)):
    global_state = db.query(EngineState).filter(EngineState.scope == "global").first()
    engine_status = global_state.status if global_state else "STOPPED"

    workers = db.query(EngineState).filter(EngineState.scope != "global").all()

    total_open = db.query(Position).filter(Position.status == "OPEN").count()
    total_closed = db.query(Position).filter(Position.status == "CLOSED").count()
    total_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.status == "CLOSED"
    ).scalar()

    recent = db.query(TradeLog).order_by(TradeLog.id.desc()).limit(10).all()

    return {
        "engine_status": engine_status,
        "workers": workers,
        "positions_summary": {
            "total_open": total_open,
            "total_closed": total_closed,
            "total_pnl": Decimal(str(total_pnl)),
        },
        "recent_trades": recent,
    }
