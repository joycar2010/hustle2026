"""Continuous Strategy Executor - Automated Trading with Trigger Management"""
import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from uuid import UUID

from app.models.account import Account
from app.services.order_executor_v2 import OrderExecutorV2
from app.services.position_manager import PositionManager, position_manager
from app.services.trigger_manager import TriggerCountManager, CompareOperator
from app.services.market_service import market_data_service
from app.services.strategy_status_pusher import status_pusher


logger = logging.getLogger(__name__)


@dataclass
class LadderConfig:
    """Ladder configuration for tiered execution"""
    enabled: bool
    opening_spread: float
    closing_spread: float
    total_qty: float
    opening_trigger_count: int
    closing_trigger_count: int


class ContinuousStrategyExecutor:
    """
    Orchestrates continuous strategy execution with:
    - Trigger count management
    - Ladder configuration support
    - Position limit enforcement
    - Automatic re-execution until conditions no longer met
    """

    def __init__(
        self,
        strategy_id: int,
        order_executor: OrderExecutorV2,
        position_mgr: Optional[PositionManager] = None,
        trigger_check_interval: float = 0.5,  # 500ms default (increased to reduce API calls and avoid frequent order cancellations)
        api_spam_prevention_delay: float = 3.0,  # Default 3 seconds to prevent API spam
        delayed_single_leg_check_delay: float = 10.0,  # Default 10 seconds for first single-leg check
        delayed_single_leg_second_check_delay: float = 1.0  # Default 1 second for second single-leg check
    ):
        """
        Initialize continuous executor.

        Args:
            strategy_id: Unique strategy identifier
            order_executor: Order execution engine
            position_mgr: Position manager (uses global if not provided)
            trigger_check_interval: Interval between trigger checks in seconds (default 0.5 = 500ms)
            api_spam_prevention_delay: Delay after order execution to prevent API spam (default 3.0 seconds)
            delayed_single_leg_check_delay: Delay before first single-leg verification (default 10.0 seconds)
            delayed_single_leg_second_check_delay: Delay before second single-leg verification (default 1.0 seconds)
        """
        self.strategy_id = strategy_id
        self.order_executor = order_executor
        self.position_mgr = position_mgr or position_manager
        self.trigger_check_interval = trigger_check_interval
        self.api_spam_prevention_delay = api_spam_prevention_delay
        self.delayed_single_leg_check_delay = delayed_single_leg_check_delay
        self.delayed_single_leg_second_check_delay = delayed_single_leg_second_check_delay

        # Execution state
        self.is_running = False
        self.current_ladder_index = 0
        self.trigger_mgr: Optional[TriggerCountManager] = None
        self.user_id: Optional[str] = None

    async def execute_reverse_opening_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        opening_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute reverse opening with continuous execution.

        Flow:
        1. For each enabled ladder:
           a. Loop until ladder total_qty reached:
              - Check trigger count accumulated
              - Validate spread still meets threshold
              - Check position limits
              - Execute single trade
              - Update position
              - Immediately check if can continue
           b. Move to next ladder

        Args:
            binance_account: Binance account for SHORT positions
            bybit_account: Bybit account for LONG positions
            ladders: List of ladder configurations
            opening_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting reverse opening continuous execution for strategy {self.strategy_id}")

        self.is_running = True
        self.user_id = user_id

        try:
            # Execute each ladder sequentially
            for ladder_idx, ladder in enumerate(ladders):
                if not ladder.enabled:
                    logger.info(f"Ladder {ladder_idx} disabled, skipping")
                    continue

                self.current_ladder_index = ladder_idx
                logger.info(f"Executing ladder {ladder_idx}")

                # Execute ladder with continuous logic
                result = await self._execute_ladder(
                    ladder_idx=ladder_idx,
                    ladder=ladder,
                    strategy_type='reverse_opening',
                    binance_account=binance_account,
                    bybit_account=bybit_account,
                    order_qty_limit=opening_m_coin
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
            logger.exception(f"Error in reverse opening continuous: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def _execute_ladder(
        self,
        ladder_idx: int,
        ladder: LadderConfig,
        strategy_type: str,
        binance_account: Account,
        bybit_account: Account,
        order_qty_limit: float
    ) -> Dict:
        """
        Execute single ladder with continuous execution.

        Args:
            ladder_idx: Ladder index
            ladder: Ladder configuration
            strategy_type: 'reverse_opening', 'reverse_closing', 'forward_opening', 'forward_closing'
            binance_account: Binance account
            bybit_account: Bybit account
            order_qty_limit: Max quantity per order

        Returns:
            Execution result
        """
        # ========== 强制输出调试信息到文件 ==========
        import datetime
        with open("ladder_debug.log", "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[{datetime.datetime.now()}] LADDER DEBUG START (ladder {ladder_idx})\n")
            f.write(f"[DEBUG] is_running initial value: {self.is_running}\n")
            f.write(f"[DEBUG] ladder total_qty: {ladder.total_qty}\n")
            f.write(f"[DEBUG] strategy_type: {strategy_type}\n")
            f.write(f"[DEBUG] order_qty_limit: {order_qty_limit}\n")
            f.write(f"{'='*80}\n")

        # Initialize trigger manager for this ladder
        trigger_key = f"{self.strategy_id}_{strategy_type}_ladder_{ladder_idx}"
        self.trigger_mgr = TriggerCountManager(self.strategy_id, trigger_key)

        # Determine if opening or closing
        is_opening = 'opening' in strategy_type
        spread_threshold = ladder.opening_spread if is_opening else ladder.closing_spread
        trigger_count_required = ladder.opening_trigger_count if is_opening else ladder.closing_trigger_count
        # Opening: spread >= threshold (large spread, good for opening)
        # Closing: spread <= threshold (small/negative spread, good for closing)
        compare_op = CompareOperator.GREATER_EQUAL if is_opening else CompareOperator.LESS_EQUAL

        with open("ladder_debug.log", "a") as f:
            f.write(f"[DEBUG] is_opening: {is_opening}\n")
            f.write(f"[DEBUG] spread_threshold: {spread_threshold}\n")
            f.write(f"[DEBUG] trigger_count_required: {trigger_count_required}\n")
            f.write(f"[DEBUG] compare_op: {compare_op}\n\n")

        logger.info(f"Starting ladder execution loop - is_running: {self.is_running}, ladder_idx: {ladder_idx}, total_qty: {ladder.total_qty}")

        loop_count = 0
        while self.is_running:
            loop_count += 1
            # Only log every 100 iterations to reduce I/O
            if loop_count % 100 == 1:
                logger.info(f"Loop iteration {loop_count}, trigger_count: {self.trigger_mgr.count}")

            # Step 1: Check position
            # Get memory position (how much we've opened/closed so far)
            position_info = self.position_mgr.get_position(
                self.strategy_id,
                ladder_idx,
                strategy_type
            )
            current_position = position_info['current_position']

            # For closing strategies, also log actual exchange positions for monitoring
            if not is_opening:
                try:
                    # Initialize clients if not already done
                    if not hasattr(binance_account, 'binance_client'):
                        from app.services.binance_client import BinanceFuturesClient
                        binance_account.binance_client = BinanceFuturesClient(
                            api_key=binance_account.api_key,
                            api_secret=binance_account.api_secret
                        )

                    if not hasattr(bybit_account, 'mt5_client'):
                        from app.services.mt5_client import MT5Client
                        bybit_account.mt5_client = MT5Client(
                            login=int(bybit_account.mt5_id),
                            password=bybit_account.mt5_primary_pwd,
                            server=bybit_account.mt5_server
                        )
                        # MT5 connection is REQUIRED for closing strategies
                        if not bybit_account.mt5_client.connect():
                            error_msg = f"MT5 connection failed for account {bybit_account.mt5_id}, cannot execute closing strategy"
                            logger.error(error_msg)
                            with open("ladder_debug.log", "a") as f:
                                f.write(f"[DEBUG] {error_msg}\n")
                            raise Exception(error_msg)

                    # Get actual positions for monitoring only (not for execution control)
                    binance_positions = await binance_account.binance_client.get_position_risk(symbol="XAUUSDT")
                    binance_qty = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions)

                    if not bybit_account.mt5_client.connected:
                        error_msg = "MT5 not connected, cannot get Bybit positions"
                        logger.error(error_msg)
                        with open("ladder_debug.log", "a") as f:
                            f.write(f"[DEBUG] {error_msg}\n")
                        raise Exception(error_msg)

                    bybit_positions = bybit_account.mt5_client.get_positions(symbol="XAUUSD.s")
                    bybit_qty = sum(abs(float(pos.get('volume', 0))) for pos in bybit_positions) * 100

                    actual_position = min(binance_qty, bybit_qty) if (binance_qty > 0 and bybit_qty > 0) else 0

                    with open("ladder_debug.log", "a") as f:
                        f.write(f"[DEBUG] Step 1 - Actual positions (monitoring): Binance={binance_qty}, Bybit={bybit_qty}, Min={actual_position}\n")
                        f.write(f"[DEBUG] Step 1 - Memory position (already closed): {current_position}\n")
                        f.write(f"[DEBUG] Step 1 - Target total_qty: {ladder.total_qty}\n")

                    logger.info(f"Step 1 - Actual positions (monitoring): Binance={binance_qty}, Bybit={bybit_qty}")
                    logger.info(f"Step 1 - Memory position: {current_position}, Target: {ladder.total_qty}")

                except Exception as e:
                    logger.error(f"Failed to get actual positions (monitoring only): {e}")
                    with open("ladder_debug.log", "a") as f:
                        f.write(f"[DEBUG] Step 1 - Failed to get actual positions: {e}\n")

            with open("ladder_debug.log", "a") as f:
                f.write(f"[DEBUG] Step 1 - Current position: {current_position}/{ladder.total_qty}\n")
            logger.info(f"Step 1 - Current position: {current_position}/{ladder.total_qty}")

            # Step 2: Check if ladder complete
            if current_position >= ladder.total_qty:
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] BREAK: Current position ({current_position}) >= total_qty ({ladder.total_qty})\n")
                logger.info(f"Ladder {ladder_idx} complete: {current_position}/{ladder.total_qty}")
                break

            # Step 3: Check trigger count
            trigger_ready = self.trigger_mgr.is_ready(trigger_count_required)
            logger.info(f"Step 3 - Trigger ready: {trigger_ready}, current count: {self.trigger_mgr.count}, required: {trigger_count_required}")
            with open("ladder_debug.log", "a") as f:
                f.write(f"[DEBUG] Step 3 - Trigger ready: {trigger_ready}, current: {self.trigger_mgr.count}, required: {trigger_count_required}\n")

            if not trigger_ready:
                # Accumulate triggers
                current_spread = await self._get_current_spread(strategy_type)
                logger.info(f"Step 3a - Current spread: {current_spread}, threshold: {spread_threshold}, compare_op: {compare_op}")
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 3a - Current spread: {current_spread}, threshold: {spread_threshold}\n")

                triggered = await self.trigger_mgr.check_and_increment(
                    current_spread,
                    spread_threshold,
                    compare_op
                )
                logger.info(f"Step 3b - Triggered: {triggered}, new count: {self.trigger_mgr.count}")
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 3b - Triggered: {triggered}, new count: {self.trigger_mgr.count}\n")

                if triggered:
                    await self._push_trigger_progress(
                        ladder_idx,
                        self.trigger_mgr.count,
                        trigger_count_required,
                        strategy_type
                    )

                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 3c - About to sleep for {self.trigger_check_interval} seconds\n")

                await asyncio.sleep(self.trigger_check_interval)

                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 3d - Woke up from sleep, is_running={self.is_running}\n")

                continue

            # Step 4: Log current spread (for monitoring, but don't block execution)
            current_spread = await self._get_current_spread(strategy_type)
            logger.info(f"Step 4 - Current spread: {current_spread}, threshold: {spread_threshold}")

            with open("ladder_debug.log", "a") as f:
                f.write(f"[DEBUG] Step 4 - Current spread: {current_spread}, threshold: {spread_threshold}, compare_op: {compare_op}\n")
                f.write(f"[DEBUG] Step 4 - About to proceed to Step 5\n")

            # Note: We don't reset triggers here even if spread doesn't meet threshold
            # Once trigger count is reached, we should execute the order to meet the total quantity target

            with open("ladder_debug.log", "a") as f:
                f.write(f"[DEBUG] Step 4.5 - Reached after comment, before Step 5\n")

            # Step 5: Calculate order quantity
            try:
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 5 - About to calculate order_qty\n")
                    f.write(f"[DEBUG] Step 5 - ladder.total_qty={ladder.total_qty}, current_position={current_position}, order_qty_limit={order_qty_limit}\n")

                remaining = ladder.total_qty - current_position
                order_qty = min(order_qty_limit, remaining)
                logger.info(f"Step 5 - Order qty: {order_qty}, remaining: {remaining}, limit: {order_qty_limit}")

                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 5 - Order qty: {order_qty}, remaining: {remaining}, limit: {order_qty_limit}\n")
                    f.flush()
                    f.write(f"[DEBUG] Step 5.5 - About to call check_can_open\n")
                    f.flush()
            except Exception as e:
                logger.error(f"Step 5 - Exception calculating order_qty: {e}")
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 5 - EXCEPTION: {e}\n")
                break

            # Step 6: Check position limits
            try:
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 6 - About to call check_can_open with strategy_id={self.strategy_id}, ladder_idx={ladder_idx}, order_qty={order_qty}, total_qty={ladder.total_qty}\n")
                    f.flush()

                result = self.position_mgr.check_can_open(
                    self.strategy_id,
                    ladder_idx,
                    strategy_type,
                    order_qty,
                    ladder.total_qty
                )

                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 6 - check_can_open returned: {result}\n")
                    f.flush()

                can_open = result['can_open']
                reason = result.get('reason', '')
                logger.info(f"Step 6 - Can open: {can_open}, reason: {reason}")

                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 6 - Can open: {can_open}, reason: {reason}\n")
                    f.flush()

                if not can_open:
                    logger.warning(f"Cannot open: {reason}")
                    with open("ladder_debug.log", "a") as f:
                        f.write(f"[DEBUG] BREAK: Cannot open - {reason}\n")
                    break
            except Exception as e:
                logger.error(f"Step 6 - Exception in check_can_open: {e}")
                with open("ladder_debug.log", "a") as f:
                    f.write(f"[DEBUG] Step 6 - EXCEPTION: {e}\n")
                break

            # Step 7: Get current prices
            market_data = await market_data_service.get_current_spread()
            binance_price = self._get_binance_price(market_data, strategy_type)
            bybit_price = self._get_bybit_price(market_data, strategy_type)
            logger.info(f"Step 7 - Binance price: {binance_price}, Bybit price: {bybit_price}")

            # Step 8: Execute order
            logger.info(f"Step 8 - Executing {strategy_type}: {order_qty} units")
            exec_result = await self._execute_order(
                strategy_type,
                binance_account,
                bybit_account,
                order_qty,
                binance_price,
                bybit_price,
                spread_threshold
            )
            logger.info(f"Step 8 result - Success: {exec_result.get('success')}, Binance filled: {exec_result.get('binance_filled_qty')}, Bybit filled: {exec_result.get('bybit_filled_qty')}")

            # Step 8.5: Schedule delayed single-leg check (10 seconds + double verification)
            # This prevents false alerts due to exchange API data sync delays
            if exec_result.get('is_single_leg'):
                logger.warning(f"Potential single-leg detected, scheduling delayed verification in 10 seconds")
                # Schedule async delayed check (non-blocking)
                asyncio.create_task(self._delayed_single_leg_check(
                    strategy_type=strategy_type,
                    exec_result=exec_result,
                    binance_account=binance_account,
                    bybit_account=bybit_account
                ))

            if not exec_result['success']:
                logger.error(f"Execution failed: {exec_result}")
                return {'success': False, 'error': exec_result.get('error')}

            # Step 9: Handle three scenarios
            binance_filled = exec_result.get('binance_filled_qty', 0)

            # Scenario 1: Binance not filled
            if binance_filled == 0:
                logger.info("Scenario 1: Binance not filled, resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)
                continue

            # Step 10: Record position
            filled_qty = min(
                exec_result.get('binance_filled_qty', 0),
                exec_result.get('bybit_filled_qty', 0)
            )

            # For both opening and closing, use record_opening (additive) to track
            # how many lots have been executed toward the ladder's total_qty target.
            # record_closing uses subtraction and requires current_position > 0,
            # which would prevent the completion check (current_position >= total_qty) from ever triggering.
            self.position_mgr.record_opening(
                self.strategy_id,
                ladder_idx,
                strategy_type,
                filled_qty
            )

            logger.info(f"Position updated: {'+'if is_opening else '-'}{filled_qty}")

            # Step 11: Push status updates
            await self._push_position_change(ladder_idx, filled_qty, position_info)
            await self._push_order_executed(ladder_idx, exec_result, current_spread)

            # Step 12: Reset triggers after successful execution
            # CRITICAL FIX: Always reset triggers after order execution to allow next cycle to accumulate fresh triggers
            # This prevents the issue where trigger count remains high and blocks subsequent executions
            with open("ladder_debug.log", "a") as f:
                f.write(f"[DEBUG] Step 12 - Order executed successfully\n")
                f.write(f"[DEBUG] Step 12 - binance_filled={binance_filled}, order_qty={order_qty}, ratio={binance_filled/order_qty if order_qty > 0 else 0:.2%}\n")
                f.write(f"[DEBUG] Step 12 - Current trigger count before reset: {self.trigger_mgr.count}\n")
                f.write(f"[DEBUG] Step 12 - Current position after fill: {current_position + filled_qty}/{ladder.total_qty}\n")
                f.write(f"[DEBUG] Step 12 - Resetting trigger count to allow next cycle\n")

            logger.info(f"Order executed: {binance_filled}/{order_qty} filled, resetting triggers from {self.trigger_mgr.count} to 0")
            self.trigger_mgr.reset()
            await self._push_trigger_reset(ladder_idx, strategy_type)

            with open("ladder_debug.log", "a") as f:
                f.write(f"[DEBUG] Step 12 - Trigger count after reset: {self.trigger_mgr.count}\n")

            # Small delay to prevent API spam (configurable via api_spam_prevention_delay)
            logger.info(f"Waiting {self.api_spam_prevention_delay} seconds to prevent API spam")
            await asyncio.sleep(self.api_spam_prevention_delay)

        # ========== 循环退出后输出原因 ==========
        with open("ladder_debug.log", "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"=== LADDER DEBUG END ===\n")
            f.write(f"[DEBUG] Loop exited after {loop_count} iterations\n")
            f.write(f"[DEBUG] is_running: {self.is_running}\n")
            f.write(f"[DEBUG] Final position: {current_position}/{ladder.total_qty}\n")
            f.write(f"[DEBUG] Exit reason: {'is_running=False' if not self.is_running else 'position >= total_qty'}\n")
            f.write(f"{'='*80}\n\n")

        return {'success': True}

    async def _get_current_spread(self, strategy_type: str) -> float:
        """Get current spread for strategy type"""
        market_data = await market_data_service.get_current_spread()
        spreads = market_data_service.calculate_spread(
            market_data.binance_quote,
            market_data.bybit_quote
        )

        if strategy_type == 'reverse_opening':
            return spreads.reverse_entry_spread
        elif strategy_type == 'reverse_closing':
            return spreads.reverse_exit_spread
        elif strategy_type == 'forward_opening':
            return spreads.forward_entry_spread
        elif strategy_type == 'forward_closing':
            return spreads.forward_exit_spread
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

    def _check_spread_condition(
        self,
        current_spread: float,
        threshold: float,
        compare_op: CompareOperator
    ) -> bool:
        """Check if spread meets condition"""
        if compare_op == CompareOperator.GREATER_EQUAL:
            return current_spread >= threshold
        elif compare_op == CompareOperator.LESS_EQUAL:
            return current_spread <= threshold
        return False

    def _get_binance_price(self, market_data, strategy_type: str) -> float:
        """Get appropriate Binance price for strategy type"""
        if 'opening' in strategy_type:
            if 'reverse' in strategy_type:
                # Reverse opening: Binance SHORT, use ask (sell at ask or higher for MAKER)
                return market_data.binance_quote.ask_price
            else:
                # Forward opening: Binance LONG, use bid (buy at bid or lower for MAKER)
                return market_data.binance_quote.bid_price
        else:
            if 'reverse' in strategy_type:
                # Reverse closing: Binance LONG close, use bid (buy at bid or lower for MAKER)
                return market_data.binance_quote.bid_price
            else:
                # Forward closing: Binance SHORT close, use ask (sell at ask or higher for MAKER)
                return market_data.binance_quote.ask_price

    def _get_bybit_price(self, market_data, strategy_type: str) -> float:
        """Get appropriate Bybit price for strategy type (market orders)"""
        if 'opening' in strategy_type:
            if 'reverse' in strategy_type:
                # Reverse opening: Bybit LONG, use ask for market buy
                return market_data.bybit_quote.ask_price
            else:
                # Forward opening: Bybit SHORT, use bid for market sell
                return market_data.bybit_quote.bid_price
        else:
            if 'reverse' in strategy_type:
                # Reverse closing: Bybit SHORT close, use bid for market sell
                return market_data.bybit_quote.bid_price
            else:
                # Forward closing: Bybit LONG close, use ask for market buy
                return market_data.bybit_quote.ask_price

    async def _execute_order(
        self,
        strategy_type: str,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        spread_threshold: float = None
    ) -> Dict:
        """Execute order based on strategy type"""
        if strategy_type == 'reverse_opening':
            return await self.order_executor.execute_reverse_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold
            )
        elif strategy_type == 'reverse_closing':
            return await self.order_executor.execute_reverse_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold
            )
        elif strategy_type == 'forward_opening':
            return await self.order_executor.execute_forward_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold
            )
        elif strategy_type == 'forward_closing':
            return await self.order_executor.execute_forward_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold
            )
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

    async def _push_trigger_progress(
        self,
        ladder_idx: int,
        current_count: int,
        required_count: int,
        strategy_type: str
    ):
        """Push trigger progress update via WebSocket"""
        import datetime
        with open("ladder_debug.log", "a") as f:
            f.write(f"[{datetime.datetime.now()}] PUSH TRIGGER PROGRESS: user_id={self.user_id}, strategy_id={self.strategy_id}, count={current_count}/{required_count}\n")

        if self.user_id:
            # Extract action from strategy_type (e.g., 'reverse_opening' -> 'opening')
            action = 'opening' if 'opening' in strategy_type else 'closing'

            with open("ladder_debug.log", "a") as f:
                f.write(f"[{datetime.datetime.now()}] PUSHING WebSocket: action={action}, count={current_count}/{required_count}\n")

            await status_pusher.push_custom_event(
                self.strategy_id,
                'trigger_progress',
                {
                    'ladder_index': ladder_idx,
                    'current_count': current_count,
                    'required_count': required_count,
                    'progress_percent': (current_count / required_count) * 100,
                    'action': action,
                    'strategy_type': strategy_type
                },
                self.user_id
            )

            with open("ladder_debug.log", "a") as f:
                f.write(f"[{datetime.datetime.now()}] WebSocket PUSHED successfully\n")

    async def _push_trigger_reset(self, ladder_idx: int, strategy_type: str):
        """Push trigger reset notification"""
        if self.user_id:
            action = 'opening' if 'opening' in strategy_type else 'closing'
            await status_pusher.push_custom_event(
                self.strategy_id,
                'trigger_reset',
                {
                    'ladder_index': ladder_idx,
                    'action': action,
                    'strategy_type': strategy_type
                },
                self.user_id
            )

    async def _push_position_change(
        self,
        ladder_idx: int,
        filled_qty: float,
        position_info: Dict
    ):
        """Push position change notification"""
        if self.user_id:
            await status_pusher.push_position_change(
                self.strategy_id,
                ladder_idx,
                'opening' if position_info['current_position'] > 0 else 'closing',
                filled_qty,
                position_info['current_position'],
                position_info['total_opened'],
                position_info['total_closed'],
                self.user_id
            )

    async def _push_order_executed(
        self,
        ladder_idx: int,
        exec_result: Dict,
        current_spread: float
    ):
        """Push order executed notification"""
        if self.user_id:
            await status_pusher.push_order_executed(
                self.strategy_id,
                f"ladder_{ladder_idx}",
                ladder_idx,
                exec_result.get('binance_filled_qty', 0),
                exec_result.get('bybit_filled_qty', 0),
                current_spread,
                self.user_id
            )

    async def _delayed_single_leg_check(
        self,
        strategy_type: str,
        exec_result: Dict,
        binance_account: Account,
        bybit_account: Account
    ):
        """
        Delayed single-leg check with 10-second wait + double verification.
        This prevents false alerts due to exchange API data sync delays.

        Args:
            strategy_type: Strategy type (e.g., 'reverse_closing')
            exec_result: Original execution result
            binance_account: Binance account
            bybit_account: Bybit account
        """
        try:
            logger.info(f"[SINGLE_LEG_CHECK] Starting {self.delayed_single_leg_check_delay}-second delayed verification for {strategy_type}")

            # Step 1: Wait for exchange data to fully sync (configurable delay)
            await asyncio.sleep(self.delayed_single_leg_check_delay)

            # Step 2: First verification - get actual positions
            try:
                # Initialize clients if needed
                if not hasattr(binance_account, 'binance_client'):
                    from app.services.binance_client import BinanceFuturesClient
                    binance_account.binance_client = BinanceFuturesClient(
                        api_key=binance_account.api_key,
                        api_secret=binance_account.api_secret
                    )

                if not hasattr(bybit_account, 'mt5_client'):
                    from app.services.mt5_client import MT5Client
                    bybit_account.mt5_client = MT5Client(
                        login=int(bybit_account.mt5_id),
                        password=bybit_account.mt5_primary_pwd,
                        server=bybit_account.mt5_server
                    )
                    if not bybit_account.mt5_client.connect():
                        logger.error("[SINGLE_LEG_CHECK] MT5 connection failed, cannot verify positions")
                        return

                # Get actual positions
                binance_positions = await binance_account.binance_client.get_position_risk(symbol="XAUUSDT")
                binance_qty = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions)

                bybit_positions = bybit_account.mt5_client.get_positions(symbol="XAUUSD.s")
                bybit_qty_lot = sum(abs(float(pos.get('volume', 0))) for pos in bybit_positions)
                bybit_qty = bybit_qty_lot * 100  # Convert Lot to XAU

                pos_diff = abs(binance_qty - bybit_qty)

                logger.info(
                    f"[SINGLE_LEG_CHECK] First verification (10s delay): "
                    f"Binance={binance_qty} XAU, Bybit={bybit_qty} XAU, Diff={pos_diff}"
                )

                # If positions match (within 0.01 XAU tolerance), no single-leg risk
                if pos_diff < 0.01:
                    logger.info("[SINGLE_LEG_CHECK] First verification passed: positions are consistent, no alert needed")
                    return

                # Step 3: Second verification (configurable delay) to rule out temporary data fluctuation
                await asyncio.sleep(self.delayed_single_leg_second_check_delay)

                binance_positions2 = await binance_account.binance_client.get_position_risk(symbol="XAUUSDT")
                binance_qty2 = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions2)

                bybit_positions2 = bybit_account.mt5_client.get_positions(symbol="XAUUSD.s")
                bybit_qty_lot2 = sum(abs(float(pos.get('volume', 0))) for pos in bybit_positions2)
                bybit_qty2 = bybit_qty_lot2 * 100

                pos_diff2 = abs(binance_qty2 - bybit_qty2)

                logger.info(
                    f"[SINGLE_LEG_CHECK] Second verification (11s delay): "
                    f"Binance={binance_qty2} XAU, Bybit={bybit_qty2} XAU, Diff={pos_diff2}"
                )

                # Step 4: Final decision - only alert if both verifications show inconsistency
                if pos_diff2 >= 0.01:
                    logger.error(
                        f"[SINGLE_LEG_CHECK] CONFIRMED SINGLE-LEG after double verification: "
                        f"Binance={binance_qty2} XAU, Bybit={bybit_qty2} XAU, Diff={pos_diff2}"
                    )

                    # Update exec_result with verified positions
                    exec_result['single_leg_details'] = {
                        'binance_filled': binance_qty2,
                        'bybit_filled': bybit_qty2,
                        'bybit_filled_xau': bybit_qty2,
                        'unfilled_qty': pos_diff2,
                        'verification_time': '10s_double_check'
                    }

                    # Send alert
                    await self._send_single_leg_alert(
                        strategy_type=strategy_type,
                        exec_result=exec_result
                    )
                else:
                    logger.info(
                        f"[SINGLE_LEG_CHECK] Second verification passed: positions synced, "
                        f"first check was due to data delay (false positive avoided)"
                    )

            except Exception as e:
                logger.error(f"[SINGLE_LEG_CHECK] Error during position verification: {e}")
                # Don't send alert on verification errors to avoid false positives

        except Exception as e:
            logger.error(f"[SINGLE_LEG_CHECK] Delayed check failed: {e}")

    async def _send_single_leg_alert(
        self,
        strategy_type: str,
        exec_result: Dict
    ):
        """Send single-leg trade alert via WebSocket and Feishu"""
        if not self.user_id:
            return

        # Determine strategy name and action
        if 'reverse' in strategy_type:
            strategy_name = "反向套利"
        else:
            strategy_name = "正向套利"

        if 'opening' in strategy_type:
            action = "开仓"
        else:
            action = "平仓"

        # Prepare alert details
        import datetime
        details = exec_result.get('single_leg_details', {})
        details['timestamp'] = datetime.datetime.utcnow().isoformat()

        # Send WebSocket notification
        from app.websocket.manager import manager
        alert_message = {
            "type": "single_leg_alert",
            "data": {
                "strategy_type": strategy_name,
                "action": action,
                "binance_filled": details.get("binance_filled", 0),
                "bybit_filled": details.get("bybit_filled", 0),
                "unfilled_qty": details.get("unfilled_qty", 0),
                "timestamp": details.get("timestamp"),
                "level": "critical",
                "title": "单腿交易警告",
                "message": f"{strategy_name} {action}: Binance成交 {details.get('binance_filled', 0)}, Bybit成交 {details.get('bybit_filled', 0)}, 未成交 {details.get('unfilled_qty', 0)}"
            }
        }
        await manager.send_to_user(alert_message, self.user_id)

        # Send Feishu notification
        try:
            from app.services.risk_alert_service import RiskAlertService
            from app.core.database import get_db

            # Get database session
            async for db in get_db():
                risk_alert_service = RiskAlertService(db)

                # Determine direction based on strategy type
                direction = "多头" if "forward" in strategy_type.lower() else "空头"
                exchange = "Binance"  # Single-leg usually happens on Binance side

                await risk_alert_service.check_single_leg(
                    user_id=self.user_id,
                    exchange=exchange,
                    quantity=details.get("unfilled_qty", 0),
                    duration=0,  # Immediate alert
                    direction=direction,
                    binance_filled=details.get("binance_filled", 0),
                    bybit_filled=details.get("bybit_filled", 0)
                )
                break  # Only need first session
        except Exception as e:
            logger.error(f"Failed to send Feishu single-leg alert: {e}")

    def stop(self):
        """Stop continuous execution"""
        logger.info(f"Stopping continuous execution for strategy {self.strategy_id}")
        self.is_running = False

    async def execute_forward_opening_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        opening_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute forward opening with continuous execution.

        Args:
            binance_account: Binance account for LONG positions
            bybit_account: Bybit account for SHORT positions
            ladders: List of ladder configurations
            opening_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        import datetime
        with open("ladder_debug.log", "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[{datetime.datetime.now()}] CONTINUOUS EXECUTOR: Starting forward opening\n")
            f.write(f"Strategy ID: {self.strategy_id}\n")
            f.write(f"Binance: {binance_account.account_name}, Bybit: {bybit_account.account_name}\n")
            f.write(f"Ladders: {len(ladders)}, Opening M Coin: {opening_m_coin}\n")
            f.write(f"{'='*80}\n")

        logger.info(f"Starting forward opening continuous execution for strategy {self.strategy_id}")
        logger.info(f"Binance: {binance_account.account_name}, Bybit: {bybit_account.account_name}, Ladders: {len(ladders)}")

        self.is_running = True
        self.user_id = user_id

        try:
            for ladder_idx, ladder in enumerate(ladders):
                if not ladder.enabled:
                    logger.info(f"Ladder {ladder_idx} disabled, skipping")
                    continue

                self.current_ladder_index = ladder_idx
                logger.info(f"Executing ladder {ladder_idx}")

                result = await self._execute_ladder(
                    ladder_idx=ladder_idx,
                    ladder=ladder,
                    strategy_type='forward_opening',
                    binance_account=binance_account,
                    bybit_account=bybit_account,
                    order_qty_limit=opening_m_coin
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
            logger.exception(f"Error in forward opening continuous: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def execute_reverse_closing_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        closing_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute reverse closing with continuous execution.

        Args:
            binance_account: Binance account
            bybit_account: Bybit account
            ladders: List of ladder configurations
            closing_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting reverse closing continuous execution for strategy {self.strategy_id}")

        self.is_running = True
        self.user_id = user_id

        try:
            for ladder_idx, ladder in enumerate(ladders):
                if not ladder.enabled:
                    logger.info(f"Ladder {ladder_idx} disabled, skipping")
                    continue

                self.current_ladder_index = ladder_idx
                logger.info(f"Executing ladder {ladder_idx}")

                result = await self._execute_ladder(
                    ladder_idx=ladder_idx,
                    ladder=ladder,
                    strategy_type='reverse_closing',
                    binance_account=binance_account,
                    bybit_account=bybit_account,
                    order_qty_limit=closing_m_coin
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
            logger.exception(f"Error in reverse closing continuous: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

    async def execute_forward_closing_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        closing_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute forward closing with continuous execution.

        Args:
            binance_account: Binance account
            bybit_account: Bybit account
            ladders: List of ladder configurations
            closing_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting forward closing continuous execution for strategy {self.strategy_id}")

        self.is_running = True
        self.user_id = user_id

        try:
            for ladder_idx, ladder in enumerate(ladders):
                if not ladder.enabled:
                    logger.info(f"Ladder {ladder_idx} disabled, skipping")
                    continue

                self.current_ladder_index = ladder_idx
                logger.info(f"Executing ladder {ladder_idx}")

                result = await self._execute_ladder(
                    ladder_idx=ladder_idx,
                    ladder=ladder,
                    strategy_type='forward_closing',
                    binance_account=binance_account,
                    bybit_account=bybit_account,
                    order_qty_limit=closing_m_coin
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
            logger.exception(f"Error in forward closing continuous: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

