"""Arbitrage Strategy Executor V2.0 - Integrated Flow"""
import asyncio
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

from .trigger_manager import TriggerCountManager, CompareOperator
from .position_manager import PositionManager, position_manager
from .order_executor_v2 import OrderExecutorV2
from .strategy_status_pusher import status_pusher


logger = logging.getLogger(__name__)


@dataclass
class LadderConfig:
    """Ladder configuration"""
    enabled: bool
    opening_spread: float
    closing_spread: float
    total_qty: float
    opening_trigger_count: int
    closing_trigger_count: int


@dataclass
class StrategyConfig:
    """Strategy configuration"""
    strategy_id: int
    symbol: str
    strategy_type: str  # 'reverse' or 'forward'
    opening_m_coin: float  # Max quantity per opening order
    closing_m_coin: float  # Max quantity per closing order
    ladders: List[LadderConfig]


class ArbitrageStrategyExecutorV2:
    """
    Integrated arbitrage strategy executor combining:
    - TriggerCountManager (trigger counting)
    - PositionManager (position tracking)
    - OrderExecutorV2 (optimized order execution)
    """

    def __init__(
        self,
        config: StrategyConfig,
        binance_api,
        bybit_api,
        position_mgr: Optional[PositionManager] = None,
        user_id: Optional[str] = None
    ):
        """
        Initialize strategy executor.

        Args:
            config: Strategy configuration
            binance_api: Binance API client
            bybit_api: Bybit API client
            position_mgr: Position manager (uses global if not provided)
            user_id: Optional user ID for WebSocket push
        """
        self.config = config
        self.binance_api = binance_api
        self.bybit_api = bybit_api
        self.position_mgr = position_mgr or position_manager
        self.user_id = user_id

        # Initialize order executor
        self.order_executor = OrderExecutorV2(
            config.symbol,
            binance_api,
            bybit_api
        )

        # Execution state
        self.is_running = False
        self.current_ladder_index = 0
        self.trigger_manager: Optional[TriggerCountManager] = None
        self.current_action: Optional[str] = None

    async def start_reverse_opening(self) -> Dict:
        """
        Start reverse opening strategy execution.

        Flow:
        1. Initialize state
        2. For each ladder:
           a. Wait for trigger count
           b. Check position limits
           c. Execute orders
           d. Update position
        3. Move to next ladder when complete

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting reverse opening for strategy {self.config.strategy_id}")

        self.is_running = True
        self.current_ladder_index = 0
        self.current_action = 'reverse_opening'

        # Push execution started event
        await status_pusher.push_execution_started(
            self.config.strategy_id,
            'reverse_opening',
            self.user_id
        )

        try:
            # Execute each ladder sequentially
            for ladder_idx, ladder in enumerate(self.config.ladders):
                if not ladder.enabled:
                    logger.info(f"Ladder {ladder_idx} disabled, skipping")
                    continue

                self.current_ladder_index = ladder_idx
                logger.info(f"Executing ladder {ladder_idx}")

                # Execute ladder
                result = await self._execute_ladder_reverse_opening(
                    ladder_idx,
                    ladder
                )

                if not result['success']:
                    logger.error(f"Ladder {ladder_idx} failed: {result.get('error')}")

                    # Push error event
                    await status_pusher.push_error(
                        self.config.strategy_id,
                        'reverse_opening',
                        result.get('error', 'Unknown error'),
                        {'ladder_index': ladder_idx},
                        self.user_id
                    )

                    return {
                        'success': False,
                        'error': result.get('error'),
                        'ladder_index': ladder_idx
                    }

            logger.info("All ladders completed successfully")

            # Push execution completed event
            await status_pusher.push_execution_completed(
                self.config.strategy_id,
                'reverse_opening',
                {'message': 'All ladders completed'},
                self.user_id
            )

            return {'success': True, 'message': 'All ladders completed'}

        except Exception as e:
            logger.exception(f"Error in reverse opening: {e}")

            # Push error event
            await status_pusher.push_error(
                self.config.strategy_id,
                'reverse_opening',
                str(e),
                None,
                self.user_id
            )

            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def _execute_ladder_reverse_opening(
        self,
        ladder_idx: int,
        ladder: LadderConfig
    ) -> Dict:
        """
        Execute single ladder reverse opening.

        Args:
            ladder_idx: Ladder index
            ladder: Ladder configuration

        Returns:
            Execution result
        """
        # Initialize trigger manager for this ladder
        self.trigger_manager = TriggerCountManager(
            self.config.strategy_id,
            f'reverse_opening_ladder_{ladder_idx}'
        )

        # Execute until ladder total quantity is reached
        while True:
            # Check current position
            position_info = self.position_mgr.get_position(
                self.config.strategy_id,
                ladder_idx
            )
            current_position = position_info['current_position']

            # Check if ladder is complete
            if current_position >= ladder.total_qty:
                logger.info(
                    f"Ladder {ladder_idx} complete: "
                    f"{current_position}/{ladder.total_qty}"
                )
                break

            # Step 1: Wait for trigger count
            logger.info(
                f"Waiting for {ladder.opening_trigger_count} triggers "
                f"(current: {self.trigger_manager.count})"
            )
            await self._wait_for_triggers(
                required_count=ladder.opening_trigger_count,
                spread_calculator=self._calc_bybit_long_spread,
                threshold=ladder.opening_spread,
                compare_op=CompareOperator.GREATER_EQUAL
            )

            # Step 2: Calculate order quantity
            remaining = ladder.total_qty - current_position
            order_qty = min(self.config.opening_m_coin, remaining)

            # Check if can open position
            can_open, reason = self.position_mgr.check_can_open(
                self.config.strategy_id,
                ladder_idx,
                order_qty,
                ladder.total_qty
            )

            if not can_open:
                logger.warning(f"Cannot open position: {reason}")
                break

            # Step 3: Re-check spread before execution
            current_spread = await self._calc_bybit_long_spread()
            if current_spread < ladder.opening_spread:
                logger.info(
                    f"Spread no longer meets threshold: "
                    f"{current_spread} < {ladder.opening_spread}"
                )
                self.trigger_manager.reset()
                continue

            # Step 4: Execute orders
            logger.info(f"Executing reverse opening: {order_qty} units")
            exec_result = await self.order_executor.execute_reverse_opening(
                order_qty
            )

            if not exec_result['success']:
                logger.error(f"Order execution failed: {exec_result}")
                return {
                    'success': False,
                    'error': exec_result.get('reason', 'Unknown error')
                }

            # Step 5: Record position
            filled_qty = min(
                exec_result['binance_filled'],
                exec_result['bybit_filled']
            )

            self.position_mgr.record_opening(
                self.config.strategy_id,
                ladder_idx,
                filled_qty
            )

            # Get updated position info
            position_info = self.position_mgr.get_position(
                self.config.strategy_id,
                ladder_idx
            )

            logger.info(
                f"Position updated: +{filled_qty} "
                f"(Binance: {exec_result['binance_filled']}, "
                f"Bybit: {exec_result['bybit_filled']})"
            )

            # Push position change event
            await status_pusher.push_position_change(
                self.config.strategy_id,
                ladder_idx,
                'opening',
                filled_qty,
                position_info['current_position'],
                position_info['total_opened'],
                position_info['total_closed'],
                self.user_id
            )

            # Push order executed event
            await status_pusher.push_order_executed(
                self.config.strategy_id,
                'reverse_opening',
                ladder_idx,
                exec_result['binance_filled'],
                exec_result['bybit_filled'],
                await self._calc_bybit_long_spread(),
                self.user_id
            )

            # Reset trigger count for next round
            self.trigger_manager.reset()

        return {'success': True}

    async def _wait_for_triggers(
        self,
        required_count: int,
        spread_calculator,
        threshold: float,
        compare_op: CompareOperator
    ):
        """
        Wait for trigger count to reach required threshold.

        Args:
            required_count: Required number of triggers
            spread_calculator: Async function to calculate spread
            threshold: Spread threshold value
            compare_op: Comparison operator
        """
        while not self.trigger_manager.is_ready(required_count):
            # Calculate current spread
            current_spread = await spread_calculator()

            # Check and increment trigger count
            triggered = await self.trigger_manager.check_and_increment(
                current_spread,
                threshold,
                compare_op
            )

            if triggered:
                logger.info(
                    f"Trigger {self.trigger_manager.count}/{required_count}: "
                    f"spread={current_spread:.2f}, threshold={threshold:.2f}"
                )

                # Push trigger progress
                await status_pusher.push_trigger_progress(
                    self.config.strategy_id,
                    self.current_action or 'unknown',
                    self.current_ladder_index,
                    self.trigger_manager.count,
                    required_count,
                    current_spread,
                    threshold,
                    self.user_id
                )

            # Short wait before next check
            await asyncio.sleep(0.05)

    async def _calc_bybit_long_spread(self) -> float:
        """
        Calculate bybit long spread (reverse opening).
        Formula: binance_ask - bybit_ask
        """
        binance_book = await self.binance_api.get_orderbook(self.config.symbol)
        bybit_book = await self.bybit_api.get_orderbook(self.config.symbol)

        return binance_book['ask'] - bybit_book['ask']

    async def _calc_bybit_close_spread(self) -> float:
        """
        Calculate bybit close spread (reverse closing).
        Formula: binance_bid - bybit_bid
        """
        binance_book = await self.binance_api.get_orderbook(self.config.symbol)
        bybit_book = await self.bybit_api.get_orderbook(self.config.symbol)

        return binance_book['bid'] - bybit_book['bid']

    async def _calc_binance_long_spread(self) -> float:
        """
        Calculate binance long spread (forward opening).
        Formula: bybit_bid - binance_bid
        """
        binance_book = await self.binance_api.get_orderbook(self.config.symbol)
        bybit_book = await self.bybit_api.get_orderbook(self.config.symbol)

        return bybit_book['bid'] - binance_book['bid']

    async def _calc_binance_close_spread(self) -> float:
        """
        Calculate binance close spread (forward closing).
        Formula: bybit_ask - binance_ask
        """
        binance_book = await self.binance_api.get_orderbook(self.config.symbol)
        bybit_book = await self.bybit_api.get_orderbook(self.config.symbol)

        return bybit_book['ask'] - binance_book['ask']

    async def start_reverse_closing(self) -> Dict:
        """
        Start reverse closing strategy execution.

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting reverse closing for strategy {self.config.strategy_id}")

        self.is_running = True
        self.current_ladder_index = 0

        try:
            # Execute each ladder sequentially
            for ladder_idx, ladder in enumerate(self.config.ladders):
                if not ladder.enabled:
                    logger.info(f"Ladder {ladder_idx} disabled, skipping")
                    continue

                self.current_ladder_index = ladder_idx
                logger.info(f"Executing ladder {ladder_idx}")

                # Execute ladder
                result = await self._execute_ladder_reverse_closing(
                    ladder_idx,
                    ladder
                )

                if not result['success']:
                    logger.error(f"Ladder {ladder_idx} failed: {result.get('error')}")
                    return {
                        'success': False,
                        'error': result.get('error'),
                        'ladder_index': ladder_idx
                    }

            logger.info("All ladders completed successfully")
            return {'success': True, 'message': 'All ladders completed'}

        except Exception as e:
            logger.exception(f"Error in reverse closing: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def _execute_ladder_reverse_closing(
        self,
        ladder_idx: int,
        ladder: LadderConfig
    ) -> Dict:
        """
        Execute single ladder reverse closing.

        Args:
            ladder_idx: Ladder index
            ladder: Ladder configuration

        Returns:
            Execution result
        """
        # Initialize trigger manager
        self.trigger_manager = TriggerCountManager(
            self.config.strategy_id,
            f'reverse_closing_ladder_{ladder_idx}'
        )

        closed_qty = 0

        # Execute until ladder total quantity is closed
        while closed_qty < ladder.total_qty:
            # Check current position
            position_info = self.position_mgr.get_position(
                self.config.strategy_id,
                ladder_idx
            )
            current_position = position_info['current_position']

            # Check if enough position to close
            if current_position <= 0:
                logger.info(f"No position to close for ladder {ladder_idx}")
                break

            # Step 1: Wait for trigger count
            logger.info(
                f"Waiting for {ladder.closing_trigger_count} triggers "
                f"(current: {self.trigger_manager.count})"
            )
            await self._wait_for_triggers(
                required_count=ladder.closing_trigger_count,
                spread_calculator=self._calc_bybit_close_spread,
                threshold=ladder.closing_spread,
                compare_op=CompareOperator.LESS_EQUAL
            )

            # Step 2: Calculate order quantity
            remaining_to_close = min(
                ladder.total_qty - closed_qty,
                current_position
            )
            order_qty = min(self.config.closing_m_coin, remaining_to_close)

            # Check if can close position
            can_close, reason = self.position_mgr.check_can_close(
                self.config.strategy_id,
                ladder_idx,
                order_qty
            )

            if not can_close:
                logger.warning(f"Cannot close position: {reason}")
                break

            # Step 3: Re-check spread before execution
            current_spread = await self._calc_bybit_close_spread()
            if current_spread > ladder.closing_spread:
                logger.info(
                    f"Spread no longer meets threshold: "
                    f"{current_spread} > {ladder.closing_spread}"
                )
                self.trigger_manager.reset()
                continue

            # Step 4: Execute orders
            logger.info(f"Executing reverse closing: {order_qty} units")
            exec_result = await self.order_executor.execute_reverse_closing(
                order_qty
            )

            if not exec_result['success']:
                logger.error(f"Order execution failed: {exec_result}")
                return {
                    'success': False,
                    'error': exec_result.get('reason', 'Unknown error')
                }

            # Step 5: Record position
            filled_qty = min(
                exec_result['binance_filled'],
                exec_result['bybit_filled']
            )

            self.position_mgr.record_closing(
                self.config.strategy_id,
                ladder_idx,
                filled_qty
            )

            closed_qty += filled_qty

            logger.info(
                f"Position closed: -{filled_qty} "
                f"(Binance: {exec_result['binance_filled']}, "
                f"Bybit: {exec_result['bybit_filled']})"
            )

            # Reset trigger count for next round
            self.trigger_manager.reset()

        return {'success': True}
    async def start_forward_opening(self) -> Dict:
        """
        Start forward opening strategy execution.

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting forward opening for strategy {self.config.strategy_id}")

        self.is_running = True
        self.current_ladder_index = 0

        try:
            for ladder_idx, ladder in enumerate(self.config.ladders):
                if not ladder.enabled:
                    continue

                self.current_ladder_index = ladder_idx
                result = await self._execute_ladder_forward_opening(
                    ladder_idx,
                    ladder
                )

                if not result['success']:
                    return {
                        'success': False,
                        'error': result.get('error'),
                        'ladder_index': ladder_idx
                    }

            return {'success': True, 'message': 'All ladders completed'}

        except Exception as e:
            logger.exception(f"Error in forward opening: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def _execute_ladder_forward_opening(
        self,
        ladder_idx: int,
        ladder: LadderConfig
    ) -> Dict:
        """Execute single ladder forward opening."""
        self.trigger_manager = TriggerCountManager(
            self.config.strategy_id,
            f'forward_opening_ladder_{ladder_idx}'
        )

        while True:
            position_info = self.position_mgr.get_position(
                self.config.strategy_id,
                ladder_idx
            )
            current_position = position_info['current_position']

            if current_position >= ladder.total_qty:
                break

            await self._wait_for_triggers(
                required_count=ladder.opening_trigger_count,
                spread_calculator=self._calc_binance_long_spread,
                threshold=ladder.opening_spread,
                compare_op=CompareOperator.GREATER_EQUAL
            )

            remaining = ladder.total_qty - current_position
            order_qty = min(self.config.opening_m_coin, remaining)

            can_open, reason = self.position_mgr.check_can_open(
                self.config.strategy_id,
                ladder_idx,
                order_qty,
                ladder.total_qty
            )

            if not can_open:
                logger.warning(f"Cannot open position: {reason}")
                break

            current_spread = await self._calc_binance_long_spread()
            if current_spread < ladder.opening_spread:
                self.trigger_manager.reset()
                continue

            exec_result = await self.order_executor.execute_forward_opening(
                order_qty
            )

            if not exec_result['success']:
                return {
                    'success': False,
                    'error': exec_result.get('reason', 'Unknown error')
                }

            filled_qty = min(
                exec_result['binance_filled'],
                exec_result['bybit_filled']
            )

            self.position_mgr.record_opening(
                self.config.strategy_id,
                ladder_idx,
                filled_qty
            )

            self.trigger_manager.reset()

        return {'success': True}

    async def start_forward_closing(self) -> Dict:
        """
        Start forward closing strategy execution.

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting forward closing for strategy {self.config.strategy_id}")

        self.is_running = True
        self.current_ladder_index = 0

        try:
            for ladder_idx, ladder in enumerate(self.config.ladders):
                if not ladder.enabled:
                    continue

                self.current_ladder_index = ladder_idx
                result = await self._execute_ladder_forward_closing(
                    ladder_idx,
                    ladder
                )

                if not result['success']:
                    return {
                        'success': False,
                        'error': result.get('error'),
                        'ladder_index': ladder_idx
                    }

            return {'success': True, 'message': 'All ladders completed'}

        except Exception as e:
            logger.exception(f"Error in forward closing: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def _execute_ladder_forward_closing(
        self,
        ladder_idx: int,
        ladder: LadderConfig
    ) -> Dict:
        """Execute single ladder forward closing."""
        self.trigger_manager = TriggerCountManager(
            self.config.strategy_id,
            f'forward_closing_ladder_{ladder_idx}'
        )

        closed_qty = 0

        while closed_qty < ladder.total_qty:
            position_info = self.position_mgr.get_position(
                self.config.strategy_id,
                ladder_idx
            )
            current_position = position_info['current_position']

            if current_position <= 0:
                break

            await self._wait_for_triggers(
                required_count=ladder.closing_trigger_count,
                spread_calculator=self._calc_binance_close_spread,
                threshold=ladder.closing_spread,
                compare_op=CompareOperator.LESS_EQUAL
            )

            remaining_to_close = min(
                ladder.total_qty - closed_qty,
                current_position
            )
            order_qty = min(self.config.closing_m_coin, remaining_to_close)

            can_close, reason = self.position_mgr.check_can_close(
                self.config.strategy_id,
                ladder_idx,
                order_qty
            )

            if not can_close:
                logger.warning(f"Cannot close position: {reason}")
                break

            current_spread = await self._calc_binance_close_spread()
            if current_spread > ladder.closing_spread:
                self.trigger_manager.reset()
                continue

            exec_result = await self.order_executor.execute_forward_closing(
                order_qty
            )

            if not exec_result['success']:
                return {
                    'success': False,
                    'error': exec_result.get('reason', 'Unknown error')
                }

            filled_qty = min(
                exec_result['binance_filled'],
                exec_result['bybit_filled']
            )

            self.position_mgr.record_closing(
                self.config.strategy_id,
                ladder_idx,
                filled_qty
            )

            closed_qty += filled_qty
            self.trigger_manager.reset()

        return {'success': True}

    def stop(self):
        """Stop strategy execution."""
        logger.info(f"Stopping strategy {self.config.strategy_id}")
        self.is_running = False

    def get_status(self) -> Dict:
        """
        Get current execution status.

        Returns:
            Status dictionary
        """
        trigger_progress = None
        if self.trigger_manager:
            # Get progress with default required count
            trigger_progress = self.trigger_manager.get_progress(1)

        return {
            'is_running': self.is_running,
            'current_ladder_index': self.current_ladder_index,
            'trigger_progress': trigger_progress
        }
