import asyncio
import json
from decimal import Decimal

import redis
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.db.models import SubAccount, MasterAccount
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from engine.models import Position, TradeLog, EngineState
from engine.schemas import (
    PositionResponse, TradeLogResponse, EngineStateResponse,
    PositionSummary, DashboardResponse, FundingSummary,
    PositionHistoryResponse,
)

router = APIRouter(prefix="/api/engine", tags=["engine"])


class BalanceResponse(BaseModel):
    spot_usdt_free: str = "0"
    spot_usdt_locked: str = "0"
    funding_usdt: str = "0"
    earn_total: str = "0"
    margin_level: str = "0"
    margin_usdt_free: str = "0"
    margin_usdt_borrowed: str = "0"
    futures_total_balance: str = "0"
    futures_available: str = "0"
    futures_unrealized_pnl: str = "0"
    bnb_free: str = "0"
    bnb_interest: str = "0"


class TransferRequest(BaseModel):
    from_wallet: str
    to_wallet: str
    asset: str = "USDT"
    amount: Decimal


def _user_positions(db: Session, user_id: int):
    return db.query(Position).filter(Position.user_id == user_id)


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(
    request: Request,
    sub_account_id: int = Query(None),
    status: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = _user_positions(db, user_id)
    if sub_account_id:
        q = q.filter(Position.sub_account_id == sub_account_id)
    if status:
        q = q.filter(Position.status == status.upper())
    if symbol:
        q = q.filter(Position.symbol == symbol.upper())
    q = q.order_by(Position.id.desc())
    return q.offset((page - 1) * size).limit(size).all()


@router.get("/positions/summary", response_model=PositionSummary)
def positions_summary(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    total_open = _user_positions(db, user_id).filter(Position.status == "OPEN").count()
    total_closed = _user_positions(db, user_id).filter(Position.status == "CLOSED").count()
    total_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.user_id == user_id, Position.status == "CLOSED"
    ).scalar()
    return {
        "total_open": total_open,
        "total_closed": total_closed,
        "total_pnl": Decimal(str(total_pnl)),
    }


@router.get("/positions/{position_id}", response_model=PositionResponse)
def get_position(position_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    pos = _user_positions(db, user_id).filter(Position.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return pos


@router.get("/trade-logs", response_model=list[TradeLogResponse])
def list_trade_logs(
    request: Request,
    sub_account_id: int = Query(None),
    action: str = Query(None),
    position_id: int = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = db.query(TradeLog).filter(TradeLog.user_id == user_id)
    if sub_account_id:
        q = q.filter(TradeLog.sub_account_id == sub_account_id)
    if action:
        q = q.filter(TradeLog.action == action.upper())
    if position_id:
        q = q.filter(TradeLog.position_id == position_id)
    q = q.order_by(TradeLog.id.desc())
    return q.offset((page - 1) * size).limit(size).all()


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    global_state = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope == "global",
    ).first()
    engine_status = global_state.status if global_state else "STOPPED"

    workers = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope != "global",
    ).all()

    total_open = _user_positions(db, user_id).filter(Position.status == "OPEN").count()
    total_closed = _user_positions(db, user_id).filter(Position.status == "CLOSED").count()
    total_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.user_id == user_id, Position.status == "CLOSED"
    ).scalar()

    recent = db.query(TradeLog).filter(TradeLog.user_id == user_id).order_by(TradeLog.id.desc()).limit(10).all()

    open_positions = _user_positions(db, user_id).filter(Position.status == "OPEN").all()
    total_funding = sum(Decimal(str(p.cumulative_funding_fee or 0)) for p in open_positions)
    total_interest = sum(Decimal(str(p.cumulative_interest or 0)) for p in open_positions)
    ratios = [p.funding_rate_ratio for p in open_positions if p.funding_rate_ratio]
    avg_ratio = sum(ratios) / len(ratios) if ratios else None

    return {
        "engine_status": engine_status,
        "workers": workers,
        "positions_summary": {
            "total_open": total_open,
            "total_closed": total_closed,
            "total_pnl": Decimal(str(total_pnl)),
        },
        "funding_summary": {
            "total_funding_fee": total_funding,
            "total_interest": total_interest,
            "avg_funding_ratio": avg_ratio,
            "position_count": len(open_positions),
        },
        "recent_trades": recent,
    }


@router.get("/positions/history", response_model=PositionHistoryResponse)
def positions_history(
    request: Request,
    start_date: str = Query(None),
    end_date: str = Query(None),
    sub_account_id: int = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    user_id = get_current_user_id(request)
    q = _user_positions(db, user_id).filter(Position.status == "CLOSED")
    if sub_account_id:
        q = q.filter(Position.sub_account_id == sub_account_id)
    if start_date:
        q = q.filter(Position.closed_at >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(Position.closed_at <= datetime.fromisoformat(end_date))

    total_q = q
    total_pnl = Decimal(str(db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.id.in_(total_q.with_entities(Position.id))
    ).scalar()))
    total_funding = Decimal(str(db.query(func.coalesce(func.sum(Position.cumulative_funding_fee), 0)).filter(
        Position.id.in_(total_q.with_entities(Position.id))
    ).scalar()))
    total_interest = Decimal(str(db.query(func.coalesce(func.sum(Position.cumulative_interest), 0)).filter(
        Position.id.in_(total_q.with_entities(Position.id))
    ).scalar()))
    count = total_q.count()

    positions = q.order_by(Position.closed_at.desc()).offset((page - 1) * size).limit(size).all()

    return {
        "positions": positions,
        "total_pnl": total_pnl,
        "total_funding_fee": total_funding,
        "total_interest": total_interest,
        "net_pnl": total_pnl + total_funding - total_interest,
        "count": count,
    }


@router.get("/funding-fees")
def funding_fees_summary(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    positions = _user_positions(db, user_id).filter(Position.status == "OPEN").all()
    result = []
    for p in positions:
        result.append({
            "position_id": p.id,
            "symbol": p.symbol,
            "sub_account_id": p.sub_account_id,
            "borrow_qty": str(p.borrow_qty or 0),
            "cumulative_funding_fee": str(p.cumulative_funding_fee or 0),
            "cumulative_interest": str(p.cumulative_interest or 0),
            "funding_rate_ratio": str(p.funding_rate_ratio) if p.funding_rate_ratio else None,
            "opened_at": str(p.opened_at) if p.opened_at else None,
        })
    return result


@router.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
async def get_account_balance(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        spot, margin, futures, funding, earn = await asyncio.gather(
            client.get_spot_account(),
            client.get_margin_account(),
            client.get_futures_account(),
            client.get_funding_account(),
            client.get_simple_earn_account(),
        )

    spot_free = "0"
    spot_locked = "0"
    for a in spot.get("balances", []):
        if a["asset"] == "USDT":
            spot_free = a.get("free", "0")
            spot_locked = a.get("locked", "0")
            break

    funding_usdt = "0"
    for a in (funding if isinstance(funding, list) else []):
        if a.get("asset") == "USDT":
            funding_usdt = a.get("free", "0")
            break

    earn_total = "0"
    if isinstance(earn, dict):
        earn_total = earn.get("totalAmountInUSDT", "0")

    margin_free = "0"
    margin_borrowed = "0"
    bnb_free = "0"
    bnb_interest = "0"
    for a in margin.get("userAssets", []):
        if a["asset"] == "USDT":
            margin_free = a.get("free", "0")
            margin_borrowed = a.get("borrowed", "0")
        elif a["asset"] == "BNB":
            bnb_free = a.get("free", "0")
            bnb_interest = a.get("interest", "0")

    return BalanceResponse(
        spot_usdt_free=spot_free,
        spot_usdt_locked=spot_locked,
        funding_usdt=funding_usdt,
        earn_total=earn_total,
        margin_level=margin.get("marginLevel", "0"),
        margin_usdt_free=margin_free,
        margin_usdt_borrowed=margin_borrowed,
        futures_total_balance=futures.get("totalWalletBalance", "0"),
        futures_available=futures.get("availableBalance", "0"),
        futures_unrealized_pnl=futures.get("totalUnrealizedProfit", "0"),
        bnb_free=bnb_free,
        bnb_interest=bnb_interest,
    )


@router.get("/accounts/{account_id}/max-borrowable/{asset}")
async def get_max_borrowable(account_id: int, asset: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        amount = await client.get_max_borrowable(asset.upper())

    return {"asset": asset.upper(), "max_borrowable": str(amount)}


class TailCleanupRequest(BaseModel):
    max_usdt_amount: Decimal = Decimal("10")


@router.get("/positions/tail")
def list_tail_positions(
    request: Request,
    max_usdt: Decimal = Query(Decimal("10")),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    positions = _user_positions(db, user_id).filter(
        Position.status == "OPEN",
        Position.open_usdt_amount <= max_usdt,
        Position.open_usdt_amount > 0,
    ).all()
    return [
        {
            "id": p.id,
            "symbol": p.symbol,
            "sub_account_id": p.sub_account_id,
            "open_usdt_amount": str(p.open_usdt_amount),
            "borrow_qty": str(p.borrow_qty),
            "opened_at": str(p.opened_at),
        }
        for p in positions
    ]


@router.post("/positions/tail/cleanup")
async def cleanup_tail_positions(
    data: TailCleanupRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    positions = _user_positions(db, user_id).filter(
        Position.status == "OPEN",
        Position.open_usdt_amount <= data.max_usdt_amount,
        Position.open_usdt_amount > 0,
    ).all()

    if not positions:
        return {"message": "No tail positions found", "closed": 0}

    closed = 0
    errors = []
    for pos in positions:
        account = db.query(SubAccount).filter(
            SubAccount.id == pos.sub_account_id, SubAccount.user_id == user_id,
        ).first()
        if not account:
            continue
        try:
            from engine.trading.binance_trading import BinanceTradingClient
            from engine.notify.feishu_sender import FeishuSender
            from engine.trading.order_executor import execute_close
            from engine.spread_feed import SpreadSnapshot

            async with BinanceTradingClient(account.api_key, account.api_secret) as client:
                dummy_spread = SpreadSnapshot(
                    symbol=pos.symbol, spot_bid=0, spot_ask=0,
                    fut_bid=0, fut_ask=0, spread_long=0, spread_short=0, ts=0,
                )
                await execute_close(pos, dummy_spread, client, FeishuSender(), account.note or f"#{account.id}")
                closed += 1
        except Exception as e:
            errors.append(f"{pos.symbol}#{pos.id}: {e}")

    return {
        "message": f"Cleaned up {closed} tail positions",
        "closed": closed,
        "errors": errors,
    }


@router.post("/accounts/{account_id}/transfer")
async def manual_transfer(account_id: int, data: TransferRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.fund.transfer_manager import TRANSFER_TYPES
    key = (data.from_wallet.lower(), data.to_wallet.lower())
    transfer_type = TRANSFER_TYPES.get(key)
    if not transfer_type:
        raise HTTPException(status_code=400, detail=f"Invalid transfer direction: {data.from_wallet} → {data.to_wallet}")

    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        result = await client.transfer(transfer_type, data.asset, data.amount)

    return {"message": f"Transferred {data.amount} {data.asset} from {data.from_wallet} to {data.to_wallet}", "tranId": result.get("tranId")}


class CrossTransferRequest(BaseModel):
    target_type: str
    target_sub_account_id: int | None = None
    asset: str = "USDT"
    amount: Decimal


@router.post("/accounts/{account_id}/transfer-cross")
async def cross_account_transfer(account_id: int, data: CrossTransferRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    from engine.trading.binance_trading import BinanceTradingClient

    if data.target_type == "master":
        async with BinanceTradingClient(account.api_key, account.api_secret) as client:
            result = await client.sub_to_master(data.asset, data.amount)
        return {"message": f"Transferred {data.amount} {data.asset} to master account", "tranId": result.get("tranId")}

    elif data.target_type == "sub":
        if not data.target_sub_account_id:
            raise HTTPException(status_code=400, detail="target_sub_account_id is required for sub-to-sub transfer")
        target = db.query(SubAccount).filter(
            SubAccount.id == data.target_sub_account_id, SubAccount.user_id == user_id,
        ).first()
        if not target:
            raise HTTPException(status_code=404, detail="Target sub-account not found")

        master = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
        if not master:
            raise HTTPException(status_code=400, detail="Master account not configured, required for sub-to-sub transfer")

        async with BinanceTradingClient(master.api_key, master.api_secret) as client:
            result = await client.universal_transfer(
                from_email=account.email,
                to_email=target.email,
                from_account_type="SPOT",
                to_account_type="SPOT",
                asset=data.asset,
                amount=data.amount,
            )
        return {"message": f"Transferred {data.amount} {data.asset} from {account.note} to {target.note}", "tranId": result.get("tranId")}
    else:
        raise HTTPException(status_code=400, detail="Invalid target_type, must be 'master' or 'sub'")


def _redis():
    return redis.from_url(settings.redis_url, decode_responses=True)


def _user_redis_key(user_id: int, key: str) -> str:
    return f"engine:{user_id}:{key}"


@router.get("/pushed-symbols")
def get_pushed_symbols(request: Request):
    user_id = get_current_user_id(request)
    r = _redis()
    raw = r.get(_user_redis_key(user_id, "pushed_symbols"))
    return {"pushed_symbols": json.loads(raw) if raw else []}


@router.post("/push-symbol/{symbol}")
def push_symbol(symbol: str, request: Request):
    user_id = get_current_user_id(request)
    r = _redis()
    sym = symbol.upper()
    key = _user_redis_key(user_id, "push_commands")
    r.rpush(key, json.dumps({"action": "push", "symbol": sym}))
    r.expire(key, 120)
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    raw = r.get(ps_key)
    current = set(json.loads(raw)) if raw else set()
    current.add(sym)
    r.set(ps_key, json.dumps(sorted(current)))
    return {"message": f"Pushed {sym}"}


@router.delete("/push-symbol/{symbol}")
def remove_pushed_symbol(symbol: str, request: Request):
    user_id = get_current_user_id(request)
    r = _redis()
    sym = symbol.upper()
    key = _user_redis_key(user_id, "push_commands")
    r.rpush(key, json.dumps({"action": "remove", "symbol": sym}))
    r.expire(key, 120)
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    raw = r.get(ps_key)
    current = set(json.loads(raw)) if raw else set()
    current.discard(sym)
    r.set(ps_key, json.dumps(sorted(current)))
    return {"message": f"Removed {sym}"}


class PartialRepayRequest(BaseModel):
    sub_account_id: int
    symbol: str
    amount: Decimal


@router.post("/partial-repay")
async def partial_repay(data: PartialRepayRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == data.sub_account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    base_asset = data.symbol.upper().replace("USDT", "")
    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        await client.margin_repay(base_asset, data.amount)

    return {"message": f"Repaid {data.amount} {base_asset} for account {account.note}"}


# ─── Engine Start/Stop Control ───


@router.post("/workers/start")
def start_engine(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    r = _redis()
    r.rpush(f"engine:{user_id}:commands", json.dumps({"action": "start"}))
    r.expire(f"engine:{user_id}:commands", 120)
    state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    if not state:
        state = EngineState(scope="global", user_id=user_id, status="STARTING")
        db.add(state)
    else:
        state.status = "STARTING"
    db.commit()
    return {"message": "Engine start signal sent"}


@router.post("/workers/stop")
def stop_engine(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    r = _redis()
    r.rpush(f"engine:{user_id}:commands", json.dumps({"action": "stop"}))
    r.expire(f"engine:{user_id}:commands", 120)
    state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    if state:
        state.status = "STOPPING"
        db.commit()
    return {"message": "Engine stop signal sent"}


@router.get("/workers/status")
def workers_status(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    workers = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope != "global",
    ).all()
    return {"workers": [EngineStateResponse.model_validate(w) for w in workers]}
