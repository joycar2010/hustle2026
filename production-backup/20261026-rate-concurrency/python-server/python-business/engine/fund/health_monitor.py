"""Periodic health checks with Feishu alerts for stuck positions and stale heartbeats."""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import SessionLocal
from engine.models import Position, EngineState
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

STUCK_STATUSES = {
    "PENDING_BORROW", "BORROW_SUBMITTING", "BORROW_OUTCOME_UNKNOWN",
    "BORROWED", "SPOT_SOLD",
    "CLOSING_FUTURES", "FUTURES_CLOSED", "CLOSING_SPOT", "SPOT_BOUGHT", "REPAYING",
}
STUCK_THRESHOLD_MIN = 10
IMMEDIATE_STUCK_STATUSES = {"BORROW_OUTCOME_UNKNOWN"}
HEARTBEAT_STALE_SEC = 120


def position_stuck_minutes(position, now: datetime) -> int:
    updated = position.updated_at or position.created_at
    if not updated:
        return 0
    if updated.tzinfo is None and now.tzinfo is not None:
        updated = updated.replace(tzinfo=timezone.utc)
    return max(0, int((now - updated).total_seconds() / 60))


def position_is_stuck(position, now: datetime) -> bool:
    status = str(getattr(position, "status", "") or "")
    if status not in STUCK_STATUSES:
        return False
    return (
        status in IMMEDIATE_STUCK_STATUSES
        or position_stuck_minutes(position, now) >= STUCK_THRESHOLD_MIN
    )


async def run_health_check(notifier: FeishuSender):
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        stuck_positions = db.query(Position).filter(
            Position.status.in_(STUCK_STATUSES),
        ).all()

        stuck_alerts = []
        for p in stuck_positions:
            if not position_is_stuck(p, now):
                continue
            stuck_alerts.append({
                "id": p.id,
                "symbol": p.symbol,
                "status": p.status,
                "stuck_minutes": position_stuck_minutes(p, now),
            })

        if stuck_alerts:
            logger.warning(f"Health check: {len(stuck_alerts)} stuck positions detected")
            await notifier.notify_stuck_positions(stuck_alerts)

        stale_workers = []
        workers = db.query(EngineState).filter(
            EngineState.scope != "global",
            EngineState.status == "RUNNING",
        ).all()
        for w in workers:
            if w.last_heartbeat:
                delta = (now - w.last_heartbeat).total_seconds()
                if delta > HEARTBEAT_STALE_SEC:
                    stale_workers.append({
                        "scope": w.scope,
                        "last_heartbeat": str(w.last_heartbeat),
                    })

        if stale_workers:
            logger.warning(f"Health check: {len(stale_workers)} stale workers detected")
            await notifier.notify_heartbeat_stale(stale_workers)

    except Exception as e:
        logger.error(f"Health check failed: {e}")
    finally:
        db.close()
