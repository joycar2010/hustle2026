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

        logger.info(f"Started execution task {task_id} for strategy {executor.strategy_id}")
        logger.error(f"TASK MANAGER: Task {task_id} created and started")
        return task_id

    def _on_task_complete(self, task_id: str, task: asyncio.Task):
        """Callback when task completes"""
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
            elif task.exception():
                self.task_info[task_id]['status'] = 'failed'
                self.task_info[task_id]['error'] = str(task.exception())
                logger.error(f"Task {task_id} failed: {task.exception()}")
            else:
                self.task_info[task_id]['status'] = 'completed'
                logger.info(f"Task {task_id} completed successfully")

        # Remove from active strategy map when task ends
        strategy_id = self.task_info.get(task_id, {}).get('strategy_id')
        if strategy_id and self._strategy_to_task.get(strategy_id) == task_id:
            self._strategy_to_task.pop(strategy_id, None)

    async def stop_task(self, task_id: str) -> bool:
        """
        Stop execution task.

        Args:
            task_id: Task ID to stop

        Returns:
            True if task was stopped, False if task not found
        """
        if task_id not in self.tasks:
            logger.warning(f"Task {task_id} not found")
            return False

        # Stop executor
        if task_id in self.executors:
            self.executors[task_id].stop()

        # Cancel task
        if task_id in self.tasks:
            self.tasks[task_id].cancel()
            try:
                await self.tasks[task_id]
            except asyncio.CancelledError:
                pass

        logger.info(f"Stopped task {task_id}")
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
