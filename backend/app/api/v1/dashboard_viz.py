"""Dashboard visualization API endpoints for admin panel charts."""
from fastapi import APIRouter, Depends, Query
from app.core.security import get_current_user
from app.core.database import AsyncSessionLocal
from sqlalchemy import text
from datetime import datetime, timedelta
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/dashboard/sparkline")
async def get_dashboard_sparkline(
    hours: int = Query(24, ge=1, le=168),
    interval: str = Query("1h", regex="^(15m|30m|1h|4h|1d)$"),
    current_user=Depends(get_current_user),
):
    """Return aggregated net asset time series for sparkline chart."""
    interval_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    bucket_minutes = interval_map.get(interval, 60)
    since = datetime.utcnow() - timedelta(hours=hours)

    try:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(text("""
                SELECT
                    date_trunc('hour', s.timestamp) + 
                    (EXTRACT(minute FROM s.timestamp)::int / :bucket * interval '1 minute' * :bucket) AS bucket_time,
                    SUM(s.net_assets) AS total_equity,
                    SUM(s.balance) AS total_balance,
                    SUM(s.daily_pnl) AS total_pnl
                FROM account_snapshots s
                WHERE s.timestamp >= :since
                GROUP BY bucket_time
                ORDER BY bucket_time
            """), {"bucket": bucket_minutes, "since": since})

            data = []
            for row in rows.fetchall():
                data.append({
                    "time": row[0].isoformat() if row[0] else None,
                    "equity": round(float(row[1] or 0), 2),
                    "balance": round(float(row[2] or 0), 2),
                    "pnl": round(float(row[3] or 0), 2),
                })
            return {"interval": interval, "hours": hours, "data": data}
    except Exception as e:
        logger.error(f"sparkline query error: {e}")
        return {"interval": interval, "hours": hours, "data": []}


@router.get("/dashboard/pnl-history")
async def get_dashboard_pnl_history(
    days: int = Query(7, ge=1, le=90),
    current_user=Depends(get_current_user),
):
    """Return daily PnL aggregated across all accounts for bar chart."""
    since = datetime.utcnow() - timedelta(days=days)

    try:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(text("""
                SELECT
                    date_trunc('day', s.timestamp) AS day,
                    SUM(s.daily_pnl) AS total_pnl,
                    COUNT(DISTINCT s.account_id) AS account_count
                FROM account_snapshots s
                WHERE s.timestamp >= :since
                GROUP BY day
                ORDER BY day
            """), {"since": since})

            data = []
            for row in rows.fetchall():
                data.append({
                    "date": row[0].strftime("%Y-%m-%d") if row[0] else None,
                    "pnl": round(float(row[1] or 0), 2),
                    "accounts": int(row[2] or 0),
                })
            return {"days": days, "data": data}
    except Exception as e:
        logger.error(f"pnl-history query error: {e}")
        return {"days": days, "data": []}


@router.get("/dashboard/platform-distribution")
async def get_platform_distribution(
    current_user=Depends(get_current_user),
):
    """Return current asset distribution by platform for donut chart."""
    try:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(text("""
                SELECT
                    a.platform_id,
                    COALESCE(
                        CASE a.platform_id
                            WHEN 1 THEN 'Binance'
                            WHEN 2 THEN 'Bybit'
                            WHEN 3 THEN 'IC Markets'
                            WHEN 4 THEN 'Gate.io'
                            WHEN 5 THEN 'OKX'
                            ELSE 'Other'
                        END, 'Unknown'
                    ) AS platform_name,
                    COUNT(*) AS account_count,
                    SUM(s.net_assets) AS total_equity
                FROM accounts a
                LEFT JOIN LATERAL (
                    SELECT net_assets FROM account_snapshots
                    WHERE account_id = a.account_id
                    ORDER BY timestamp DESC LIMIT 1
                ) s ON true
                WHERE a.is_active = true
                GROUP BY a.platform_id
                ORDER BY total_equity DESC NULLS LAST
            """))

            data = []
            for row in rows.fetchall():
                data.append({
                    "platform_id": row[0],
                    "platform_name": row[1],
                    "account_count": int(row[2] or 0),
                    "total_equity": round(float(row[3] or 0), 2),
                })
            return {"data": data}
    except Exception as e:
        logger.error(f"platform-distribution query error: {e}")
        return {"data": []}
