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
from app.utils.quantity_converter import quantity_converter


logger = logging.getLogger(__name__)


def _get_pair_config(pair_code: str = "XAU"):
    """Get symbol names and conversion factor from hedging pair config, with fallback"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair(pair_code)
        if pair:
            return pair.symbol_a.symbol, pair.symbol_b.symbol, pair.conversion_factor
    except Exception:
        pass
    return "XAUUSDT", "XAUUSD+", 100.0


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
        pair_code: str = "XAU",
        order_executor: OrderExecutorV2 = None,
        position_mgr: Optional[PositionManager] = None,
        hedge_multiplier: float = 1.0,
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
        self.pair_code = pair_code
        self.order_executor = order_executor
        self.position_mgr = position_mgr or position_manager
        self.hedge_multiplier = hedge_multiplier
        self.trigger_check_interval = trigger_check_interval
        self.api_spam_prevention_delay = api_spam_prevention_delay
        self.delayed_single_leg_check_delay = delayed_single_leg_check_delay
        self.delayed_single_leg_second_check_delay = delayed_single_leg_second_check_delay

        # Execution state
        self.is_running = False
        self.stop_requested = False  # Graceful stop: wait for safe exit point before stopping
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
        self.stop_requested = False
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account  # stored for position snapshot
        self.position_mgr.reset_strategy(self.strategy_id)

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

        logger.info(f"Starting ladder {ladder_idx} [{strategy_type}] loop: total_qty={ladder.total_qty}, threshold={spread_threshold}, triggers_required={trigger_count_required}")

        consecutive_no_fills = 0  # Track consecutive Binance timeouts/cancels without any fill
        MAX_CONSECUTIVE_NO_FILLS = 5  # After 5 consecutive no-fills, stop the ladder
        unhedged_binance_xau = 0.0  # Accumulated Binance fills not yet hedged (below 0.01 Lot)
        MIN_HEDGE_LOT = 0.01         # ICMarkets minimum lot size
        loop_count = 0
        current_position = 0  # initialise so the post-loop debug block always has a value
        while self.is_running and not self.stop_requested:
            loop_count += 1

            # Step 1: Check position
            # Get memory position (how much we've opened/closed so far)
            position_info = self.position_mgr.get_position(
                self.strategy_id,
                ladder_idx,
                strategy_type
            )
            current_position = position_info['current_position']

            # Log every 100 iterations (50s at 0.5s interval) to avoid log spam
            if loop_count % 100 == 1:
                logger.info(f"[ladder={ladder_idx}] iter={loop_count} pos={current_position}/{ladder.total_qty} triggers={self.trigger_mgr.count}/{trigger_count_required}")

            # Step 2: Check if ladder complete
            if current_position >= ladder.total_qty:
                logger.info(f"Ladder {ladder_idx} complete: {current_position}/{ladder.total_qty}")
                break

            # Step 3: Check trigger count
            trigger_ready = self.trigger_mgr.is_ready(trigger_count_required)

            if not trigger_ready:
                # Accumulate triggers
                try:
                    current_spread = await self._get_current_spread(strategy_type)
                except Exception as e:
                    logger.warning(f"[ladder={ladder_idx}] Failed to get spread for trigger check: {e}")
                    await asyncio.sleep(self.trigger_check_interval)
                    continue

                triggered = await self.trigger_mgr.check_and_increment(
                    current_spread,
                    spread_threshold,
                    compare_op,
                    required_count=trigger_count_required,  # enables express mode for extreme spreads
                )

                if triggered:
                    logger.debug(f"[ladder={ladder_idx}] trigger {self.trigger_mgr.count}/{trigger_count_required} spread={current_spread:.3f} threshold={spread_threshold}")
                    await self._push_trigger_progress(
                        ladder_idx,
                        self.trigger_mgr.count,
                        trigger_count_required,
                        strategy_type
                    )

                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 4: Re-check spread after trigger count is satisfied
            # If spread no longer meets threshold, reset triggers and wait again
            try:
                current_spread = await self._get_current_spread(strategy_type)
            except Exception as e:
                logger.warning(f"[ladder={ladder_idx}] Failed to get spread for re-check: {e}")
                await asyncio.sleep(self.trigger_check_interval)
                continue

            spread_ok = (
                (compare_op == CompareOperator.GREATER_EQUAL and current_spread >= spread_threshold) or
                (compare_op == CompareOperator.LESS_EQUAL and current_spread <= spread_threshold)
            )

            if not spread_ok:
                # Spread no longer satisfies condition — reset trigger count and wait
                logger.info(f"[ladder={ladder_idx}] Spread condition lapsed (spread={current_spread:.3f} threshold={spread_threshold}), resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)
                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 5: Calculate order quantity
            is_closing = strategy_type in ('reverse_closing', 'forward_closing')
            try:
                remaining = ladder.total_qty - current_position
                order_qty = min(order_qty_limit, remaining)
                logger.info(f"[ladder={ladder_idx}] Order qty: {order_qty}, remaining: {remaining}, limit: {order_qty_limit}")
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Exception calculating order_qty: {e}")
                break

            # Step 6: Check position limits
            try:
                result = self.position_mgr.check_can_open(
                    self.strategy_id,
                    ladder_idx,
                    strategy_type,
                    order_qty,
                    ladder.total_qty
                )

                can_open = result['can_open']
                reason = result.get('reason', '')

                if not can_open:
                    logger.warning(f"[ladder={ladder_idx}] Cannot open: {reason}")
                    break
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Exception in check_can_open: {e}")
                break

            # Step 7: Get current prices
            try:
                sym_a, sym_b, _ = _get_pair_config(self.pair_code)
                market_data = await market_data_service.get_current_spread(
                    binance_symbol=sym_a,
                    bybit_symbol=sym_b,
                )
                binance_price = self._get_binance_price(market_data, strategy_type)
                bybit_price = self._get_bybit_price(market_data, strategy_type)
                logger.info(f"[ladder={ladder_idx}] Prices — Binance={binance_price}, Bybit={bybit_price}")
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Failed to get market data: {e}")
                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 7.5: Snapshot positions before execution (for single-leg detection)
            try:
                pre_snapshot = await self._snapshot_positions(binance_account, bybit_account)
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Failed to snapshot positions: {e}")
                pre_snapshot = {}

            # ── Inject accumulated unhedged qty for B-side sizing ──────────────
            # If previous iterations had Binance fills too small for B-side (< 0.01 Lot),
            # we carry the deficit here and add it to the current order's B-side target.
            # This is passed via executor state so order_executor can use it.
            self._unhedged_binance_xau = unhedged_binance_xau

            # Step 7.9: Cancel any lingering open orders on A-side before placing new one
            # Prevents order accumulation on the exchange when previous cancels failed
            try:
                sym_a, _, _ = _get_pair_config(self.pair_code)
                from app.core.proxy_utils import build_proxy_url
                if binance_account.platform_id == 1:
                    from app.services.binance_client import BinanceFuturesClient
                    _cancel_client = BinanceFuturesClient(
                        binance_account.api_key, binance_account.api_secret,
                        proxy_url=build_proxy_url(binance_account.proxy_config)
                    )
                    try:
                        open_orders = await _cancel_client.get_open_orders(symbol=sym_a)
                        if open_orders and len(open_orders) > 0:
                            await _cancel_client.cancel_all_orders(sym_a)
                            logger.warning(f"[ladder={ladder_idx}] Cancelled {len(open_orders)} lingering open orders on {sym_a} before new order")
                    finally:
                        await _cancel_client.close()
                elif binance_account.platform_id == 2:
                    from app.services.bybit_client import BybitV5Client
                    _cancel_client = BybitV5Client(
                        api_key=binance_account.api_key, api_secret=binance_account.api_secret,
                        proxy_url=build_proxy_url(binance_account.proxy_config),
                    )
                    try:
                        resp = await _cancel_client.cancel_all_orders(category='linear', symbol=sym_a)
                        if resp: logger.warning(f"[ladder={ladder_idx}] Cancelled lingering Bybit orders on {sym_a}")
                    finally:
                        await _cancel_client.close()
            except Exception as e:
                logger.warning(f"[ladder={ladder_idx}] Failed to cancel lingering orders: {e}")

            # Step 8: Execute order
            logger.info(f"[ladder={ladder_idx}] Executing {strategy_type}: {order_qty} units")
            try:
                exec_result = await self._execute_order(
                    strategy_type,
                    binance_account,
                    bybit_account,
                    order_qty,
                    binance_price,
                    bybit_price,
                    spread_threshold,
                )
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Exception executing order: {e}")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)
                await asyncio.sleep(self.api_spam_prevention_delay)
                continue

            logger.info(f"[ladder={ladder_idx}] Result — success={exec_result.get('success')}, binance_filled={exec_result.get('binance_filled_qty')}, bybit_filled={exec_result.get('bybit_filled_qty')}")

            # Step 8.3: Immediately notify frontend to restore button when LADDER target is reached
            # 仅在本次成交使 current_position 达到/超过 total_qty 时才发送 button restore 通知。
            # 否则会在多批次场景（如 total_qty=2, m_coin=1）第一批次就错误地恢复按钮，
            # 导致用户看到按钮恢复后策略仍在继续交易第二批次。
            _binance_filled_now = exec_result.get('binance_filled_qty', 0)
            _new_position_after_fill = current_position + _binance_filled_now
            _ladder_will_complete = _new_position_after_fill >= ladder.total_qty

            if (exec_result.get('success')
                    and _binance_filled_now > 0
                    and _ladder_will_complete):
                try:
                    from app.services.strategy_status_pusher import status_pusher
                    action = 'opening' if 'opening' in strategy_type else 'closing'
                    bybit_filled_lot = exec_result.get('bybit_filled_qty', 0)
                    bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_lot)

                    await status_pusher.push_orders_filled(
                        strategy_id=self.strategy_id,
                        action=action,
                        binance_filled=_binance_filled_now,
                        bybit_filled=bybit_filled_xau,
                        user_id=self.user_id
                    )
                    logger.info(
                        f"[BUTTON_RESTORE] ✓ 最终成交通知已发送 "
                        f"(pos {current_position:.2f}→{_new_position_after_fill:.2f}/{ladder.total_qty}): "
                        f"strategy_id={self.strategy_id}, action={action}"
                    )
                except Exception as e:
                    logger.warning(f"[BUTTON_RESTORE] Failed to send button restore notification: {e}")
            elif exec_result.get('success') and _binance_filled_now > 0:
                # 中间批次成交：不发送 button restore，仅记录日志
                logger.info(
                    f"[BUTTON_RESTORE] 中间批次成交不发送通知 "
                    f"(pos {current_position:.2f}→{_new_position_after_fill:.2f}/{ladder.total_qty})"
                )

            # Step 8.5: Schedule single-leg check if Binance had any fill
            # Non-blocking: uses asyncio.create_task so it never interrupts the main execution loop
            binance_filled_qty = exec_result.get('binance_filled_qty', 0)
            if binance_filled_qty and binance_filled_qty > 0:
                asyncio.create_task(self._delayed_single_leg_check(
                    strategy_type=strategy_type,
                    exec_result=exec_result,
                    binance_account=binance_account,
                    bybit_account=bybit_account,
                    pre_snapshot=pre_snapshot
                ))

            if not exec_result['success']:
                logger.error(f"Execution failed: {exec_result.get('error')}")

                # CRITICAL: MT5 position exhausted — no more position to close.
                # Treat as normal completion (not an error) and exit the ladder loop.
                if exec_result.get('position_exhausted') and not is_opening:
                    logger.info(
                        f"[ladder={ladder_idx}] MT5持仓已耗尽 ({exec_result.get('error')})，"
                        f"平仓策略视为完成 pos={current_position}/{ladder.total_qty}"
                    )
                    # Send button restore notification so frontend knows we are done
                    try:
                        from app.services.strategy_status_pusher import status_pusher as _sp
                        await _sp.push_orders_filled(
                            strategy_id=self.strategy_id,
                            action='closing',
                            binance_filled=current_position,
                            bybit_filled=current_position,
                            user_id=self.user_id
                        )
                    except Exception as _e:
                        logger.warning(f"[BUTTON_RESTORE] Failed to send position_exhausted restore: {_e}")
                    break

                # CRITICAL: Binance API outage detected — stop strategy and send emergency alert
                if exec_result.get('binance_api_error'):
                    logger.error(f"[EMERGENCY] Binance API outage during {strategy_type} execution — stopping strategy immediately")
                    self.is_running = False
                    await self._send_binance_api_emergency_alert(strategy_type, exec_result)
                    return {'success': False, 'error': 'Binance API outage'}

                # CRITICAL: Terminal (non-retryable) Binance error — stop the strategy and notify.
                # Without this guard the loop keeps retrying forever, e.g. -4411 TradFi-Perps
                # agreement, -2015 API key invalid, -4401 account blocked, etc.
                binance_result = exec_result.get('binance_result') or {}
                if binance_result.get('terminal_error'):
                    err_code = binance_result.get('error_code', 'unknown')
                    err_msg = binance_result.get('error', '未知错误')
                    logger.error(
                        f"[TERMINAL] Binance returned non-retryable error (code={err_code}) during "
                        f"{strategy_type} — stopping strategy: {err_msg}"
                    )
                    self.is_running = False
                    try:
                        from app.core.redis_client import redis_client as _rc
                        import json as _json
                        # Human-readable hint for common compliance errors
                        hints = {
                            -4411: 'Binance 要求签署 TradFi-Perps 合约协议。请登录 Binance 网页端 → 合约交易 → 黄金品种，完成协议签署后重试。',
                            -4412: 'Binance 账户类型需要升级，请在网页端完成账户升级。',
                            -4400: 'API 账户无交易权限，请检查 API Key 是否开启了合约交易权限。',
                            -4401: 'Binance 账户合约交易已被冻结，请联系 Binance 客服。',
                            -2015: 'API Key 无效或 IP 未加白名单。',
                        }
                        try:
                            _code_int = int(err_code)
                        except (TypeError, ValueError):
                            _code_int = None
                        hint = hints.get(_code_int, '请检查 Binance 账户状态和 API 权限。')
                        evt = {
                            "user_id": self.user_id or "",
                            "type": "risk_alert",
                            "data": {
                                "alert_type": "binance_terminal_error",
                                "level": "critical",
                                "title": "⛔ Binance 账户异常 — 策略已停止",
                                "message": f"{err_msg}",
                                "popup_config": {
                                    "title": "⛔ Binance 账户异常",
                                    "content": f"错误代码: {err_code}\n{err_msg}\n\n{hint}",
                                    "sound_file": "liquidation.mp3",
                                    "sound_repeat": 3,
                                },
                            },
                        }
                        if self.user_id:
                            await _rc.publish("ws:user_event", _json.dumps(evt))
                        logger.info(f"[TERMINAL] Alert published to ws:user_event for user {self.user_id}")
                    except Exception as _alert_err:
                        logger.warning(f"[TERMINAL] Failed to publish stop alert: {_alert_err}")
                    return {'success': False, 'error': f'Terminal Binance error: {err_code}'}

                # CRITICAL FIX: Even if execution failed, record Binance filled qty to prevent over-trading
                binance_filled = exec_result.get('binance_filled_qty', 0)
                if binance_filled > 0:
                    # Record the filled quantity to position manager
                    self.position_mgr.record_opening(
                        self.strategy_id,
                        ladder_idx,
                        strategy_type,
                        binance_filled
                    )
                    logger.warning(f"Execution failed but Binance filled {binance_filled} XAU - recorded to prevent over-trading")

                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)
                await asyncio.sleep(self.api_spam_prevention_delay)
                continue

            # Step 9: Handle three scenarios
            binance_filled = exec_result.get('binance_filled_qty', 0)
            spread_cancelled = exec_result.get('spread_cancelled', False)
            is_partial = binance_filled > 0 and binance_filled < order_qty * 0.95

            # Scenario 1 pre-check: If monitor reports filled=0, verify via REST API
            # The WS-based monitor can miss fills (ORDER_TRADE_UPDATE not received, 
            # or TradFi-Perps orders have delayed WS events). A false-negative here
            # means we leave unfilled Binance orders on the exchange that later fill
            # without a corresponding B-side hedge → single-leg exposure.
            if binance_filled == 0 and exec_result.get('binance_order_id'):
                try:
                    _order_id = exec_result['binance_order_id']
                    _rest_status = await self.order_executor.base_executor.check_binance_order_status(
                        binance_account, sym_a, _order_id
                    )
                    if _rest_status and _rest_status.get('success'):
                        _actual_filled = _rest_status.get('filled_qty', 0)
                        _actual_status = _rest_status.get('status', '')
                        if _actual_filled > 0:
                            logger.warning(
                                f"[ladder={ladder_idx}] REST verify: order {_order_id} actually filled "
                                f"{_actual_filled} (status={_actual_status}), WS monitor missed it! "
                                f"Executing emergency B-side hedge."
                            )
                            binance_filled = _actual_filled
                            exec_result['binance_filled_qty'] = _actual_filled
                            # Emergency B-side hedge: the executor missed it, do it now
                            try:
                                sym_a_h, sym_b_h, conv_h = _get_pair_config(self.pair_code)
                                from app.utils.quantity_converter import quantity_converter as _qc
                                _b_qty = _qc.xau_to_lot(_actual_filled)
                                # Determine B-side direction based on strategy type
                                _is_opening_s = 'opening' in strategy_type
                                if strategy_type in ('forward_opening', 'reverse_closing'):
                                    _b_side = "Sell"
                                    _close_pos = not _is_opening_s  # forward_opening=open short, reverse_closing=close short
                                else:
                                    _b_side = "Buy"
                                    _close_pos = not _is_opening_s
                                logger.warning(f"[EMERGENCY_HEDGE] Placing B-side {_b_side} {_b_qty} lot on {sym_b_h}")
                                _b_result = await self.order_executor.base_executor.place_bybit_order(
                                    account=bybit_account,
                                    symbol=sym_b_h,
                                    side=_b_side,
                                    order_type="Market",
                                    quantity=str(round(_b_qty, 2)),
                                    close_position=_close_pos,
                                )
                                if _b_result.get('success'):
                                    logger.warning(f"[EMERGENCY_HEDGE] B-side hedge SUCCESS: {_b_result.get('order_id')}")
                                    exec_result['bybit_filled_qty'] = _b_qty
                                else:
                                    logger.error(f"[EMERGENCY_HEDGE] B-side hedge FAILED: {_b_result.get('error')}")
                            except Exception as _hedge_err:
                                logger.error(f"[EMERGENCY_HEDGE] B-side hedge exception: {_hedge_err}")
                except Exception as _e:
                    logger.warning(f"[ladder={ladder_idx}] REST verify failed: {_e}")

            # Scenario 1: Binance not filled or spread cancelled
            if binance_filled == 0:
                consecutive_no_fills += 1
                logger.info(f"Scenario 1: Binance not filled ({consecutive_no_fills}/{MAX_CONSECUTIVE_NO_FILLS}), resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)

                # After too many consecutive no-fills, pause and reset (don't permanently stop)
                # The strategy should keep waiting for market conditions to improve
                if consecutive_no_fills >= MAX_CONSECUTIVE_NO_FILLS:
                    logger.warning(
                        f"[ladder={ladder_idx}] {consecutive_no_fills} consecutive no-fills — "
                        f"pausing {MAX_CONSECUTIVE_NO_FILLS * 2}s then resuming"
                    )
                    consecutive_no_fills = 0  # Reset counter to allow another round
                    await asyncio.sleep(MAX_CONSECUTIVE_NO_FILLS * 2)  # 10s pause
                    self.trigger_mgr.reset()
                    continue

                # Progressive backoff: 1s → 2s → 3s → 4s → 5s
                is_opening = strategy_type in ('reverse_opening', 'forward_opening')
                base_wait = (self.order_executor.open_wait_after_cancel_no_trade
                             if is_opening else self.order_executor.close_wait_after_cancel_no_trade)
                wait_time = base_wait * consecutive_no_fills
                logger.info(f"Waiting {wait_time}s after cancel ({'spread' if spread_cancelled else 'timeout'}, no-fill #{consecutive_no_fills})")
                # Safe exit point 1: Binance order cancelled — no single-leg risk
                if self.stop_requested:
                    logger.info(f"[GRACEFUL STOP] Stop requested — exiting after Binance cancel (safe, no single-leg)")
                    self.is_running = False
                    break
                await asyncio.sleep(wait_time)
                continue

            # Scenario 1b: Partial fill after cancel
            if is_partial:
                is_opening = strategy_type in ('reverse_opening', 'forward_opening')
                wait_time = (self.order_executor.open_wait_after_cancel_part
                             if is_opening else self.order_executor.close_wait_after_cancel_part)
                logger.info(f"Partial fill {binance_filled}/{order_qty}, waiting {wait_time}s before continuing")

            # Step 10: Record position
            # Use Binance filled qty as the position basis (Binance is primary leg).
            # Bybit MT5 fill may lag or return 0 due to sync delay — using min() would
            # cause position to never accumulate and the loop to never terminate.
            binance_filled_xau = exec_result.get('binance_filled_qty', 0)
            bybit_filled_lot = exec_result.get('bybit_filled_qty', 0)
            bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_lot)
            filled_qty = binance_filled_xau  # primary leg determines position progress

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

            consecutive_no_fills = 0  # Reset on successful fill

            # ── Unhedged accumulator: handle B-side below-min-lot skips ─────────
            # When a partial Binance fill is too small to meet 0.01 Lot minimum,
            # order_executor returns b_side_skipped_below_min=True. Accumulate
            # the skipped XAU here and retry B-side on the next iteration.
            if exec_result.get('b_side_skipped_below_min') and binance_filled_xau > 0:
                unhedged_binance_xau += binance_filled_xau
                logger.warning(
                    f"[HEDGE_ACCUM] B-side skipped (< {MIN_HEDGE_LOT} Lot), "
                    f"accumulated unhedged={unhedged_binance_xau:.4f} XAU"
                )
            elif binance_filled_xau > 0 and bybit_filled_lot > 0:
                # Successful dual-side fill — reset accumulator
                if unhedged_binance_xau > 0:
                    logger.info(f"[HEDGE_ACCUM] Cleared accumulator after successful B-side fill")
                unhedged_binance_xau = 0.0
            elif unhedged_binance_xau > 0 and exec_result.get('bybit_filled_qty', 0) > 0:
                unhedged_binance_xau = 0.0

            logger.info(f"Position updated: {'+'if is_opening else '-'}{filled_qty}")

            # Step 11: Push status updates
            await self._push_position_change(ladder_idx, filled_qty, position_info)
            await self._push_order_executed(ladder_idx, exec_result, current_spread)

            # Step 12: Reset triggers after successful execution
            # CRITICAL FIX: Always reset triggers after order execution to allow next cycle to accumulate fresh triggers
            # This prevents the issue where trigger count remains high and blocks subsequent executions
            logger.info(f"[ladder={ladder_idx}] Filled {binance_filled}/{order_qty}, resetting triggers. New pos: {current_position + filled_qty}/{ladder.total_qty}")
            self.trigger_mgr.reset()
            await self._push_trigger_reset(ladder_idx, strategy_type)

            # Safe exit point 2: Both legs filled — no single-leg risk
            if self.stop_requested:
                logger.info(f"[GRACEFUL STOP] Stop requested — exiting after dual-leg fill (safe, binance={binance_filled} bybit={exec_result.get('bybit_filled_qty', 0)})")
                self.is_running = False
                break

            # ── 目标达成立即退出，不等待 api_spam_prevention_delay ──────────────────
            # 若本次成交已填满当前梯度的总量，直接 break 进入下一梯度或退出，
            # 无需再等 api_spam_prevention_delay（3s），避免双边成交后按钮复原延迟。
            new_position = current_position + filled_qty
            if new_position >= ladder.total_qty:
                logger.info(
                    f"[ladder={ladder_idx}] 目标已达成 ({new_position:.4f}/{ladder.total_qty})，"
                    f"跳过 api_spam_prevention_delay，立即退出"
                )
                break

            # Small delay to prevent API spam (configurable via api_spam_prevention_delay)
            # 仅在目标未完成、需要继续触发时等待，防止频繁 API 调用
            logger.info(f"Waiting {self.api_spam_prevention_delay} seconds to prevent API spam")
            await asyncio.sleep(self.api_spam_prevention_delay)

        logger.info(f"[ladder={ladder_idx}] Loop exited after {loop_count} iterations. pos={current_position}/{ladder.total_qty} stop_req={self.stop_requested} is_running={self.is_running}")
        return {'success': True}

    async def _get_current_spread(self, strategy_type: str) -> float:
        """Get current spread for strategy type (pair-aware)"""
        sym_a, sym_b, _ = _get_pair_config(self.pair_code)
        market_data = await market_data_service.get_current_spread(
            binance_symbol=sym_a,
            bybit_symbol=sym_b,
        )
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
        """Get reference Binance price for strategy type.

        NOTE: The actual order price is NOT used when post_only=True because
        place_binance_order delegates to place_maker_order (priceMatch=QUEUE),
        which sets the price server-side atomically at the current BBO.

        This value is only used for logging (Step 7) and spread calculation.
        Return the natural side price for reference.
        """
        if 'opening' in strategy_type:
            if 'reverse' in strategy_type:
                return market_data.binance_quote.ask_price   # Reverse opening: SELL SHORT
            else:
                return market_data.binance_quote.bid_price   # Forward opening: BUY LONG
        else:
            if 'reverse' in strategy_type:
                return market_data.binance_quote.bid_price   # Reverse closing: BUY SHORT close
            else:
                return market_data.binance_quote.ask_price   # Forward closing: SELL LONG close

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
        spread_threshold: float = None,
    ) -> Dict:
        """Execute order based on strategy type"""
        if strategy_type == 'reverse_opening':
            return await self.order_executor.execute_reverse_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
                accumulated_unhedged_xau=getattr(self, '_unhedged_binance_xau', 0.0),
            )
        elif strategy_type == 'reverse_closing':
            return await self.order_executor.execute_reverse_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
            )
        elif strategy_type == 'forward_opening':
            return await self.order_executor.execute_forward_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
                accumulated_unhedged_xau=getattr(self, '_unhedged_binance_xau', 0.0),
            )
        elif strategy_type == 'forward_closing':
            return await self.order_executor.execute_forward_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
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
        if self.user_id:
            # Extract action from strategy_type (e.g., 'reverse_opening' -> 'opening')
            action = 'opening' if 'opening' in strategy_type else 'closing'
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
        """Push position change notification and broadcast real-time MT5 position snapshot."""
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

        # Read MT5 + Binance positions directly (bypasses 60s cache) and push to frontend immediately
        try:
            from app.websocket.manager import manager as ws_manager
            from app.services.binance_client import BinanceFuturesClient

            bybit_account = getattr(self, '_bybit_account', None)
            binance_account = getattr(self, '_binance_account', None)

            long_lots = 0.0
            short_lots = 0.0
            binance_long_xau = 0.0
            binance_short_xau = 0.0

            # Bybit: read from MT5 directly
            sym_a, sym_b, conv_factor = _get_pair_config(self.pair_code)
            if bybit_account and hasattr(bybit_account, 'mt5_client') and bybit_account.mt5_client:
                loop = asyncio.get_event_loop()
                positions = await loop.run_in_executor(
                    None,
                    lambda: bybit_account.mt5_client.get_positions(sym_b)
                )
                long_lots = round(sum(p['volume'] for p in positions if p.get('type') == 0), 2)
                short_lots = round(sum(p['volume'] for p in positions if p.get('type') == 1), 2)

            # Binance: read from REST API directly
            if binance_account and binance_account.api_key and binance_account.api_secret:
                try:
                    _proxy = build_proxy_url(getattr(binance_account, 'proxy_config', None))
                    client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret, proxy_url=_proxy)
                    pos_data = await client.get_position_risk(sym_a)
                    await client.close()
                    for pos in pos_data:
                        amt = float(pos.get("positionAmt", 0))
                        if amt > 0:
                            binance_long_xau = round(amt, 3)
                        elif amt < 0:
                            binance_short_xau = round(abs(amt), 3)
                except Exception as be:
                    logger.warning(f"[POSITION_SNAPSHOT] Binance fetch failed: {be}")

            await ws_manager.broadcast_position_snapshot(long_lots, short_lots, binance_long_xau, binance_short_xau)
            logger.info(f"[POSITION_SNAPSHOT] bybit long={long_lots} short={short_lots} | binance long={binance_long_xau} short={binance_short_xau}")
        except Exception as e:
            logger.warning(f"[POSITION_SNAPSHOT] Failed: {e}")

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

    async def _push_execution_completed(self, strategy_type: str, reason: str = 'completed'):
        """Push execution completed notification via WebSocket"""
        if self.user_id:
            action = 'opening' if 'opening' in strategy_type else 'closing'
            await status_pusher.push_custom_event(
                self.strategy_id,
                'execution_completed',
                {
                    'action': action,
                    'strategy_type': strategy_type,
                    'reason': reason
                },
                self.user_id
            )

    async def _snapshot_positions(
        self,
        binance_account: Account,
        bybit_account: Account
    ) -> Dict:
        """
        Snapshot current positions for both accounts before order execution.
        Used as baseline for single-leg detection via position delta comparison.
        """
        try:
            # Init Binance client if needed
            if not hasattr(binance_account, 'binance_client'):
                from app.services.binance_client import BinanceFuturesClient
                binance_account.binance_client = BinanceFuturesClient(
                    api_key=binance_account.api_key,
                    api_secret=binance_account.api_secret
                )

            # Init MT5 client if needed
            if not hasattr(bybit_account, 'mt5_client'):
                from app.services.mt5_client import MT5Client
                bybit_account.mt5_client = MT5Client(
                    login=int(bybit_account.mt5_id),
                    password=bybit_account.mt5_primary_pwd,
                    server=bybit_account.mt5_server
                )
                if not bybit_account.mt5_client.connect():
                    logger.warning("[SNAPSHOT] MT5 connection failed, snapshot will be empty")
                    return {'binance_qty': None, 'bybit_qty_xau': None}

            sym_a, sym_b, conv_factor = _get_pair_config(self.pair_code)
            binance_positions = await binance_account.binance_client.get_position_risk(symbol=sym_a)
            binance_qty = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions)

            bybit_positions = bybit_account.mt5_client.get_positions(symbol=sym_b)
            bybit_qty_lot = sum(abs(float(pos.get('volume', 0))) for pos in bybit_positions)
            bybit_qty_xau = bybit_qty_lot * conv_factor

            logger.info(f"[SNAPSHOT] Pre-execution: Binance={binance_qty} XAU, Bybit={bybit_qty_xau} XAU ({bybit_qty_lot} Lot)")
            return {'binance_qty': binance_qty, 'bybit_qty_xau': bybit_qty_xau}

        except Exception as e:
            logger.warning(f"[SNAPSHOT] Failed to snapshot positions: {e}")
            return {'binance_qty': None, 'bybit_qty_xau': None}

    async def _delayed_single_leg_check(
        self,
        strategy_type: str,
        exec_result: Dict,
        binance_account: Account,
        bybit_account: Account,
        pre_snapshot: Dict = None
    ):
        """
        Single-leg detection based on position DELTA comparison after 3-second wait.

        Rules:
        1. Wait 3 seconds after Binance fill for exchange data to sync
        2. Compute position delta: post - pre for both sides
        3. If both sides fully filled → no alert
        4. If partial: bybit_delta_xau / binance_delta_xau < 0.6 → alert
           (ratio accounts for 1 XAU Binance = 0.01 Lot Bybit conversion)
        5. Alert is non-blocking: never interrupts the main execution loop
        """
        try:
            logger.info(f"[SINGLE_LEG_CHECK] Waiting {self.delayed_single_leg_check_delay}s after Binance fill for {strategy_type}")
            await asyncio.sleep(self.delayed_single_leg_check_delay)

            # Ensure clients are initialized
            try:
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
                        logger.error("[SINGLE_LEG_CHECK] MT5 connection failed, skipping check")
                        return

                # Get post-execution positions
                sym_a, sym_b, conv_factor = _get_pair_config(self.pair_code)
                binance_positions = await binance_account.binance_client.get_position_risk(symbol=sym_a)
                post_binance_qty = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions)

                bybit_positions = bybit_account.mt5_client.get_positions(symbol=sym_b)
                bybit_qty_lot = sum(abs(float(pos.get('volume', 0))) for pos in bybit_positions)
                post_bybit_qty_xau = bybit_qty_lot * conv_factor

                # Compute deltas using pre-snapshot
                if pre_snapshot and pre_snapshot.get('binance_qty') is not None:
                    binance_delta = abs(post_binance_qty - pre_snapshot['binance_qty'])
                    bybit_delta_xau = abs(post_bybit_qty_xau - pre_snapshot['bybit_qty_xau'])
                else:
                    # Fallback: use exec_result filled quantities
                    binance_delta = exec_result.get('binance_filled_qty', 0)
                    bybit_filled_lot = exec_result.get('bybit_filled_qty', 0)
                    bybit_delta_xau = bybit_filled_lot * conv_factor

                logger.info(
                    f"[SINGLE_LEG_CHECK] Delta: Binance={binance_delta:.4f} XAU, "
                    f"Bybit={bybit_delta_xau:.4f} XAU | "
                    f"Post: Binance={post_binance_qty} XAU, Bybit={post_bybit_qty_xau} XAU"
                )

                # No Binance fill detected → nothing to check
                if binance_delta < 0.001:
                    logger.info("[SINGLE_LEG_CHECK] No Binance position change detected, skipping")
                    return

                # Both sides fully matched (within 5% tolerance) → no alert
                if bybit_delta_xau >= binance_delta * 0.95:
                    logger.info(
                        f"[SINGLE_LEG_CHECK] Both sides matched: "
                        f"Bybit/Binance ratio={bybit_delta_xau/binance_delta:.2%}, no alert"
                    )
                    return

                # Compute fill ratio
                ratio = bybit_delta_xau / binance_delta if binance_delta > 0 else 0

                if ratio < 0.6:
                    logger.error(
                        f"[SINGLE_LEG_CHECK] SINGLE-LEG CONFIRMED: "
                        f"Binance delta={binance_delta:.4f} XAU, "
                        f"Bybit delta={bybit_delta_xau:.4f} XAU, "
                        f"ratio={ratio:.2%} < 60%"
                    )
                    exec_result['single_leg_details'] = {
                        'binance_filled': binance_delta,
                        'bybit_filled': bybit_delta_xau,
                        'bybit_filled_xau': bybit_delta_xau,
                        'unfilled_qty': binance_delta - bybit_delta_xau,
                        'fill_ratio': ratio,
                        'verification_method': 'position_delta_3s'
                    }
                    await self._send_single_leg_alert(
                        strategy_type=strategy_type,
                        exec_result=exec_result
                    )
                else:
                    logger.info(
                        f"[SINGLE_LEG_CHECK] Partial fill but ratio={ratio:.2%} >= 60%, no alert"
                    )

            except Exception as e:
                logger.error(f"[SINGLE_LEG_CHECK] Position check error: {e}")

        except Exception as e:
            logger.error(f"[SINGLE_LEG_CHECK] Delayed check failed: {e}")

    async def _send_binance_api_emergency_alert(
        self,
        strategy_type: str,
        exec_result: Dict
    ):
        """
        Send emergency alert when Binance API is down during execution.
        Strategy is stopped immediately. Alert sent via WebSocket and Feishu.
        """
        if not self.user_id:
            return

        strategy_name = "正向套利" if "forward" in strategy_type else "反向套利"
        action = "开仓" if "opening" in strategy_type else "平仓"
        order_id = exec_result.get("binance_order_id", "未知")

        import datetime
        timestamp = datetime.datetime.utcnow().isoformat()

        # WebSocket emergency alert
        try:
            from app.websocket.manager import manager
            alert_message = {
                "type": "binance_api_emergency",
                "data": {
                    "strategy_type": strategy_name,
                    "action": action,
                    "order_id": order_id,
                    "timestamp": timestamp,
                    "level": "critical",
                    "title": "🚨 Binance交易系统异常 — 策略已紧急停止",
                    "message": (
                        f"{strategy_name} {action}：Binance API连续查询失败，"
                        f"订单 {order_id} 状态未知，策略已自动停止。"
                        f"请立即登录Binance交易软件人工核查持仓和挂单！"
                    )
                }
            }
            await manager.send_to_user(alert_message, self.user_id)
            logger.error(f"[EMERGENCY] WebSocket alert sent for Binance API outage: order_id={order_id}")
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed to send WebSocket alert: {e}")

        # Feishu emergency alert
        try:
            from app.services.feishu_service import get_feishu_service
            from app.core.database import get_db
            from app.models.user import User
            from sqlalchemy import select as sa_select
            feishu = get_feishu_service()
            if feishu:
                async for db in get_db():
                    result = await db.execute(sa_select(User).where(User.user_id == self.user_id))
                    user = result.scalar_one_or_none()
                    if user and (user.feishu_open_id or user.email):
                        receiver_id = user.feishu_open_id if user.feishu_open_id else user.email
                        receive_id_type = "open_id" if user.feishu_open_id else "email"
                        content = (
                            f"🚨 Binance交易系统异常\n"
                            f"策略：{strategy_name} {action}\n"
                            f"订单号：{order_id}\n"
                            f"时间：{timestamp}\n"
                            f"原因：Binance API连续{exec_result.get('api_error_count', 3)}次查询失败\n"
                            f"处理：策略已自动停止，请立即人工核查Binance持仓和挂单！"
                        )
                        await feishu.send_text_message(receiver_id, receive_id_type, content)
                    break
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed to send Feishu alert: {e}")

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

        # Send WebSocket notification via Redis bridge (Go Hub).
        # Python ws_manager.active_connections is empty — frontend only connects to Go /ws.
        # We wrap this as a risk_alert so the global handler in market.js dispatches it,
        # and so the alert_type "single_leg_alert" is gated by the frontend
        # singleLegAlertEnabled toggle (see notification.js handleRiskAlert).
        try:
            from app.core.redis_client import redis_client as _rc
            import json as _json

            msg = f"{strategy_name} {action}: Binance成交 {details.get('binance_filled', 0)}, Bybit成交 {details.get('bybit_filled', 0)}, 未成交 {details.get('unfilled_qty', 0)}"
            evt = {
                "user_id": self.user_id,
                "type": "risk_alert",
                "data": {
                    "alert_type": "single_leg_alert",
                    "level": "critical",
                    "title": "单腿交易警告",
                    "message": msg,
                    "timestamp": details.get("timestamp"),
                    "template_key": "single_leg_alert",
                    "popup_config": {
                        "title": "单腿交易警告",
                        "content": msg,
                        "sound_file": "single_leg.mp3",
                        "sound_repeat": 5,
                    },
                    # Pass through raw fields so the frontend deduplication keeps working.
                    "strategy_type": strategy_name,
                    "action": action,
                    "binance_filled": details.get("binance_filled", 0),
                    "bybit_filled": details.get("bybit_filled", 0),
                    "unfilled_qty": details.get("unfilled_qty", 0),
                },
            }
            await _rc.publish("ws:user_event", _json.dumps(evt))
        except Exception as ws_err:
            logger.warning(f"[SINGLE_LEG] Redis WS publish failed: {ws_err}")

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
        """Request graceful stop.

        Sets stop_requested=True so the loop exits only at a safe point:
        - After Binance+Bybit both fill (双边成交完成)
        - After Binance order is cancelled (撤单，无单腿风险)
        Never interrupts mid-execution to prevent single-leg exposure.
        """
        logger.info(f"Stop requested for strategy {self.strategy_id} — will exit at next safe point")
        self.stop_requested = True
        self.is_running = False  # also set for legacy checks

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
        logger.info(f"Starting forward opening continuous execution for strategy {self.strategy_id}")
        logger.info(f"Binance: {binance_account.account_name}, Bybit: {bybit_account.account_name}, Ladders: {len(ladders)}")

        self.is_running = True
        self.stop_requested = False
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        self.position_mgr.reset_strategy(self.strategy_id)

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
        self.stop_requested = False
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        self.position_mgr.reset_strategy(self.strategy_id)

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
            await self._push_execution_completed('reverse_closing')
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
        self.stop_requested = False
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        self.position_mgr.reset_strategy(self.strategy_id)

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
            await self._push_execution_completed('forward_closing')
            return {'success': True, 'message': 'All ladders completed'}

        except Exception as e:
            logger.exception(f"Error in forward closing continuous: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self.is_running = False

