import asyncio
import logging
from datetime import datetime, timezone

from app.db.models import SubAccount
from app.db.session import SessionLocal
from engine.models import EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.worker import Worker
from engine.fund.delisting_scanner import scan_delisting_announcements

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config_loader: ConfigLoader, spread_feed: SpreadFeed, user_id: int = None):
        self.config = config_loader
        self.spread_feed = spread_feed
        self.user_id = user_id
        self._workers: dict[int, Worker] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._running = False

    async def start(self):
        self._running = True
        asyncio.create_task(self._supervisor_loop())
        asyncio.create_task(self._delisting_scan_loop())
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

    async def _supervisor_loop(self):
        while self._running:
            try:
                await self._reconcile()
            except Exception as e:
                logger.error(f"Supervisor error: {e}")
            await asyncio.sleep(10)

    async def _reconcile(self):
        enabled_ids = await asyncio.to_thread(self._get_enabled_accounts)

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

    async def _delisting_scan_loop(self):
        await asyncio.sleep(30)
        while self._running:
            try:
                flagged = await scan_delisting_announcements()
                if flagged:
                    logger.warning(f"Delisting scan flagged: {flagged}")
            except Exception as e:
                logger.error(f"Delisting scan error: {e}")
            await asyncio.sleep(300)

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
