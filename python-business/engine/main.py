import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
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


def _get_running_user_ids() -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(EngineState.user_id).filter(
            EngineState.scope == "global",
            EngineState.user_id.isnot(None),
            EngineState.status == "RUNNING",
        ).all()
        return {r.user_id for r in rows}
    finally:
        db.close()


def _update_user_global_state(user_id: int, status: str):
    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(
            EngineState.user_id == user_id, EngineState.scope == "global",
        ).first()
        if not state:
            state = EngineState(scope="global", user_id=user_id)
            db.add(state)
        state.status = status
        state.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
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
        state = db.query(EngineState).filter(
            EngineState.scope == "global", EngineState.user_id.is_(None),
        ).first()
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

    running_user_ids = _get_running_user_ids()
    if running_user_ids:
        for uid in running_user_ids:
            ue = UserEngine(uid, spread_feed)
            await ue.start()
            user_engines[uid] = ue
            logger.info(f"Recovered engine for user {uid} (was RUNNING)")
    else:
        active_user_ids = _get_active_user_ids()
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
    command_task = asyncio.create_task(_command_consumer_loop(user_engines, spread_feed, shutdown_event))

    await shutdown_event.wait()

    logger.info("Shutting down gracefully...")
    heartbeat_task.cancel()
    reconcile_task.cancel()
    command_task.cancel()

    for uid, ue in user_engines.items():
        await ue.stop()
        logger.info(f"Stopped engine for user {uid}")

    await spread_feed.stop()

    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(
            EngineState.scope == "global", EngineState.user_id.is_(None),
        ).first()
        if state:
            state.status = "STOPPED"
            state.last_heartbeat = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

    logger.info("Engine stopped")


async def _command_consumer_loop(
    user_engines: dict[int, UserEngine],
    spread_feed: SpreadFeed,
    shutdown_event: asyncio.Event,
):
    r = aioredis.from_url(settings.redis_url, decode_responses=True)

    while not shutdown_event.is_set():
        try:
            for uid in list(user_engines.keys()):
                if uid == 0:
                    continue
                key = f"engine:{uid}:commands"
                while True:
                    raw = await r.lpop(key)
                    if not raw:
                        break
                    cmd = json.loads(raw)
                    if cmd["action"] == "stop":
                        if uid in user_engines:
                            await user_engines[uid].stop()
                            del user_engines[uid]
                            logger.info(f"Stopped engine for user {uid} (user command)")
                            _update_user_global_state(uid, "STOPPED")
                    elif cmd["action"] == "start":
                        if uid not in user_engines:
                            ue = UserEngine(uid, spread_feed)
                            await ue.start()
                            user_engines[uid] = ue
                            logger.info(f"Started engine for user {uid} (user command)")
                            _update_user_global_state(uid, "RUNNING")

            keys = await r.keys("engine:*:commands")
            for key in keys:
                parts = key.split(":")
                if len(parts) == 3 and parts[1].isdigit():
                    uid = int(parts[1])
                    if uid in user_engines:
                        continue
                    raw = await r.lpop(key)
                    if not raw:
                        continue
                    cmd = json.loads(raw)
                    if cmd["action"] == "start":
                        ue = UserEngine(uid, spread_feed)
                        await ue.start()
                        user_engines[uid] = ue
                        logger.info(f"Started engine for user {uid} (user command)")
                        _update_user_global_state(uid, "RUNNING")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Command consumer error: {e}")

        await asyncio.sleep(3)

    await r.aclose()


async def _user_reconcile_loop(
    user_engines: dict[int, UserEngine],
    spread_feed: SpreadFeed,
    shutdown_event: asyncio.Event,
):
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(60)
            wanted_ids = _get_running_user_ids()
            running_ids = {uid for uid in user_engines if uid != 0}

            for uid in wanted_ids - running_ids:
                ue = UserEngine(uid, spread_feed)
                await ue.start()
                user_engines[uid] = ue
                logger.info(f"Auto-recovered engine for user {uid}")
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
                state = db.query(EngineState).filter(
                    EngineState.scope == "global", EngineState.user_id.is_(None),
                ).first()
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
