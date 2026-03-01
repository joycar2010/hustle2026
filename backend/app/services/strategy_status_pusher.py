"""Strategy Execution Status Push Service for WebSocket"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime

from app.websocket.manager import manager


logger = logging.getLogger(__name__)


class StrategyExecutionStatusPusher:
    """
    Pushes real-time strategy execution status via WebSocket.

    Pushes:
    - Execution state changes (started, stopped, completed)
    - Trigger count progress
    - Position changes
    - Ladder progress
    - Errors and warnings
    """

    def __init__(self, websocket_manager=None):
        """
        Initialize status pusher.

        Args:
            websocket_manager: WebSocket manager instance (uses global if not provided)
        """
        self.manager = websocket_manager or manager
        self._push_queue = asyncio.Queue()
        self._is_running = False
        self._push_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the status push service"""
        if self._is_running:
            logger.warning("Status pusher already running")
            return

        self._is_running = True
        self._push_task = asyncio.create_task(self._push_worker())
        logger.info("Strategy execution status pusher started")

    async def stop(self):
        """Stop the status push service"""
        if not self._is_running:
            return

        self._is_running = False
        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass

        logger.info("Strategy execution status pusher stopped")

    async def _push_worker(self):
        """Background worker to process push queue"""
        while self._is_running:
            try:
                # Get message from queue with timeout
                message = await asyncio.wait_for(
                    self._push_queue.get(),
                    timeout=1.0
                )

                # Send via WebSocket
                await self._send_message(message)

            except asyncio.TimeoutError:
                # No message in queue, continue
                continue
            except Exception as e:
                logger.exception(f"Error in push worker: {e}")

    async def _send_message(self, message: Dict):
        """Send message via WebSocket"""
        try:
            message_type = message.get('type')
            user_id = message.get('user_id')

            if user_id:
                # Send to specific user
                await self.manager.send_to_user(message, user_id)
            else:
                # Broadcast to all
                await self.manager.broadcast(message)

        except Exception as e:
            logger.exception(f"Error sending WebSocket message: {e}")

    async def push_execution_started(
        self,
        strategy_id: int,
        action: str,
        user_id: Optional[str] = None
    ):
        """
        Push execution started event.

        Args:
            strategy_id: Strategy ID
            action: Action type (reverse_opening, reverse_closing, etc.)
            user_id: Optional user ID for targeted push
        """
        message = {
            'type': 'strategy_execution_started',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_execution_stopped(
        self,
        strategy_id: int,
        action: str,
        reason: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """Push execution stopped event"""
        message = {
            'type': 'strategy_execution_stopped',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_execution_completed(
        self,
        strategy_id: int,
        action: str,
        result: Dict,
        user_id: Optional[str] = None
    ):
        """Push execution completed event"""
        message = {
            'type': 'strategy_execution_completed',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'result': result,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_trigger_progress(
        self,
        strategy_id: int,
        action: str,
        ladder_index: int,
        current_count: int,
        required_count: int,
        current_spread: float,
        threshold: float,
        user_id: Optional[str] = None
    ):
        """
        Push trigger count progress.

        Args:
            strategy_id: Strategy ID
            action: Action type
            ladder_index: Current ladder index
            current_count: Current trigger count
            required_count: Required trigger count
            current_spread: Current spread value
            threshold: Threshold spread value
            user_id: Optional user ID
        """
        progress_percent = min(100, (current_count / required_count) * 100) if required_count > 0 else 0

        message = {
            'type': 'strategy_trigger_progress',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'ladder_index': ladder_index,
                'current_count': current_count,
                'required_count': required_count,
                'progress_percent': progress_percent,
                'current_spread': current_spread,
                'threshold': threshold,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_position_change(
        self,
        strategy_id: int,
        ladder_index: int,
        change_type: str,  # 'opening' or 'closing'
        quantity: float,
        current_position: float,
        total_opened: float,
        total_closed: float,
        user_id: Optional[str] = None
    ):
        """
        Push position change event.

        Args:
            strategy_id: Strategy ID
            ladder_index: Ladder index
            change_type: Type of change ('opening' or 'closing')
            quantity: Quantity changed
            current_position: Current position after change
            total_opened: Total opened quantity
            total_closed: Total closed quantity
            user_id: Optional user ID
        """
        message = {
            'type': 'strategy_position_change',
            'data': {
                'strategy_id': strategy_id,
                'ladder_index': ladder_index,
                'change_type': change_type,
                'quantity': quantity,
                'current_position': current_position,
                'total_opened': total_opened,
                'total_closed': total_closed,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_ladder_progress(
        self,
        strategy_id: int,
        action: str,
        ladder_index: int,
        current_qty: float,
        total_qty: float,
        user_id: Optional[str] = None
    ):
        """Push ladder progress update"""
        progress_percent = min(100, (current_qty / total_qty) * 100) if total_qty > 0 else 0

        message = {
            'type': 'strategy_ladder_progress',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'ladder_index': ladder_index,
                'current_qty': current_qty,
                'total_qty': total_qty,
                'progress_percent': progress_percent,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_order_executed(
        self,
        strategy_id: int,
        action: str,
        ladder_index: int,
        binance_filled: float,
        bybit_filled: float,
        spread_at_execution: float,
        user_id: Optional[str] = None
    ):
        """Push order execution event"""
        message = {
            'type': 'strategy_order_executed',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'ladder_index': ladder_index,
                'binance_filled': binance_filled,
                'bybit_filled': bybit_filled,
                'spread_at_execution': spread_at_execution,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_error(
        self,
        strategy_id: int,
        action: str,
        error_message: str,
        error_details: Optional[Dict] = None,
        user_id: Optional[str] = None
    ):
        """Push error event"""
        message = {
            'type': 'strategy_execution_error',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'error_message': error_message,
                'error_details': error_details or {},
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)

    async def push_warning(
        self,
        strategy_id: int,
        action: str,
        warning_message: str,
        user_id: Optional[str] = None
    ):
        """Push warning event"""
        message = {
            'type': 'strategy_execution_warning',
            'data': {
                'strategy_id': strategy_id,
                'action': action,
                'warning_message': warning_message,
                'timestamp': datetime.utcnow().isoformat()
            },
            'user_id': user_id
        }
        await self._push_queue.put(message)


# Global status pusher instance
status_pusher = StrategyExecutionStatusPusher()
