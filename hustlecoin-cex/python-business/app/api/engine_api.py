import asyncio
import json
import time
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
    PositionHistoryResponse, HealthResponse, WorkerHealth,
    StuckPosition, APIMetricsResponse,
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
        st = status.upper()
        if st == "ACTIVE":
            # dashboard-visible live states: hedged + borrowed-idle + pending-repay
            q = q.filter(Position.status.in_(["OPEN", "BORROWED_IDLE", "PENDING_REPAY"]))
        else:
            q = q.filter(Position.status == st)
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


@router.get("/positions/{position_id:int}", response_model=PositionResponse)
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

    # 仅当前存在子账户对应的 worker(过滤已删账户残留行;顶栏「引擎 X/Y」分母据此)
    _scopes = _live_worker_scopes(db, user_id)
    workers = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope.in_(_scopes),
    ).all() if _scopes else []

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


@router.get("/accounts/{account_id}/loan-history")
async def get_loan_history(
    account_id: int,
    request: Request,
    type: str = Query("BORROW"),
    asset: str = Query(None),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """币安全仓 借/还/利息 原始流水(对账用)。type=BORROW/REPAY/INTEREST。"""
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
    t = (type or "BORROW").upper()
    a = asset.upper() if asset else None
    try:
        async with BinanceTradingClient(account.api_key, account.api_secret) as client:
            if t == "INTEREST":
                data = await client.get_interest_history(asset=a, size=size)
            else:
                data = await client.get_loan_records(txn_type=t, asset=a, size=size)
    except BinanceAPIError as e:
        raise HTTPException(status_code=400, detail=f"查询失败: {e.message}")
    return {"type": t, "rows": data.get("rows", []), "total": data.get("total", 0)}


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
            from contextlib import AsyncExitStack
            from engine.trading.binance_trading import BinanceTradingClient
            from engine.notify.feishu_sender import FeishuSender
            from engine.trading.order_executor import execute_close
            from engine.spread_feed import SpreadSnapshot

            master = None
            if getattr(pos, "hedge_account", None) == "master":
                master = _load_master_account(db, user_id)
                if not master:
                    errors.append(f"{pos.symbol}#{pos.id}: 合约腿在主账户但主账户未配置")
                    continue

            async with AsyncExitStack() as stack:
                client = await stack.enter_async_context(
                    BinanceTradingClient(account.api_key, account.api_secret))
                fc = None
                if master:
                    fc = await stack.enter_async_context(BinanceTradingClient(
                        master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
                    await _assert_master_one_way(fc)
                dummy_spread = SpreadSnapshot(
                    symbol=pos.symbol, spot_bid=0, spot_ask=0,
                    fut_bid=0, fut_ask=0, spread_long=0, spread_short=0, ts=0,
                )
                await execute_close(pos, dummy_spread, client, FeishuSender(),
                                    account.note or f"#{account.id}", futures_client=fc)
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


# 钱包 → 币安万向划转账户类型
_UT_ACCT_TYPE = {"spot": "SPOT", "futures": "USDT_FUTURE", "margin": "MARGIN"}


class CrossTransferRequest(BaseModel):
    asset: str = "USDT"
    amount: Decimal
    direction: str = "out"            # out=本账户(account_id)转出, in=本账户转入
    counterparty_type: str = "master"  # master | sub
    counterparty_sub_account_id: int | None = None
    from_wallet: str = "spot"          # spot | futures | margin
    to_wallet: str = "spot"
    # 旧字段兼容(原仅支持 本账户→master / 本账户→sub)
    target_type: str | None = None
    target_sub_account_id: int | None = None


@router.post("/accounts/{account_id}/transfer-cross")
async def cross_account_transfer(account_id: int, data: CrossTransferRequest, request: Request, db: Session = Depends(get_db)):
    """主/子账户互转(master↔sub、sub↔sub)。一律用【主账户】key 调 universalTransfer:
    direction=out 本账户转出, in 本账户转入;对手方 master(email 省略)或另一子账户。"""
    user_id = get_current_user_id(request)
    anchor = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not anchor:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    cp_type = data.counterparty_type or data.target_type or "master"
    cp_sub_id = data.counterparty_sub_account_id or data.target_sub_account_id
    if cp_type not in ("master", "sub"):
        raise HTTPException(status_code=400, detail="counterparty_type 必须是 master 或 sub")
    if data.direction not in ("out", "in"):
        raise HTTPException(status_code=400, detail="direction 必须是 out 或 in")

    # universalTransfer 是主账户专属端点,任何方向都用主账户 key
    master = _load_master_account(db, user_id)
    if not master:
        raise HTTPException(status_code=400, detail="主账户未配置,无法跨账户划转")

    # 对手方 email(master → None 省略表示主账户)+ 标签
    if cp_type == "master":
        cp_email, cp_label = None, "主账户"
    else:
        if not cp_sub_id:
            raise HTTPException(status_code=400, detail="子↔子划转需指定对手子账户")
        cp = db.query(SubAccount).filter(
            SubAccount.id == cp_sub_id, SubAccount.user_id == user_id,
        ).first()
        if not cp:
            raise HTTPException(status_code=404, detail="对手子账户不存在")
        cp_email, cp_label = cp.email, (cp.note or f"#{cp.id}")

    from_acct = _UT_ACCT_TYPE.get((data.from_wallet or "spot").lower(), "SPOT")
    to_acct = _UT_ACCT_TYPE.get((data.to_wallet or "spot").lower(), "SPOT")

    # from_wallet/to_wallet 恒指实际转账的「源钱包/目标钱包」(与方向无关)
    if data.direction == "out":      # 本账户 → 对手方
        from_email, to_email = anchor.email, cp_email
        src_label, dst_label = (anchor.note or f"#{anchor.id}"), cp_label
    else:                            # 对手方 → 本账户
        from_email, to_email = cp_email, anchor.email
        src_label, dst_label = cp_label, (anchor.note or f"#{anchor.id}")

    if from_email == to_email:
        raise HTTPException(status_code=400, detail="源账户与目标账户不能相同")

    from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
    try:
        async with BinanceTradingClient(master.api_key, master.api_secret) as client:
            result = await client.universal_transfer(
                asset=data.asset, amount=data.amount,
                from_account_type=from_acct, to_account_type=to_acct,
                from_email=from_email, to_email=to_email,
            )
    except BinanceAPIError as e:
        raise HTTPException(status_code=400, detail=f"划转失败: {e.message}")
    return {
        "message": f"已划转 {data.amount} {data.asset}: {src_label} → {dst_label}",
        "tranId": result.get("tranId"),
    }


def _redis():
    return redis.from_url(settings.redis_url, decode_responses=True)


def _user_redis_key(user_id: int, key: str) -> str:
    return f"engine:{user_id}:{key}"


@router.get("/pushed-symbols")
def get_pushed_symbols(request: Request):
    user_id = get_current_user_id(request)
    r = _redis()
    raw = r.get(_user_redis_key(user_id, "pushed_symbols"))
    pushed = json.loads(raw) if raw else []
    # 推送时间戳(engine:{uid}:pushed_at,symbol→unix秒)统一在此回填/清理:
    # 覆盖手动 push(API 已记)与引擎自动推送(此处首次见到即补 now);移除的清掉。
    at_key = _user_redis_key(user_id, "pushed_at")
    try:
        at = r.hgetall(at_key) or {}
        now = int(time.time())
        miss = [s for s in pushed if s not in at]
        if miss:
            r.hset(at_key, mapping={s: now for s in miss})
            for s in miss:
                at[s] = str(now)
        stale = [s for s in at.keys() if s not in pushed]
        if stale:
            r.hdel(at_key, *stale)
        pushed_at = {s: int(at[s]) for s in pushed if s in at}
    except Exception:
        pushed_at = {}
    return {"pushed_symbols": pushed, "pushed_at": pushed_at}


@router.post("/push-symbol/{symbol}")
def push_symbol(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    r = _redis()
    sym = symbol.upper().strip()
    if not sym.endswith("USDT"):
        sym = f"{sym}USDT"
    # 校验:必须是可交易币种(在 symbols 表且 active/margin/futures)且有点差,
    # 否则推送进去也借不了、看不到数据,徒增「无法推送」困惑。
    from app.db.models import Symbol
    s = db.query(Symbol).filter(Symbol.symbol == sym).first()
    if not s or not (s.is_active and s.margin_tradable and s.futures_tradable):
        raise HTTPException(status_code=400, detail=f"{sym} 不可交易(非借币/合约支持的 USDT 交易对)")
    key = _user_redis_key(user_id, "push_commands")
    r.rpush(key, json.dumps({"action": "push", "symbol": sym}))
    r.expire(key, 120)
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    raw = r.get(ps_key)
    current = set(json.loads(raw)) if raw else set()
    current.add(sym)
    r.set(ps_key, json.dumps(sorted(current)))
    r.hsetnx(_user_redis_key(user_id, "pushed_at"), sym, int(time.time()))  # 记首次推送时刻(已存在不覆盖)
    # 通知前端 dashboard 实时刷新推送列表(经 WS pushed_update)
    r.publish("pushed:updates", json.dumps({"user_id": user_id, "pushed_symbols": sorted(current)}))
    return {"message": f"Pushed {sym}"}


@router.delete("/push-symbol/{symbol}")
def remove_pushed_symbol(symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    sym = symbol.upper()

    sub_ids = [s.id for s in db.query(SubAccount.id).filter(SubAccount.user_id == user_id).all()]
    if sub_ids:
        open_count = db.query(Position).filter(
            Position.sub_account_id.in_(sub_ids),
            Position.symbol == sym,
            Position.status == "OPEN",
        ).count()
        if open_count > 0:
            raise HTTPException(status_code=409, detail=f"无法移除 {sym}：仍有 {open_count} 个持仓未平")

    r = _redis()
    key = _user_redis_key(user_id, "push_commands")
    r.rpush(key, json.dumps({"action": "remove", "symbol": sym}))
    r.expire(key, 120)
    ps_key = _user_redis_key(user_id, "pushed_symbols")
    raw = r.get(ps_key)
    current = set(json.loads(raw)) if raw else set()
    current.discard(sym)
    r.set(ps_key, json.dumps(sorted(current)))
    r.hdel(_user_redis_key(user_id, "pushed_at"), sym)  # 清推送时间戳
    r.publish("pushed:updates", json.dumps({"user_id": user_id, "pushed_symbols": sorted(current)}))

    # 移除即清该币的单一规则覆盖(SymbolRule + AccountSymbolRule)→ 再推进来回归全局参数。
    # 与"移除保留规则"的旧行为相反,按用户诉求改:删除而非保留。无持仓时才会走到这(上方已校验)。
    try:
        from app.db.models import SymbolRule, AccountSymbolRule
        db.query(SymbolRule).filter(
            SymbolRule.user_id == user_id, SymbolRule.symbol == sym,
        ).delete(synchronize_session=False)
        if sub_ids:
            db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id.in_(sub_ids), AccountSymbolRule.symbol == sym,
            ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
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


# ─── Manual Open / Close (executed API-side, works regardless of engine state) ───


def _build_spread_snapshot(symbol: str):
    """Build a SpreadSnapshot from the Redis spreads hash for manual execution."""
    from engine.spread_feed import SpreadSnapshot
    raw = _redis().hget("spreads", symbol)
    if not raw:
        return None
    p = json.loads(raw)
    return SpreadSnapshot(
        symbol=p["symbol"],
        spot_bid=Decimal(str(p["spot_bid"])),
        spot_ask=Decimal(str(p["spot_ask"])),
        fut_bid=Decimal(str(p["fut_bid"])),
        fut_ask=Decimal(str(p["fut_ask"])),
        spread_long=Decimal(str(p["spread_long"])),
        spread_short=Decimal(str(p["spread_short"])),
        ts=p["ts"],
    )


def _load_global_rules_snapshot(db: Session, user_id: int):
    from app.db.models import GlobalRules
    from engine.config_loader import GlobalRulesSnapshot, DEFAULT_GLOBAL
    rules = (db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
             or db.query(GlobalRules).first())
    if not rules:
        return DEFAULT_GLOBAL
    return GlobalRulesSnapshot(
        auto_push_spread=rules.auto_push_spread,
        remove_spread=rules.remove_spread,
        open_spread=rules.open_spread,
        close_spread=rules.close_spread,
        order_amount=rules.order_amount,
        close_funding_ratio=rules.close_funding_ratio,
        repay_funding_ratio=rules.repay_funding_ratio,
        borrow_delay_sec=rules.borrow_delay_sec,
        confirm_delay_sec=rules.confirm_delay_sec,
        confirm_skip_spread=rules.confirm_skip_spread,
        repay_ban_minutes=rules.repay_ban_minutes,
        interest_filter=rules.interest_filter,
        max_positions=rules.max_positions or 10,
        auto_start_on_boot=bool(rules.auto_start_on_boot),
        futures_liquidation_threshold=rules.futures_liquidation_threshold,
        repay_spread=rules.repay_spread,
        max_daily_interest_rate=rules.max_daily_interest_rate,
        slippage_pct=getattr(rules, "slippage_pct", None) or Decimal("0.1"),
        follow_type=getattr(rules, "follow_type", None) or "market",
        stabilize_sec=getattr(rules, "stabilize_sec", None) or Decimal("0"),
        tier_ratios=getattr(rules, "tier_ratios", None) or "",
        borrow_spread=getattr(rules, "borrow_spread", None) if getattr(rules, "borrow_spread", None) is not None else Decimal("0.5"),
        borrow_rate_per_sec=getattr(rules, "borrow_rate_per_sec", None) if getattr(rules, "borrow_rate_per_sec", None) is not None else Decimal("2"),
        borrow_via_otoco=bool(getattr(rules, "borrow_via_otoco", False)),
        otoco_legs=int(getattr(rules, "otoco_legs", 2) or 2),
        hedge_via_master=bool(getattr(rules, "hedge_via_master", False)),
    )


def _load_master_account(db: Session, user_id: int):
    """user_id 行优先;兼容历史 upsert 不写 user_id 的 NULL 行。"""
    return (db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
            or db.query(MasterAccount).filter(MasterAccount.user_id.is_(None)).first()
            or db.query(MasterAccount).first())


async def _assert_master_one_way(fc):
    """主账户必须单向持仓 —— 下单不带 positionSide,双向模式会先卖现货再 -4061 回滚。
    引擎进程的 master_client 注册表在创建时断言;API 进程直建 client 须同样校验。"""
    if await fc.get_position_mode():
        raise ValueError("主账户处于双向持仓模式,请先在币安合约设置切回单向持仓")


class ManualOpenRequest(BaseModel):
    sub_account_id: int
    symbol: str
    order_amount: Decimal | None = None  # override global order_amount for this open


@router.post("/manual-open")
async def manual_open(data: ManualOpenRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = db.query(SubAccount).filter(
        SubAccount.id == data.sub_account_id, SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    if not account.is_enabled:
        raise HTTPException(status_code=400, detail="账户已禁用，无法开仓")

    symbol = data.symbol.upper()
    spread = _build_spread_snapshot(symbol)
    if not spread:
        raise HTTPException(status_code=400, detail=f"无 {symbol} 行情数据，无法开仓")

    import dataclasses
    rules = _load_global_rules_snapshot(db, user_id)
    if data.order_amount and data.order_amount > 0:
        rules = dataclasses.replace(rules, order_amount=data.order_amount)

    master = None
    if getattr(rules, "hedge_via_master", False):
        master = _load_master_account(db, user_id)
        if not master:
            raise HTTPException(status_code=400, detail="已开启主账户对冲,但主账户未配置")

    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_open
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(BinanceTradingClient(
                account.api_key, account.api_secret, sub_account_id=account.id))
            fc = None
            if master:
                fc = await stack.enter_async_context(BinanceTradingClient(
                    master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
            # spread_feed=None → skip the post-delay re-confirm; manual open forces
            # at the current spread (interest-rate filter still applies).
            await execute_open(
                account.id, symbol, spread, rules, client, notifier, account.note,
                spread_feed=None, futures_client=fc, user_id=user_id,
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"开仓失败: {e}")

    latest = db.query(Position).filter(
        Position.sub_account_id == account.id, Position.symbol == symbol,
    ).order_by(Position.id.desc()).first()
    if latest and latest.status == "OPEN":
        return {"message": f"开仓成功 {symbol} @ {account.note}", "position_id": latest.id, "status": "OPEN"}
    detail = latest.error_message if latest else "未知错误"
    return {"message": f"开仓未完成 {symbol}: {detail}", "status": latest.status if latest else "FAILED"}


class ManualCloseRequest(BaseModel):
    position_id: int


@router.post("/manual-close")
async def manual_close(data: ManualCloseRequest, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    position = db.query(Position).filter(
        Position.id == data.position_id, Position.user_id == user_id,
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "OPEN":
        raise HTTPException(status_code=400, detail=f"持仓状态为 {position.status}，无法平仓")

    account = db.query(SubAccount).filter(SubAccount.id == position.sub_account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    spread = _build_spread_snapshot(position.symbol)
    if not spread:
        # Close still works without live spread; use zeros only for the recorded close_spread.
        from engine.spread_feed import SpreadSnapshot
        spread = SpreadSnapshot(position.symbol, Decimal("0"), Decimal("0"),
                                Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), 0)

    master = None
    if getattr(position, "hedge_account", None) == "master":
        master = _load_master_account(db, user_id)
        if not master:
            raise HTTPException(status_code=400, detail="该持仓合约腿在主账户,但主账户未配置")

    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_close
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(BinanceTradingClient(
                account.api_key, account.api_secret, sub_account_id=account.id))
            fc = None
            if master:
                fc = await stack.enter_async_context(BinanceTradingClient(
                    master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
            await execute_close(position, spread, client, notifier, account.note,
                                futures_client=fc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"平仓失败: {e}")

    db.refresh(position)
    return {"message": f"平仓完成 {position.symbol}", "status": position.status,
            "realized_pnl": str(position.realized_pnl or 0)}


class ManualPositionRequest(BaseModel):
    position_id: int


@router.post("/manual-hedge")
async def manual_hedge(data: ManualPositionRequest, request: Request, db: Session = Depends(get_db)):
    """手动对冲：把 BORROWED_IDLE 持仓卖现货+合约跟多 → OPEN。"""
    user_id = get_current_user_id(request)
    position = db.query(Position).filter(
        Position.id == data.position_id, Position.user_id == user_id,
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "BORROWED_IDLE":
        raise HTTPException(status_code=400, detail=f"持仓状态为 {position.status}，无法对冲")
    account = db.query(SubAccount).filter(SubAccount.id == position.sub_account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    spread = _build_spread_snapshot(position.symbol)
    if not spread:
        raise HTTPException(status_code=400, detail=f"无 {position.symbol} 行情数据，无法对冲")
    rules = _load_global_rules_snapshot(db, user_id)
    master = None
    if getattr(rules, "hedge_via_master", False):
        master = _load_master_account(db, user_id)
        if not master:
            raise HTTPException(status_code=400, detail="已开启主账户对冲,但主账户未配置")

    from contextlib import AsyncExitStack
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_hedge
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(BinanceTradingClient(
                account.api_key, account.api_secret, sub_account_id=account.id))
            fc = None
            if master:
                fc = await stack.enter_async_context(BinanceTradingClient(
                    master.api_key, master.api_secret, sub_account_id=-(user_id or 1)))
            await execute_hedge(position, spread, rules, client, notifier, account.note,
                                futures_client=fc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"对冲失败: {e}")
    db.refresh(position)
    return {"message": f"对冲完成 {position.symbol}", "status": position.status}


@router.post("/manual-repay")
async def manual_repay(data: ManualPositionRequest, request: Request, db: Session = Depends(get_db)):
    """手动还币：把 PENDING_REPAY 持仓的杠杆负债还清 → CLOSED。"""
    user_id = get_current_user_id(request)
    position = db.query(Position).filter(
        Position.id == data.position_id, Position.user_id == user_id,
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "PENDING_REPAY":
        raise HTTPException(status_code=400, detail=f"持仓状态为 {position.status}，无法还币")
    account = db.query(SubAccount).filter(SubAccount.id == position.sub_account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.order_executor import execute_repay
    from engine.notify.feishu_sender import FeishuSender
    notifier = FeishuSender()
    try:
        async with BinanceTradingClient(account.api_key, account.api_secret,
                                        sub_account_id=account.id) as client:
            await execute_repay(position, client, notifier, account.note)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"还币失败: {e}")
    db.refresh(position)
    return {"message": f"还币完成 {position.symbol}", "status": position.status,
            "realized_pnl": str(position.realized_pnl or 0)}


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


def _owned_sub(db: Session, user_id: int, account_id: int) -> SubAccount:
    acc = db.query(SubAccount).filter(
        SubAccount.id == account_id, SubAccount.user_id == user_id,
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return acc


@router.post("/workers/{account_id}/restart")
def restart_one_worker(account_id: int, request: Request, db: Session = Depends(get_db)):
    """单独重启某子账户的 worker(卡死/心跳超时时无需整体停启)。经 Redis 命令 →
    orchestrator.restart_worker 取消并重建该 task,其余 worker 不动。"""
    user_id = get_current_user_id(request)
    _owned_sub(db, user_id, account_id)
    r = _redis()
    r.rpush(f"engine:{user_id}:commands", json.dumps({"action": "restart_worker", "account_id": account_id}))
    r.expire(f"engine:{user_id}:commands", 120)
    return {"message": f"worker #{account_id} 重启信号已发送"}


@router.post("/workers/{account_id}/stop")
def stop_one_worker(account_id: int, request: Request, db: Session = Depends(get_db)):
    """停用单个 worker = 禁用该子账户(is_enabled=False);orchestrator 下轮对账停其 worker。
    注:若该账户尚有在场持仓,worker 会被保留以管理平仓/还币(不会孤儿化),属预期安全行为。"""
    user_id = get_current_user_id(request)
    acc = _owned_sub(db, user_id, account_id)
    acc.is_enabled = False
    db.commit()
    return {"message": f"worker #{account_id} 已停用(约10s内生效;有在场持仓则保留至平仓)"}


@router.post("/workers/{account_id}/start")
def start_one_worker(account_id: int, request: Request, db: Session = Depends(get_db)):
    """启用单个 worker = 启用该子账户(is_enabled=True);orchestrator 下轮对账拉起。"""
    user_id = get_current_user_id(request)
    acc = _owned_sub(db, user_id, account_id)
    acc.is_enabled = True
    db.commit()
    return {"message": f"worker #{account_id} 已启用(约10s内拉起)"}


def _live_worker_scopes(db: Session, user_id: int) -> list[str]:
    """当前仍存在的子账户对应的 worker scope。用于过滤掉已删除子账户残留的
    engine_state(sub:N)僵尸行 —— 它们 heartbeat 永久过期、显示「超时」却无法删除。"""
    sub_ids = [r.id for r in db.query(SubAccount.id).filter(SubAccount.user_id == user_id).all()]
    return [f"sub:{i}" for i in sub_ids]


@router.get("/workers/status")
def workers_status(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    scopes = _live_worker_scopes(db, user_id)
    if not scopes:
        return {"workers": []}
    workers = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope.in_(scopes),
    ).all()
    return {"workers": [EngineStateResponse.model_validate(w) for w in workers]}


STUCK_STATUSES = {
    "PENDING_BORROW", "BORROWED", "SPOT_SOLD",
    "CLOSING_FUTURES", "FUTURES_CLOSED", "CLOSING_SPOT", "SPOT_BOUGHT", "REPAYING",
}
HEARTBEAT_STALE_SEC = 120


@router.get("/health", response_model=HealthResponse)
def engine_health(request: Request, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    from engine.metrics import all_metrics_snapshot
    from app.services.spread_reader import spread_reader

    user_id = get_current_user_id(request)

    global_state = db.query(EngineState).filter(
        EngineState.user_id == user_id, EngineState.scope == "global",
    ).first()
    engine_status = global_state.status if global_state else "STOPPED"

    now = datetime.now(timezone.utc)
    scopes = _live_worker_scopes(db, user_id)
    worker_rows = db.query(EngineState).filter(
        EngineState.user_id == user_id,
        EngineState.scope.in_(scopes),
    ).all() if scopes else []

    workers = []
    any_stale = False
    for w in worker_rows:
        stale = False
        if w.last_heartbeat:
            delta = (now - w.last_heartbeat).total_seconds()
            stale = delta > HEARTBEAT_STALE_SEC
        if stale:
            any_stale = True
        workers.append(WorkerHealth(
            scope=w.scope,
            status=w.status,
            last_heartbeat=w.last_heartbeat,
            heartbeat_stale=stale,
            active_positions=w.active_positions or 0,
            total_cycles=w.total_cycles or 0,
            error_message=w.error_message,
        ))

    stuck = []
    stuck_rows = db.query(Position).filter(
        Position.user_id == user_id,
        Position.status.in_(STUCK_STATUSES),
    ).all()
    for p in stuck_rows:
        updated = p.updated_at or p.created_at
        if updated:
            mins = int((now - updated).total_seconds() / 60)
        else:
            mins = 0
        stuck.append(StuckPosition(
            id=p.id,
            symbol=p.symbol,
            sub_account_id=p.sub_account_id,
            status=p.status,
            stuck_minutes=mins,
            error_message=p.error_message,
        ))

    total_open = db.query(Position).filter(
        Position.user_id == user_id, Position.status == "OPEN",
    ).count()

    raw_metrics = all_metrics_snapshot()
    api_metrics = {k: APIMetricsResponse(**v) for k, v in raw_metrics.items()}

    spread_health = spread_reader.health()
    spread_count = spread_health.get("active_symbols", 0)

    overall = "HEALTHY"
    if engine_status in ("STOPPED", "ERROR"):
        overall = "UNHEALTHY"
    elif any_stale or len(stuck) > 0:
        overall = "DEGRADED"

    # uptime from global engine state
    uptime_sec = None
    if global_state and global_state.started_at and engine_status == "RUNNING":
        uptime_sec = int((now - global_state.started_at).total_seconds())

    # IP-wide used weight (published to Redis by engine workers + balance_pusher)
    used_weight, weight_limit, weight_age = 0, 6000, None
    uid_used, uid_limit = 0, 180000   # 借币 UID 权重(顶栏「UID」),即使 redis 异常也要有定义
    throttle_rate = 0.0
    try:
        r = _redis()
        raw = r.get("engine:weight:latest")
        if raw:
            wd = json.loads(raw)
            used_weight = int(wd.get("used_weight_1m", 0))
            weight_limit = int(wd.get("limit", 6000))
            if wd.get("weight_time"):
                weight_age = int(datetime.now(timezone.utc).timestamp() - float(wd["weight_time"]))
        # Per-symbol borrow throttle (req/s): borrow/repay are UID-weighted (1500 each,
        # limit 180000 → 2/s/account), NOT IP-weighted. Use the busiest UID's remaining
        # headroom spread across the user's pushed symbols.
        UID_PER_BORROW = 1500
        uraw = r.get("engine:uid_weight:latest")
        if uraw:
            ud = json.loads(uraw)
            uid_used = int(ud.get("used_uid_weight_1m", 0))
            uid_limit = int(ud.get("uid_limit", 180000))
        pushed_raw = r.get(_user_redis_key(user_id, "pushed_symbols"))
        pushed_count = len(json.loads(pushed_raw)) if pushed_raw else 0
        uid_headroom = max(0, uid_limit - uid_used)
        per_acct_ceiling = uid_headroom / UID_PER_BORROW / 60  # UID hard ceiling (~2/s)
        # honor configurable per-account target rate (GlobalRules.borrow_rate_per_sec)
        try:
            from app.db.models import GlobalRules
            gr = (db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
                  or db.query(GlobalRules).first())
            cfg_rate = float(gr.borrow_rate_per_sec) if gr and gr.borrow_rate_per_sec is not None else 2.0
        except Exception:
            cfg_rate = 2.0
        per_acct = min(per_acct_ceiling, cfg_rate)
        if pushed_count > 0:
            throttle_rate = round(per_acct / pushed_count, 3)
    except Exception:
        pass

    # Aggregate borrow rate for the dashboard — folds in the two REAL ceilings so the
    # number reflects what can actually be sustained, not an inflated paper sum:
    #   (1) Per-UID hard cap: every account ≤ 180000/1500/60 = 2.0 borrow/s. Clamp each
    #       account's configured rate to UID_HARD_CEIL before summing, so a single
    #       account mis-set to e.g. 9.6 can no longer make the aggregate lie.
    #   (2) Shared IP budget: the borrow call is 0 IP weight, but each borrow cycle drags
    #       read calls (interest/lot/book) off the host-wide IP budget. That shared budget
    #       caps the whole host's borrow cadence no matter how many UIDs are added.
    UID_HARD_CEIL = 180000 / 1500 / 60  # 2.0 borrow/s per UID
    # Conservative IP weight charged by the reads around one borrow cycle; calibrate from
    # the per-cycle X-SAPI-USED-IP-WEIGHT-1M delta if it needs tightening.
    IP_WEIGHT_PER_BORROW_CYCLE = 10
    agg_borrow_rate = 0.0
    single_borrow_rate = 0.0
    try:
        from app.db.models import GlobalRules
        gr = (db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
              or db.query(GlobalRules).first())
        default_rate = float(gr.borrow_rate_per_sec) if gr and gr.borrow_rate_per_sec is not None else 2.0
        subs = db.query(SubAccount).filter(
            SubAccount.user_id == user_id, SubAccount.is_enabled == True,
        ).all()
        uid_capped_sum = sum(
            min(float(s.borrow_rate_per_sec) if s.borrow_rate_per_sec else default_rate, UID_HARD_CEIL)
            for s in subs
        )
        # host-shared IP ceiling (steady-state from the published IP weight limit)
        ip_host_ceiling = (weight_limit / IP_WEIGHT_PER_BORROW_CYCLE / 60) if weight_limit else float("inf")
        agg_borrow_rate = round(min(uid_capped_sum, ip_host_ceiling), 2)
        # 单UID建仓速率: 实时实际速率 = 最近60s内最忙子账户成功借币(TradeLog action=BORROW)次数 / 60。
        # 反映引擎此刻真正的单账户建仓节奏(非理论上限);无近期借币则为 0。
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        rows = (db.query(TradeLog.sub_account_id, func.count(TradeLog.id))
                .filter(TradeLog.user_id == user_id,
                        TradeLog.action == "BORROW",
                        TradeLog.status == "SUCCESS",
                        TradeLog.created_at >= cutoff)
                .group_by(TradeLog.sub_account_id).all())
        max_cnt = max((c for _, c in rows), default=0)
        single_borrow_rate = round(max_cnt / 60.0, 2)
    except Exception:
        pass

    return HealthResponse(
        status=overall,
        engine_status=engine_status,
        workers=workers,
        stuck_positions=stuck,
        open_positions=total_open,
        api_metrics=api_metrics,
        spread_count=spread_count,
        uptime_sec=uptime_sec,
        used_weight_1m=used_weight,
        weight_limit=weight_limit,
        weight_age_sec=weight_age,
        uid_used_1m=uid_used,
        uid_limit=uid_limit,
        throttle_rate=throttle_rate,
        agg_borrow_rate=agg_borrow_rate,
        single_borrow_rate=single_borrow_rate,
    )
