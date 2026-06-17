"""Execution Task Manager - Manages background continuous execution tasks"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime
from uuid import uuid4

from app.services.continuous_executor import ContinuousStrategyExecutor


logger = logging.getLogger(__name__)


class ExecutionTaskManager:
    """Manages background execution tasks for continuous strategy execution"""

    def __init__(self):
        self.tasks: Dict[str, asyncio.Task] = {}
        self.executors: Dict[str, ContinuousStrategyExecutor] = {}
        self.task_info: Dict[str, Dict] = {}
        # Maps strategy_id -> task_id for active (running) tasks
        self._strategy_to_task: Dict[str, str] = {}

    def get_running_task_id_for_strategy(self, strategy_id: str) -> Optional[str]:
        """Return the task_id of the currently running task for this strategy_id, or None."""
        task_id = self._strategy_to_task.get(strategy_id)
        if task_id is None:
            return None
        task = self.tasks.get(task_id)
        if task is None or task.done():
            # Task already finished — clean up stale mapping
            self._strategy_to_task.pop(strategy_id, None)
            return None
        return task_id

    def _stop_executor_sync(self, task_id: str) -> None:
        """Signal executor to stop and cancel the asyncio task (non-awaited)."""
        if task_id in self.executors:
            self.executors[task_id].stop()
        if task_id in self.tasks:
            self.tasks[task_id].cancel()

    def start_task(
        self,
        executor: ContinuousStrategyExecutor,
        coro,
        task_id: Optional[str] = None
    ) -> str:
        """
        Start background execution task.

        If a task for the same strategy_id is already running it is stopped
        first to prevent duplicate orders.

        Args:
            executor: Continuous strategy executor instance
            coro: Coroutine to execute
            task_id: Optional task ID (generates UUID if not provided)

        Returns:
            Task ID
        """
        if task_id is None:
            task_id = str(uuid4())

        # ── Duplicate-prevention: stop any existing running task for this strategy ──
        existing_task_id = self.get_running_task_id_for_strategy(executor.strategy_id)
        if existing_task_id is not None:
            logger.error(
                f"TASK MANAGER: strategy_id={executor.strategy_id} already has running task "
                f"{existing_task_id} — stopping it before starting new task {task_id}"
            )
            self._stop_executor_sync(existing_task_id)
            # Mark as cancelled in task_info so frontend polling sees it
            if existing_task_id in self.task_info:
                self.task_info[existing_task_id]['status'] = 'cancelled'
                self.task_info[existing_task_id]['completed_at'] = datetime.utcnow().isoformat()
            self._strategy_to_task.pop(executor.strategy_id, None)

        logger.error("=" * 80)
        logger.error(f"TASK MANAGER: Creating task {task_id}")
        logger.error(f"Executor strategy_id: {executor.strategy_id}")
        logger.error(f"Coroutine: {coro}")
        logger.error("=" * 80)

        # Create and store task
        task = asyncio.create_task(coro)
        self.tasks[task_id] = task
        self.executors[task_id] = executor
        self.task_info[task_id] = {
            'task_id': task_id,
            'strategy_id': executor.strategy_id,
            'started_at': datetime.utcnow().isoformat(),
            'status': 'running'
        }
        self._strategy_to_task[executor.strategy_id] = task_id

        # Add callback to update status when task completes
        task.add_done_callback(lambda t: self._on_task_complete(task_id, t))

        # 心跳看门狗(20260617,方案B): 监控 executor._last_heartbeat, 若循环挂死(长时间不更新)
        # 则强制 cancel 并标记 hung->自动重启(走 _recover_crashed_strategy 同链路)。
        # 解决"已有超时的await仍在底层(httpx/socks5 C层)卡死、wait_for救不了"的根本问题。
        try:
            self._hung_task_ids = getattr(self, "_hung_task_ids", set())
            wd = asyncio.create_task(self._heartbeat_watchdog(task_id, executor))
            self._watchdogs = getattr(self, "_watchdogs", {})
            self._watchdogs[task_id] = wd
        except RuntimeError:
            pass

        logger.info(f"Started execution task {task_id} for strategy {executor.strategy_id}")
        logger.error(f"TASK MANAGER: Task {task_id} created and started")
        return task_id

    def _on_task_complete(self, task_id: str, task: asyncio.Task):
        """Callback when task completes"""
        # 退役该task的看门狗
        try:
            _wd = getattr(self, "_watchdogs", {}).pop(task_id, None)
            if _wd is not None and not _wd.done():
                _wd.cancel()
        except Exception:
            pass
        logger.error("=" * 80)
        logger.error(f"TASK MANAGER: Task {task_id} completed")
        logger.error(f"Cancelled: {task.cancelled()}")
        logger.error(f"Exception: {task.exception() if not task.cancelled() else 'N/A'}")
        logger.error("=" * 80)

        if task_id in self.task_info:
            self.task_info[task_id]['completed_at'] = datetime.utcnow().isoformat()

            if task.cancelled():
                self.task_info[task_id]['status'] = 'cancelled'
                logger.info(f"Task {task_id} was cancelled")
                # 心跳看门狗标记的挂死cancel: 走自恢复(方案B), 区别于用户手动停的cancel
                _hung = getattr(self, "_hung_task_ids", set())
                if task_id in _hung:
                    _hung.discard(task_id)
                    _sid = self.task_info[task_id].get('strategy_id')
                    try:
                        _started = datetime.fromisoformat(self.task_info[task_id]['started_at']) if self.task_info[task_id].get('started_at') else None
                        _up = (datetime.utcnow() - _started).total_seconds() if _started else 999.0
                    except Exception:
                        _up = 999.0
                    try:
                        asyncio.create_task(self._recover_crashed_strategy(_sid, max(_up, 60.0)))  # >=60s 确保走重放分支
                        logger.info(f"[HB_WATCHDOG] {_sid} 挂死cancel已交自恢复重放")
                    except RuntimeError:
                        pass
            elif task.exception():
                self.task_info[task_id]['status'] = 'failed'
                self.task_info[task_id]['error'] = str(task.exception())
                logger.error(f"Task {task_id} failed: {task.exception()}")
            else:
                self.task_info[task_id]['status'] = 'completed'
                logger.info(f"Task {task_id} completed successfully")

        # ── 崩溃静默自恢复: 仅当任务因【未捕获异常】结束(status='failed')才处理 ──
        # 'cancelled'(手动/收盘硬停) 与 'completed'(容量满/优雅停 stop_requested) 均不触发, 故不误伤正常退出。
        # 运行≥60s后偶发崩溃→标记待恢复(交 StrategyResumeMonitor 开市+未在跑时用快照回放);
        # <60s 启动即崩多为持久故障(密钥/IP/配置)→不自动循环以免崩溃风暴, 仅记日志。全程不通知用户。
        info = self.task_info.get(task_id)
        if info and info.get('status') == 'failed':
            try:
                _started = datetime.fromisoformat(info['started_at']) if info.get('started_at') else None
                _uptime = (datetime.utcnow() - _started).total_seconds() if _started else 0.0
            except Exception:
                _uptime = 0.0
            try:
                asyncio.create_task(self._recover_crashed_strategy(info.get('strategy_id'), _uptime))
            except RuntimeError:
                pass  # 无运行中的事件循环, 跳过

        # Remove from active strategy map when task ends
        strategy_id = self.task_info.get(task_id, {}).get('strategy_id')
        if strategy_id and self._strategy_to_task.get(strategy_id) == task_id:
            self._strategy_to_task.pop(strategy_id, None)

    async def _recover_crashed_strategy(self, strategy_id, uptime_sec: float):
        """连续策略任务因崩溃(未捕获异常)结束后的【静默】自恢复。不通知用户, 仅记后端日志。

        - uptime≥60s: 视为运行中偶发崩溃 → mark_resume_pending, 由 StrategyResumeMonitor
          在 开市+预热+当前未在跑+有快照 时用快照原样回放(按实际持仓算 remaining, 不会重复多开)。
        - uptime<60s: 启动即崩多为持久故障(币安密钥/IP白名单/配置) → 不自动循环, 仅告警日志, 避免崩溃风暴。
        """
        try:
            from app.services.strategy_resume_service import _parse_strategy_id, mark_resume_pending
            user_id, pair_code, action = _parse_strategy_id(strategy_id or "")
            if not user_id:
                return
            if uptime_sec >= 60.0:
                await mark_resume_pending(user_id, pair_code, action)
                logger.info(
                    f"[CRASH_RECOVERY] {strategy_id} crashed after {uptime_sec:.0f}s — "
                    f"marked pending for silent auto-resume"
                )
            else:
                logger.warning(
                    f"[CRASH_RECOVERY] {strategy_id} crashed within {uptime_sec:.0f}s (<60s) — "
                    f"likely persistent fault, NOT auto-resuming (check keys/IP/config)"
                )
        except Exception as e:
            logger.error(f"[CRASH_RECOVERY] handler failed for {strategy_id}: {e}")

    # 挂死自愈速率限制(20260617): {strategy_id: [最近cancel时刻...]}, 15min窗口内最多 _HUNG_MAX_RESTARTS 次,
    # 超限则只cancel不重启(避免持续性故障如桥长期不可达导致重启风暴)。
    _HUNG_WINDOW_SEC = 900.0
    _HUNG_MAX_RESTARTS = 3

    def _hung_restart_allowed(self, strategy_id: str) -> bool:
        import time as _t
        self._hung_restart_hist = getattr(self, "_hung_restart_hist", {})
        now = _t.monotonic()
        hist = [t for t in self._hung_restart_hist.get(strategy_id, []) if now - t < self._HUNG_WINDOW_SEC]
        if len(hist) >= self._HUNG_MAX_RESTARTS:
            self._hung_restart_hist[strategy_id] = hist
            return False
        hist.append(now)
        self._hung_restart_hist[strategy_id] = hist
        return True

    async def _heartbeat_watchdog(self, task_id: str, executor):
        """监控单个 task 的循环心跳; 挂死->cancel+标记hung(供_on_task_complete走自恢复)。"""
        import time as _t
        CHECK_INTERVAL = 15.0     # 每15s查一次
        HUNG_THRESHOLD = 90.0     # 心跳停滞>90s判挂死(正常每轮<10s; 留足偶发慢交易余量)
        GRACE_AFTER_START = 30.0  # 启动后宽限(首轮初始化/取数)
        _start = _t.monotonic()
        try:
            while True:
                await asyncio.sleep(CHECK_INTERVAL)
                t = self.tasks.get(task_id)
                if t is None or t.done():
                    return  # task 已结束, 看门狗退役
                hb = getattr(executor, "_last_heartbeat", None)
                now = _t.monotonic()
                if hb is None:
                    if now - _start > (GRACE_AFTER_START + HUNG_THRESHOLD):
                        # 启动后迟迟无任何心跳=启动阶段就挂死
                        pass
                    else:
                        continue
                elif (now - hb) < HUNG_THRESHOLD:
                    continue  # 心跳新鲜, 正常
                # ── 判定挂死 ──
                sid = self.task_info.get(task_id, {}).get("strategy_id")
                stale = (now - hb) if hb is not None else (now - _start)
                allow = self._hung_restart_allowed(sid or task_id)
                self._hung_task_ids = getattr(self, "_hung_task_ids", set())
                if allow:
                    self._hung_task_ids.add(task_id)  # 标记: _on_task_complete 据此走自恢复
                    logger.error(
                        f"[HB_WATCHDOG] Task {task_id} ({sid}) 循环挂死(心跳停滞{stale:.0f}s>{HUNG_THRESHOLD:.0f}s) "
                        f"-> 强制cancel + 自动重启(方案B)"
                    )
                else:
                    logger.error(
                        f"[HB_WATCHDOG] Task {task_id} ({sid}) 再次挂死但15min内重启已达上限"
                        f"({self._HUNG_MAX_RESTARTS}次) -> 仅cancel不重启(疑似持续性故障, 请排查)"
                    )
                t.cancel()
                return
        except asyncio.CancelledError:
            return
        except Exception as _e:
            logger.warning(f"[HB_WATCHDOG] watchdog error for {task_id}: {_e}")
            return

    async def stop_task(self, task_id: str) -> bool:
        """
        Stop execution task via graceful stop_requested flag.

        Does NOT cancel the asyncio task — lets the execution loop exit
        at the next safe point and push stop_confirmed via WebSocket.

        Args:
            task_id: Task ID to stop

        Returns:
            True if task was stopped, False if task not found
        """
        if task_id not in self.tasks:
            logger.warning(f"Task {task_id} not found")
            return False

        if task_id in self.executors:
            self.executors[task_id].stop()
            logger.info(f"Signaled graceful stop for task {task_id} — loop will exit at next safe point")
        else:
            logger.warning(f"No executor found for task {task_id}")

        # 硬停兜底(20260617): 软停只置 stop_requested 标志, 靠循环走到安全点退出。
        # 但若循环【挂死】在某无超时 await(实测 cq001 ICXAU forward_opening 卡死),
        # 永远到不了检查点 -> task 不退出 -> 残留运行集 -> 前端15s轮询反复重亮按钮("自动重启"假象)。
        # 看门狗: 软停后 HARD_CANCEL_AFTER 秒内 task 仍未结束, 就 task.cancel() 强制中断挂死的 await。
        # cancel 走 _on_task_complete 的 'cancelled' 分支 -> status='cancelled' -> 明确【不触发自恢复】,
        # 故"硬停=必停、不会被拉回"。正常循环会在看门狗到点前优雅退出, 不受影响。
        _task = self.tasks.get(task_id)
        if _task is not None and not _task.done():
            HARD_CANCEL_AFTER = 12.0  # 留足优雅退出余量(单次执行<5s, 8s超时兜底), 超时仍未退=挂死->硬杀
            async def _hard_cancel_watchdog(tid, t):
                try:
                    await asyncio.wait_for(asyncio.shield(t), timeout=HARD_CANCEL_AFTER)
                    return  # 已优雅退出, 无需硬杀
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    return  # task 已以异常/取消结束
                if not t.done():
                    logger.warning(
                        f"[HARD_STOP] Task {tid} 软停 {HARD_CANCEL_AFTER}s 后仍未退出(疑似循环挂死) "
                        f"-> 强制 cancel, 杜绝停不掉/前端重亮"
                    )
                    t.cancel()
            try:
                asyncio.create_task(_hard_cancel_watchdog(task_id, _task))
            except RuntimeError:
                pass  # 无运行中事件循环

        return True

    def get_status(self, task_id: str) -> Optional[Dict]:
        """
        Get task status.

        Args:
            task_id: Task ID

        Returns:
            Task status dictionary or None if not found
        """
        if task_id not in self.task_info:
            return None

        info = self.task_info[task_id].copy()

        # Add current executor state if still running
        if task_id in self.executors:
            executor = self.executors[task_id]
            info['is_running'] = executor.is_running
            info['current_ladder_index'] = executor.current_ladder_index

        return info

    def get_all_tasks(self) -> Dict[str, Dict]:
        """Get status of all tasks"""
        return {
            task_id: self.get_status(task_id)
            for task_id in self.task_info.keys()
        }

    def cleanup_completed_tasks(self, max_age_hours: int = 24):
        """
        Clean up completed tasks older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours for completed tasks
        """
        now = datetime.utcnow()
        to_remove = []

        for task_id, info in self.task_info.items():
            if info['status'] in ['completed', 'failed', 'cancelled']:
                if 'completed_at' in info:
                    completed_at = datetime.fromisoformat(info['completed_at'])
                    age_hours = (now - completed_at).total_seconds() / 3600

                    if age_hours > max_age_hours:
                        to_remove.append(task_id)

        for task_id in to_remove:
            self.task_info.pop(task_id, None)
            self.tasks.pop(task_id, None)
            self.executors.pop(task_id, None)
            logger.info(f"Cleaned up old task {task_id}")

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")


# Global task manager instance
execution_task_manager = ExecutionTaskManager()
