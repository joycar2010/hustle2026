from fastapi import APIRouter, HTTPException, Query, Request, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Blacklist, CustomMonitorSymbol
from app.db.schemas.spread import SpreadData, HealthResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services.custom_monitor_feed import custom_monitor_feed
from app.services.spread_reader import spread_reader

router = APIRouter(prefix="/api", tags=["spreads"])


def _spread_score(item: SpreadData) -> float:
    values = (item.spread_long, item.spread_short)
    return max(
        (abs(float(value)) for value in values if value is not None),
        default=0.0,
    )


def _custom_monitor_rows(
    db: Session,
    user_id: int | None,
) -> list[SpreadData]:
    """Build pinned, display-only rows from this tenant's private feed."""

    if user_id is None:
        return []
    rows = db.query(CustomMonitorSymbol).filter(
        CustomMonitorSymbol.user_id == user_id,
        CustomMonitorSymbol.is_active.is_(True),
        CustomMonitorSymbol.is_removed.is_(False),
    ).order_by(CustomMonitorSymbol.sort_order, CustomMonitorSymbol.id).all()
    snapshots = custom_monitor_feed.get_user_snapshots(user_id)
    result: list[SpreadData] = []
    for monitor in rows:
        spot = str(monitor.spot_symbol).upper()
        futures = str(monitor.futures_symbol).upper()
        display = monitor.display_symbol or spot.removesuffix("USDT")
        source = snapshots.get(int(monitor.id))
        if source is not None and (
            source.spot_symbol != spot or source.futures_symbol != futures
        ):
            source = None
        if source is not None:
            payload = source.model_dump()
            payload.update({
                "symbol": display,
                "spot_symbol": spot,
                "futures_symbol": futures,
                "custom_monitor_id": monitor.id,
                "is_custom": True,
                "data_status": "LIVE",
                "execution_eligible": False,
            })
            result.append(SpreadData(**payload))
            continue
        result.append(SpreadData(
            symbol=display,
            ts=0,
            spot_symbol=spot,
            futures_symbol=futures,
            custom_monitor_id=monitor.id,
            is_custom=True,
            data_status="WAITING_DATA",
            execution_eligible=False,
        ))
    return result


def _custom_monitor_id(item: SpreadData) -> int | None:
    if item.custom_monitor_id is not None:
        return int(item.custom_monitor_id)
    if item.is_custom or str(item.symbol).upper().startswith("CUSTOM:"):
        try:
            return int(str(item.symbol).split(":", 1)[1])
        except (TypeError, ValueError, IndexError):
            return None
    return None


def _visible_spreads(request: Request, db: Session, limit: int | None = None) -> list[SpreadData]:
    """Merge private monitor rows without widening the execution universe."""

    user_id = getattr(request.state, "user_id", None)
    blocked = _blacklist_symbols(db, request)
    universe = _universe_symbols()
    public_rows = []
    for item in spread_reader.get_all():
        # Drop any private/legacy payload found in the public execution hash.
        if _custom_monitor_id(item) is not None or item.is_custom:
            continue
        symbol = item.symbol.upper()
        if symbol not in blocked and (universe is None or symbol in universe):
            public_rows.append(item)
    public_rows.sort(key=_spread_score, reverse=True)
    result = _custom_monitor_rows(db, user_id) + public_rows
    return result if limit is None else result[:limit]


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


def _universe_symbols() -> set[str] | None:
    """币安在交易白名单 engine:universe(现货∩合约 status==TRADING 的 USDT 对,
    由 market_data_pusher 随上/退市动态刷新)。退市/单腿下架的币会自动移出该集 →
    据此在监控第一步剔除,无需人工拉黑名单。返回 None 表示集不可用(Redis 异常/空),
    此时调用方应跳过白名单过滤,避免 exchangeInfo 抖动误清空整表。"""
    try:
        import json as _j
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        raw = rc.get("engine:universe")
        rc.close()
        if not raw:
            return None
        parsed = _j.loads(raw)
        if not isinstance(parsed, list):
            return None
        # An explicitly published empty universe is an authoritative
        # fail-closed state, distinct from a missing Redis key/error.
        return {str(s).upper() for s in parsed if str(s).strip()}
    except Exception:
        return None


@router.get("/spreads", response_model=list[SpreadData])
async def get_all_spreads(request: Request, db: Session = Depends(get_db)):
    # A borrow inventory miss is account-scoped, while this endpoint is a
    # market signal feed.  Do not hide the spread for every operator/account;
    # the C3 account-facts endpoint reports the executable account state.
    return _visible_spreads(request, db)


@router.get("/spreads/top", response_model=list[SpreadData])
async def get_top_spreads(request: Request, limit: int = Query(default=20, ge=1, le=500),
                          db: Session = Depends(get_db)):
    return _visible_spreads(request, db, limit=limit)


@router.get("/spreads/{symbol}", response_model=SpreadData)
async def get_symbol_spread(
    symbol: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    requested_custom_id = None
    data = None
    if str(symbol).upper().startswith("CUSTOM:"):
        try:
            requested_custom_id = int(str(symbol).split(":", 1)[1])
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        data = custom_monitor_feed.get_snapshot(user_id, requested_custom_id)
    else:
        data = spread_reader.get_symbol(symbol)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    custom_id = data.custom_monitor_id or requested_custom_id
    if data.is_custom and custom_id is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    if custom_id is not None:
        owned = db.query(CustomMonitorSymbol.id).filter(
            CustomMonitorSymbol.id == custom_id,
            CustomMonitorSymbol.user_id == user_id,
            CustomMonitorSymbol.is_active.is_(True),
            CustomMonitorSymbol.is_removed.is_(False),
        ).first()
        if owned is None:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return data


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return spread_reader.health()
