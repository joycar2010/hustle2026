from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.models import Blacklist
from app.db.schemas.blacklist import BlacklistCreate, BlacklistBulkCreate, BlacklistResponse
from app.db.schemas.common import MessageResponse
from app.db.session import get_db

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])


@router.get("/", response_model=list[BlacklistResponse])
def list_blacklist(db: Session = Depends(get_db)):
    return db.query(Blacklist).order_by(Blacklist.symbol).all()


@router.post("/", response_model=BlacklistResponse, status_code=201)
def add_to_blacklist(data: BlacklistCreate, db: Session = Depends(get_db)):
    item = Blacklist(symbol=data.symbol, reason=data.reason)
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Symbol {data.symbol} already in blacklist")
    return item


@router.delete("/{symbol}", response_model=MessageResponse)
def remove_from_blacklist(symbol: str, db: Session = Depends(get_db)):
    symbol = symbol.upper().strip()
    item = db.query(Blacklist).filter(Blacklist.symbol == symbol).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not in blacklist")
    db.delete(item)
    db.commit()
    return {"message": f"Symbol {symbol} removed from blacklist"}


@router.post("/bulk", response_model=MessageResponse, status_code=201)
def bulk_add_to_blacklist(data: BlacklistBulkCreate, db: Session = Depends(get_db)):
    added = 0
    for sym in data.symbols:
        existing = db.query(Blacklist).filter(Blacklist.symbol == sym).first()
        if not existing:
            db.add(Blacklist(symbol=sym, reason=data.reason))
            added += 1
    db.commit()
    return {"message": f"Added {added} symbols to blacklist (skipped {len(data.symbols) - added} duplicates)"}
