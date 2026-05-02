from fastapi import APIRouter, HTTPException, Query

from app.db.schemas.spread import SpreadData, HealthResponse
from app.services.spread_reader import spread_reader

router = APIRouter(prefix="/api", tags=["spreads"])


@router.get("/spreads", response_model=list[SpreadData])
async def get_all_spreads():
    return spread_reader.get_all()


@router.get("/spreads/top", response_model=list[SpreadData])
async def get_top_spreads(limit: int = Query(default=20, ge=1, le=500)):
    return spread_reader.get_top(limit)


@router.get("/spreads/{symbol}", response_model=SpreadData)
async def get_symbol_spread(symbol: str):
    data = spread_reader.get_symbol(symbol)
    if not data:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return data


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return spread_reader.health()
