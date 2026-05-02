from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.models import Blacklist
from app.db.schemas.blacklist import BlacklistCreate, BlacklistBulkCreate, BlacklistResponse
from app.db.schemas.common import MessageResponse, PaginatedResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])


@router.get("/", response_model=PaginatedResponse[BlacklistResponse])
def list_blacklist(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = db.query(Blacklist).filter(Blacklist.user_id == user_id)
    if search:
        q = q.filter(Blacklist.symbol.ilike(f"%{search.upper()}%"))
    total = q.count()
    items = q.order_by(Blacklist.symbol).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/", response_model=BlacklistResponse, status_code=201)
def add_to_blacklist(data: BlacklistCreate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    existing = db.query(Blacklist).filter(
        Blacklist.user_id == user_id,
        Blacklist.symbol == data.symbol,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Symbol {data.symbol} already in blacklist")

    item = Blacklist(user_id=user_id, symbol=data.symbol, reason=data.reason)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{symbol}", response_model=MessageResponse)
def remove_from_blacklist(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    symbol = symbol.upper().strip()
    item = db.query(Blacklist).filter(
        Blacklist.user_id == user_id,
        Blacklist.symbol == symbol,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not in blacklist")
    db.delete(item)
    db.commit()
    return {"message": f"Symbol {symbol} removed from blacklist"}


@router.post("/bulk", response_model=MessageResponse, status_code=201)
def bulk_add_to_blacklist(data: BlacklistBulkCreate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    added = 0
    for sym in data.symbols:
        existing = db.query(Blacklist).filter(
            Blacklist.user_id == user_id,
            Blacklist.symbol == sym,
        ).first()
        if not existing:
            db.add(Blacklist(user_id=user_id, symbol=sym, reason=data.reason))
            added += 1
    db.commit()
    return {"message": f"Added {added} symbols to blacklist (skipped {len(data.symbols) - added} duplicates)"}
