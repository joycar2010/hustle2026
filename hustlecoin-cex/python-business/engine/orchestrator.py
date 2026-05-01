import asyncio
import logging
from datetime import datetime, timezone

from app.db.models import SubAccount
from app.db.session import SessionLocal
from engine.models import EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.worker import Worker

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config_loader: ConfigLoader, spread_feed: SpreadFeed):
        self.config = config_loader
        self.spread_feed = spread_feed
        self._workers: dict[int, Worker] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._running = False
        self._paused = False
        self._paused_workers: set[int] = set()

    async def start(self):
        self._running = True
        asyncio.create_task(self._supervisor_loop())
        logger.info("Orchestrator started")

    async def stop(self):
        self._running = False
        for account_id, worker in list(self._workers.items()):
            logger.info(f"Stopping worker for sub-account {account_id}")
            await worker.stop()
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._workers.clear()
        self._tasks.clear()
        logger.info("Orchestrator stopped")

    async def pause(self, target: str = "global"):
        if target == "global":
            self._paused = True
            for account_id, worker in list(self._workers.items()):
                await worker.stop()
            self._tasks.clear()
            self._workers.clear()
            self._update_global_state("PAUSED")
            logger.info("Engine paused globally")
        else:
            sub_id = int(target.split(":")[1])
            if sub_id in self._workers:
                await self._workers[sub_id].stop()
                self._paused_workers.add(sub_id)
                logger.info(f"Worker {sub_id} paused")

    async def resume(self, target: str = "global"):
        if target == "global":
            self._paused = False
            self._paused_workers.clear()
            self._update_global_state("RUNNING")
            logger.info("Engine resumed — workers will respawn on next cycle")
        else:
            sub_id = int(target.split(":")[1])
            self._paused_workers.discard(sub_id)
            logger.info(f"Worker {sub_id} resumed — will respawn on next cycle")

    def _update_global_state(self, status: str):
        db = SessionLocal()
        try:
            state = db.query(EngineState).filter(EngineState.scope == "global").first()
            if state:
                state.status = status
                state.last_heartbeat = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    async def _supervisor_loop(self):
        while self._running:
            try:
                await self._reconcile()
            except Exception as e:
                logger.error(f"Supervisor error: {e}")
            await asyncio.sleep(10)

    async def _reconcile(self):
        if self._paused:
            return

        enabled_ids = await asyncio.to_thread(self._get_enabled_accounts)
        enabled_ids -= self._paused_workers

        for account_id in enabled_ids:
            if account_id in self._workers:
                task = self._tasks.get(account_id)
                if task and task.done():
                    exc = task.exception() if not task.cancelled() else None
                    if exc:
                        logger.error(f"Worker for sub-account {account_id} crashed: {exc}")
                    del self._workers[account_id]
                    del self._tasks[account_id]
                else:
                    continue

            logger.info(f"Spawning worker for sub-account {account_id}")
            worker = Worker(account_id, self.config, self.spread_feed)
            self._workers[account_id] = worker
            self._tasks[account_id] = asyncio.create_task(worker.run())

        for account_id in list(self._workers.keys()):
            if account_id not in enabled_ids:
                logger.info(f"Disabling worker for sub-account {account_id}")
                await self._workers[account_id].stop()
                self._tasks[account_id].cancel()
                del self._workers[account_id]
                del self._tasks[account_id]

    def _get_enabled_accounts(self) -> set[int]:
        db = SessionLocal()
        try:
            accounts = db.query(SubAccount.id).filter(
                SubAccount.is_enabled == True,
                SubAccount.margin_enabled == True,
                SubAccount.futures_enabled == True,
            ).all()
            return {a.id for a in accounts}
        finally:
            db.close()
