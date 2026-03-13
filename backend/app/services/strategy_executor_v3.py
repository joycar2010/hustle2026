"""Arbitrage Strategy Executor V3.0 - Optimized Opening Strategy

This version implements the optimized opening strategy logic based on the requirements:
- Enhanced configuration with single_order_qty, max_runtime, spread thresholds
- Precision handling (round to 2 decimals)
- Position validation before and after opening
- Ladder switching validation
- Three execution scenarios handling
- API retry mechanism (3 times)
- Manual stop control
- Comprehensive logging

Key Changes from V2:
1. Focus on opening strategies only (no closing logic in this version)
2. Enhanced data structures with ExecutionState
3. Improved error handling and validation
4. Bybit retry logic with spread validation on 4th attempt
5. Real-time position tracking and validation
"""

import asyncio
import logging
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from .trigger_manager import TriggerCountManager, CompareOperator
from .position_manager import PositionManager, position_manager
from .order_executor_v2 import OrderExecutorV2
from .strategy_status_pusher import status_pusher


logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures (Phase 1: Basic Configuration Optimization)
# ============================================================================

@dataclass
class LadderConfig:
    """Ladder configuration with enhanced parameters"""
    enabled: bool
    opening_spread: float  # Opening spread threshold
    closing_spread: float  # Closing spread threshold (not used in this version)
    total_qty: float  # Total quantity for this ladder
    opening_trigger_count: int  # Trigger count threshold for opening
    closing_trigger_count: int  # Trigger count threshold (not used)
    single_order_qty: float  # Single order quantity limit


@dataclass
class StrategyConfig:
    """Strategy configuration with enhanced parameters"""
    strategy_id: int
    symbol: str
    strategy_type: str  # 'reverse' or 'forward'
    opening_m_coin: float  # Max quantity per opening order (legacy, use ladder.single_order_qty)
    closing_m_coin: float  # Max quantity per closing order (not used)
    ladders: List[LadderConfig]
    max_runtime_hours: float = 24.0  # Maximum runtime in hours
    max_spread_threshold: float = 0.02  # Maximum spread deviation threshold
    price_deviation_threshold: float = 0.01  # Price deviation threshold
    min_trade_qty: float = 0.01  # Minimum trade quantity


@dataclass
class ExecutionState:
    """Execution state tracking"""
    is_running: bool = False
    current_ladder_index: int = 0
    ladder_accumulated_qty: float = 0.0  # Accumulated quantity for current ladder
    start_time: Optional[datetime] = None
    stop_requested: bool = False  # Manual stop flag
    last_error: Optional[str] = None


# ============================================================================
# Utility Functions (Phase 2: Core Logic Optimization)
# ============================================================================

def round_quantity(qty: float) -> float:
    """Round quantity to 2 decimal places"""
    return round(qty, 2)


def validate_quantity(qty: float, min_qty: float = 0.01) -> bool:
    """Validate if quantity meets minimum trade unit"""
    return qty >= min_qty


# ============================================================================
# ArbitrageStrategyExecutorV3 Class
# ============================================================================

