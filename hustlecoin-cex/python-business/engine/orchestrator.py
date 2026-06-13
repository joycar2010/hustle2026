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

    async def restart_worker(self, account_id: int):
        """单独重启某 worker(运维:卡死/心跳超时时无需整体停启)。取消并移除其 task,
        立即对账重建(若该账户仍启用或有在场持仓)。其余 worker 不受影响。"""
        w = self._workers.get(account_id)
        if w:
            logger.info(f"Restarting worker for sub-account {account_id}")
            try:
                await w.stop()
            except Exception:
                pass
            t = self._tasks.get(account_id)
            if t:
                t.cancel()
                try:
                    await asyncio.gather(t, return_exceptions=True)
                except Exception:
                    pass
            self._workers.pop(account_id, None)
            self._tasks.pop(account_id, None)
        else:
            logger.info(f"restart_worker: sub-account {account_id} 无在运行 worker,尝试对账拉起")
        try:
            await self._reconcile()
        except Exception as e:
            logger.error(f"restart_worker reconcile error: {e}")

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

    # 有这些状态在场的账户必须保有 worker(平仓/还币/资金费/风控都在 worker 循环里),
    # 即使准入规则(futures_enabled / hedge_via_master 回退)已不再放行它开新仓
    _IN_FLIGHT_STATUSES = (
        "OPEN", "BORROWED_IDLE", "PENDING_REPAY", "PENDING_BORROW", "BORROWED",
        "HEDGING", "SPOT_SOLD", "CLOSING_FUTURES", "FUTURES_CLOSED",
        "CLOSING_SPOT", "SPOT_BOUGHT", "REPAYING",
    )

    def _get_enabled_accounts(self) -> set[int]:
        db = SessionLocal()
        try:
            q = db.query(SubAccount.id).filter(
                SubAccount.is_enabled == True,
                SubAccount.margin_enabled == True,
            )
            # hedge_via_master: 合约腿在主账户,子 key 无需合约权限 —— 不再以
            # futures_enabled 作为 worker 准入条件(否则收回子 key 合约权限会连借币腿一起停摆)
            if not getattr(self.config.global_rules, "hedge_via_master", False):
                q = q.filter(SubAccount.futures_enabled == True)
            ids = {a.id for a in q.all()}

            # 在场持仓账户保留: 开关 True→False 回退后,futures_enabled=False 账户的
            # 存量 master 仓位不能失去 worker(否则无人触发 unhedge/repay,利息空烧)
            from engine.models import Position
            base = {a.id for a in db.query(SubAccount.id).filter(
                SubAccount.is_enabled == True, SubAccount.margin_enabled == True,
            ).all()}
            holders = {r.sub_account_id for r in db.query(Position.sub_account_id).filter(
                Position.status.in_(self._IN_FLIGHT_STATUSES),
            ).distinct().all()}
            ids |= (holders & base)
            return ids
        finally:
            db.close()
