"""Sub-account API: admin CRUD + ViewContext dependency for read endpoints.

Endpoints (mounted under /api/v1):
  POST   /users/{user_id}/sub-accounts   — admin only; create sub for that parent
  GET    /users/{user_id}/sub-accounts   — admin only; list parent's subs
  DELETE /sub-accounts/{sub_id}          — admin only; soft-deactivate

Pure data:
  GET    /me/subaccount                  — sub's own banner data (multiplier etc.)

Helpers exported for other endpoints to import:
  get_view_context  — FastAPI dependency, resolves caller → ViewContext
  require_not_subaccount — guard for write endpoints
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import UUID

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.services.subaccount_nav import (
    get_parent_nav, invalidate_parent_nav, get_active_subscription,
    list_active_subscriptions_by_sub,
)
from app.services.subaccount_fx import cny_to_usdt

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_ROLES = {'超级管理员', '系统管理员', 'super_admin', 'system_admin', 'admin'}


# ───────────────────── Request/Response models ─────────────────────
class SubAccountCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    invested_cny: float = Field(..., gt=0)
    fx_override: Optional[float] = Field(None, description="可选：管理员手动指定 CNY→USDT 汇率（CNY/USDT）")
    note: Optional[str] = None


class SubAccountResponse(BaseModel):
    id: str
    sub_user_id: str
    sub_username: str
    parent_user_id: str
    invested_cny: float
    invested_usdt: float
    fx_cny_to_usdt: float
    shares: float
    nav_per_share_at_join: float
    parent_total_assets_at_join: float
    status: str
    created_at: str

    # Live computed
    parent_nav_per_share_now: Optional[float] = None
    sub_current_value_usdt: Optional[float] = None
    sub_current_value_cny: Optional[float] = None
    multiplier: Optional[float] = None


# ───────────────────── ViewContext (used by read endpoints) ─────────────────────
@dataclass
class ViewContext:
    auth_user_id: str         # who logged in
    data_user_id: str         # whose data to read (parent if sub, else self)
    is_sub: bool
    multiplier: float = 1.0   # apply to balance/PnL/qty fields when serving sub
    sub_invested_usdt: float = 0.0
    sub_invested_cny: float = 0.0
    sub_current_value_usdt: float = 0.0


async def get_view_context(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ViewContext:
    row = (await db.execute(text(
        "SELECT is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": user_id})).first()
    if not row or not row[0]:
        return ViewContext(auth_user_id=user_id, data_user_id=user_id, is_sub=False)

    # M2M: fetch all active subscriptions, ordered by shares DESC. Primary = first.
    subs = await list_active_subscriptions_by_sub(db, user_id)
    if not subs:
        # is_subaccount=True but no active subscription → locked out
        return ViewContext(auth_user_id=user_id, data_user_id=user_id, is_sub=True, multiplier=0.0)

    # Primary subscription drives single-parent views (dashboard/positions/orders).
    # Banner/historical-PnL aggregate across all subs via separate path.
    _sid, primary_parent, primary_shares, inv_usdt, inv_cny, _nav_join, _created = subs[0]
    nav = await get_parent_nav(db, primary_parent)
    if nav.total_assets_usdt <= 0:
        mult = 0.0; cur_value = 0.0
    else:
        cur_value = float(primary_shares * nav.nav_per_share)
        mult = cur_value / float(nav.total_assets_usdt) if float(nav.total_assets_usdt) else 0.0

    # Aggregate invested/current across all parents for banner fallback
    agg_inv_usdt = sum((float(r[3]) for r in subs), 0.0)
    agg_inv_cny = sum((float(r[4]) for r in subs), 0.0)
    agg_cur = cur_value  # primary only; /me/subaccount aggregates properly
    for (_s, pu, sh, _iu, _ic, _n, _c) in subs[1:]:
        try:
            _nav_p = await get_parent_nav(db, pu)
            agg_cur += float(sh * _nav_p.nav_per_share)
        except Exception:
            pass

    return ViewContext(
        auth_user_id=user_id,
        data_user_id=primary_parent,
        is_sub=True,
        multiplier=float(mult),
        sub_invested_usdt=agg_inv_usdt,
        sub_invested_cny=agg_inv_cny,
        sub_current_value_usdt=agg_cur,
    )


async def require_not_subaccount(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> str:
    row = (await db.execute(text(
        "SELECT is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": user_id})).first()
    if row and row[0]:
        raise HTTPException(status_code=403, detail="子账号无此操作权限")
    return user_id


# ───────────────────── Admin guard ─────────────────────
async def _require_admin(db: AsyncSession, user_id: str) -> str:
    row = (await db.execute(text(
        "SELECT role FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": user_id})).first()
    if not row or row[0] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="仅超管/系统管理员可管理子账号")
    return user_id


# ───────────────────── helpers ─────────────────────
async def _row_to_sub_response(db: AsyncSession, row: Any, sub_username: str) -> Dict[str, Any]:
    parent_uid = str(row[2])
    nav = await get_parent_nav(db, parent_uid)
    shares = Decimal(str(row[7]))
    cur_value = float(shares * nav.nav_per_share)
    mult = cur_value / float(nav.total_assets_usdt) if float(nav.total_assets_usdt) else 0.0
    return {
        "id": str(row[0]),
        "sub_user_id": str(row[1]),
        "sub_username": sub_username,
        "parent_user_id": parent_uid,
        "invested_cny": float(row[3]),
        "fx_cny_to_usdt": float(row[4]),
        "invested_usdt": float(row[5]),
        "parent_total_assets_at_join": float(row[6]),
        "shares": float(shares),
        "nav_per_share_at_join": float(row[8]) if row[8] else 1.0,
        "status": row[9],
        "created_at": row[10].isoformat() if row[10] else "",
        "parent_nav_per_share_now": float(nav.nav_per_share),
        "sub_current_value_usdt": cur_value,
        "sub_current_value_cny": cur_value * float(row[4]),
        "multiplier": mult,
    }


# ───────────────────── Endpoints ─────────────────────
@router.post("/users/{parent_user_id}/sub-accounts", status_code=201)
async def create_sub_account(
    parent_user_id: str,
    body: SubAccountCreate,
    operator_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await _require_admin(db, operator_id)

    # Sanity: parent exists, is not itself a sub
    parent = (await db.execute(text(
        "SELECT user_id, username, is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()
    if not parent:
        raise HTTPException(status_code=404, detail="父账号不存在")
    if parent[2]:
        raise HTTPException(status_code=400, detail="子账号下不能再挂子账号")

    # Username uniqueness
    dup = (await db.execute(text(
        "SELECT 1 FROM users WHERE username = :n LIMIT 1"
    ), {"n": body.username})).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"用户名 {body.username} 已被占用")

    # FX
    if body.fx_override and body.fx_override > 0:
        fx_rate = Decimal(str(body.fx_override))
        invested_usdt = (Decimal(str(body.invested_cny)) / fx_rate).quantize(Decimal("0.00000001"))
        fx_source = "admin_override"
    else:
        invested_usdt, fx_rate, fx_source = await cny_to_usdt(Decimal(str(body.invested_cny)))

    # Bootstrap parent_share_state if this is the first sub (NAV=1.0 baseline).
    ps_row = (await db.execute(text(
        "SELECT virtual_shares FROM parent_share_state WHERE parent_user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()
    if not ps_row:
        _cur_total = (await db.execute(text("""
            SELECT COALESCE(SUM(total_assets), 0) FROM (
              SELECT DISTINCT ON (s.account_id) s.total_assets
              FROM account_snapshots s
              JOIN accounts a ON s.account_id = a.account_id
              WHERE a.user_id = CAST(:u AS UUID)
              ORDER BY s.account_id, s.timestamp DESC
            ) q
        """), {"u": parent_user_id})).first()
        bootstrap_total = float(_cur_total[0] or 0)
        # Virtual shares = current total assets → NAV starts at 1.0
        await db.execute(text("""
            INSERT INTO parent_share_state (parent_user_id, virtual_shares, bootstrap_total_assets)
            VALUES (CAST(:u AS UUID), :v, :t)
            ON CONFLICT (parent_user_id) DO NOTHING
        """), {"u": parent_user_id, "v": bootstrap_total, "t": bootstrap_total})
        await db.commit()
        await invalidate_parent_nav(parent_user_id)

    # Parent NAV at join
    nav = await get_parent_nav(db, parent_user_id, force=True)
    nav_per_share = nav.nav_per_share if nav.nav_per_share > 0 else Decimal("1")
    shares = (invested_usdt / nav_per_share).quantize(Decimal("0.00000001"))

    # Insert sub user (real auth account)
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    sub_row = (await db.execute(text("""
        INSERT INTO users (
            username, password_hash, role, is_active,
            parent_user_id, is_subaccount, openclaw_enabled, fund_view_enabled
        ) VALUES (
            :n, :p, '子账号', true, CAST(:pa AS UUID), true, false, false
        ) RETURNING user_id
    """), {"n": body.username, "p": pw_hash, "pa": parent_user_id})).first()
    sub_user_id = str(sub_row[0])

    # Insert subscription
    sub_id_row = (await db.execute(text("""
        INSERT INTO sub_account_subscriptions (
            sub_user_id, parent_user_id,
            invested_cny, fx_cny_to_usdt, invested_usdt,
            parent_total_assets_at_join, nav_per_share_at_join, shares,
            status, created_by
        ) VALUES (
            CAST(:s AS UUID), CAST(:pa AS UUID),
            :icny, :fx, :iusdt,
            :pta, :nav, :sh,
            'active', CAST(:op AS UUID)
        ) RETURNING id
    """), {
        "s": sub_user_id, "pa": parent_user_id,
        "icny": float(body.invested_cny), "fx": float(fx_rate), "iusdt": float(invested_usdt),
        "pta": float(nav.total_assets_usdt), "nav": float(nav_per_share), "sh": float(shares),
        "op": operator_id,
    })).first()
    await db.commit()
    await invalidate_parent_nav(parent_user_id)

    logger.info(
        f"[subacc] create username={body.username} parent={parent[1]} "
        f"cny={body.invested_cny} usdt={invested_usdt} fx={fx_rate}({fx_source}) "
        f"shares={shares}"
    )

    # Pull back full record
    full = (await db.execute(text("""
        SELECT id, sub_user_id, parent_user_id, invested_cny, fx_cny_to_usdt,
               invested_usdt, parent_total_assets_at_join, shares,
               nav_per_share_at_join, status, created_at
        FROM sub_account_subscriptions WHERE id = :i
    """), {"i": str(sub_id_row[0])})).first()
    resp = await _row_to_sub_response(db, full, body.username)
    resp["fx_source"] = fx_source
    return resp


@router.get("/users/{parent_user_id}/sub-accounts")
async def list_sub_accounts(
    parent_user_id: str,
    operator_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    await _require_admin(db, operator_id)
    rows = (await db.execute(text("""
        SELECT s.id, s.sub_user_id, s.parent_user_id, s.invested_cny, s.fx_cny_to_usdt,
               s.invested_usdt, s.parent_total_assets_at_join, s.shares,
               s.nav_per_share_at_join, s.status, s.created_at, u.username
        FROM sub_account_subscriptions s
        JOIN users u ON u.user_id = s.sub_user_id
        WHERE s.parent_user_id = CAST(:u AS UUID)
        ORDER BY s.created_at DESC
    """), {"u": parent_user_id})).fetchall()
    out = []
    for r in rows:
        rec = await _row_to_sub_response(db, r, r[11])
        out.append(rec)
    return out


@router.delete("/sub-accounts/{sub_id}", status_code=200)
async def delete_sub_account(
    sub_id: str,
    operator_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await _require_admin(db, operator_id)
    row = (await db.execute(text(
        "SELECT sub_user_id, parent_user_id, status FROM sub_account_subscriptions WHERE id = CAST(:i AS UUID)"
    ), {"i": sub_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if row[2] == 'inactive':
        return {"ok": True, "already_inactive": True}

    # Soft-deactivate subscription + disable user login
    await db.execute(text(
        "UPDATE sub_account_subscriptions SET status='inactive', updated_at=NOW() WHERE id = CAST(:i AS UUID)"
    ), {"i": sub_id})
    await db.execute(text(
        "UPDATE users SET is_active=false, update_time=NOW() WHERE user_id = CAST(:u AS UUID)"
    ), {"u": str(row[0])})
    await db.commit()
    await invalidate_parent_nav(str(row[1]))
    logger.info(f"[subacc] deactivated sub_id={sub_id} sub_user={row[0]} parent={row[1]}")
    return {"ok": True}


@router.get("/me/subaccount")
async def my_subaccount_banner(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Sub-account banner. With M2M support, returns per-parent breakdown and aggregate.
    Force-bypass NAV cache so user sees fresh numbers when they refresh."""
    # Pull is_subaccount + fund_view_enabled + role in one query so we can gate
    # the non-sub (parent) view_caps on the admin-granted fund_view permission.
    row = (await db.execute(text(
        "SELECT is_subaccount, COALESCE(fund_view_enabled, false), role "
        "FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": user_id})).first()
    if not row or not row[0]:
        # Non-sub (parent / regular / admin) path. Admin roles bypass the gate
        # because admins must always be able to see every surface.
        _ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员',
                        'admin', 'super_admin'}
        _is_admin = bool(row and len(row) > 2 and row[2] in _ADMIN_ROLES)
        _fund_flow = True if _is_admin else bool(row[1]) if row else True
        return {"is_sub": False, "multiplier": 1.0, "invested_cny": 0, "invested_usdt": 0,
                "current_value_usdt": 0, "subscriptions": [],
                "view_caps": {"fund_flow": _fund_flow, "can_trade": True, "can_edit_account": True}}

    subs = await list_active_subscriptions_by_sub(db, user_id)
    if not subs:
        return {"is_sub": True, "multiplier": 0.0, "invested_cny": 0, "invested_usdt": 0,
                "current_value_usdt": 0, "subscriptions": [],
                "view_caps": {"fund_flow": False, "can_trade": False, "can_edit_account": False}}

    sub_breakdown: List[Dict[str, Any]] = []
    agg_inv_cny = 0.0; agg_inv_usdt = 0.0; agg_cur = 0.0
    # Primary multiplier = largest-shares parent's mult (used by existing WS / projection path)
    primary_mult = 0.0
    for idx, (sid, parent_uid, shares, inv_usdt, inv_cny, nav_at_join, created_at) in enumerate(subs):
        nav = await get_parent_nav(db, parent_uid, force=True)
        cur_value = float(shares * nav.nav_per_share) if nav.total_assets_usdt > 0 else 0.0
        mult = cur_value / float(nav.total_assets_usdt) if float(nav.total_assets_usdt) else 0.0
        # parent username (for UI hint)
        pu_row = (await db.execute(text(
            "SELECT username FROM users WHERE user_id = CAST(:u AS UUID)"
        ), {"u": parent_uid})).first()
        sub_breakdown.append({
            "subscription_id": sid,
            "parent_user_id": parent_uid,
            "parent_username": pu_row[0] if pu_row else "",
            "invested_cny": float(inv_cny),
            "invested_usdt": float(inv_usdt),
            "shares": float(shares),
            "nav_per_share_at_join": float(nav_at_join),
            "nav_per_share_now": float(nav.nav_per_share),
            "current_value_usdt": cur_value,
            "multiplier": float(mult),
            "is_primary": idx == 0,
        })
        agg_inv_cny += float(inv_cny)
        agg_inv_usdt += float(inv_usdt)
        agg_cur += cur_value
        if idx == 0:
            primary_mult = float(mult)

    return {
        "is_sub": True,
        "multiplier": primary_mult,   # backward-compat; WS still uses primary
        "invested_cny": agg_inv_cny,
        "invested_usdt": agg_inv_usdt,
        "current_value_usdt": agg_cur,
        "subscriptions": sub_breakdown,
        "view_caps": {
            "fund_flow": False,
            "can_trade": False,
            "can_edit_account": False,
        },
    }


