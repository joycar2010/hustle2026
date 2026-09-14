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
from sqlalchemy import case, func

from app.config import settings
from app.db.models import BalanceSnapshot, SubAccount
from app.db.models_auth import User
from app.db.session import get_db
from app.middleware.permissions import require_admin
from app.services.fund_aggregate import aggregate_user_funds
from engine.models import Position

router = APIRouter(prefix="/api/admin/funds", tags=["admin-funds"])

# A position remains financially relevant until the exchange debt/hedge has
# been reconciled.  The worker and balance pusher use the same terminal
# boundary; limiting this view to OPEN hid BORROWED_IDLE/PENDING_REPAY rows and
# made the deployed amount and position count appear as zero during normal
# lifecycle transitions.
_TERMINAL_POSITION_STATUSES = ("CLOSED", "FAILED")


def _r2(x: float) -> float:
    return round(float(x or 0), 2)


def _position_metrics(db: Session):
    """Return per-user and platform position/PnL metrics from the ledger.

    Balance snapshots contain exchange wallet values, but they do not contain
    the position ledger.  Keeping these aggregates in this endpoint prevents
    the headline cards from showing zero merely because the Redis balance
    snapshot has no open futures or because all PnL is realized.  PnL follows
    the history endpoint's accounting convention:
    ``realized_pnl + cumulative_funding_fee - cumulative_interest``.
    """
    owner_id = func.coalesce(Position.user_id, SubAccount.user_id)
    active = Position.status.notin_(_TERMINAL_POSITION_STATUSES)
    # A position may have been created before open_usdt_amount was persisted.
    # Some older schemas exposed borrow_usdt_amount, while the current ledger
    # only has open_usdt_amount.  Resolve the optional column safely so the
    # aggregate remains compatible with both schemas (and SQLite test ledgers).
    legacy_notional = getattr(Position, "borrow_usdt_amount", Position.open_usdt_amount)
    notional = func.coalesce(Position.open_usdt_amount, legacy_notional)
    active_rows = db.query(
        owner_id,
        func.coalesce(func.sum(notional), 0),
        func.count(Position.id),
    ).outerjoin(SubAccount, Position.sub_account_id == SubAccount.id).filter(
        active
    ).group_by(owner_id).all()

    # Only CLOSED rows contribute settled PnL and close count.  Funding and
    # interest on an active row are still provisional and must not leak into
    # the headline "total PNL" card.
    settled = Position.status == "CLOSED"
    pnl_expr = (
        func.coalesce(Position.realized_pnl, 0)
        + func.coalesce(Position.cumulative_funding_fee, 0)
        - func.coalesce(Position.cumulative_interest, 0)
    )
    pnl_rows = db.query(
        owner_id,
        func.coalesce(func.sum(pnl_expr), 0),
        func.coalesce(func.sum(case((settled, 1), else_=0)), 0),
    ).outerjoin(SubAccount, Position.sub_account_id == SubAccount.id).filter(
        settled
    ).group_by(owner_id).all()

    active_map = {
        uid: {"notional": float(value or 0), "open_positions": int(count or 0)}
        for uid, value, count in active_rows
    }
    pnl_map = {
        uid: {"realized_net_pnl": float(value or 0), "closed_positions": int(count or 0)}
        for uid, value, count in pnl_rows
    }

    platform = {
        "position_notional": sum(v["notional"] for v in active_map.values()),
        "open_positions": sum(v["open_positions"] for v in active_map.values()),
        "realized_net_pnl": sum(v["realized_net_pnl"] for v in pnl_map.values()),
        "closed_positions": sum(v["closed_positions"] for v in pnl_map.values()),
    }
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today_start + timedelta(days=1)
    today_rows = db.query(
        func.coalesce(func.sum(pnl_expr), 0),
        func.count(Position.id),
    ).filter(
        Position.status == "CLOSED",
        Position.closed_at >= today_start,
        Position.closed_at < tomorrow,
    ).one()
    platform["today_pnl"] = float(today_rows[0] or 0)
    platform["today_closed"] = int(today_rows[1] or 0)
    per_user = {}
    for uid in set(active_map) | set(pnl_map):
        per_user[uid] = {
            **active_map.get(uid, {"notional": 0.0, "open_positions": 0}),
            **pnl_map.get(uid, {"realized_net_pnl": 0.0, "closed_positions": 0}),
        }
    return per_user, platform


