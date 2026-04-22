"""Sub-account NAV & share-based accounting.

Model: each parent user has a pool of "shares" against their total assets.
Parent holds an implicit 1.0 NAV at bootstrap; sub-accounts subscribe by
depositing CNY (converted to USDT once, frozen at creation) which buys
`shares = invested_usdt / current_nav_per_share`. Thereafter:
    sub_current_value_usdt = sub.shares * parent_nav_per_share_now
    multiplier             = sub_current_value_usdt / parent_total_assets_usdt

This keeps sub_value coupled to parent PnL without drift from parent
deposits/withdrawals (those are handled via future subscription writes,
not by mutating existing rows).
"""
from __future__ import annotations

import json
import logging
import time
import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)

_NAV_CACHE_PREFIX = "subacc:nav:"
_NAV_CACHE_TTL = 20  # seconds


@dataclass
class ParentNavSnapshot:
    parent_user_id: str
    total_assets_usdt: Decimal   # summed over parent's accounts
    total_shares: Decimal        # parent.virtual_shares + Σ(active subs.shares)
    nav_per_share: Decimal       # total_assets_usdt / total_shares
    computed_at: int             # unix seconds


async def _compute_parent_total_assets_usdt(db: AsyncSession, parent_user_id: str) -> Decimal:
    """Aggregate the parent's most recent account snapshots (USDT)."""
    row = (await db.execute(text("""
        SELECT COALESCE(SUM(total_assets), 0)
        FROM (
          SELECT DISTINCT ON (s.account_id) s.total_assets
          FROM account_snapshots s
          JOIN accounts a ON s.account_id = a.account_id
          WHERE a.user_id = CAST(:uid AS UUID)
          ORDER BY s.account_id, s.timestamp DESC
        ) q
    """), {"uid": parent_user_id})).first()
    return Decimal(str(row[0] or 0))


async def _sum_active_shares(db: AsyncSession, parent_user_id: str) -> Decimal:
    row = (await db.execute(text("""
        SELECT COALESCE(SUM(shares), 0)
        FROM sub_account_subscriptions
        WHERE parent_user_id = CAST(:uid AS UUID) AND status = 'active'
    """), {"uid": parent_user_id})).first()
    return Decimal(str(row[0] or 0))