class ArbitrageStrategyExecutorV3:
    """Optimized Arbitrage Strategy Executor V3 - Focus on Opening Strategies"""

    def __init__(
        self,
        position_manager,
        order_executor,
        trigger_count_manager,
        logger
    ):
        self.position_manager = position_manager
        self.order_executor = order_executor
        self.trigger_count_manager = trigger_count_manager
        self.logger = logger

        # Execution state dictionary {strategy_id: ExecutionState}
        self.execution_states: Dict[int, ExecutionState] = {}

        # Strategy configuration dictionary {strategy_id: StrategyConfig}
        self.strategy_configs: Dict[int, StrategyConfig] = {}

        # API retry configuration
        self.api_retry_times = 3
        self.api_retry_delay = 0.5  # seconds

        # Detection interval configuration
        self.normal_check_interval = 0.01  # 10ms
        self.after_bybit_check_interval = 0.1  # 100ms

        # Closing strategy wait time configuration (to prevent high-frequency order cancellation)
        self.close_wait_after_cancel_no_trade = 3.0  # Wait 3 seconds after canceling unfilled order
        self.close_wait_after_cancel_part = 2.0  # Wait 2 seconds after canceling partially filled order

        # Opening strategy wait time configuration (to prevent high-frequency order cancellation)
        self.open_wait_after_cancel_no_trade = 3.0  # Wait 3 seconds after canceling unfilled order
        self.open_wait_after_cancel_part = 2.0  # Wait 2 seconds after canceling partially filled order

    # ========================================================================
    # Phase 2: Position Validation Methods
    # ========================================================================

    async def validate_position_before_opening(
        self,
        config: StrategyConfig,
        ladder: LadderConfig
    ) -> Tuple[bool, str]:
        """Validate position before opening - ensure no existing position"""
        try:
            positions = await self._api_call_with_retry(
                self.position_manager.get_positions,
                config.symbol
            )

            if not positions:
                return True, "No existing position"

            # Check if there's any position
            for exchange, pos_data in positions.items():
                if pos_data and pos_data.get('qty', 0) != 0:
                    msg = f"Position validation failed: existing {exchange} position {pos_data.get('qty', 0)}"
                    self.logger.warning(msg)
                    return False, msg

            return True, "Position validation passed"

        except Exception as e:
            msg = f"Position validation error: {str(e)}"
            self.logger.error(msg)
            return False, msg

    async def validate_position_after_opening(
        self,
        config: StrategyConfig,
        expected_binance_qty: float,
        expected_bybit_qty: float
    ) -> Tuple[bool, str]:
        """Validate position after opening - ensure positions match expected quantities"""
        try:
            positions = await self._api_call_with_retry(
                self.position_manager.get_positions,
                config.symbol
            )

            if not positions:
                return False, "No position data after opening"

            binance_qty = positions.get('binance', {}).get('qty', 0)
            bybit_qty = positions.get('bybit', {}).get('qty', 0)

            # Round to 2 decimals for comparison
            binance_qty = round_quantity(binance_qty)
            bybit_qty = round_quantity(bybit_qty)
            expected_binance_qty = round_quantity(expected_binance_qty)
            expected_bybit_qty = round_quantity(expected_bybit_qty)

            # Check if positions match expected
            if binance_qty != expected_binance_qty:
                msg = f"Binance position mismatch: expected {expected_binance_qty}, got {binance_qty}"
                self.logger.warning(msg)
                return False, msg

            if bybit_qty != expected_bybit_qty:
                msg = f"Bybit position mismatch: expected {expected_bybit_qty}, got {bybit_qty}"
                self.logger.warning(msg)
                return False, msg

            return True, f"Position validation passed: Binance={binance_qty}, Bybit={bybit_qty}"

        except Exception as e:
            msg = f"Position validation error: {str(e)}"
            self.logger.error(msg)
            return False, msg

    async def can_switch_to_next_ladder(
        self,
        config: StrategyConfig,
        current_ladder_index: int
    ) -> Tuple[bool, str]:
        """Check if can switch to next ladder - validate position before switching"""
        try:
            # Check if there's a next ladder
            if current_ladder_index >= len(config.ladders) - 1:
                return False, "Already at last ladder"

            # Validate no existing position before switching
            positions = await self._api_call_with_retry(
                self.position_manager.get_positions,
                config.symbol
            )

            if not positions:
                return True, "No position, can switch"

            # Check if there's any position
            for exchange, pos_data in positions.items():
                if pos_data and pos_data.get('qty', 0) != 0:
                    msg = f"Cannot switch ladder: existing {exchange} position {pos_data.get('qty', 0)}"
                    self.logger.warning(msg)
                    return False, msg

            return True, "Position clear, can switch to next ladder"

        except Exception as e:
            msg = f"Ladder switch validation error: {str(e)}"
            self.logger.error(msg)
            return False, msg

    # ========================================================================
    # Phase 2: Control and Utility Methods
    # ========================================================================

    def _should_stop(self, strategy_id: int) -> bool:
        """Check if strategy should stop"""
        state = self.execution_states.get(strategy_id)
        if not state:
            return True

        # Check manual stop flag
        if state.stop_requested:
            self.logger.info(f"Strategy {strategy_id} manual stop requested")
            return True

        # Check max runtime
        config = self.strategy_configs.get(strategy_id)
        if config and state.start_time:
            elapsed_hours = (datetime.now() - state.start_time).total_seconds() / 3600
            if elapsed_hours >= config.max_runtime_hours:
                self.logger.info(f"Strategy {strategy_id} max runtime {config.max_runtime_hours}h reached")
                return True

        return False

    def request_stop(self, strategy_id: int) -> bool:
        """Request manual stop for strategy"""
        state = self.execution_states.get(strategy_id)
        if state:
            state.stop_requested = True
            self.logger.info(f"Strategy {strategy_id} stop requested")
            return True
        return False

    async def _api_call_with_retry(self, func, *args, **kwargs):
        """Execute API call with retry mechanism"""
        last_error = None
        for attempt in range(self.api_retry_times):
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                last_error = e
                self.logger.warning(f"API call failed (attempt {attempt + 1}/{self.api_retry_times}): {str(e)}")
                if attempt < self.api_retry_times - 1:
                    await asyncio.sleep(self.api_retry_delay)

        # All retries failed
        self.logger.error(f"API call failed after {self.api_retry_times} attempts: {str(last_error)}")
        raise last_error

    def _log_opening_operation(
        self,
        strategy_id: int,
        operation: str,
        details: dict
    ):
        """Log opening operation with comprehensive details"""
        log_msg = f"[Strategy {strategy_id}] {operation}: {details}"
        self.logger.info(log_msg)

    # ========================================================================
    # Phase 3: Spread Calculation Methods
    # ========================================================================

    def _calc_binance_long_spread(self, binance_bid: float, bybit_ask: float) -> float:
        """Calculate spread for Binance long (reverse opening)"""
        if bybit_ask <= 0:
            return 0.0
        spread = (binance_bid - bybit_ask) / bybit_ask
        return round(spread, 4)

    def _calc_bybit_long_spread(self, bybit_bid: float, binance_ask: float) -> float:
        """Calculate spread for Bybit long (forward opening)"""
        if binance_ask <= 0:
            return 0.0
        spread = (bybit_bid - binance_ask) / binance_ask
        return round(spread, 4)

    # ========================================================================
    # Phase 4: Reverse Opening Strategy (Binance Long + Bybit Short)
    # ========================================================================

    async def execute_reverse_opening(
        self,
        config: StrategyConfig
    ) -> dict:
        """Execute reverse opening strategy (Binance long + Bybit short)"""
        strategy_id = config.strategy_id

        # Initialize execution state
        if strategy_id not in self.execution_states:
            self.execution_states[strategy_id] = ExecutionState()

        state = self.execution_states[strategy_id]
        state.is_running = True
        state.start_time = datetime.now()
        state.stop_requested = False
        state.current_ladder_index = 0
        state.ladder_accumulated_qty = 0.0

        # Store config
        self.strategy_configs[strategy_id] = config

        self._log_opening_operation(
            strategy_id,
            "REVERSE_OPENING_START",
            {
                "symbol": config.symbol,
                "ladders": len(config.ladders),
                "max_runtime_hours": config.max_runtime_hours
            }
        )

        try:
            result = await self._reverse_opening_cycle(config, state)
            return result
        except Exception as e:
            state.last_error = str(e)
            self.logger.error(f"Reverse opening error: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            state.is_running = False

    async def _reverse_opening_cycle(
        self,
        config: StrategyConfig,
        state: ExecutionState
    ) -> dict:
        """Main cycle for reverse opening strategy"""
        strategy_id = config.strategy_id

        while not self._should_stop(strategy_id):
            # Get current ladder
            if state.current_ladder_index >= len(config.ladders):
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_OPENING_COMPLETE",
                    {"message": "All ladders completed"}
                )
                return {"success": True, "message": "All ladders completed"}

            ladder = config.ladders[state.current_ladder_index]

            # Skip disabled ladder
            if not ladder.enabled:
                state.current_ladder_index += 1
                continue

            # Check trigger count
            trigger_count = self.trigger_count_manager.get_count(
                strategy_id,
                state.current_ladder_index,
                "opening"
            )

            if trigger_count < ladder.opening_trigger_count:
                await asyncio.sleep(self.normal_check_interval)
                continue

            # Validate position before opening
            valid, msg = await self.validate_position_before_opening(config, ladder)
            if not valid:
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_OPENING_VALIDATION_FAILED",
                    {"ladder": state.current_ladder_index, "reason": msg}
                )
                await asyncio.sleep(self.normal_check_interval)
                continue

            # Execute opening
            result = await self._reverse_opening_place_orders(config, ladder, state)

            if result["success"]:
                # Reset trigger count and move to next ladder
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "opening"
                )
                state.current_ladder_index += 1
                state.ladder_accumulated_qty = 0.0
            else:
                # Log error and continue
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_OPENING_FAILED",
                    {"ladder": state.current_ladder_index, "error": result.get("error")}
                )
                # Reset trigger count when order fails to prevent high-frequency re-ordering
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "opening"
                )

            await asyncio.sleep(self.normal_check_interval)

        return {"success": True, "message": "Strategy stopped"}

    async def _reverse_opening_place_orders(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState
    ) -> dict:
        """Place orders for reverse opening (Binance long + Bybit short)"""
        strategy_id = config.strategy_id

        # Calculate order quantity
        remaining_qty = ladder.total_qty - state.ladder_accumulated_qty
        order_qty = min(ladder.single_order_qty, remaining_qty)
        order_qty = round_quantity(order_qty)

        if not validate_quantity(order_qty, config.min_trade_qty):
            return {"success": False, "error": "Order quantity too small"}

        self._log_opening_operation(
            strategy_id,
            "REVERSE_OPENING_ORDER_START",
            {
                "ladder": state.current_ladder_index,
                "order_qty": order_qty,
                "accumulated": state.ladder_accumulated_qty,
                "total": ladder.total_qty
            }
        )

        # Get market prices
        try:
            binance_ticker = await self._api_call_with_retry(
                self.order_executor.get_binance_ticker,
                config.symbol
            )
            bybit_ticker = await self._api_call_with_retry(
                self.order_executor.get_bybit_ticker,
                config.symbol
            )

            binance_bid = float(binance_ticker.get('bidPrice', 0))
            bybit_ask = float(bybit_ticker.get('ask1Price', 0))

            # Calculate spread
            spread = self._calc_binance_long_spread(binance_bid, bybit_ask)

            self._log_opening_operation(
                strategy_id,
                "REVERSE_OPENING_SPREAD_CHECK",
                {
                    "binance_bid": binance_bid,
                    "bybit_ask": bybit_ask,
                    "spread": spread,
                    "threshold": ladder.opening_spread
                }
            )

        except Exception as e:
            return {"success": False, "error": f"Failed to get market prices: {str(e)}"}

        # Execute orders and monitor
        result = await self._monitor_reverse_opening_execution(
            config, ladder, state, order_qty, spread
        )

        return result

    async def _monitor_reverse_opening_execution(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        order_qty: float,
        initial_spread: float
    ) -> dict:
        """Monitor reverse opening execution with three scenarios"""
        strategy_id = config.strategy_id

        # Place Binance market buy order
        try:
            binance_order = await self._api_call_with_retry(
                self.order_executor.place_binance_market_order,
                config.symbol,
                "BUY",
                order_qty
            )
            self._log_opening_operation(
                strategy_id,
                "BINANCE_ORDER_PLACED",
                {"order_id": binance_order.get('orderId'), "qty": order_qty}
            )
        except Exception as e:
            return {"success": False, "error": f"Binance order failed: {str(e)}"}

        # Monitor Binance order status
        bybit_retry_count = 0
        max_bybit_retries = 4

        while bybit_retry_count < max_bybit_retries:
            if self._should_stop(strategy_id):
                return {"success": False, "error": "Strategy stopped"}

            await asyncio.sleep(self.normal_check_interval)

            # Check Binance order status
            try:
                binance_status = await self._api_call_with_retry(
                    self.order_executor.get_binance_order_status,
                    config.symbol,
                    binance_order['orderId']
                )
                filled_qty = float(binance_status.get('executedQty', 0))
                order_status = binance_status.get('status')

                self._log_opening_operation(
                    strategy_id,
                    "BINANCE_ORDER_STATUS",
                    {"status": order_status, "filled_qty": filled_qty}
                )

            except Exception as e:
                self.logger.warning(f"Failed to get Binance order status: {str(e)}")
                continue

            # Scenario 1: Binance unfilled + spread not met
            if filled_qty == 0:
                # Check current spread
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    binance_bid = float(binance_ticker.get('bidPrice', 0))
                    bybit_ask = float(bybit_ticker.get('ask1Price', 0))
                    current_spread = self._calc_binance_long_spread(binance_bid, bybit_ask)

                    if current_spread < ladder.opening_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "SCENARIO_1_ABORT",
                            {"reason": "Binance unfilled and spread not met", "spread": current_spread}
                        )
                        # Cancel Binance order
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait to prevent high-frequency order cancellation
                        await asyncio.sleep(self.open_wait_after_cancel_no_trade)
                        return {"success": False, "error": "Spread not met, order cancelled"}

                except Exception as e:
                    self.logger.warning(f"Failed to check spread: {str(e)}")

            # Scenario 2: Binance fully filled
            if order_status == 'FILLED':
                result = await self._handle_binance_filled_reverse(
                    config, ladder, state, filled_qty, bybit_retry_count
                )
                return result

            # Scenario 3: Binance partially filled + spread not met
            if filled_qty > 0 and filled_qty < order_qty:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    binance_bid = float(binance_ticker.get('bidPrice', 0))
                    bybit_ask = float(bybit_ticker.get('ask1Price', 0))
                    current_spread = self._calc_binance_long_spread(binance_bid, bybit_ask)

                    if current_spread < ladder.opening_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "SCENARIO_3_ABORT",
                            {"reason": "Binance partially filled and spread not met", "filled_qty": filled_qty}
                        )
                        # Cancel remaining Binance order
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait to prevent high-frequency order cancellation
                        await asyncio.sleep(self.open_wait_after_cancel_part)
                        # Place Bybit order for filled quantity
                        result = await self._handle_binance_filled_reverse(
                            config, ladder, state, filled_qty, bybit_retry_count
                        )
                        return result

                except Exception as e:
                    self.logger.warning(f"Failed to check spread for partial fill: {str(e)}")

        return {"success": False, "error": "Max Bybit retries reached"}

    async def _handle_binance_filled_reverse(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        filled_qty: float,
        retry_count: int
    ) -> dict:
        """Handle Binance filled scenario - place Bybit short order with retry"""
        strategy_id = config.strategy_id
        max_retries = 4

        filled_qty = round_quantity(filled_qty)

        self._log_opening_operation(
            strategy_id,
            "BYBIT_ORDER_START",
            {"qty": filled_qty, "retry": retry_count + 1}
        )

        # Hybrid order strategy: try limit order first, fallback to market order
        try:
            # Step 1: Place aggressive limit order first (better price than market)
            bybit_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_limit_order,
                config.symbol,
                "SELL",
                filled_qty,
                "ask"
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_LIMIT_ORDER_PLACED",
                {"order_id": bybit_order.get('orderId'), "qty": filled_qty, "price_type": "ask", "strategy": "hybrid"}
            )

            # Step 2: Wait 0.5 seconds to check if limit order fills
            await asyncio.sleep(0.5)

            bybit_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_order['orderId']
            )
            bybit_filled_qty = float(bybit_status.get('cumExecQty', 0))
            bybit_order_status = bybit_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_LIMIT_ORDER_STATUS",
                {"status": bybit_order_status, "filled_qty": bybit_filled_qty, "wait_time": "0.5s"}
            )

            if bybit_order_status == 'Filled':
                # Validate position after opening
                valid, msg = await self.validate_position_after_opening(
                    config,
                    filled_qty,  # Binance long
                    -filled_qty  # Bybit short
                )

                if valid:
                    state.ladder_accumulated_qty += filled_qty
                    self._log_opening_operation(
                        strategy_id,
                        "REVERSE_OPENING_SUCCESS_LIMIT",
                        {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "limit"}
                    )
                    return {"success": True, "qty": filled_qty}
                else:
                    self._log_opening_operation(
                        strategy_id,
                        "POSITION_VALIDATION_FAILED",
                        {"reason": msg}
                    )
                    return {"success": False, "error": f"Position validation failed: {msg}"}

            # Step 3: Limit order not filled, cancel and use market order as fallback
            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_LIMIT_NOT_FILLED",
                {"reason": "Limit order not filled in 0.5s, switching to market order"}
            )

            await self._api_call_with_retry(
                self.order_executor.cancel_bybit_order,
                config.symbol,
                bybit_order['orderId']
            )

            # Place market order as fallback (100% fill guarantee)
            bybit_market_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_market_order,
                config.symbol,
                "SELL",
                filled_qty
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_MARKET_ORDER_PLACED",
                {"order_id": bybit_market_order.get('orderId'), "qty": filled_qty, "strategy": "market_fallback"}
            )

            # Wait briefly and check market order status
            await asyncio.sleep(0.3)

            market_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_market_order['orderId']
            )
            market_filled_qty = float(market_status.get('cumExecQty', 0))
            market_order_status = market_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_MARKET_ORDER_STATUS",
                {"status": market_order_status, "filled_qty": market_filled_qty}
            )

            if market_order_status == 'Filled':
                # Validate position after opening
                valid, msg = await self.validate_position_after_opening(
                    config,
                    filled_qty,  # Binance long
                    -filled_qty  # Bybit short
                )

                if valid:
                    state.ladder_accumulated_qty += filled_qty
                    self._log_opening_operation(
                        strategy_id,
                        "REVERSE_OPENING_SUCCESS_MARKET",
                        {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "market"}
                    )
                    return {"success": True, "qty": filled_qty}
                else:
                    self._log_opening_operation(
                        strategy_id,
                        "POSITION_VALIDATION_FAILED",
                        {"reason": msg}
                    )
                    return {"success": False, "error": f"Position validation failed: {msg}"}

            # Market order also not filled (rare case), retry the whole process
            retry_count += 1
            if retry_count < max_retries:
                self._log_opening_operation(
                    strategy_id,
                    "BYBIT_OPENING_MARKET_NOT_FILLED_RETRY",
                    {"reason": "Market order not filled, retrying", "retry": retry_count}
                )
                return await self._handle_binance_filled_reverse(
                    config, ladder, state, filled_qty, retry_count
                )
            else:
                return {"success": False, "error": "Max retries reached, market order still not filled"}

        except Exception as e:
            return {"success": False, "error": f"Bybit order failed: {str(e)}"}

    # ========================================================================
    # Phase 5: Forward Opening Strategy (Bybit Long + Binance Short)
    # ========================================================================

    async def execute_forward_opening(
        self,
        config: StrategyConfig
    ) -> dict:
        """Execute forward opening strategy (Bybit long + Binance short)"""
        strategy_id = config.strategy_id

        # Initialize execution state
        if strategy_id not in self.execution_states:
            self.execution_states[strategy_id] = ExecutionState()

        state = self.execution_states[strategy_id]
        state.is_running = True
        state.start_time = datetime.now()
        state.stop_requested = False
        state.current_ladder_index = 0
        state.ladder_accumulated_qty = 0.0

        # Store config
        self.strategy_configs[strategy_id] = config

        self._log_opening_operation(
            strategy_id,
            "FORWARD_OPENING_START",
            {
                "symbol": config.symbol,
                "ladders": len(config.ladders),
                "max_runtime_hours": config.max_runtime_hours
            }
        )

        try:
            result = await self._forward_opening_cycle(config, state)
            return result
        except Exception as e:
            state.last_error = str(e)
            self.logger.error(f"Forward opening error: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            state.is_running = False

    async def _forward_opening_cycle(
        self,
        config: StrategyConfig,
        state: ExecutionState
    ) -> dict:
        """Main cycle for forward opening strategy"""
        strategy_id = config.strategy_id

        while not self._should_stop(strategy_id):
            # Get current ladder
            if state.current_ladder_index >= len(config.ladders):
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_OPENING_COMPLETE",
                    {"message": "All ladders completed"}
                )
                return {"success": True, "message": "All ladders completed"}

            ladder = config.ladders[state.current_ladder_index]

            # Skip disabled ladder
            if not ladder.enabled:
                state.current_ladder_index += 1
                continue

            # Check trigger count
            trigger_count = self.trigger_count_manager.get_count(
                strategy_id,
                state.current_ladder_index,
                "opening"
            )

            if trigger_count < ladder.opening_trigger_count:
                await asyncio.sleep(self.normal_check_interval)
                continue

            # Validate position before opening
            valid, msg = await self.validate_position_before_opening(config, ladder)
            if not valid:
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_OPENING_VALIDATION_FAILED",
                    {"ladder": state.current_ladder_index, "reason": msg}
                )
                await asyncio.sleep(self.normal_check_interval)
                continue

            # Execute opening
            result = await self._forward_opening_place_orders(config, ladder, state)

            if result["success"]:
                # Reset trigger count and move to next ladder
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "opening"
                )
                state.current_ladder_index += 1
                state.ladder_accumulated_qty = 0.0
            else:
                # Log error and continue
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_OPENING_FAILED",
                    {"ladder": state.current_ladder_index, "error": result.get("error")}
                )
                # Reset trigger count when order fails to prevent high-frequency re-ordering
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "opening"
                )

            await asyncio.sleep(self.normal_check_interval)

        return {"success": True, "message": "Strategy stopped"}

    async def _forward_opening_place_orders(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState
    ) -> dict:
        """Place orders for forward opening (Bybit long + Binance short)"""
        strategy_id = config.strategy_id

        # Calculate order quantity
        remaining_qty = ladder.total_qty - state.ladder_accumulated_qty
        order_qty = min(ladder.single_order_qty, remaining_qty)
        order_qty = round_quantity(order_qty)

        if not validate_quantity(order_qty, config.min_trade_qty):
            return {"success": False, "error": "Order quantity too small"}

        self._log_opening_operation(
            strategy_id,
            "FORWARD_OPENING_ORDER_START",
            {
                "ladder": state.current_ladder_index,
                "order_qty": order_qty,
                "accumulated": state.ladder_accumulated_qty,
                "total": ladder.total_qty
            }
        )

        # Get market prices
        try:
            binance_ticker = await self._api_call_with_retry(
                self.order_executor.get_binance_ticker,
                config.symbol
            )
            bybit_ticker = await self._api_call_with_retry(
                self.order_executor.get_bybit_ticker,
                config.symbol
            )

            bybit_bid = float(bybit_ticker.get('bid1Price', 0))
            binance_ask = float(binance_ticker.get('askPrice', 0))

            # Calculate spread
            spread = self._calc_bybit_long_spread(bybit_bid, binance_ask)

            self._log_opening_operation(
                strategy_id,
                "FORWARD_OPENING_SPREAD_CHECK",
                {
                    "bybit_bid": bybit_bid,
                    "binance_ask": binance_ask,
                    "spread": spread,
                    "threshold": ladder.opening_spread
                }
            )

        except Exception as e:
            return {"success": False, "error": f"Failed to get market prices: {str(e)}"}

        # Execute orders and monitor
        result = await self._monitor_forward_opening_execution(
            config, ladder, state, order_qty, spread
        )

        return result

    async def _monitor_forward_opening_execution(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        order_qty: float,
        initial_spread: float
    ) -> dict:
        """Monitor forward opening execution with three scenarios"""
        strategy_id = config.strategy_id

        # Place Binance market sell order
        try:
            binance_order = await self._api_call_with_retry(
                self.order_executor.place_binance_market_order,
                config.symbol,
                "SELL",
                order_qty
            )
            self._log_opening_operation(
                strategy_id,
                "BINANCE_ORDER_PLACED",
                {"order_id": binance_order.get('orderId'), "qty": order_qty}
            )
        except Exception as e:
            return {"success": False, "error": f"Binance order failed: {str(e)}"}

        # Monitor Binance order status
        bybit_retry_count = 0
        max_bybit_retries = 4

        while bybit_retry_count < max_bybit_retries:
            if self._should_stop(strategy_id):
                return {"success": False, "error": "Strategy stopped"}

            await asyncio.sleep(self.normal_check_interval)

            # Check Binance order status
            try:
                binance_status = await self._api_call_with_retry(
                    self.order_executor.get_binance_order_status,
                    config.symbol,
                    binance_order['orderId']
                )
                filled_qty = float(binance_status.get('executedQty', 0))
                order_status = binance_status.get('status')

                self._log_opening_operation(
                    strategy_id,
                    "BINANCE_ORDER_STATUS",
                    {"status": order_status, "filled_qty": filled_qty}
                )

            except Exception as e:
                self.logger.warning(f"Failed to get Binance order status: {str(e)}")
                continue


            # Scenario 1: Binance unfilled + spread not met (Forward Opening)
            if filled_qty == 0:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    bybit_bid = float(bybit_ticker.get('bid1Price', 0))
                    binance_ask = float(binance_ticker.get('askPrice', 0))
                    current_spread = self._calc_bybit_long_spread(bybit_bid, binance_ask)

                    if current_spread < ladder.opening_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "SCENARIO_1_ABORT",
                            {"reason": "Binance unfilled and spread not met", "spread": current_spread}
                        )
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait to prevent high-frequency order cancellation
                        await asyncio.sleep(self.open_wait_after_cancel_no_trade)
                        return {"success": False, "error": "Spread not met, order cancelled"}
                except Exception as e:
                    self.logger.warning(f"Failed to check spread: {str(e)}")

            # Scenario 2: Binance fully filled (Forward Opening)
            if order_status == 'FILLED':
                result = await self._handle_binance_filled_forward(
                    config, ladder, state, filled_qty, bybit_retry_count
                )
                return result

            # Scenario 3: Binance partially filled + spread not met (Forward Opening)
            if filled_qty > 0 and filled_qty < order_qty:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    bybit_bid = float(bybit_ticker.get('bid1Price', 0))
                    binance_ask = float(binance_ticker.get('askPrice', 0))
                    current_spread = self._calc_bybit_long_spread(bybit_bid, binance_ask)

                    if current_spread < ladder.opening_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "SCENARIO_3_ABORT",
                            {"reason": "Binance partially filled and spread not met", "filled_qty": filled_qty}
                        )
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait to prevent high-frequency order cancellation
                        await asyncio.sleep(self.open_wait_after_cancel_part)
                        result = await self._handle_binance_filled_forward(
                            config, ladder, state, filled_qty, bybit_retry_count
                        )
                        return result
                except Exception as e:
                    self.logger.warning(f"Failed to check spread for partial fill: {str(e)}")

        return {"success": False, "error": "Max Bybit retries reached"}

    async def _handle_binance_filled_forward(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        filled_qty: float,
        retry_count: int
    ) -> dict:
        """Handle Binance filled scenario for forward opening - place Bybit long order with retry"""
        strategy_id = config.strategy_id
        max_retries = 4

        filled_qty = round_quantity(filled_qty)

        self._log_opening_operation(
            strategy_id,
            "BYBIT_ORDER_START",
            {"qty": filled_qty, "retry": retry_count + 1}
        )

        # Hybrid order strategy: try limit order first, fallback to market order
        try:
            # Step 1: Place aggressive limit order first (better price than market)
            bybit_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_limit_order,
                config.symbol,
                "BUY",
                filled_qty,
                "bid"
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_LIMIT_ORDER_PLACED",
                {"order_id": bybit_order.get('orderId'), "qty": filled_qty, "price_type": "bid", "strategy": "hybrid"}
            )

            # Step 2: Wait 0.5 seconds to check if limit order fills
            await asyncio.sleep(0.5)

            bybit_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_order['orderId']
            )
            bybit_filled_qty = float(bybit_status.get('cumExecQty', 0))
            bybit_order_status = bybit_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_LIMIT_ORDER_STATUS",
                {"status": bybit_order_status, "filled_qty": bybit_filled_qty, "wait_time": "0.5s"}
            )

            if bybit_order_status == 'Filled':
                valid, msg = await self.validate_position_after_opening(
                    config,
                    -filled_qty,  # Binance short
                    filled_qty    # Bybit long
                )

                if valid:
                    state.ladder_accumulated_qty += filled_qty
                    self._log_opening_operation(
                        strategy_id,
                        "FORWARD_OPENING_SUCCESS_LIMIT",
                        {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "limit"}
                    )
                    return {"success": True, "qty": filled_qty}
                else:
                    self._log_opening_operation(
                        strategy_id,
                        "POSITION_VALIDATION_FAILED",
                        {"reason": msg}
                    )
                    return {"success": False, "error": f"Position validation failed: {msg}"}

            # Step 3: Limit order not filled, cancel and use market order as fallback
            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_LIMIT_NOT_FILLED",
                {"reason": "Limit order not filled in 0.5s, switching to market order"}
            )

            await self._api_call_with_retry(
                self.order_executor.cancel_bybit_order,
                config.symbol,
                bybit_order['orderId']
            )

            # Place market order as fallback (100% fill guarantee)
            bybit_market_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_market_order,
                config.symbol,
                "BUY",
                filled_qty
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_MARKET_ORDER_PLACED",
                {"order_id": bybit_market_order.get('orderId'), "qty": filled_qty, "strategy": "market_fallback"}
            )

            # Wait briefly and check market order status
            await asyncio.sleep(0.3)

            market_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_market_order['orderId']
            )
            market_filled_qty = float(market_status.get('cumExecQty', 0))
            market_order_status = market_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_OPENING_MARKET_ORDER_STATUS",
                {"status": market_order_status, "filled_qty": market_filled_qty}
            )

            if market_order_status == 'Filled':
                valid, msg = await self.validate_position_after_opening(
                    config,
                    -filled_qty,  # Binance short
                    filled_qty    # Bybit long
                )

                if valid:
                    state.ladder_accumulated_qty += filled_qty
                    self._log_opening_operation(
                        strategy_id,
                        "FORWARD_OPENING_SUCCESS_MARKET",
                        {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "market"}
                    )
                    return {"success": True, "qty": filled_qty}
                else:
                    self._log_opening_operation(
                        strategy_id,
                        "POSITION_VALIDATION_FAILED",
                        {"reason": msg}
                    )
                    return {"success": False, "error": f"Position validation failed: {msg}"}

            retry_count += 1
            if retry_count < max_retries:
                self._log_opening_operation(
                    strategy_id,
                    "BYBIT_OPENING_MARKET_NOT_FILLED_RETRY",
                    {"reason": "Market order not filled, retrying", "retry": retry_count}
                )
                return await self._handle_binance_filled_forward(
                    config, ladder, state, filled_qty, retry_count
                )
            else:
                return {"success": False, "error": "Max retries reached, market order still not filled"}

        except Exception as e:
            return {"success": False, "error": f"Bybit order failed: {str(e)}"}

    # ========================================================================
    # Phase 6: Reverse Closing Strategy (Binance Bid + Bybit Bid)
    # ========================================================================

    async def execute_reverse_closing(
        self,
        config: StrategyConfig
    ) -> dict:
        """Execute reverse closing strategy (Binance bid + Bybit bid)"""
        strategy_id = config.strategy_id

        if strategy_id not in self.execution_states:
            self.execution_states[strategy_id] = ExecutionState()

        state = self.execution_states[strategy_id]
        state.is_running = True
        state.start_time = datetime.now()
        state.stop_requested = False
        state.current_ladder_index = 0
        state.ladder_accumulated_qty = 0.0

        self.strategy_configs[strategy_id] = config

        self._log_opening_operation(
            strategy_id,
            "REVERSE_CLOSING_START",
            {
                "symbol": config.symbol,
                "ladders": len(config.ladders),
                "max_runtime_hours": config.max_runtime_hours
            }
        )

        try:
            result = await self._reverse_closing_cycle(config, state)
            return result
        except Exception as e:
            state.last_error = str(e)
            self.logger.error(f"Reverse closing error: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            state.is_running = False

    async def _reverse_closing_cycle(
        self,
        config: StrategyConfig,
        state: ExecutionState
    ) -> dict:
        """Main cycle for reverse closing strategy"""
        strategy_id = config.strategy_id

        while not self._should_stop(strategy_id):
            if state.current_ladder_index >= len(config.ladders):
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_CLOSING_COMPLETE",
                    {"message": "All ladders completed"}
                )
                return {"success": True, "message": "All ladders completed"}

            ladder = config.ladders[state.current_ladder_index]

            if not ladder.enabled:
                state.current_ladder_index += 1
                continue

            trigger_count = self.trigger_count_manager.get_count(
                strategy_id,
                state.current_ladder_index,
                "closing"
            )

            if trigger_count < ladder.closing_trigger_count:
                await asyncio.sleep(self.normal_check_interval)
                continue

            result = await self._reverse_closing_place_orders(config, ladder, state)

            if result["success"]:
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "closing"
                )
                state.current_ladder_index += 1
                state.ladder_accumulated_qty = 0.0
            else:
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_CLOSING_FAILED",
                    {"ladder": state.current_ladder_index, "error": result.get("error")}
                )
                # Reset trigger count when order fails to prevent high-frequency re-ordering
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "closing"
                )

            await asyncio.sleep(self.normal_check_interval)

        return {"success": True, "message": "Strategy stopped"}

    async def _reverse_closing_place_orders(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState
    ) -> dict:
        """Place orders for reverse closing (Binance bid + Bybit bid)"""
        strategy_id = config.strategy_id

        remaining_qty = ladder.total_qty - state.ladder_accumulated_qty
        order_qty = min(ladder.single_order_qty, remaining_qty)
        order_qty = round_quantity(order_qty)

        if not validate_quantity(order_qty, config.min_trade_qty):
            return {"success": False, "error": "Order quantity too small"}

        self._log_opening_operation(
            strategy_id,
            "REVERSE_CLOSING_ORDER_START",
            {
                "ladder": state.current_ladder_index,
                "order_qty": order_qty,
                "accumulated": state.ladder_accumulated_qty,
                "total": ladder.total_qty
            }
        )

        try:
            binance_ticker = await self._api_call_with_retry(
                self.order_executor.get_binance_ticker,
                config.symbol
            )
            bybit_ticker = await self._api_call_with_retry(
                self.order_executor.get_bybit_ticker,
                config.symbol
            )

            binance_bid = float(binance_ticker.get('bidPrice', 0))
            bybit_bid = float(bybit_ticker.get('bid1Price', 0))

            spread = self._calc_reverse_closing_spread(bybit_bid, binance_bid)

            self._log_opening_operation(
                strategy_id,
                "REVERSE_CLOSING_SPREAD_CHECK",
                {
                    "bybit_bid": bybit_bid,
                    "binance_bid": binance_bid,
                    "spread": spread,
                    "threshold": ladder.closing_spread
                }
            )

        except Exception as e:
            return {"success": False, "error": f"Failed to get market prices: {str(e)}"}

        result = await self._monitor_reverse_closing_execution(
            config, ladder, state, order_qty, spread
        )

        return result

    def _calc_reverse_closing_spread(self, bybit_bid: float, binance_bid: float) -> float:
        """Calculate spread for reverse closing"""
        if binance_bid <= 0:
            return 0.0
        spread = (bybit_bid - binance_bid) / binance_bid
        return round(spread, 4)

    def _calc_forward_closing_spread(self, binance_ask: float, bybit_ask: float) -> float:
        """Calculate spread for forward closing"""
        if bybit_ask <= 0:
            return 0.0
        spread = (binance_ask - bybit_ask) / bybit_ask
        return round(spread, 4)

    async def _monitor_reverse_closing_execution(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        order_qty: float,
        initial_spread: float
    ) -> dict:
        """Monitor reverse closing execution with three scenarios"""
        strategy_id = config.strategy_id

        try:
            binance_order = await self._api_call_with_retry(
                self.order_executor.place_binance_limit_order,
                config.symbol,
                "SELL",
                order_qty,
                "bid"
            )
            self._log_opening_operation(
                strategy_id,
                "BINANCE_CLOSING_ORDER_PLACED",
                {"order_id": binance_order.get('orderId'), "qty": order_qty, "price_type": "bid"}
            )
        except Exception as e:
            return {"success": False, "error": f"Binance closing order failed: {str(e)}"}

        bybit_retry_count = 0
        max_bybit_retries = 4

        while bybit_retry_count < max_bybit_retries:
            if self._should_stop(strategy_id):
                return {"success": False, "error": "Strategy stopped"}

            await asyncio.sleep(self.normal_check_interval)

            try:
                binance_status = await self._api_call_with_retry(
                    self.order_executor.get_binance_order_status,
                    config.symbol,
                    binance_order['orderId']
                )
                filled_qty = float(binance_status.get('executedQty', 0))
                order_status = binance_status.get('status')

                self._log_opening_operation(
                    strategy_id,
                    "BINANCE_CLOSING_ORDER_STATUS",
                    {"status": order_status, "filled_qty": filled_qty}
                )

            except Exception as e:
                self.logger.warning(f"Failed to get Binance order status: {str(e)}")
                continue
            if filled_qty == 0:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    bybit_bid = float(bybit_ticker.get('bid1Price', 0))
                    binance_bid = float(binance_ticker.get('bidPrice', 0))
                    current_spread = self._calc_reverse_closing_spread(bybit_bid, binance_bid)

                    if current_spread < ladder.closing_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "REVERSE_CLOSING_SCENARIO_1_ABORT",
                            {"reason": "Binance unfilled and spread not met", "spread": current_spread}
                        )
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait after canceling unfilled order to prevent high-frequency re-ordering
                        self.logger.info(f"Waiting {self.close_wait_after_cancel_no_trade}s after canceling unfilled order")
                        await asyncio.sleep(self.close_wait_after_cancel_no_trade)
                        return {"success": False, "error": "Spread not met, order cancelled"}
                except Exception as e:
                    self.logger.warning(f"Failed to check spread: {str(e)}")

            if order_status == 'FILLED':
                result = await self._handle_binance_filled_reverse_closing(
                    config, ladder, state, filled_qty, bybit_retry_count
                )
                return result

            if filled_qty > 0 and filled_qty < order_qty:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    bybit_bid = float(bybit_ticker.get('bid1Price', 0))
                    binance_bid = float(binance_ticker.get('bidPrice', 0))
                    current_spread = self._calc_reverse_closing_spread(bybit_bid, binance_bid)

                    if current_spread < ladder.closing_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "REVERSE_CLOSING_SCENARIO_3_ABORT",
                            {"reason": "Binance partially filled and spread not met", "filled_qty": filled_qty}
                        )
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait after canceling partially filled order to prevent high-frequency re-ordering
                        self.logger.info(f"Waiting {self.close_wait_after_cancel_part}s after canceling partially filled order")
                        await asyncio.sleep(self.close_wait_after_cancel_part)
                        result = await self._handle_binance_filled_reverse_closing(
                            config, ladder, state, filled_qty, bybit_retry_count
                        )
                        return result
                except Exception as e:
                    self.logger.warning(f"Failed to check spread for partial fill: {str(e)}")

        return {"success": False, "error": "Max Bybit retries reached"}

    async def _handle_binance_filled_reverse_closing(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        filled_qty: float,
        retry_count: int
    ) -> dict:
        """Handle Binance filled scenario for reverse closing"""
        strategy_id = config.strategy_id
        max_retries = 4

        filled_qty = round_quantity(filled_qty)

        self._log_opening_operation(
            strategy_id,
            "BYBIT_CLOSING_ORDER_START",
            {"qty": filled_qty, "retry": retry_count + 1}
        )

        try:
            # Step 1: Place aggressive limit order first (better price than market)
            bybit_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_limit_order,
                config.symbol,
                "BUY",
                filled_qty,
                "bid"
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_LIMIT_ORDER_PLACED",
                {"order_id": bybit_order.get('orderId'), "qty": filled_qty, "price_type": "bid", "strategy": "hybrid"}
            )

            # Step 2: Wait 0.5 seconds to check if limit order fills
            await asyncio.sleep(0.5)

            bybit_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_order['orderId']
            )
            bybit_filled_qty = float(bybit_status.get('cumExecQty', 0))
            bybit_order_status = bybit_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_LIMIT_ORDER_STATUS",
                {"status": bybit_order_status, "filled_qty": bybit_filled_qty, "wait_time": "0.5s"}
            )

            if bybit_order_status == 'Filled':
                state.ladder_accumulated_qty += filled_qty
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_CLOSING_SUCCESS_LIMIT",
                    {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "limit"}
                )
                return {"success": True, "qty": filled_qty}

            # Step 3: Limit order not filled, cancel and use market order as fallback
            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_LIMIT_NOT_FILLED",
                {"reason": "Limit order not filled in 0.5s, switching to market order"}
            )

            await self._api_call_with_retry(
                self.order_executor.cancel_bybit_order,
                config.symbol,
                bybit_order['orderId']
            )

            # Place market order as fallback (100% fill guarantee)
            bybit_market_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_market_order,
                config.symbol,
                "BUY",
                filled_qty
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_MARKET_ORDER_PLACED",
                {"order_id": bybit_market_order.get('orderId'), "qty": filled_qty, "strategy": "market_fallback"}
            )

            # Wait briefly and check market order status
            await asyncio.sleep(0.3)

            market_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_market_order['orderId']
            )
            market_filled_qty = float(market_status.get('cumExecQty', 0))
            market_order_status = market_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_MARKET_ORDER_STATUS",
                {"status": market_order_status, "filled_qty": market_filled_qty}
            )

            if market_order_status == 'Filled':
                state.ladder_accumulated_qty += filled_qty
                self._log_opening_operation(
                    strategy_id,
                    "REVERSE_CLOSING_SUCCESS_MARKET",
                    {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "market"}
                )
                return {"success": True, "qty": filled_qty}

            # Market order also not filled (rare case), retry the whole process
            retry_count += 1
            if retry_count < max_retries:
                self._log_opening_operation(
                    strategy_id,
                    "BYBIT_CLOSING_MARKET_NOT_FILLED_RETRY",
                    {"reason": "Market order not filled, retrying", "retry": retry_count}
                )
                return await self._handle_binance_filled_reverse_closing(
                    config, ladder, state, filled_qty, retry_count
                )
            else:
                return {"success": False, "error": "Max retries reached, market order still not filled"}

        except Exception as e:
            return {"success": False, "error": f"Bybit closing order failed: {str(e)}"}

    # ========================================================================
    # Phase 7: Forward Closing Strategy (Binance Ask + Bybit Ask)
    # ========================================================================

    async def execute_forward_closing(
        self,
        config: StrategyConfig
    ) -> dict:
        """Execute forward closing strategy (Binance ask + Bybit ask)"""
        strategy_id = config.strategy_id

        if strategy_id not in self.execution_states:
            self.execution_states[strategy_id] = ExecutionState()

        state = self.execution_states[strategy_id]
        state.is_running = True
        state.start_time = datetime.now()
        state.stop_requested = False
        state.current_ladder_index = 0
        state.ladder_accumulated_qty = 0.0

        self.strategy_configs[strategy_id] = config

        self._log_opening_operation(
            strategy_id,
            "FORWARD_CLOSING_START",
            {
                "symbol": config.symbol,
                "ladders": len(config.ladders),
                "max_runtime_hours": config.max_runtime_hours
            }
        )

        try:
            result = await self._forward_closing_cycle(config, state)
            return result
        except Exception as e:
            state.last_error = str(e)
            self.logger.error(f"Forward closing error: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            state.is_running = False

    async def _forward_closing_cycle(
        self,
        config: StrategyConfig,
        state: ExecutionState
    ) -> dict:
        """Main cycle for forward closing strategy"""
        strategy_id = config.strategy_id

        while not self._should_stop(strategy_id):
            if state.current_ladder_index >= len(config.ladders):
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_CLOSING_COMPLETE",
                    {"message": "All ladders completed"}
                )
                return {"success": True, "message": "All ladders completed"}

            ladder = config.ladders[state.current_ladder_index]

            if not ladder.enabled:
                state.current_ladder_index += 1
                continue

            trigger_count = self.trigger_count_manager.get_count(
                strategy_id,
                state.current_ladder_index,
                "closing"
            )

            if trigger_count < ladder.closing_trigger_count:
                await asyncio.sleep(self.normal_check_interval)
                continue

            result = await self._forward_closing_place_orders(config, ladder, state)

            if result["success"]:
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "closing"
                )
                state.current_ladder_index += 1
                state.ladder_accumulated_qty = 0.0
            else:
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_CLOSING_FAILED",
                    {"ladder": state.current_ladder_index, "error": result.get("error")}
                )
                # Reset trigger count when order fails to prevent high-frequency re-ordering
                self.trigger_count_manager.reset_count(
                    strategy_id,
                    state.current_ladder_index,
                    "closing"
                )

            await asyncio.sleep(self.normal_check_interval)

        return {"success": True, "message": "Strategy stopped"}

    async def _forward_closing_place_orders(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState
    ) -> dict:
        """Place orders for forward closing (Binance ask + Bybit ask)"""
        strategy_id = config.strategy_id

        remaining_qty = ladder.total_qty - state.ladder_accumulated_qty
        order_qty = min(ladder.single_order_qty, remaining_qty)
        order_qty = round_quantity(order_qty)

        if not validate_quantity(order_qty, config.min_trade_qty):
            return {"success": False, "error": "Order quantity too small"}

        self._log_opening_operation(
            strategy_id,
            "FORWARD_CLOSING_ORDER_START",
            {
                "ladder": state.current_ladder_index,
                "order_qty": order_qty,
                "accumulated": state.ladder_accumulated_qty,
                "total": ladder.total_qty
            }
        )

        try:
            binance_ticker = await self._api_call_with_retry(
                self.order_executor.get_binance_ticker,
                config.symbol
            )
            bybit_ticker = await self._api_call_with_retry(
                self.order_executor.get_bybit_ticker,
                config.symbol
            )

            binance_ask = float(binance_ticker.get('askPrice', 0))
            bybit_ask = float(bybit_ticker.get('ask1Price', 0))

            spread = self._calc_forward_closing_spread(binance_ask, bybit_ask)

            self._log_opening_operation(
                strategy_id,
                "FORWARD_CLOSING_SPREAD_CHECK",
                {
                    "binance_ask": binance_ask,
                    "bybit_ask": bybit_ask,
                    "spread": spread,
                    "threshold": ladder.closing_spread
                }
            )

        except Exception as e:
            return {"success": False, "error": f"Failed to get market prices: {str(e)}"}

        result = await self._monitor_forward_closing_execution(
            config, ladder, state, order_qty, spread
        )

        return result

    async def _monitor_forward_closing_execution(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        order_qty: float,
        initial_spread: float
    ) -> dict:
        """Monitor forward closing execution with three scenarios"""
        strategy_id = config.strategy_id

        try:
            binance_order = await self._api_call_with_retry(
                self.order_executor.place_binance_limit_order,
                config.symbol,
                "BUY",
                order_qty,
                "ask"
            )
            self._log_opening_operation(
                strategy_id,
                "BINANCE_CLOSING_ORDER_PLACED",
                {"order_id": binance_order.get('orderId'), "qty": order_qty, "price_type": "ask"}
            )
        except Exception as e:
            return {"success": False, "error": f"Binance closing order failed: {str(e)}"}

        bybit_retry_count = 0
        max_bybit_retries = 4

        while bybit_retry_count < max_bybit_retries:
            if self._should_stop(strategy_id):
                return {"success": False, "error": "Strategy stopped"}

            await asyncio.sleep(self.normal_check_interval)

            try:
                binance_status = await self._api_call_with_retry(
                    self.order_executor.get_binance_order_status,
                    config.symbol,
                    binance_order['orderId']
                )
                filled_qty = float(binance_status.get('executedQty', 0))
                order_status = binance_status.get('status')

                self._log_opening_operation(
                    strategy_id,
                    "BINANCE_CLOSING_ORDER_STATUS",
                    {"status": order_status, "filled_qty": filled_qty}
                )

            except Exception as e:
                self.logger.warning(f"Failed to get Binance order status: {str(e)}")
                continue

            if filled_qty == 0:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    binance_ask = float(binance_ticker.get('askPrice', 0))
                    bybit_ask = float(bybit_ticker.get('ask1Price', 0))
                    current_spread = self._calc_forward_closing_spread(binance_ask, bybit_ask)

                    if current_spread < ladder.closing_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "FORWARD_CLOSING_SCENARIO_1_ABORT",
                            {"reason": "Binance unfilled and spread not met", "spread": current_spread}
                        )
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait after canceling unfilled order to prevent high-frequency re-ordering
                        self.logger.info(f"Waiting {self.close_wait_after_cancel_no_trade}s after canceling unfilled order")
                        await asyncio.sleep(self.close_wait_after_cancel_no_trade)
                        return {"success": False, "error": "Spread not met, order cancelled"}
                except Exception as e:
                    self.logger.warning(f"Failed to check spread: {str(e)}")

            if order_status == 'FILLED':
                result = await self._handle_binance_filled_forward_closing(
                    config, ladder, state, filled_qty, bybit_retry_count
                )
                return result

            if filled_qty > 0 and filled_qty < order_qty:
                try:
                    binance_ticker = await self._api_call_with_retry(
                        self.order_executor.get_binance_ticker,
                        config.symbol
                    )
                    bybit_ticker = await self._api_call_with_retry(
                        self.order_executor.get_bybit_ticker,
                        config.symbol
                    )
                    binance_ask = float(binance_ticker.get('askPrice', 0))
                    bybit_ask = float(bybit_ticker.get('ask1Price', 0))
                    current_spread = self._calc_forward_closing_spread(binance_ask, bybit_ask)

                    if current_spread < ladder.closing_spread:
                        self._log_opening_operation(
                            strategy_id,
                            "FORWARD_CLOSING_SCENARIO_3_ABORT",
                            {"reason": "Binance partially filled and spread not met", "filled_qty": filled_qty}
                        )
                        await self._api_call_with_retry(
                            self.order_executor.cancel_binance_order,
                            config.symbol,
                            binance_order['orderId']
                        )
                        # Wait after canceling partially filled order to prevent high-frequency re-ordering
                        self.logger.info(f"Waiting {self.close_wait_after_cancel_part}s after canceling partially filled order")
                        await asyncio.sleep(self.close_wait_after_cancel_part)
                        result = await self._handle_binance_filled_forward_closing(
                            config, ladder, state, filled_qty, bybit_retry_count
                        )
                        return result
                except Exception as e:
                    self.logger.warning(f"Failed to check spread for partial fill: {str(e)}")

        return {"success": False, "error": "Max Bybit retries reached"}

    async def _handle_binance_filled_forward_closing(
        self,
        config: StrategyConfig,
        ladder: LadderConfig,
        state: ExecutionState,
        filled_qty: float,
        retry_count: int
    ) -> dict:
        """Handle Binance filled scenario for forward closing"""
        strategy_id = config.strategy_id
        max_retries = 4

        filled_qty = round_quantity(filled_qty)

        self._log_opening_operation(
            strategy_id,
            "BYBIT_CLOSING_ORDER_START",
            {"qty": filled_qty, "retry": retry_count + 1}
        )

        try:
            # Step 1: Place aggressive limit order first (better price than market)
            bybit_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_limit_order,
                config.symbol,
                "SELL",
                filled_qty,
                "ask"
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_LIMIT_ORDER_PLACED",
                {"order_id": bybit_order.get('orderId'), "qty": filled_qty, "price_type": "ask", "strategy": "hybrid"}
            )

            # Step 2: Wait 0.5 seconds to check if limit order fills
            await asyncio.sleep(0.5)

            bybit_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_order['orderId']
            )
            bybit_filled_qty = float(bybit_status.get('cumExecQty', 0))
            bybit_order_status = bybit_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_LIMIT_ORDER_STATUS",
                {"status": bybit_order_status, "filled_qty": bybit_filled_qty, "wait_time": "0.5s"}
            )

            if bybit_order_status == 'Filled':
                state.ladder_accumulated_qty += filled_qty
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_CLOSING_SUCCESS_LIMIT",
                    {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "limit"}
                )
                return {"success": True, "qty": filled_qty}

            # Step 3: Limit order not filled, cancel and use market order as fallback
            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_LIMIT_NOT_FILLED",
                {"reason": "Limit order not filled in 0.5s, switching to market order"}
            )

            await self._api_call_with_retry(
                self.order_executor.cancel_bybit_order,
                config.symbol,
                bybit_order['orderId']
            )

            # Place market order as fallback (100% fill guarantee)
            bybit_market_order = await self._api_call_with_retry(
                self.order_executor.place_bybit_market_order,
                config.symbol,
                "SELL",
                filled_qty
            )
            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_MARKET_ORDER_PLACED",
                {"order_id": bybit_market_order.get('orderId'), "qty": filled_qty, "strategy": "market_fallback"}
            )

            # Wait briefly and check market order status
            await asyncio.sleep(0.3)

            market_status = await self._api_call_with_retry(
                self.order_executor.get_bybit_order_status,
                config.symbol,
                bybit_market_order['orderId']
            )
            market_filled_qty = float(market_status.get('cumExecQty', 0))
            market_order_status = market_status.get('orderStatus')

            self._log_opening_operation(
                strategy_id,
                "BYBIT_CLOSING_MARKET_ORDER_STATUS",
                {"status": market_order_status, "filled_qty": market_filled_qty}
            )

            if market_order_status == 'Filled':
                state.ladder_accumulated_qty += filled_qty
                self._log_opening_operation(
                    strategy_id,
                    "FORWARD_CLOSING_SUCCESS_MARKET",
                    {"qty": filled_qty, "accumulated": state.ladder_accumulated_qty, "order_type": "market"}
                )
                return {"success": True, "qty": filled_qty}

            # Market order also not filled (rare case), retry the whole process
            retry_count += 1
            if retry_count < max_retries:
                self._log_opening_operation(
                    strategy_id,
                    "BYBIT_CLOSING_MARKET_NOT_FILLED_RETRY",
                    {"reason": "Market order not filled, retrying", "retry": retry_count}
                )
                return await self._handle_binance_filled_forward_closing(
                    config, ladder, state, filled_qty, retry_count
                )
            else:
                return {"success": False, "error": "Max retries reached, market order still not filled"}

        except Exception as e:
            return {"success": False, "error": f"Bybit closing order failed: {str(e)}"}
