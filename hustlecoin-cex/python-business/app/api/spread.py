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


def _no_inventory_symbols() -> set[str]:
    """无券币(借币 -3045 写入 engine:noinv:*,全局=币安杠杆池级别)。/spreads 利差监控排除:
    无券币常因被抢空而点差虚高,显示出来也借不到,徒占榜首。"""
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        keys = rc.keys("engine:noinv:*")
        rc.close()
        return {k.split("engine:noinv:", 1)[1].upper() for k in keys}
    except Exception:
        return set()


@router.get("/spreads", response_model=list[SpreadData])
async def get_all_spreads(request: Request, db: Session = Depends(get_db)):
    bl = _blacklist_symbols(db, request) | _no_inventory_symbols()
    items = [d for d in spread_reader.get_all() if d.symbol.upper() not in bl]
    # 有券币按点差(取多/空较大方向)从高到低排序
    items.sort(key=lambda x: max(abs(x.spread_long), abs(x.spread_short)), reverse=True)
    return items


@router.get("/spreads/top", response_model=list[SpreadData])
async def get_top_spreads(request: Request, limit: int = Query(default=20, ge=1, le=500),
                          db: Session = Depends(get_db)):
    bl = _blacklist_symbols(db, request) | _no_inventory_symbols()
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