@router.get("/overview")
def funds_overview(request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    r = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)

    users = db.query(User).filter(User.is_active == True).order_by(User.id).all()

    # Redis snapshots intentionally expire after 30s.  During a pusher restart
    # that used to turn every user into ``null`` and made the platform totals
    # look like zero.  Keep the latest persisted snapshot as a clearly marked
    # read-only fallback so operators can distinguish stale data from a real
    # zero balance.  The snapshot table is already written from the same
    # aggregate_user_funds() source of truth.
    snapshot_by_user = {}
    if users:
        user_ids = [u.id for u in users]
        rows = (db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.user_id.in_(user_ids))
                .order_by(BalanceSnapshot.user_id, BalanceSnapshot.ts.desc())
                .all())
        for row in rows:
            if row.user_id not in snapshot_by_user:
                snapshot_by_user[row.user_id] = row

    # 每用户有效持仓名义额 + 持仓数(DB 聚合,一次查全量,O(1) 次查询)。
    # ``BORROWED_IDLE`` 等状态已经产生真实借币债务，也必须纳入统计。
    # Position ledger metrics are independent from the wallet snapshots.
    position_map, position_totals = _position_metrics(db)

    out_users = []
    tot = {"equity": 0.0, "available": 0.0, "borrowed": 0.0, "unrealized_pnl": 0.0,
           "master_equity": 0.0, "deployed_notional": 0.0,
           "realized_net_pnl": 0.0, "total_pnl": 0.0,
           "closed_positions": 0, "open_positions": 0,
           "users_with_data": 0, "users_realtime": 0, "users_with_snapshot": 0}

    for u in users:
        pos = position_map.get(u.id, {})
        deployed = float(pos.get("notional", 0))
        open_pos = int(pos.get("open_positions", 0))
        realized_net = float(pos.get("realized_net_pnl", 0))
        closed_pos = int(pos.get("closed_positions", 0))
        raw = None
        try:
            raw = r.get(f"balance:latest:{u.id}")
        except Exception:
            raw = None

        if not raw:
            snapshot = snapshot_by_user.get(u.id)
            if snapshot is not None:
                # BalanceSnapshot contains aggregate values only; account
                # details cannot be reconstructed safely, so leave accounts
                # empty and label this row as a stale persisted snapshot.
                ts = snapshot.ts
                if ts is not None and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = max(0, int((datetime.now(timezone.utc) - ts).total_seconds())) if ts else None
                equity = float(snapshot.equity or 0)
                available = float(snapshot.available or 0)
                borrowed = float(snapshot.borrowed or 0)
                unrealized = float(snapshot.unrealized_pnl or 0)
                out_users.append({
                    "user_id": u.id, "username": u.username,
                    "data_stale": True, "data_source": "snapshot",
                    "snapshot_at": ts.isoformat() if ts else None,
                    "snapshot_age_seconds": age,
                    "equity": _r2(equity), "available": _r2(available),
                    "borrowed": _r2(borrowed), "unrealized_pnl": _r2(unrealized),
                    "bnb": round(float(snapshot.bnb or 0), 4),
                    "min_margin_level": _r2(snapshot.margin_level_min) if snapshot.margin_level_min is not None else None,
                    "account_count": int(snapshot.account_count or 0),
                    "master": None, "master_equity": 0.0,
                    "deployed_notional": _r2(deployed), "open_positions": open_pos,
                    "position_notional": _r2(deployed), "realized_net_pnl": _r2(realized_net),
                    "total_pnl": _r2(realized_net), "closed_positions": closed_pos,
                    "accounts": [],
                })
                tot["equity"] += equity
                tot["available"] += available
                tot["borrowed"] += borrowed
                tot["unrealized_pnl"] += unrealized
                tot["deployed_notional"] += deployed
                tot["realized_net_pnl"] += realized_net
                tot["total_pnl"] += realized_net
                tot["closed_positions"] += closed_pos
                tot["open_positions"] += open_pos
                tot["users_with_data"] += 1
                tot["users_with_snapshot"] += 1
                continue
            out_users.append({
                "user_id": u.id, "username": u.username,
                "data_stale": True, "data_source": "none",
                "snapshot_at": None, "snapshot_age_seconds": None,
                "equity": None, "available": None, "borrowed": None,
                "unrealized_pnl": None, "bnb": None, "min_margin_level": None,
                "account_count": 0,
                "master": None,
                "deployed_notional": _r2(deployed), "open_positions": open_pos,
                "position_notional": _r2(deployed), "realized_net_pnl": _r2(realized_net),
                "total_pnl": _r2(realized_net), "closed_positions": closed_pos,
                "accounts": [],
            })
            tot["deployed_notional"] += deployed
            tot["realized_net_pnl"] += realized_net
            tot["total_pnl"] += realized_net
            tot["closed_positions"] += closed_pos
            tot["open_positions"] += open_pos
            continue

        payload = json.loads(raw)
        balances = payload.get("balances", []) or []
        master_balance = payload.get("master_balance")
        agg = aggregate_user_funds(balances, master_balance)  # single source of truth
        accounts = []
        for b in balances:
            spot = float(b.get("spot_usdt_free", 0) or 0)
            m_free = float(b.get("margin_usdt_free", 0) or 0)
            m_borrowed = float(b.get("margin_usdt_borrowed", 0) or 0)
            m_borrowed_total = float(b.get("margin_borrowed_usdt", m_borrowed) or 0)
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
                "margin_borrowed_usdt": _r2(m_borrowed_total),
                "futures_total": _r2(f_total),
                "futures_available": _r2(f_avail),
                "futures_unrealized_pnl": _r2(f_upnl),
                "margin_level": round(m_level, 2),
                "bnb_free": round(acct_bnb, 4),
            })

        mlm = agg["margin_level_min"]
        master_view = None
        if isinstance(master_balance, dict) and master_balance.get("configured"):
            master_view = {
                "account_name": master_balance.get("account_name"),
                "snapshot_at_ms": master_balance.get("snapshot_at_ms"),
                "snapshot_stale": bool(master_balance.get("snapshot_stale")),
                "spot_usdt_free": _r2(master_balance.get("spot_usdt_free")),
                "spot_usdt_locked": _r2(master_balance.get("spot_usdt_locked")),
                "margin_net_usdt": _r2(master_balance.get("margin_net_usdt")),
                "margin_usdt_free": _r2(master_balance.get("margin_usdt_free")),
                "margin_usdt_borrowed": _r2(master_balance.get("margin_usdt_borrowed")),
                "margin_borrowed_usdt": _r2(master_balance.get("margin_borrowed_usdt", master_balance.get("borrowed"))),
                "margin_interest": _r2(master_balance.get("margin_interest")),
                "margin_level": _r2(master_balance.get("margin_level")),
                "futures_total": _r2(master_balance.get("futures_total")),
                "futures_available": _r2(master_balance.get("futures_available")),
                "futures_unrealized_pnl": _r2(master_balance.get("futures_unrealized_pnl")),
                "bnb_free": round(float(master_balance.get("bnb_free", 0) or 0), 4),
                "equity": _r2(master_balance.get("equity")),
                "available": _r2(master_balance.get("available")),
                "borrowed": _r2(master_balance.get("borrowed")),
                "unrealized_pnl": _r2(master_balance.get("unrealized_pnl")),
            }
        out_users.append({
            "user_id": u.id, "username": u.username,
            "data_stale": False, "data_source": "redis",
            "snapshot_at": None, "snapshot_age_seconds": 0,
            "equity": _r2(agg["equity"]), "available": _r2(agg["available"]), "borrowed": _r2(agg["borrowed"]),
            "unrealized_pnl": _r2(agg["unrealized_pnl"]), "bnb": round(agg["bnb"], 4),
            "min_margin_level": round(mlm, 2) if mlm is not None else None,
            "account_count": agg["account_count"],
            "master": master_view,
            "master_equity": _r2(agg.get("master_equity", 0)),
            "deployed_notional": _r2(deployed), "open_positions": open_pos,
            "position_notional": _r2(deployed), "realized_net_pnl": _r2(realized_net),
            "total_pnl": _r2(realized_net), "closed_positions": closed_pos,
            "accounts": accounts,
        })

        tot["equity"] += agg["equity"]
        tot["available"] += agg["available"]
        tot["borrowed"] += agg["borrowed"]
        tot["unrealized_pnl"] += agg["unrealized_pnl"]
        tot["master_equity"] += agg.get("master_equity", 0)
        tot["deployed_notional"] += deployed
        tot["realized_net_pnl"] += realized_net
        tot["total_pnl"] += realized_net
        tot["closed_positions"] += closed_pos
        tot["open_positions"] += open_pos
        tot["users_with_data"] += 1
        tot["users_realtime"] += 1

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
            "master_equity": _r2(tot["master_equity"]),
            "deployed_notional": _r2(tot["deployed_notional"]),
            "position_notional": _r2(position_totals["position_notional"]),
            "total_position_notional": _r2(position_totals["position_notional"]),
            "open_positions": int(position_totals["open_positions"]),
            "realized_net_pnl": _r2(tot["realized_net_pnl"]),
            "total_pnl": _r2(tot["total_pnl"]),
            "closed_positions": int(position_totals["closed_positions"]),
            "total_closed": int(position_totals["closed_positions"]),
            "today_pnl": _r2(position_totals["today_pnl"]),
            "today_closed": int(position_totals["today_closed"]),
            "users_with_data": tot["users_with_data"],
            "users_realtime": tot["users_realtime"],
            "users_with_snapshot": tot["users_with_snapshot"],
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
