from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Symbol, MasterAccount
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/coins", tags=["coin-management"])


class CoinResponse(BaseModel):
    id: int
    symbol: str
    base_asset: str
    quote_asset: str
    margin_tradable: bool
    futures_tradable: bool
    is_active: bool
    is_new_coin: bool
    is_delisting: bool
    allow_open: bool
    is_risky: bool = False
    volume_24h: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class CoinPatch(BaseModel):
    is_new_coin: Optional[bool] = None
    is_delisting: Optional[bool] = None
    allow_open: Optional[bool] = None
    is_risky: Optional[bool] = None


@router.get("/", response_model=list[CoinResponse])
def list_coins(
    request: Request,
    is_new_coin: Optional[bool] = Query(None),
    is_delisting: Optional[bool] = Query(None),
    is_risky: Optional[bool] = Query(None),
    min_volume: Optional[Decimal] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    get_current_user_id(request)
    q = db.query(Symbol).filter(Symbol.is_active == True)
    if is_new_coin is not None:
        q = q.filter(Symbol.is_new_coin == is_new_coin)
    if is_delisting is not None:
        q = q.filter(Symbol.is_delisting == is_delisting)
    if is_risky is not None:
        q = q.filter(Symbol.is_risky == is_risky)
    if min_volume is not None:
        q = q.filter(Symbol.volume_24h >= min_volume)
    if search:
        q = q.filter(Symbol.symbol.ilike(f"%{search.upper()}%"))
    return q.order_by(Symbol.symbol).all()


@router.post("/{symbol}/mark-new")
def mark_new(symbol: str, request: Request, db: Session = Depends(get_db)):
    get_current_user_id(request)
    sym = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).first()
    if not sym:
        raise HTTPException(status_code=404, detail="Symbol not found")
    sym.is_new_coin = True
    sym.allow_open = False
    db.commit()
    return {"message": f"{symbol.upper()} marked as new coin (allow_open=False)"}


@router.post("/{symbol}/mark-delisting")
def mark_delisting(symbol: str, request: Request, db: Session = Depends(get_db)):
    get_current_user_id(request)
    sym = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).first()
    if not sym:
        raise HTTPException(status_code=404, detail="Symbol not found")
    sym.is_delisting = True
    db.commit()
    return {"message": f"{symbol.upper()} marked as delisting"}


@router.patch("/{symbol}", response_model=CoinResponse)
def patch_coin(symbol: str, data: CoinPatch, request: Request, db: Session = Depends(get_db)):
    get_current_user_id(request)
    sym = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).first()
    if not sym:
        raise HTTPException(status_code=404, detail="Symbol not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(sym, field, value)
    db.commit()
    db.refresh(sym)
    return sym


@router.post("/sync-volume")
async def sync_volume(request: Request, db: Session = Depends(get_db)):
    from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE
    from datetime import datetime, timezone

    user_id = get_current_user_id(request)
    master = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if not master:
        raise HTTPException(status_code=400, detail="Master account not configured")

    async with BinanceTradingClient(master.api_key, master.api_secret) as client:
        tickers = await client._request("GET", f"{SPOT_BASE}/api/v3/ticker/24hr", signed=False)

    updated = 0
    now = datetime.now(timezone.utc)
    ticker_map = {t["symbol"]: Decimal(str(t.get("quoteVolume", "0"))) for t in tickers}

    symbols = db.query(Symbol).filter(Symbol.is_active == True).all()
    for sym in symbols:
        vol = ticker_map.get(sym.symbol)
        if vol is not None:
            sym.volume_24h = vol
            sym.volume_updated_at = now
            updated += 1

    db.commit()
    return {"message": f"Updated volume for {updated} symbols"}
