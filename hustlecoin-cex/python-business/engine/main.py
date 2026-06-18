import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import Base, SubAccount, GlobalRules
from app.db.session import engine as db_engine, SessionLocal
from app.db.models_auth import User
from engine.models import Position, TradeLog, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.orchestrator import Orchestrator

logger = logging.getLogger("engine")

# 在途账户清理任务(clear_account 命令派生) —— 停机时先排空再关 client,防 use-after-close
_clear_tasks: set[asyncio.Task] = set()


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


def _get_auto_start_user_ids() -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(GlobalRules.user_id).filter(
            GlobalRules.auto_start_on_boot == True,
            GlobalRules.user_id.isnot(None),
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

    # C1: auto_start_on_boot — auto-start engines for users with this flag
    auto_start_ids = _get_auto_start_user_ids()
    for uid in auto_start_ids:
        if uid in user_engines:
            continue
        logger.info(f"Auto-starting engine for user {uid} (auto_start_on_boot=true)")
        await asyncio.sleep(1)
        ue = UserEngine(uid, spread_feed)
        await ue.start()
        user_engines[uid] = ue
        _update_user_global_state(uid, "RUNNING")

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

    # 在途清仓任务是多腿交易,必须完整结束后才能关 worker/master client
    if _clear_tasks:
        logger.info(f"Waiting for {len(_clear_tasks)} in-flight clear task(s)...")
        done, pending = await asyncio.wait(set(_clear_tasks), timeout=60)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    for uid, ue in user_engines.items():
        await ue.stop()
        logger.info(f"Stopped engine for user {uid}")

    from engine.trading.master_client import close_all as close_master_clients
    await close_master_clients()
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
                    elif cmd["action"] == "clear_account":
                        account_id = cmd.get("account_id")
                        if account_id and uid in user_engines:
                            orch = user_engines[uid].orchestrator
                            t = asyncio.create_task(
                                _clear_account_positions(orch, account_id)
                            )
                            _clear_tasks.add(t)
                            t.add_done_callback(_clear_tasks.discard)
                    elif cmd["action"] == "restart_worker":
                        account_id = cmd.get("account_id")
                        if account_id and uid in user_engines:
                            orch = user_engines[uid].orchestrator
                            asyncio.create_task(orch.restart_worker(account_id))

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


async def _clear_account_positions(orchestrator: Orchestrator, account_id: int):
    worker = orchestrator._workers.get(account_id)
    if not worker or not worker._trading_client:
        logger.warning(f"No active worker for account {account_id}, cannot clear positions")
        db = SessionLocal()
        try:
            from engine.models import Position as PositionModel
            db.query(PositionModel).filter(
                PositionModel.sub_account_id == account_id,
                PositionModel.status == "OPEN",
            ).update({"status": "FORCE_CLOSED", "error_message": "account cleared (no active worker)"})
            db.commit()
        finally:
            db.close()
        return

    from engine.trading.order_executor import execute_close
    from engine.notify.feishu_sender import FeishuSender

    notifier = worker._notifier or FeishuSender()
    account_note = f"#{account_id}"
    try:
        account_info = await asyncio.to_thread(worker._load_account)
        if account_info:
            account_note = account_info["note"]
    except Exception:
        pass

    positions = await asyncio.to_thread(worker._load_open_positions)
    spread_feed = orchestrator.spread_feed

    for pos in positions:
        spread = spread_feed.get_symbol(pos.symbol)
        if not spread:
            logger.warning(f"No spread for {pos.symbol}, skipping close")
            continue
        try:
            fc = None
            if getattr(pos, "hedge_account", None) == "master":
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(orchestrator.user_id)
            await execute_close(pos, spread, worker._trading_client, notifier, account_note,
                                futures_client=fc)
            logger.info(f"Cleared position {pos.symbol} for account {account_id}")
        except Exception as e:
            logger.error(f"Failed to clear position {pos.symbol}: {e}")

    await notifier.send("账户清理完成", f"账户: {account_note}\n已平仓 {len(positions)} 个持仓")
    logger.info(f"Account {account_id} clearing complete")


def run():
    asyncio.run(_main())
