from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.models import Symbol
from app.db.schemas.symbol import SymbolResponse, SymbolSyncResult, SymbolStats
from app.db.session import get_db
from app.services import symbol_sync

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


@router.get("/", response_model=list[SymbolResponse])
def list_symbols(
    margin_only: bool = Query(False),
    futures_only: bool = Query(False),
    active_only: bool = Query(True),
    search: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Symbol)
    if active_only:
        q = q.filter(Symbol.is_active == True)
    if margin_only:
        q = q.filter(Symbol.margin_tradable == True)
    if futures_only:
        q = q.filter(Symbol.futures_tradable == True)
    if search:
        q = q.filter(Symbol.symbol.ilike(f"%{search.upper()}%"))
    q = q.order_by(Symbol.symbol)
    return q.offset((page - 1) * size).limit(size).all()


@router.post("/sync", response_model=SymbolSyncResult)
async def trigger_sync(db: Session = Depends(get_db)):
    try:
        result = await symbol_sync.sync_symbols(db)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/stats", response_model=SymbolStats)
def get_stats(db: Session = Depends(get_db)):
    total = db.query(Symbol).count()
    active = db.query(Symbol).filter(Symbol.is_active == True).count()
    margin = db.query(Symbol).filter(and_(Symbol.is_active == True, Symbol.margin_tradable == True)).count()
    futures = db.query(Symbol).filter(and_(Symbol.is_active == True, Symbol.futures_tradable == True)).count()
    both = db.query(Symbol).filter(and_(
        Symbol.is_active == True,
        Symbol.margin_tradable == True,
        Symbol.futures_tradable == True,
    )).count()
    return {
        "total": total,
        "active": active,
        "margin_tradable": margin,
        "futures_tradable": futures,
        "both_tradable": both,
    }
