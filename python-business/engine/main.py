import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from app.db.models import Base, SubAccount
from app.db.session import engine as db_engine, SessionLocal
from app.db.models_auth import User
from engine.models import Position, TradeLog, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.orchestrator import Orchestrator

logger = logging.getLogger("engine")


class UserEngine:
    def __init__(self, user_id: int, spread_feed: SpreadFeed):
        self.user_id = user_id
        self.config_loader = ConfigLoader(user_id=user_id)
        self.orchestrator = Orchestrator(self.config_loader, spread_feed, user_id=user_id)

    async def start(self):
        await self.config_loader.start()
        await self.orchestrator.start()

    async def stop(self):
        await self.orchestrator.stop()
        await self.config_loader.stop()


def _get_active_user_ids() -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(SubAccount.user_id).filter(
            SubAccount.is_enabled == True,
            SubAccount.user_id.isnot(None),
        ).distinct().all()
        return {r.user_id for r in rows}
    finally:
        db.close()


async def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    logger.info("CEX Arbitrage Engine starting (pid=%d)", os.getpid())

    Base.metadata.create_all(bind=db_engine)
    logger.info("Database tables ensured")

    spread_feed = SpreadFeed()
    shutdown_event = asyncio.Event()

    def _shutdown(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(EngineState.scope == "global").first()
        if not state:
            state = EngineState(scope="global")
            db.add(state)
        state.status = "RUNNING"
        state.pid = os.getpid()
        state.started_at = datetime.now(timezone.utc)
        state.last_heartbeat = datetime.now(timezone.utc)
        state.error_message = None
        db.commit()
    finally:
        db.close()

    await spread_feed.start()

    user_engines: dict[int, UserEngine] = {}
    active_user_ids = _get_active_user_ids()

    for uid in active_user_ids:
        ue = UserEngine(uid, spread_feed)
        await ue.start()
        user_engines[uid] = ue
        logger.info(f"Started engine for user {uid}")

    if not active_user_ids:
        ue = UserEngine(None, spread_feed)
        await ue.start()
        user_engines[0] = ue
        logger.info("Started legacy engine (no user_id)")

    logger.info(
        "Engine running: %d spreads, %d user engines",
        spread_feed.count,
        len(user_engines),
    )

    heartbeat_task = asyncio.create_task(_heartbeat_loop(shutdown_event))
    reconcile_task = asyncio.create_task(_user_reconcile_loop(user_engines, spread_feed, shutdown_event))

    await shutdown_event.wait()

    logger.info("Shutting down gracefully...")
    heartbeat_task.cancel()
    reconcile_task.cancel()

    for uid, ue in user_engines.items():
        await ue.stop()
        logger.info(f"Stopped engine for user {uid}")

    await spread_feed.stop()

    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(EngineState.scope == "global").first()
        if state:
            state.status = "STOPPED"
            state.last_heartbeat = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

    logger.info("Engine stopped")


async def _user_reconcile_loop(user_engines: dict[int, UserEngine], spread_feed: SpreadFeed, shutdown_event: asyncio.Event):
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(60)
            current_ids = _get_active_user_ids()
            running_ids = {uid for uid in user_engines if uid != 0}

            for uid in current_ids - running_ids:
                ue = UserEngine(uid, spread_feed)
                await ue.start()
                user_engines[uid] = ue
                logger.info(f"Auto-started engine for new user {uid}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"User reconcile error: {e}")


async def _heartbeat_loop(shutdown_event: asyncio.Event):
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(10)
            db = SessionLocal()
            try:
                state = db.query(EngineState).filter(EngineState.scope == "global").first()
                if state:
                    state.last_heartbeat = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")


def run():
    asyncio.run(_main())
