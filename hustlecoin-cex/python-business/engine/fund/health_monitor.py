"""Periodic health checks with Feishu alerts for stuck positions and stale heartbeats."""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import SessionLocal
from engine.models import Position, EngineState
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

STUCK_STATUSES = {
    "PENDING_BORROW", "BORROWED", "SPOT_SOLD",
    "CLOSING_FUTURES", "FUTURES_CLOSED", "CLOSING_SPOT", "SPOT_BOUGHT", "REPAYING",
}
STUCK_THRESHOLD_MIN = 10
HEARTBEAT_STALE_SEC = 120


async def run_health_check(notifier: FeishuSender):
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        stuck_positions = db.query(Position).filter(
            Position.status.in_(STUCK_STATUSES),
        ).all()

        stuck_alerts = []
        for p in stuck_positions:
            updated = p.updated_at or p.created_at
            if not updated:
                continue
            mins = int((now - updated).total_seconds() / 60)
            if mins >= STUCK_THRESHOLD_MIN:
                stuck_alerts.append({
                    "id": p.id,
                    "symbol": p.symbol,
                    "status": p.status,
                    "stuck_minutes": mins,
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
