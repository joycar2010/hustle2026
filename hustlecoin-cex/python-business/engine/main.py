import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import Base
from app.db.session import engine as db_engine, SessionLocal
from engine.models import Position, TradeLog, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.orchestrator import Orchestrator

logger = logging.getLogger("engine")


async def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    logger.info("CEX Arbitrage Engine starting (pid=%d)", os.getpid())

    Base.metadata.create_all(bind=db_engine)
    logger.info("Database tables ensured")

    config_loader = ConfigLoader()
    spread_feed = SpreadFeed()
    orchestrator = Orchestrator(config_loader, spread_feed)

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

    await config_loader.start()
    await spread_feed.start()
    await orchestrator.start()

    logger.info(
        "Engine running: %d spreads, %d blacklisted, open_spread=%s%%",
        spread_feed.count,
        len(config_loader.blacklist),
        config_loader.global_rules.open_spread,
    )

    heartbeat_task = asyncio.create_task(_heartbeat_loop(shutdown_event))
    command_task = asyncio.create_task(_command_listener(orchestrator, shutdown_event))

    await shutdown_event.wait()

    logger.info("Shutting down gracefully...")
    heartbeat_task.cancel()
    command_task.cancel()
    await orchestrator.stop()
    await spread_feed.stop()
    await config_loader.stop()

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


async def _command_listener(orchestrator: Orchestrator, shutdown_event: asyncio.Event):
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("engine:commands")
    try:
        async for msg in pubsub.listen():
            if shutdown_event.is_set():
                break
            if msg["type"] != "message":
                continue
            try:
                data = json.loads(msg["data"])
                action = data.get("action")
                target = data.get("target", "global")
                logger.info(f"Received command: {action} target={target}")
                if action == "pause":
                    await orchestrator.pause(target)
                elif action == "resume":
                    await orchestrator.resume(target)
                elif action == "stop":
                    shutdown_event.set()
            except Exception as e:
                logger.warning(f"Command parse error: {e}")
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe("engine:commands")
        await r.aclose()


def run():
    asyncio.run(_main())
