"""API endpoints for hedge batch order records."""
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.hedge_batch_record import HedgeBatchRecord

router = APIRouter(prefix="/api/v1/trading/hedge-records", tags=["hedge-records"])


@router.get("")
async def list_hedge_records(
    pair_code: str = Query(...),
    strategy_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days: int = Query(2, ge=1, le=30),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    filters = [
        HedgeBatchRecord.user_id == uuid.UUID(user_id),
        HedgeBatchRecord.pair_code == pair_code,
        HedgeBatchRecord.create_time >= datetime.utcnow() - timedelta(days=days),
    ]
    if strategy_type:
        filters.append(HedgeBatchRecord.strategy_type == strategy_type)
    if status:
        filters.append(HedgeBatchRecord.status == status)

    result = await db.execute(
        select(HedgeBatchRecord)
        .where(and_(*filters))
        .order_by(HedgeBatchRecord.order_time.desc())
        .limit(100)
    )
    records = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "pair_code": r.pair_code,
            "strategy_type": r.strategy_type,
            "batch_no": r.batch_no,
            "order_time": r.order_time.isoformat() if r.order_time else None,
            "hedge_price": r.hedge_price,
            "hedge_qty": r.hedge_qty,
            "direction": r.direction,
            "status": r.status,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
        for r in records
    ]


@router.post("/close-batch")
async def close_batch_records(
    pair_code: str = Query(...),
    strategy_type: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Mark all open records for a pair+strategy as closed (called on position close)."""
    await db.execute(
        update(HedgeBatchRecord)
        .where(and_(
            HedgeBatchRecord.user_id == uuid.UUID(user_id),
            HedgeBatchRecord.pair_code == pair_code,
            HedgeBatchRecord.strategy_type == strategy_type,
            HedgeBatchRecord.status == "open",
        ))
        .values(status="closed", closed_at=datetime.utcnow())
    )
    await db.commit()
    return {"success": True}
