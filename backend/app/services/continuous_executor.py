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
        trigger_check_interval: float = 0.05  # 50ms default
    ):
        """
        Initialize continuous executor.

        Args:
            strategy_id: Unique strategy identifier
            order_executor: Order execution engine
            position_mgr: Position manager (uses global if not provided)
            trigger_check_interval: Interval between trigger checks in seconds (default 0.05 = 50ms)
        """
        self.strategy_id = strategy_id
        self.order_executor = order_executor
        self.position_mgr = position_mgr or position_manager
        self.trigger_check_interval = trigger_check_interval

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
        # ========== 强制输出调试信息 ==========
        print(f"\n{'='*80}")
        print(f"=== LADDER DEBUG START (ladder {ladder_idx}) ===")
        print(f"[DEBUG] is_running initial value: {self.is_running}")
        print(f"[DEBUG] ladder total_qty: {ladder.total_qty}")
        print(f"[DEBUG] strategy_type: {strategy_type}")
        print(f"[DEBUG] order_qty_limit: {order_qty_limit}")
        print(f"{'='*80}\n")

        # Initialize trigger manager for this ladder
        trigger_key = f"{self.strategy_id}_{strategy_type}_ladder_{ladder_idx}"
        self.trigger_mgr = TriggerCountManager(self.strategy_id, trigger_key)

        # Determine if opening or closing
        is_opening = 'opening' in strategy_type
        spread_threshold = ladder.opening_spread if is_opening else ladder.closing_spread
        trigger_count_required = ladder.opening_trigger_count if is_opening else ladder.closing_trigger_count
        compare_op = CompareOperator.GREATER_EQUAL if is_opening else CompareOperator.LESS_EQUAL

        print(f"[DEBUG] is_opening: {is_opening}")
        print(f"[DEBUG] spread_threshold: {spread_threshold}")
        print(f"[DEBUG] trigger_count_required: {trigger_count_required}")
        print(f"[DEBUG] compare_op: {compare_op}\n")

        logger.info(f"Starting ladder execution loop - is_running: {self.is_running}, ladder_idx: {ladder_idx}, total_qty: {ladder.total_qty}")

        loop_count = 0
        while self.is_running:
            loop_count += 1
            print(f"\n[DEBUG] ===== Loop iteration {loop_count} =====")
            print(f"[DEBUG] is_running: {self.is_running}")

            # Step 1: Check position
            position_info = self.position_mgr.get_position(
                self.strategy_id,
                ladder_idx,
                strategy_type
            )
            current_position = position_info['current_position']
            print(f"[DEBUG] Step 1 - Current position: {current_position}/{ladder.total_qty}")
            logger.info(f"Step 1 - Current position: {current_position}/{ladder.total_qty}")

            # Step 2: Check if ladder complete
            if current_position >= ladder.total_qty:
                print(f"[DEBUG] BREAK: Current position ({current_position}) >= total_qty ({ladder.total_qty})")
                logger.info(f"Ladder {ladder_idx} complete: {current_position}/{ladder.total_qty}")
                break

            # Step 3: Check trigger count
            trigger_ready = self.trigger_mgr.is_ready(trigger_count_required)
            logger.info(f"Step 3 - Trigger ready: {trigger_ready}, current count: {self.trigger_mgr.count}, required: {trigger_count_required}")

            if not trigger_ready:
                # Accumulate triggers
                current_spread = await self._get_current_spread(strategy_type)
                logger.info(f"Step 3a - Current spread: {current_spread}, threshold: {spread_threshold}, compare_op: {compare_op}")

                triggered = await self.trigger_mgr.check_and_increment(
                    current_spread,
                    spread_threshold,
                    compare_op
                )
                logger.info(f"Step 3b - Triggered: {triggered}, new count: {self.trigger_mgr.count}")

                if triggered:
                    await self._push_trigger_progress(
                        ladder_idx,
                        self.trigger_mgr.count,
                        trigger_count_required
                    )

                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 4: Validate spread still meets threshold
            current_spread = await self._get_current_spread(strategy_type)
            spread_condition_met = self._check_spread_condition(current_spread, spread_threshold, compare_op)
            logger.info(f"Step 4 - Spread condition met: {spread_condition_met}, current: {current_spread}, threshold: {spread_threshold}")

            if not spread_condition_met:
                logger.info(
                    f"Spread no longer meets threshold: {current_spread} "
                    f"{'<' if is_opening else '>'} {spread_threshold}"
                )
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx)
                continue

            # Step 5: Calculate order quantity
            remaining = ladder.total_qty - current_position
            order_qty = min(order_qty_limit, remaining)
            logger.info(f"Step 5 - Order qty: {order_qty}, remaining: {remaining}, limit: {order_qty_limit}")

            # Step 6: Check position limits
            can_open, reason = self.position_mgr.check_can_open(
                self.strategy_id,
                ladder_idx,
                order_qty,
                ladder.total_qty
            )
            logger.info(f"Step 6 - Can open: {can_open}, reason: {reason}")

            if not can_open:
                logger.warning(f"Cannot open: {reason}")
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
                bybit_price
            )
            logger.info(f"Step 8 result - Success: {exec_result.get('success')}, Binance filled: {exec_result.get('binance_filled_qty')}, Bybit filled: {exec_result.get('bybit_filled_qty')}")

            if not exec_result['success']:
                logger.error(f"Execution failed: {exec_result}")
                return {'success': False, 'error': exec_result.get('error')}

            # Step 9: Handle Binance not filled
            if exec_result.get('binance_filled_qty', 0) == 0:
                logger.info("Binance not filled, resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx)
                continue

            # Step 10: Record position
            filled_qty = min(
                exec_result.get('binance_filled_qty', 0),
                exec_result.get('bybit_filled_qty', 0)
            )

            if is_opening:
                self.position_mgr.record_opening(
                    self.strategy_id,
                    ladder_idx,
                    filled_qty
                )
            else:
                self.position_mgr.record_closing(
                    self.strategy_id,
                    ladder_idx,
                    filled_qty
                )

            logger.info(f"Position updated: {'+'if is_opening else '-'}{filled_qty}")

            # Step 11: Push status updates
            await self._push_position_change(ladder_idx, filled_qty, position_info)
            await self._push_order_executed(ladder_idx, exec_result, current_spread)

            # Step 12: DO NOT reset triggers - continue with accumulated count
            # Small delay to prevent API spam
            await asyncio.sleep(0.01)

        # ========== 循环退出后输出原因 ==========
        print(f"\n{'='*80}")
        print(f"=== LADDER DEBUG END ===")
        print(f"[DEBUG] Loop exited after {loop_count} iterations")
        print(f"[DEBUG] is_running: {self.is_running}")
        print(f"[DEBUG] Final position: {current_position}/{ladder.total_qty}")
        print(f"[DEBUG] Exit reason: {'is_running=False' if not self.is_running else 'position >= total_qty'}")
        print(f"{'='*80}\n")

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
                # Reverse opening: Binance SHORT, use ask + 0.01 for MAKER
                return market_data.binance_quote.ask_price + 0.01
            else:
                # Forward opening: Binance LONG, use bid - 0.01 for MAKER
                return market_data.binance_quote.bid_price - 0.01
        else:
            if 'reverse' in strategy_type:
                # Reverse closing: Binance LONG close, use bid - 0.01 for MAKER
                return market_data.binance_quote.bid_price - 0.01
            else:
                # Forward closing: Binance SHORT close, use ask + 0.01 for MAKER
                return market_data.binance_quote.ask_price + 0.01

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
        bybit_price: float
    ) -> Dict:
        """Execute order based on strategy type"""
        if strategy_type == 'reverse_opening':
            return await self.order_executor.execute_reverse_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price
            )
        elif strategy_type == 'reverse_closing':
            return await self.order_executor.execute_reverse_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price
            )
        elif strategy_type == 'forward_opening':
            return await self.order_executor.execute_forward_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price
            )
        elif strategy_type == 'forward_closing':
            return await self.order_executor.execute_forward_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price
            )
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

    async def _push_trigger_progress(
        self,
        ladder_idx: int,
        current_count: int,
        required_count: int
    ):
        """Push trigger progress update via WebSocket"""
        if self.user_id:
            await status_pusher.push_custom_event(
                self.strategy_id,
                'trigger_progress',
                {
                    'ladder_index': ladder_idx,
                    'current_count': current_count,
                    'required_count': required_count,
                    'progress_percent': (current_count / required_count) * 100
                },
                self.user_id
            )

    async def _push_trigger_reset(self, ladder_idx: int):
        """Push trigger reset notification"""
        if self.user_id:
            await status_pusher.push_custom_event(
                self.strategy_id,
                'trigger_reset',
                {'ladder_index': ladder_idx},
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
        print(f"=" * 80)
        print(f"CONTINUOUS EXECUTOR: Starting forward opening")
        print(f"Strategy ID: {self.strategy_id}")
        print(f"Binance: {binance_account.account_name}, Bybit: {bybit_account.account_name}")
        print(f"Ladders: {len(ladders)}, Opening M Coin: {opening_m_coin}")
        print(f"=" * 80)

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

