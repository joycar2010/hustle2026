"""Hedge ratio API - get/set hedge multiplier + user enable/disable"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user_id

router = APIRouter()

VALID_MULTIPLIERS = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]


class HedgeRatioUpdate(BaseModel):
    hedge_multiplier: float
    pair_code: Optional[str] = "XAU"


class HedgeRatioToggle(BaseModel):
    user_id: str
    enabled: bool


@router.get("/hedge-ratio")
async def get_hedge_ratio(
    pair_code: str = "XAU",
    target_user_id: str = Query(None, alias="user_id"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current hedge multiplier and enabled status. Admin can query other users via ?user_id="""
    lookup_uid = target_user_id or user_id
    # Check if user has hedge_ratio_enabled
    enabled_result = await db.execute(
        text("SELECT hedge_ratio_enabled FROM users WHERE user_id=:uid"),
        {"uid": lookup_uid}
    )
    enabled_row = enabled_result.fetchone()
    enabled = bool(enabled_row[0]) if enabled_row and enabled_row[0] else False

    # Get multiplier from strategy_configs
    result = await db.execute(
        text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
        {"uid": lookup_uid, "pc": pair_code}
    )
    row = result.fetchone()
    multiplier = float(row[0]) if row and row[0] else 1.0

    return {"hedge_multiplier": multiplier, "pair_code": pair_code, "enabled": enabled}


@router.put("/hedge-ratio")
async def update_hedge_ratio(
    body: HedgeRatioUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update hedge multiplier. Only works if user has hedge_ratio_enabled=true."""
    if body.hedge_multiplier not in VALID_MULTIPLIERS:
        raise HTTPException(status_code=400, detail=f"Invalid multiplier. Valid: {VALID_MULTIPLIERS}")

    # Check if user is enabled
    enabled_result = await db.execute(
        text("SELECT hedge_ratio_enabled FROM users WHERE user_id=:uid"),
        {"uid": user_id}
    )
    enabled_row = enabled_result.fetchone()
    if not (enabled_row and enabled_row[0]):
        raise HTTPException(status_code=403, detail="Hedge ratio adjustment not enabled for this user")

    result = await db.execute(
        text("SELECT config_id FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
        {"uid": user_id, "pc": body.pair_code}
    )
    row = result.fetchone()

    if row:
        await db.execute(
            text("UPDATE strategy_configs SET hedge_multiplier=:hm, update_time=NOW() WHERE user_id=:uid AND pair_code=:pc"),
            {"hm": body.hedge_multiplier, "uid": user_id, "pc": body.pair_code}
        )
    else:
        await db.execute(
            text("""INSERT INTO strategy_configs (config_id, user_id, strategy_type, pair_code, target_spread, order_qty, hedge_multiplier, create_time, update_time)
                    VALUES (gen_random_uuid(), :uid::uuid, 'forward_opening', :pc, 0, 0, :hm, NOW(), NOW())"""),
            {"uid": user_id, "pc": body.pair_code, "hm": body.hedge_multiplier}
        )

    await db.commit()
    return {"hedge_multiplier": body.hedge_multiplier, "pair_code": body.pair_code, "status": "updated"}


@router.put("/hedge-ratio/toggle")
async def toggle_hedge_ratio(
    body: HedgeRatioToggle,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Admin: enable/disable hedge ratio adjustment for a user"""
    await db.execute(
        text("UPDATE users SET hedge_ratio_enabled=:enabled WHERE user_id=:uid"),
        {"enabled": body.enabled, "uid": body.user_id}
    )
    await db.commit()
    return {"user_id": body.user_id, "hedge_ratio_enabled": body.enabled}