# ───────────────────── M2M: subscribe existing sub to another parent ─────────────────────
class SubscribeExistingReq(BaseModel):
    sub_user_id: str = Field(..., description="The existing sub-account's user_id")
    invested_cny: float = Field(..., gt=0)
    fx_override: Optional[float] = None
    note: Optional[str] = None


async def _recompute_primary_parent(db: AsyncSession, sub_user_id: str) -> Optional[str]:
    """Set users.parent_user_id = active subscription with largest shares.
    Returns new primary uid (or None if no active subs)."""
    row = (await db.execute(text("""
        SELECT parent_user_id FROM sub_account_subscriptions
        WHERE sub_user_id = CAST(:u AS UUID) AND status = 'active'
        ORDER BY shares DESC LIMIT 1
    """), {"u": sub_user_id})).first()
    new_primary = str(row[0]) if row else None
    await db.execute(text("""
        UPDATE users SET parent_user_id = CAST(:p AS UUID) WHERE user_id = CAST(:u AS UUID)
    """ if new_primary else """
        UPDATE users SET parent_user_id = NULL WHERE user_id = CAST(:u AS UUID)
    """), {"u": sub_user_id, "p": new_primary} if new_primary else {"u": sub_user_id})
    return new_primary


@router.post("/users/{parent_user_id}/sub-accounts/subscribe-existing", status_code=201)
async def subscribe_existing_sub(
    parent_user_id: str,
    body: SubscribeExistingReq,
    operator_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Admin: attach an existing sub-account to an additional parent (M2M)."""
    await _require_admin(db, operator_id)

    parent = (await db.execute(text(
        "SELECT user_id, username, is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()
    if not parent or parent[2]:
        raise HTTPException(status_code=400, detail="父账号不存在或自身是子账号")

    sub_u = (await db.execute(text(
        "SELECT username, is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": body.sub_user_id})).first()
    if not sub_u or not sub_u[1]:
        raise HTTPException(status_code=400, detail="目标用户不是子账号")

    # No duplicate active subscription to same parent
    dup = (await db.execute(text("""
        SELECT 1 FROM sub_account_subscriptions
        WHERE sub_user_id = CAST(:s AS UUID) AND parent_user_id = CAST(:p AS UUID) AND status = 'active'
    """), {"s": body.sub_user_id, "p": parent_user_id})).first()
    if dup:
        raise HTTPException(status_code=409, detail="该子账号已订阅此父账号")

    # FX
    if body.fx_override and body.fx_override > 0:
        fx_rate = Decimal(str(body.fx_override))
        invested_usdt = (Decimal(str(body.invested_cny)) / fx_rate).quantize(Decimal("0.00000001"))
        fx_source = "admin_override"
    else:
        invested_usdt, fx_rate, fx_source = await cny_to_usdt(Decimal(str(body.invested_cny)))

    # Bootstrap parent_share_state if needed (same logic as create_sub_account)
    ps_row = (await db.execute(text(
        "SELECT virtual_shares FROM parent_share_state WHERE parent_user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()
    if not ps_row:
        _cur_total = (await db.execute(text("""
            SELECT COALESCE(SUM(total_assets), 0) FROM (
              SELECT DISTINCT ON (s.account_id) s.total_assets
              FROM account_snapshots s
              JOIN accounts a ON s.account_id = a.account_id
              WHERE a.user_id = CAST(:u AS UUID)
              ORDER BY s.account_id, s.timestamp DESC
            ) q
        """), {"u": parent_user_id})).first()
        bootstrap_total = float(_cur_total[0] or 0)
        await db.execute(text("""
            INSERT INTO parent_share_state (parent_user_id, virtual_shares, bootstrap_total_assets)
            VALUES (CAST(:u AS UUID), :v, :t)
            ON CONFLICT (parent_user_id) DO NOTHING
        """), {"u": parent_user_id, "v": bootstrap_total, "t": bootstrap_total})
        await db.commit()
        await invalidate_parent_nav(parent_user_id)

    nav = await get_parent_nav(db, parent_user_id, force=True)
    nav_per_share = nav.nav_per_share if nav.nav_per_share > 0 else Decimal("1")
    shares = (invested_usdt / nav_per_share).quantize(Decimal("0.00000001"))

    sub_id_row = (await db.execute(text("""
        INSERT INTO sub_account_subscriptions (
            sub_user_id, parent_user_id,
            invested_cny, fx_cny_to_usdt, invested_usdt,
            parent_total_assets_at_join, nav_per_share_at_join, shares,
            status, created_by
        ) VALUES (
            CAST(:s AS UUID), CAST(:pa AS UUID),
            :icny, :fx, :iusdt,
            :pta, :nav, :sh,
            'active', CAST(:op AS UUID)
        ) RETURNING id, created_at
    """), {
        "s": body.sub_user_id, "pa": parent_user_id,
        "icny": float(body.invested_cny), "fx": float(fx_rate), "iusdt": float(invested_usdt),
        "pta": float(nav.total_assets_usdt), "nav": float(nav_per_share), "sh": float(shares),
        "op": operator_id,
    })).first()

    # Recompute primary parent (affects Go WS routing)
    new_primary = await _recompute_primary_parent(db, body.sub_user_id)
    await db.commit()
    await invalidate_parent_nav(parent_user_id)

    logger.info(
        f"[subacc-m2m] subscribe sub={sub_u[0]} to parent={parent[1]} "
        f"cny={body.invested_cny} usdt={invested_usdt} fx={fx_rate}({fx_source}) "
        f"shares={shares} primary_now={new_primary}"
    )

    return {
        "id": str(sub_id_row[0]),
        "sub_user_id": body.sub_user_id,
        "parent_user_id": parent_user_id,
        "invested_cny": float(body.invested_cny),
        "invested_usdt": float(invested_usdt),
        "fx_cny_to_usdt": float(fx_rate),
        "shares": float(shares),
        "nav_per_share_at_join": float(nav_per_share),
        "parent_total_assets_at_join": float(nav.total_assets_usdt),
        "status": "active",
        "created_at": sub_id_row[1].isoformat() if sub_id_row[1] else "",
        "primary_parent_after": new_primary,
    }


# ───────────────────── Parent cashflow (mint/burn virtual shares) ─────────────────────
class ParentCashflowReq(BaseModel):
    direction: str = Field(..., description="'deposit' or 'withdraw'")
    amount_usdt: float = Field(..., gt=0)
    note: Optional[str] = None


@router.post("/users/{parent_user_id}/parent-cashflow", status_code=201)
async def record_parent_cashflow(
    parent_user_id: str,
    body: ParentCashflowReq,
    operator_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Log a parent deposit/withdraw — mints or burns virtual shares at current NAV
    so all sub-account values stay stable. Admin-only.
    """
    await _require_admin(db, operator_id)
    if body.direction not in ('deposit', 'withdraw'):
        raise HTTPException(status_code=400, detail="direction must be 'deposit' or 'withdraw'")

    parent = (await db.execute(text(
        "SELECT user_id, username, is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()
    if not parent:
        raise HTTPException(status_code=404, detail="父账号不存在")
    if parent[2]:
        raise HTTPException(status_code=400, detail="子账号不可作为父账号")

    # Ensure share_state exists (bootstrap if missing — parent may have no subs yet)
    ps = (await db.execute(text(
        "SELECT virtual_shares FROM parent_share_state WHERE parent_user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()
    if not ps:
        cur_total_row = (await db.execute(text("""
            SELECT COALESCE(SUM(total_assets), 0) FROM (
              SELECT DISTINCT ON (s.account_id) s.total_assets
              FROM account_snapshots s
              JOIN accounts a ON s.account_id = a.account_id
              WHERE a.user_id = CAST(:u AS UUID)
              ORDER BY s.account_id, s.timestamp DESC
            ) q
        """), {"u": parent_user_id})).first()
        bootstrap = float(cur_total_row[0] or 0)
        await db.execute(text(
            "INSERT INTO parent_share_state (parent_user_id, virtual_shares, bootstrap_total_assets) "
            "VALUES (CAST(:u AS UUID), :v, :t)"
        ), {"u": parent_user_id, "v": bootstrap, "t": bootstrap})
        virtual_shares_pre = Decimal(str(bootstrap))
    else:
        virtual_shares_pre = Decimal(str(ps[0]))

    # Current NAV — force fresh (cashflow invalidates)
    await invalidate_parent_nav(parent_user_id)
    nav = await get_parent_nav(db, parent_user_id, force=True)
    if nav.nav_per_share <= 0:
        raise HTTPException(status_code=500, detail="NAV 计算失败")

    total_pre = nav.total_assets_usdt
    amt = Decimal(str(body.amount_usdt))
    shares_delta = (amt / nav.nav_per_share).quantize(Decimal("0.00000001"))
    if body.direction == 'withdraw':
        shares_delta = -shares_delta
        total_post = total_pre - amt
        if virtual_shares_pre + shares_delta < 0:
            raise HTTPException(status_code=400, detail="出金超出父账号份额，无法执行")
    else:
        total_post = total_pre + amt

    virtual_shares_post = virtual_shares_pre + shares_delta

    # Update share_state
    await db.execute(text(
        "UPDATE parent_share_state SET virtual_shares = :v, updated_at = NOW() "
        "WHERE parent_user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id, "v": float(virtual_shares_post)})

    # Record event
    evt = (await db.execute(text("""
        INSERT INTO parent_cashflow_events (
            parent_user_id, direction, amount_usdt,
            total_assets_pre, total_assets_post,
            virtual_shares_pre, virtual_shares_post,
            nav_at_event, shares_delta, note, created_by
        ) VALUES (
            CAST(:u AS UUID), :d, :a, :tp, :tpo, :vp, :vpo, :n, :sd, :note, CAST(:op AS UUID)
        ) RETURNING id, created_at
    """), {
        "u": parent_user_id, "d": body.direction, "a": float(amt),
        "tp": float(total_pre), "tpo": float(total_post),
        "vp": float(virtual_shares_pre), "vpo": float(virtual_shares_post),
        "n": float(nav.nav_per_share), "sd": float(shares_delta),
        "note": body.note, "op": operator_id,
    })).first()
    await db.commit()
    await invalidate_parent_nav(parent_user_id)

    logger.info(
        f"[parent-cashflow] parent={parent[1]} {body.direction} {amt} USDT @ NAV={nav.nav_per_share} "
        f"shares {virtual_shares_pre}→{virtual_shares_post} (Δ{shares_delta})"
    )

    return {
        "id": str(evt[0]),
        "parent_user_id": parent_user_id,
        "direction": body.direction,
        "amount_usdt": float(amt),
        "nav_at_event": float(nav.nav_per_share),
        "shares_delta": float(shares_delta),
        "virtual_shares_pre": float(virtual_shares_pre),
        "virtual_shares_post": float(virtual_shares_post),
        "total_assets_pre": float(total_pre),
        "total_assets_post": float(total_post),
        "note": body.note,
        "created_at": evt[1].isoformat() if evt[1] else "",
    }


@router.get("/users/{parent_user_id}/parent-cashflow")
async def list_parent_cashflow(
    parent_user_id: str,
    operator_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await _require_admin(db, operator_id)
    rows = (await db.execute(text("""
        SELECT id, direction, amount_usdt, total_assets_pre, total_assets_post,
               virtual_shares_pre, virtual_shares_post, nav_at_event, shares_delta,
               note, created_at
        FROM parent_cashflow_events
        WHERE parent_user_id = CAST(:u AS UUID)
        ORDER BY created_at DESC
        LIMIT 100
    """), {"u": parent_user_id})).fetchall()

    ps = (await db.execute(text(
        "SELECT virtual_shares, bootstrap_total_assets, created_at FROM parent_share_state WHERE parent_user_id = CAST(:u AS UUID)"
    ), {"u": parent_user_id})).first()

    return {
        "share_state": {
            "virtual_shares": float(ps[0]) if ps else None,
            "bootstrap_total_assets": float(ps[1]) if ps else None,
            "created_at": ps[2].isoformat() if ps and ps[2] else None,
        },
        "events": [
            {
                "id": str(r[0]), "direction": r[1], "amount_usdt": float(r[2]),
                "total_assets_pre": float(r[3]), "total_assets_post": float(r[4]),
                "virtual_shares_pre": float(r[5]), "virtual_shares_post": float(r[6]),
                "nav_at_event": float(r[7]), "shares_delta": float(r[8]),
                "note": r[9], "created_at": r[10].isoformat() if r[10] else "",
            } for r in rows
        ],
    }

