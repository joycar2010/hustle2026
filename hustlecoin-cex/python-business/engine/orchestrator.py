import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.db.models import SubAccount
from app.db.session import SessionLocal
from engine.models import EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.worker import Worker
from engine.fund.delisting_scanner import scan_delisting_announcements

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config_loader: ConfigLoader, spread_feed: SpreadFeed, user_id: int = None, shard_id: int | None = None):
        self.config = config_loader
        self.spread_feed = spread_feed
        self.user_id = user_id
        self.shard_id = shard_id
        self._workers: dict[int, Worker] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._running = False

    async def start(self):
        self._running = True
        await asyncio.to_thread(self._recover_stale_pending_borrow)
        asyncio.create_task(self._supervisor_loop())
        asyncio.create_task(self._delisting_scan_loop())
        logger.info("Orchestrator started")

    def _recover_stale_pending_borrow(self):
        """启动时回收僵尸 PENDING_BORROW:此状态是借币前的瞬态排队(尚未动用资金/下单),
        正常路径秒级转 BORROWED_IDLE/FAILED;若进程在此期间被 kill(重启),会永久卡住占位
        且 worker 视其为 active 不再重试。超龄(>2min)一律置 FAILED 释放占位(安全:无敞口)。"""
        from datetime import timedelta
        db = SessionLocal()
        try:
            from engine.models import Position
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
            q = db.query(Position).filter(Position.status == "PENDING_BORROW", Position.created_at < cutoff)
            if self.user_id is not None:
                q = q.filter(Position.user_id == self.user_id)
            stale = q.all()
            for p in stale:
                p.status = "FAILED"
                p.error_message = "stale PENDING_BORROW recovered on engine restart"
            if stale:
                db.commit()
                logger.warning(f"Recovered {len(stale)} stale PENDING_BORROW positions → FAILED")
        except Exception as e:
            logger.error(f"recover_stale_pending_borrow failed: {e}")
        finally:
            db.close()

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

        # Phase 2A: 简单均分 shard 给所有 worker
        SHARD_COUNT = settings.coin_shard_count
        enabled_list = sorted(enabled_ids)
        
        # Phase 2B: single-shard mode filtering
        if self.shard_id is not None:
            logger.info(f"Orchestrator: single-shard mode, running shard_id={self.shard_id}")
            # Only run the worker that handles this shard
            # Based on Phase 2A allocation: shard 0 → worker 9, shard 1 → worker 10, shard 2 → worker 9
            worker_for_shard = {0: 9, 1: 10, 2: 9}
            target_worker = worker_for_shard.get(self.shard_id)
            if target_worker and target_worker in enabled_ids:
                shard_allocation = {target_worker: [self.shard_id]}
                enabled_ids = {target_worker}
                enabled_list = [target_worker]
            else:
                logger.warning(f"Shard {self.shard_id} target worker {target_worker} not enabled, running nothing")
                shard_allocation = {}
                enabled_ids = set()
                enabled_list = []
        else:
            logger.info(f"Orchestrator: multi-shard mode, running all {SHARD_COUNT} shards")
            shard_allocation = {}
            if enabled_list:
                for idx, account_id in enumerate(enabled_list):
                    # 简单轮询分配: worker_0 → [0], worker_1 → [1], worker_2 → [2], worker_0 → [0], ...
                    # 如果只有2个worker, shard_count=3: worker_0 → [0, 2], worker_1 → [1]
                    assigned_shards = []
                    for shard_id in range(SHARD_COUNT):
                        if shard_id % len(enabled_list) == idx:
                            assigned_shards.append(shard_id)
                    shard_allocation[account_id] = assigned_shards

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
            worker = Worker(account_id, self.config, self.spread_feed, shard_ids=shard_allocation.get(account_id, []))
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