async def _upsert_daily_snapshot(
    db: AsyncSession,
    parent_user_id: str,
    total_assets: Decimal,
    virtual_shares: Decimal,
    active_sub_shares: Decimal,
    nav_per_share: Decimal,
    *,
    source: str = 'lazy',
) -> None:
    """Write today's NAV snapshot for this parent. Last-write-wins per (parent, day).
    Fire-and-forget — catches all exceptions so callers aren't blocked."""
    try:
        await db.execute(text("""
            INSERT INTO subscription_daily_nav
              (parent_user_id, snapshot_date, nav_per_share, total_assets_usdt,
               virtual_shares, active_sub_shares, source)
            VALUES (CAST(:u AS UUID), (NOW() AT TIME ZONE 'Asia/Shanghai')::date,
                    :nav, :ta, :vs, :ass, :src)
            ON CONFLICT (parent_user_id, snapshot_date) DO UPDATE SET
              nav_per_share = EXCLUDED.nav_per_share,
              total_assets_usdt = EXCLUDED.total_assets_usdt,
              virtual_shares = EXCLUDED.virtual_shares,
              active_sub_shares = EXCLUDED.active_sub_shares,
              source = EXCLUDED.source,
              created_at = NOW()
        """), {
            "u": parent_user_id,
            "nav": float(nav_per_share),
            "ta": float(total_assets),
            "vs": float(virtual_shares),
            "ass": float(active_sub_shares),
            "src": source,
        })
        await db.commit()
    except Exception as e:
        logger.debug(f"[nav] daily snapshot upsert failed for {parent_user_id}: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


async def list_parent_daily_navs(
    db: AsyncSession,
    parent_user_id: str,
    start_date: str,
    end_date: str,
) -> list:
    """Returns [(snapshot_date, nav_per_share, total_assets, active_sub_shares), ...] in ascending date order."""
    rows = (await db.execute(text("""
        SELECT snapshot_date, nav_per_share, total_assets_usdt, active_sub_shares
        FROM subscription_daily_nav
        WHERE parent_user_id = CAST(:u AS UUID)
          AND snapshot_date BETWEEN :sd AND :ed
        ORDER BY snapshot_date ASC
    """), {"u": parent_user_id, "sd": start_date, "ed": end_date})).fetchall()
    return [(r[0], Decimal(str(r[1])), Decimal(str(r[2])), Decimal(str(r[3]))) for r in rows]


async def list_active_subscriptions_by_sub(
    db: AsyncSession,
    sub_user_id: str,
) -> list:
    """M2M: return ALL active subscriptions for a given sub user.
    [(id, parent_user_id, shares, invested_usdt, invested_cny, nav_per_share_at_join, created_at), ...]
    Ordered by shares DESC so primary = first."""
    rows = (await db.execute(text("""
        SELECT id, parent_user_id, shares, invested_usdt, invested_cny,
               nav_per_share_at_join, created_at
        FROM sub_account_subscriptions
        WHERE sub_user_id = CAST(:u AS UUID) AND status = 'active'
        ORDER BY shares DESC
    """), {"u": sub_user_id})).fetchall()
    return [
        (str(r[0]), str(r[1]), Decimal(str(r[2])),
         Decimal(str(r[3])), Decimal(str(r[4])),
         Decimal(str(r[5])) if r[5] is not None else Decimal('1'),
         r[6])
        for r in rows
    ]


async def get_parent_nav(db: AsyncSession, parent_user_id: str, *, force: bool = False) -> ParentNavSnapshot:
    """Return current NAV snapshot for a parent. 60s Redis cache."""
    key = _NAV_CACHE_PREFIX + parent_user_id
    if not force:
        try:
            rc = redis_client.client
            if rc is not None:
                raw = await rc.get(key)
                if raw:
                    d = json.loads(raw)
                    return ParentNavSnapshot(
                        parent_user_id=d["parent_user_id"],
                        total_assets_usdt=Decimal(d["total_assets_usdt"]),
                        total_shares=Decimal(d["total_shares"]),
                        nav_per_share=Decimal(d["nav_per_share"]),
                        computed_at=int(d["computed_at"]),
                    )
        except Exception as e:
            logger.debug(f"[nav] redis get failed: {e}")

    total_assets = await _compute_parent_total_assets_usdt(db, parent_user_id)
    active_sub_shares = await _sum_active_shares(db, parent_user_id)

    # Parent virtual shares now live in parent_share_state and are mint/burned
    # on explicit cashflow events (admin-logged via /api/v1/users/.../parent-cashflow).
    # Fallback: on first subscription creation we bootstrap with NAV=1.0 baseline
    # (handled in sub-account creation path, not here).
    row = (await db.execute(text(
        "SELECT virtual_shares FROM parent_share_state WHERE parent_user_id = CAST(:uid AS UUID)"
    ), {"uid": parent_user_id})).first()
    if row and row[0] is not None:
        parent_virtual_shares = Decimal(str(row[0]))
    else:
        # Legacy parents with subs but no share_state row: fallback to MIN of join snapshots
        row2 = (await db.execute(text("""
            SELECT COALESCE(MIN(parent_total_assets_at_join), 0)
            FROM sub_account_subscriptions
            WHERE parent_user_id = CAST(:uid AS UUID) AND status = 'active'
        """), {"uid": parent_user_id})).first()
        parent_virtual_shares = Decimal(str(row2[0] or 0)) or total_assets

    total_shares = parent_virtual_shares + active_sub_shares
    if total_shares <= 0:
        # No subs yet and no assets — NAV is undefined; return 1.0 placeholder
        nav = Decimal("1")
    else:
        nav = (total_assets / total_shares).quantize(Decimal("0.00000001"))

    snap = ParentNavSnapshot(
        parent_user_id=parent_user_id,
        total_assets_usdt=total_assets,
        total_shares=total_shares,
        nav_per_share=nav,
        computed_at=int(time.time()),
    )

    # Lazy daily-snapshot upsert — so if a user opens the app at 08:00 it's
    # recorded even before the 00:05 scheduler runs. No-op for non-positive NAV.
    if total_shares > 0 and total_assets > 0:
        try:
            await _upsert_daily_snapshot(
                db, parent_user_id, total_assets, parent_virtual_shares,
                active_sub_shares, nav, source='lazy'
            )
        except Exception:
            pass

    try:
        rc = redis_client.client
        if rc is not None:
            await rc.set(key, json.dumps({
                "parent_user_id": snap.parent_user_id,
                "total_assets_usdt": str(snap.total_assets_usdt),
                "total_shares": str(snap.total_shares),
                "nav_per_share": str(snap.nav_per_share),
                "computed_at": snap.computed_at,
            }), ex=_NAV_CACHE_TTL)
    except Exception as e:
        logger.debug(f"[nav] redis set failed: {e}")

    return snap


async def invalidate_parent_nav(parent_user_id: str) -> None:
    try:
        rc = redis_client.client
        if rc is not None:
            await rc.delete(_NAV_CACHE_PREFIX + parent_user_id)
    except Exception:
        pass


@dataclass
class ActiveSubscription:
    id: str
    sub_user_id: str
    parent_user_id: str
    shares: Decimal
    invested_usdt: Decimal
    invested_cny: Decimal


async def get_active_subscription(db: AsyncSession, sub_user_id: str) -> Optional[ActiveSubscription]:
    row = (await db.execute(text("""
        SELECT id, sub_user_id, parent_user_id, shares, invested_usdt, invested_cny
        FROM sub_account_subscriptions
        WHERE sub_user_id = CAST(:uid AS UUID) AND status = 'active'
        LIMIT 1
    """), {"uid": sub_user_id})).first()
    if not row:
        return None
    return ActiveSubscription(
        id=str(row[0]), sub_user_id=str(row[1]), parent_user_id=str(row[2]),
        shares=Decimal(str(row[3])),
        invested_usdt=Decimal(str(row[4])),
        invested_cny=Decimal(str(row[5])),
    )
