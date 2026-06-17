"""Admin 实时资金总览(跨用户账户净值统计)。

数据源 = Redis balance:latest:{uid}(balance_pusher 每 30s 写,含各子账户 spot/margin/futures USDT、
净资产、已借、保证金水平、unrealized、bnb)。**只读 Redis,绝不在请求里对子账户打币安 REST**
(历史上后台轮询 REST 打爆封过 IP)。balance:latest TTL 30s,缺失即标 data_stale=true 而非回退打 REST。

口径:账户净值 equity = spot_usdt_free + margin_net_usdt + futures_total + futures_unrealized_pnl。
deployed_notional(开仓名义额,DB open_usdt_amount 之和)与 equity 分列,二者绝不混为"资金"。
"""
import json
from datetime import datetime, timezone, timedelta

import redis as redis_lib
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.db.models import BalanceSnapshot
from app.db.models_auth import User
from app.db.session import get_db
from app.middleware.permissions import require_admin
from app.services.fund_aggregate import aggregate_balances
from engine.models import Position

router = APIRouter(prefix="/api/admin/funds", tags=["admin-funds"])


def _r2(x: float) -> float:
    return round(float(x or 0), 2)


@router.get("/overview")
def funds_overview(request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    r = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)

    users = db.query(User).filter(User.is_active == True).order_by(User.id).all()

    # 每用户开仓名义额 + 开仓持仓数(DB 聚合,一次查全量,O(1) 次查询)
    notional_rows = db.query(
        Position.user_id,
        func.coalesce(func.sum(Position.open_usdt_amount), 0),
        func.count(Position.id),
    ).filter(Position.status == "OPEN").group_by(Position.user_id).all()
    notional_map = {uid: (float(n or 0), int(c)) for uid, n, c in notional_rows}

    out_users = []
    tot = {"equity": 0.0, "available": 0.0, "borrowed": 0.0, "unrealized_pnl": 0.0,
           "deployed_notional": 0.0, "users_with_data": 0}

    for u in users:
        deployed, open_pos = notional_map.get(u.id, (0.0, 0))
        raw = None
        try:
            raw = r.get(f"balance:latest:{u.id}")
        except Exception:
            raw = None

        if not raw:
            out_users.append({
                "user_id": u.id, "username": u.username,
                "data_stale": True,
                "equity": None, "available": None, "borrowed": None,
                "unrealized_pnl": None, "bnb": None, "min_margin_level": None,
                "account_count": 0,
                "deployed_notional": _r2(deployed), "open_positions": open_pos,
                "accounts": [],
            })
            continue

        payload = json.loads(raw)
        balances = payload.get("balances", []) or []
        agg = aggregate_balances(balances)  # 单一真源:与 balance_snapshot 落库口径一致
        accounts = []
        for b in balances:
            spot = float(b.get("spot_usdt_free", 0) or 0)
            m_free = float(b.get("margin_usdt_free", 0) or 0)
            m_borrowed = float(b.get("margin_usdt_borrowed", 0) or 0)
            m_net = float(b.get("margin_net_usdt", 0) or 0)
            f_total = float(b.get("futures_total", 0) or 0)
            f_avail = float(b.get("futures_available", 0) or 0)
            f_upnl = float(b.get("futures_unrealized_pnl", 0) or 0)
            m_level = float(b.get("margin_level", 0) or 0)
            acct_bnb = float(b.get("bnb_free", 0) or 0)
            accounts.append({
                "account_id": b.get("account_id"),
                "note": b.get("note"),
                "equity": _r2(spot + m_net + f_total + f_upnl),
                "spot_usdt_free": _r2(spot),
                "margin_net_usdt": _r2(m_net),
                "margin_usdt_free": _r2(m_free),
                "margin_usdt_borrowed": _r2(m_borrowed),
                "futures_total": _r2(f_total),
                "futures_available": _r2(f_avail),
                "futures_unrealized_pnl": _r2(f_upnl),
                "margin_level": round(m_level, 2),
                "bnb_free": round(acct_bnb, 4),
            })

        mlm = agg["margin_level_min"]
        out_users.append({
            "user_id": u.id, "username": u.username,
            "data_stale": False,
            "equity": _r2(agg["equity"]), "available": _r2(agg["available"]), "borrowed": _r2(agg["borrowed"]),
            "unrealized_pnl": _r2(agg["unrealized_pnl"]), "bnb": round(agg["bnb"], 4),
            "min_margin_level": round(mlm, 2) if mlm is not None else None,
            "account_count": agg["account_count"],
            "deployed_notional": _r2(deployed), "open_positions": open_pos,
            "accounts": accounts,
        })

        tot["equity"] += agg["equity"]
        tot["available"] += agg["available"]
        tot["borrowed"] += agg["borrowed"]
        tot["unrealized_pnl"] += agg["unrealized_pnl"]
        tot["deployed_notional"] += deployed
        tot["users_with_data"] += 1

    try:
        r.close()
    except Exception:
        pass

    return {
        "users": out_users,
        "totals": {
            "equity": _r2(tot["equity"]),
            "available": _r2(tot["available"]),
            "borrowed": _r2(tot["borrowed"]),
            "unrealized_pnl": _r2(tot["unrealized_pnl"]),
            "deployed_notional": _r2(tot["deployed_notional"]),
            "users_with_data": tot["users_with_data"],
            "users_total": len(users),
        },
    }


