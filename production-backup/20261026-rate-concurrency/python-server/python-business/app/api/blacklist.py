from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.models import Blacklist, Symbol
from app.db.schemas.blacklist import BlacklistCreate, BlacklistBulkCreate, BlacklistResponse
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])

# 黑名单用户隔离:个人黑名单 user_id=登录用户;全局系统黑名单 user_id IS NULL
# (引擎自动加的死币/持续无券,对所有用户生效)。读=本人 ∪ 全局,与
# config_loader / spread.py / websocket.py 三处口径一致。手动增删只作用于本人,
# 用户不能删全局系统条目或他人条目。


@router.get("/", response_model=list[BlacklistResponse])
def list_blacklist(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    # 本人 ∪ 全局(NULL):即引擎对该用户实际生效的黑名单集合
    items = (
        db.query(Blacklist)
        .filter(or_(Blacklist.user_id == uid, Blacklist.user_id.is_(None)))
        .order_by(Blacklist.symbol)
        .all()
    )
    # 历史版本退市扫描只写 symbols.is_delisting，未必同步写入 blacklist。
    # 补成只读系统条目，让黑名单页与交易闸门一致；临时陈旧/无券不会进入这里。
    known = {item.symbol.upper() for item in items if item.symbol}
    for symbol in db.query(Symbol).filter(Symbol.is_delisting.is_(True)).order_by(Symbol.symbol).all():
        name = (symbol.symbol or '').upper().strip()
        if not name or name in known:
            continue
        items.append({
            'id': -int(symbol.id),
            'symbol': name,
            'reason': '已确认退市（Binance）',
            'created_at': symbol.updated_at or symbol.created_at or datetime.now(timezone.utc),
            'user_id': None,
        })
        known.add(name)
    items.sort(key=lambda item: item.symbol if hasattr(item, 'symbol') else item['symbol'])
    return items


@router.post("/", response_model=BlacklistResponse, status_code=201)
def add_to_blacklist(data: BlacklistCreate, request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    item = Blacklist(symbol=data.symbol, reason=data.reason, user_id=uid)
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Symbol {data.symbol} already in blacklist")
    return item


@router.delete("/{symbol}", response_model=MessageResponse)
def remove_from_blacklist(symbol: str, request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    symbol = symbol.upper().strip()
    # 只允许删本人条目;全局系统条目(NULL)由引擎自动管理,用户不可在此删除
    item = db.query(Blacklist).filter(
        Blacklist.symbol == symbol, Blacklist.user_id == uid
    ).first()
    if not item:
        # 区分:符号属全局系统黑名单 vs 根本不在黑名单
        is_global = db.query(Blacklist).filter(
            Blacklist.symbol == symbol, Blacklist.user_id.is_(None)
        ).first() is not None
        if is_global:
            raise HTTPException(status_code=403, detail=f"{symbol} 为系统全局黑名单,不可删除")
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not in blacklist")
    db.delete(item)
    db.commit()
    return {"message": f"Symbol {symbol} removed from blacklist"}


@router.post("/bulk", response_model=MessageResponse, status_code=201)
def bulk_add_to_blacklist(data: BlacklistBulkCreate, request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    added = 0
    for sym in data.symbols:
        # 已是本人或全局条目则跳过(避免重复 / 与全局重复拉黑)
        existing = db.query(Blacklist).filter(
            Blacklist.symbol == sym,
            or_(Blacklist.user_id == uid, Blacklist.user_id.is_(None)),
        ).first()
        if not existing:
            db.add(Blacklist(symbol=sym, reason=data.reason, user_id=uid))
            added += 1
    db.commit()
    return {"message": f"Added {added} symbols to blacklist (skipped {len(data.symbols) - added} duplicates)"}
