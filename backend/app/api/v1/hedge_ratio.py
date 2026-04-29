"Hedge ratio API - get/set hedge multiplier + user enable/disable"
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List
from app.core.database import get_db
from app.core.security import get_current_user_id
import json

router = APIRouter()

DEFAULT_MULTIPLIER_OPTIONS = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]


class HedgeRatioUpdate(BaseModel):
    hedge_multiplier: float
    pair_code: Optional[str] = "XAU"


class HedgeRatioToggle(BaseModel):
    user_id: str
    enabled: bool
    options: Optional[List[float]] = None


@router.get("/hedge-ratio")
async def get_hedge_ratio(
    pair_code: str = "XAU",
    target_user_id: str = Query(None, alias="user_id"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current hedge multiplier, enabled status, and available options."""
    lookup_uid = target_user_id or user_id
    row = (await db.execute(
        text("SELECT hedge_ratio_enabled, hedge_multiplier_options FROM users WHERE user_id=:uid"),
        {"uid": lookup_uid}
    )).fetchone()
    enabled = bool(row[0]) if row and row[0] else False
    options = row[1] if row and row[1] else DEFAULT_MULTIPLIER_OPTIONS
    if isinstance(options, str):
        options = json.loads(options)

    result = (await db.execute(
        text("SELECT hedge_multiplier FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
        {"uid": lookup_uid, "pc": pair_code}
    )).fetchone()
    multiplier = float(result[0]) if result and result[0] else 1.0

    return {
        "hedge_multiplier": multiplier,
        "pair_code": pair_code,
        "enabled": enabled,
        "options": options,
    }


@router.put("/hedge-ratio")
async def update_hedge_ratio(
    body: HedgeRatioUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update hedge multiplier. Validates against user-specific options."""
    # Load user's allowed options
    urow = (await db.execute(
        text("SELECT hedge_ratio_enabled, hedge_multiplier_options FROM users WHERE user_id=:uid"),
        {"uid": user_id}
    )).fetchone()
    if not (urow and urow[0]):
        raise HTTPException(status_code=403, detail="Hedge ratio adjustment not enabled for this user")

    valid = urow[1] if urow[1] else DEFAULT_MULTIPLIER_OPTIONS
    if isinstance(valid, str):
        valid = json.loads(valid)
    if body.hedge_multiplier not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid multiplier. Valid: {valid}")

    # Block modification while any continuous strategy is running
    from app.services.execution_task_manager import execution_task_manager
    for suffix in ['forward_opening_continuous', 'forward_closing_continuous',
                   'reverse_opening_continuous', 'reverse_closing_continuous']:
        sid = f"{user_id}_{suffix}"
        if execution_task_manager.get_running_task_id_for_strategy(sid):
            raise HTTPException(status_code=409, detail="\u7b56\u7565\u6267\u884c\u4e2d\uff0c\u65e0\u6cd5\u4fee\u6539\u5bf9\u51b2\u500d\u6570\u3002\u8bf7\u5148\u505c\u6b62\u7b56\u7565\u3002")

    row = (await db.execute(
        text("SELECT config_id FROM strategy_configs WHERE user_id=:uid AND pair_code=:pc LIMIT 1"),
        {"uid": user_id, "pc": body.pair_code}
    )).fetchone()

    if row:
        await db.execute(
            text("UPDATE strategy_configs SET hedge_multiplier=:hm, update_time=NOW() WHERE user_id=:uid AND pair_code=:pc"),
            {"hm": body.hedge_multiplier, "uid": user_id, "pc": body.pair_code}
        )
    else:
        await db.execute(
            text("""INSERT INTO strategy_configs (
                        config_id, user_id, strategy_type, pair_code,
                        target_spread, order_qty, retry_times, mt5_stuck_threshold,
                        is_enabled, opening_m_coin, closing_m_coin,
                        hedge_multiplier, create_time, update_time
                    ) VALUES (
                        gen_random_uuid(), CAST(:uid AS uuid), 'forward', :pc,
                        0, 0, 3, 30,
                        false, 5, 5,
                        :hm, NOW(), NOW()
                    )"""),
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
    """Admin: enable/disable hedge ratio and optionally set custom multiplier options."""
    if body.options is not None:
        opts_json = json.dumps(sorted(body.options))
        await db.execute(
            text("UPDATE users SET hedge_ratio_enabled=:enabled, hedge_multiplier_options=:opts WHERE user_id=:uid"),
            {"enabled": body.enabled, "opts": opts_json, "uid": body.user_id}
        )
    else:
        await db.execute(
            text("UPDATE users SET hedge_ratio_enabled=:enabled WHERE user_id=:uid"),
            {"enabled": body.enabled, "uid": body.user_id}
        )
    await db.commit()
    return {"user_id": body.user_id, "hedge_ratio_enabled": body.enabled}
