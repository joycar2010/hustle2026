from fastapi import APIRouter, HTTPException, Query, Request, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Blacklist
from app.db.schemas.spread import SpreadData, HealthResponse
from app.db.session import get_db
from app.services.spread_reader import spread_reader

router = APIRouter(prefix="/api", tags=["spreads"])


def _blacklist_symbols(db: Session, request: Request) -> set[str]:
    """本用户黑名单 ∪ 全局系统黑名单(user_id IS NULL,如死币 HOMEUSDT)。利差监控据此排除。"""
    uid = getattr(request.state, "user_id", None)
    q = db.query(Blacklist.symbol)
    if uid is not None:
        q = q.filter(or_(Blacklist.user_id == uid, Blacklist.user_id.is_(None)))
    else:
        q = q.filter(Blacklist.user_id.is_(None))
    return {s[0].upper() for s in q.all() if s[0]}


@router.get("/spreads", response_model=list[SpreadData])
async def get_all_spreads(request: Request, db: Session = Depends(get_db)):
    bl = _blacklist_symbols(db, request)
    return [d for d in spread_reader.get_all() if d.symbol.upper() not in bl]


@router.get("/spreads/top", response_model=list[SpreadData])
async def get_top_spreads(request: Request, limit: int = Query(default=20, ge=1, le=500),
                          db: Session = Depends(get_db)):
    bl = _blacklist_symbols(db, request)
    items = [d for d in spread_reader.get_all() if d.symbol.upper() not in bl]
    items.sort(key=lambda x: max(abs(x.spread_long), abs(x.spread_short)), reverse=True)
    return items[:limit]


@router.get("/spreads/{symbol}", response_model=SpreadData)
async def get_symbol_spread(symbol: str):
    data = spread_reader.get_symbol(symbol)
    if not data:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return data


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return spread_reader.health()