@router.get("/curve")
def funds_curve(
    request: Request,
    user_id: int = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """资金净值时间序列(来自 balance_snapshot)。user_id 指定=该用户;不指定=全平台按分钟桶汇总。"""
    require_admin(request)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    if user_id is not None:
        rows = (db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.user_id == user_id, BalanceSnapshot.ts >= since)
                .order_by(BalanceSnapshot.ts).all())
        points = [{
            "ts": str(r.ts),
            "equity": float(r.equity or 0),
            "available": float(r.available or 0),
            "borrowed": float(r.borrowed or 0),
            "unrealized_pnl": float(r.unrealized_pnl or 0),
            "margin_level_min": float(r.margin_level_min) if r.margin_level_min is not None else None,
        } for r in rows]
        return {"user_id": user_id, "days": days, "points": points}

    # 全平台:同一 pusher 周期各用户 ts 相差亚秒,按分钟桶聚合求和
    bucket = func.date_trunc("minute", BalanceSnapshot.ts)
    rows = (db.query(
                bucket.label("b"),
                func.coalesce(func.sum(BalanceSnapshot.equity), 0),
                func.coalesce(func.sum(BalanceSnapshot.borrowed), 0),
                func.coalesce(func.sum(BalanceSnapshot.unrealized_pnl), 0),
            )
            .filter(BalanceSnapshot.ts >= since)
            .group_by(bucket).order_by(bucket).all())
    points = [{
        "ts": str(b), "equity": float(eq or 0), "borrowed": float(bw or 0), "unrealized_pnl": float(up or 0),
    } for b, eq, bw, up in rows]
    return {"user_id": None, "days": days, "points": points}


@router.get("/pnl-attribution")
def pnl_attribution(
    request: Request,
    group_by: str = Query("day", pattern="^(user|symbol|day)$"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """盈亏多维归因:按 用户/币种/日 聚合已平仓的净盈亏。
    净PnL = realized_pnl + 累计资金费 − 累计利息(与 /history、/curve 同口径)。"""
    require_admin(request)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    realized = func.coalesce(func.sum(Position.realized_pnl), 0)
    funding = func.coalesce(func.sum(Position.cumulative_funding_fee), 0)
    interest = func.coalesce(func.sum(Position.cumulative_interest), 0)
    cnt = func.count(Position.id)

    base = db.query(Position).filter(Position.status == "CLOSED", Position.closed_at >= since)

    if group_by == "user":
        key = Position.user_id
    elif group_by == "symbol":
        key = Position.symbol
    else:
        key = func.date(Position.closed_at)

    rows = (base.with_entities(key.label("k"), realized, funding, interest, cnt)
            .group_by(key).order_by(key).all())

    unames = ({u.id: u.username for u in db.query(User.id, User.username).all()}
              if group_by == "user" else {})
    out = []
    for k, r, f, i, c in rows:
        r, f, i = float(r or 0), float(f or 0), float(i or 0)
        if group_by == "user":
            label = unames.get(k, f"#{k}") if k is not None else "(无归属)"
        elif group_by == "day":
            label = str(k)
        else:
            label = str(k)
        out.append({
            "key": str(k), "label": label,
            "realized": round(r, 4), "funding": round(f, 4), "interest": round(i, 4),
            "net": round(r + f - i, 4), "count": int(c),
        })

    # day 维度按日期升序(便于看趋势);user/symbol 按净盈亏降序
    if group_by == "day":
        out.sort(key=lambda x: x["key"])
    else:
        out.sort(key=lambda x: x["net"], reverse=True)

    totals = {
        "realized": round(sum(o["realized"] for o in out), 4),
        "funding": round(sum(o["funding"] for o in out), 4),
        "interest": round(sum(o["interest"] for o in out), 4),
        "net": round(sum(o["net"] for o in out), 4),
        "count": sum(o["count"] for o in out),
    }
    return {"group_by": group_by, "days": days, "rows": out, "totals": totals}
