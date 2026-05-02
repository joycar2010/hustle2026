import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.db.models import SubAccount
from app.db.session import SessionLocal
from app.config import settings
from engine.models import EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.worker import Worker

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config_loader: ConfigLoader, spread_feed: SpreadFeed, user_id: int | None = None):
        self.config = config_loader
        self.spread_feed = spread_feed
        self.user_id = user_id
        self._workers: dict[int, Worker] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._running = False
        self._manual_pushed: set[str] = set()

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

    async def _supervisor_loop(self):
        while self._running:
            try:
                await asyncio.wait_for(self._reconcile(), timeout=30)
            except asyncio.TimeoutError:
                logger.error("Reconcile timed out after 30s")
            except Exception as e:
                logger.error(f"Reconcile error: {e}")

            try:
                await asyncio.wait_for(self.sync_pushed_to_redis(), timeout=10)
            except asyncio.TimeoutError:
                logger.error("Redis sync timed out after 10s")
            except Exception as e:
                logger.error(f"Redis sync error: {e}")

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

            logger.info(f"Spawning worker for sub-account {account_id} (user_id={self.user_id})")
            worker = Worker(account_id, self.config, self.spread_feed, user_id=self.user_id)
            self._workers[account_id] = worker
            self._tasks[account_id] = asyncio.create_task(worker.run())

        for account_id in list(self._workers.keys()):
            if account_id not in enabled_ids:
                logger.info(f"Disabling worker for sub-account {account_id}")
                await self._workers[account_id].stop()
                self._tasks[account_id].cancel()
                del self._workers[account_id]
                del self._tasks[account_id]

    def _redis_key(self, key: str) -> str:
        if self.user_id is not None:
            return f"engine:{self.user_id}:{key}"
        return f"engine:{key}"

    async def sync_pushed_to_redis(self):
        try:
            r = aioredis.from_url(settings.redis_url, decode_responses=True)

            cmd_key = self._redis_key("push_commands")
            pipe = r.pipeline()
            pipe.lrange(cmd_key, 0, -1)
            pipe.delete(cmd_key)
            results = await pipe.execute()
            raw_cmds = results[0]

            for raw in raw_cmds:
                try:
                    cmd = json.loads(raw)
                    action, symbol = cmd["action"], cmd["symbol"]
                    for w in self._workers.values():
                        if action == "push":
                            w._pushed_symbols.add(symbol)
                        elif action == "remove":
                            w._pushed_symbols.discard(symbol)
                    if action == "push":
                        self._manual_pushed.add(symbol)
                    elif action == "remove":
                        self._manual_pushed.discard(symbol)
                    logger.info(f"Executed push command: {action} {symbol}")
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Invalid push command: {raw} — {e}")

            all_symbols = set(self._manual_pushed)
            for w in self._workers.values():
                all_symbols.update(w._pushed_symbols)
            pushed_key = self._redis_key("pushed_symbols")
            await r.set(pushed_key, json.dumps(sorted(all_symbols)))

            await r.aclose()
        except Exception as e:
            logger.warning(f"Redis pushed symbols sync error: {e}")

    def _get_enabled_accounts(self) -> set[int]:
        db = SessionLocal()
        try:
            q = db.query(SubAccount.id).filter(
                SubAccount.is_enabled == True,
                SubAccount.margin_enabled == True,
                SubAccount.futures_enabled == True,
            )
            if self.user_id is not None:
                q = q.filter(SubAccount.user_id == self.user_id)
            accounts = q.all()
            return {a.id for a in accounts}
        finally:
            db.close()
