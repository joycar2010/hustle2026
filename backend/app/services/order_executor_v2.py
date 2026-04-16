"""Order Executor V2.0 - Optimized with shorter timeouts"""
import asyncio
import inspect
import time
import logging
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.account import Account
from app.services.order_executor import order_executor as base_executor
from app.utils.quantity_converter import quantity_converter

logger = logging.getLogger(__name__)


def _get_pair_symbols(pair_code: str = "XAU"):
    """Get symbol names from hedging pair config, with fallback"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair(pair_code)
        if pair:
            return pair.symbol_a.symbol, pair.symbol_b.symbol
    except Exception:
        pass
    return "XAUUSDT", "XAUUSD+"


def _a_to_b(qty: float, pair_code: str = "XAU") -> float:
    """Convert A-side quantity (e.g. XAU) to B-side (e.g. Lot) using pair conv factor."""
    conv = quantity_converter.get_pair_converter(pair_code)
    if conv:
        return conv.a_to_b(qty)
    return quantity_converter.xau_to_lot(qty)


def _b_to_a(qty: float, pair_code: str = "XAU") -> float:
    """Convert B-side quantity (e.g. Lot) to A-side (e.g. XAU) using pair conv factor."""
    conv = quantity_converter.get_pair_converter(pair_code)
    if conv:
        return conv.b_to_a(qty)
    return float(quantity_converter.lot_to_xau(qty))


def _trigger_position_refresh():
    """触发持仓立即刷新，避免等待30秒周期。

    Two-step process:
    1. Invalidate the 60s account_data_service cache so the next read is fresh
    2. Signal AccountBalanceStreamer to re-poll immediately (skip remaining interval)
    """
    try:
        from app.services.account_service import account_data_service
        account_data_service.invalidate_cache()
        logger.info("[ORDER_EXECUTOR] Cache invalidated")
    except Exception as e:
        logger.warning(f"[ORDER_EXECUTOR] Cache invalidation failed: {e}")

    try:
        from app.tasks.broadcast_tasks import account_balance_streamer
        account_balance_streamer.trigger_immediate_refresh()
        logger.info("[ORDER_EXECUTOR] Triggered immediate position refresh")
    except Exception as e:
        logger.warning(f"[ORDER_EXECUTOR] Failed to trigger position refresh: {e}")


def _get_mt5_client_for_account(account: Account):
    """Get MT5HttpClient connected to the TRADING bridge (not system/data bridge).

    The system bridge (8001) has no trading positions.
    We look up the trading bridge port from mt5_clients (is_system_service=False).
    Returns an MT5HttpClient pointing at the correct bridge.
    """
    from app.services.mt5_http_client import MT5HttpClient
    import os, asyncio, logging
    _log = logging.getLogger(__name__)

    # Determine trading bridge URL from DB (sync, cache in module-level dict)
    bridge_url = _get_trading_bridge_url(str(account.account_id))
    api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))
    client = MT5HttpClient(base_url=bridge_url, api_key=api_key)
    _log.info(f"[MT5] Using trading bridge {bridge_url} for account {account.account_id}")
    return client


# Module-level cache so we don't hit the DB on every single position check
_trading_bridge_cache: dict = {}   # account_id -> bridge_url


def _get_trading_bridge_url(account_id: str) -> str:
    """Look up the trading bridge URL for an account from mt5_clients table."""
    import os
    if account_id in _trading_bridge_cache:
        return _trading_bridge_cache[account_id]

    default_url = os.getenv("MT5_BRIDGE_URL", "http://172.31.14.113:8002")
    try:
        # Synchronous DB lookup (called from sync context inside run_in_executor or direct async path)
        import asyncio as _asyncio
        from sqlalchemy import create_engine, text
        import os as _os
        db_url = _os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        if not db_url:
            return default_url
        engine = create_engine(db_url, pool_size=1, max_overflow=0, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT bridge_service_port FROM mt5_clients "
                    "WHERE account_id = :aid AND is_active = true AND is_system_service = false "
                    "ORDER BY priority LIMIT 1"
                ),
                {"aid": account_id}
            ).fetchone()
        engine.dispose()
        if row and row[0]:
            url = f"http://172.31.14.113:{row[0]}"
            _trading_bridge_cache[account_id] = url
            return url
    except Exception as e:
        logger.debug(f"[MT5] Bridge lookup failed for {account_id}: {e}")

    _trading_bridge_cache[account_id] = default_url
    return default_url


class OrderExecutorV2:
    """
    Optimized order executor with V2.0 specifications:
    - Binance timeout: 0.6 seconds (increased for better fill rate)
    - Bybit timeout: 0.1 seconds
    - Single retry for unfilled orders
    """

    def __init__(self):
        self.binance_timeout = 2.0
        self.bybit_timeout = 0.3  # 0.1→0.3: Bybit订单有更多时间进入市场，同时保持快速执行
        self.max_retries = 3  # 1→3: 增加重试次数，降低单腿风险
        self.order_check_interval = 0.5  # 0.2→0.5: 每次平仓REST调用减少60%，防止IP封禁
        self.spread_check_interval = 1.0
        self.mt5_deal_sync_wait = 5.0  # 3.0→5.0: MT5成交同步最大等待时间
        self.mt5_poll_interval = 0.5  # 新增：轮询检查间隔（每0.5秒检查一次）
        self.mt5_deal_recheck_wait = 1.0  # 2.0→1.0: 二次确认等待时间缩短
        self.api_retry_delay = 0.5
        self.max_binance_limit_retries = 25
        self.open_wait_after_cancel_no_trade = 1.0
        self.open_wait_after_cancel_part = 2.0
        self.close_wait_after_cancel_no_trade = 1.0
        self.close_wait_after_cancel_part = 2.0
        self.partial_fill_threshold = 0.95  # 95%以上算完全成交
        self.base_executor = base_executor

    async def execute_reverse_opening(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: Optional[AsyncSession] = None,
        spread_threshold: float = None,
        pair_code: str = "XAU",
        hedge_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Execute reverse opening (Binance short, Bybit long).

        Flow:
        1. Binance limit SELL order (open short)
        2. Monitor Binance order (0.3s timeout)
        3. Bybit market BUY order (open long) with Binance filled quantity
        4. Monitor Bybit order (0.1s timeout)
        5. Chase Bybit if not fully filled (1 retry)
        """
        # Step 1: Place A-side SELL order (MAKER/PostOnly) — routes by platform_id
        sym_a, sym_b = _get_pair_symbols(pair_code)
        binance_result = await self._place_a_side_order(
            account=binance_account,
            symbol=sym_a,
            side="SELL",
            quantity=quantity,
            price=binance_price,
            position_side="SHORT",
            pair_code=pair_code,
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "A侧下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]

        # Step 2: Monitor A-side order — routes by platform_id
        monitor_result = await self._monitor_a_side_order(
            binance_account,
            sym_a,
            binance_order_id,
            self.binance_timeout,
            spread_threshold=spread_threshold,
            compare_op='>=',  # Reverse opening: spread >= threshold triggers opening
            strategy_type='reverse_opening',
            pair_code=pair_code,
        )

        binance_filled_qty = monitor_result["filled_qty"]
        spread_cancelled = monitor_result["spread_cancelled"]
        binance_api_error = monitor_result.get("api_error", False)

        if binance_filled_qty == 0:
            if binance_api_error:
                logger.error(f"[REVERSE_OPENING] CRITICAL: Binance API outage detected for order {binance_order_id}, NOT cancelling order")
                return {
                    "success": False,
                    "binance_filled_qty": 0,
                    "bybit_filled_qty": 0,
                    "binance_order_id": binance_order_id,
                    "is_single_leg": False,
                    "binance_api_error": True,
                    "message": "Binance交易系统异常，无法查询订单状态，请立即人工检查！"
                }
            # Order already cancelled by monitor (timeout or spread breach)
            message = "点差不满足条件，订单已撤销" if spread_cancelled else "A侧未匹配到订单，取消策略执行，下次再试!"
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": message
            }
        bybit_quantity = _a_to_b(binance_filled_qty, pair_code) * hedge_multiplier
        logger.info(f"[REVERSE_OPENING] Bybit order: binance_filled={binance_filled_qty} XAU -> bybit_quantity={bybit_quantity} Lot (multiplier={hedge_multiplier})")

        bybit_filled_qty = await self._execute_bybit_market_buy(
            bybit_account,
            sym_b,
            bybit_quantity,
            close_position=False  # Open new LONG position
        )

        logger.info(f"[REVERSE_OPENING] Bybit filled: {bybit_filled_qty} Lot")

        # Check if Bybit order not filled at all
        if bybit_filled_qty == 0:
            return {
                "success": False,
                "error": "Bybit订单未成交",
                "binance_filled_qty": binance_filled_qty,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": True,
                "message": "Bybit订单已取消，等待下次重试",
                "single_leg_details": {
                    "binance_filled": binance_filled_qty,
                    "bybit_filled": 0,
                    "bybit_filled_xau": 0,
                    "unfilled_qty": binance_filled_qty
                }
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = _b_to_a(bybit_filled_qty, pair_code)
        # Only consider it single-leg if Bybit filled < 80% of Binance filled
        # This tolerates normal fill variance and exchange data delays
        expected_hedge_xau = binance_filled_qty * hedge_multiplier
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < expected_hedge_xau * 0.80

        # Add detailed logging for single-leg detection
        logger.info(
            f"[REVERSE_OPENING] Single-leg check: "
            f"Binance={binance_filled_qty} XAU, "
            f"Bybit={bybit_filled_qty} Lot ({bybit_filled_xau} XAU), "
            f"Fill ratio={bybit_filled_xau/binance_filled_qty*100:.1f}%, "
            f"Threshold=80%, "
            f"is_single_leg={is_single_leg}"
        )

        # 双边成交完成，立即通知前端恢复按钮（不等待持仓刷新）
        try:
            from app.services.strategy_status_pusher import status_pusher
            await status_pusher.push_orders_filled(
                strategy_id=0,  # Will be set by caller if needed
                action='opening',
                binance_filled=binance_filled_qty,
                bybit_filled=bybit_filled_xau,
                user_id=None
            )
            logger.info(f"[REVERSE_OPENING] ✓ Button restore notification sent")
        except Exception as e:
            logger.warning(f"[REVERSE_OPENING] Failed to push orders filled notification: {e}")

        # Trigger immediate position refresh after successful execution
        _trigger_position_refresh()

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_xau,  # 修复：使用XAU而不是Lot
                "bybit_filled_xau": bybit_filled_xau,
                "unfilled_qty": binance_filled_qty - bybit_filled_xau
            } if is_single_leg else None
        }

    async def execute_reverse_closing(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: Optional[AsyncSession] = None,
        spread_threshold: float = None,
        pair_code: str = "XAU",
        hedge_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Execute reverse closing (Binance long close, Bybit short close).

        Flow:
        1. Check Bybit LONG position exists
        2. Binance limit BUY order (close short)
        3. Monitor Binance order (0.3s timeout)
        4. Bybit market SELL order (close long) with Binance filled quantity
        5. Monitor Bybit order (0.1s timeout)
        6. Chase Bybit if not fully filled (1 retry)
        """
        # Step 0: Pre-check Bybit LONG position before placing any orders
        sym_a, sym_b = _get_pair_symbols(pair_code)
        mt5_client = _get_mt5_client_for_account(bybit_account)

        # Check if LONG position exists
        _pos_result = mt5_client.get_positions(sym_b)
        bybit_positions = (await _pos_result) if inspect.isawaitable(_pos_result) else _pos_result
        long_positions = [p for p in bybit_positions if p['type'] == 0]  # type=0 is LONG

        if not long_positions:
            return {
                "success": False,
                "error": "Bybit没有LONG持仓可以平仓",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "position_exhausted": True,
                "message": "Bybit没有LONG持仓，无法执行反向平仓"
            }

        total_long_volume = sum(p['volume'] for p in long_positions)
        required_volume = _a_to_b(quantity, pair_code)

        if total_long_volume < required_volume:
            return {
                "success": False,
                "error": f"Bybit LONG持仓不足: 当前{total_long_volume} Lot, 需要{required_volume} Lot",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "position_exhausted": True,
                "message": f"Bybit LONG持仓不足，无法执行反向平仓"
            }

        # Step 1: Place A-side BUY order (MAKER/PostOnly) — routes by platform_id
        binance_result = await self._place_a_side_order(
            account=binance_account,
            symbol=sym_a,
            side="BUY",
            quantity=quantity,
            price=binance_price,
            position_side="SHORT",
            pair_code=pair_code,
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "A侧下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]

        # Step 2: Monitor A-side order — routes by platform_id
        monitor_result = await self._monitor_a_side_order(
            binance_account,
            sym_a,
            binance_order_id,
            self.binance_timeout,
            spread_threshold=spread_threshold,
            compare_op='<=',  # Reverse closing: spread <= threshold triggers closing
            strategy_type='reverse_closing',
            pair_code=pair_code,
        )

        binance_filled_qty = monitor_result["filled_qty"]
        spread_cancelled = monitor_result["spread_cancelled"]
        binance_api_error = monitor_result.get("api_error", False)

        if binance_filled_qty == 0:
            if binance_api_error:
                logger.error(f"[REVERSE_CLOSING] CRITICAL: Binance API outage detected for order {binance_order_id}, NOT cancelling order")
                return {
                    "success": False,
                    "binance_filled_qty": 0,
                    "bybit_filled_qty": 0,
                    "binance_order_id": binance_order_id,
                    "is_single_leg": False,
                    "binance_api_error": True,
                    "message": "Binance交易系统异常，无法查询订单状态，请立即人工检查！"
                }
            # Order already cancelled by monitor (timeout or spread breach)
            message = "点差不满足条件，订单已撤销" if spread_cancelled else "A侧未匹配到订单，取消策略执行，下次再试!"
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": message
            }

        # Step 3: Place Bybit market SELL order with Binance filled quantity (close LONG position)
        bybit_quantity = _a_to_b(binance_filled_qty, pair_code) * hedge_multiplier
        bybit_filled_qty = await self._execute_bybit_market_sell(
            bybit_account,
            sym_b,
            bybit_quantity,
            close_position=True  # Close existing LONG position
        )

        # Check if Bybit order not filled at all
        if bybit_filled_qty == 0:
            return {
                "success": False,
                "error": "Bybit订单未成交",
                "binance_filled_qty": binance_filled_qty,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": True,
                "message": "Bybit订单已取消，等待下次重试",
                "single_leg_details": {
                    "binance_filled": binance_filled_qty,
                    "bybit_filled": 0,
                    "bybit_filled_xau": 0,
                    "unfilled_qty": binance_filled_qty
                }
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = _b_to_a(bybit_filled_qty, pair_code)
        # Only consider it single-leg if Bybit filled < 80% of Binance filled
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.80

        # 双边成交完成，立即通知前端恢复按钮（不等待持仓刷新）
        try:
            from app.services.strategy_status_pusher import status_pusher
            await status_pusher.push_orders_filled(
                strategy_id=0,
                action='closing',
                binance_filled=binance_filled_qty,
                bybit_filled=bybit_filled_xau,
                user_id=None
            )
            logger.info(f"[REVERSE_CLOSING] ✓ Button restore notification sent")
        except Exception as e:
            logger.warning(f"[REVERSE_CLOSING] Failed to push orders filled notification: {e}")

        # Trigger immediate position refresh after successful execution
        _trigger_position_refresh()

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_xau,  # 修复：使用XAU而不是Lot
                "bybit_filled_xau": bybit_filled_xau,
                "unfilled_qty": binance_filled_qty - bybit_filled_xau
            } if is_single_leg else None
        }

    async def execute_forward_opening(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: Optional[AsyncSession] = None,
        spread_threshold: float = None,
        pair_code: str = "XAU",
        hedge_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Execute forward opening (Binance long, Bybit short).

        Flow:
        1. Binance limit BUY order (open long)
        2. Monitor Binance order (0.3s timeout)
        3. Bybit market SELL order (open short) with Binance filled quantity
        4. Monitor Bybit order (0.1s timeout)
        5. Chase Bybit if not fully filled (1 retry)
        """
        # Step 1: Place A-side BUY order (MAKER/PostOnly) — routes by platform_id
        sym_a, sym_b = _get_pair_symbols(pair_code)
        binance_result = await self._place_a_side_order(
            account=binance_account,
            symbol=sym_a,
            side="BUY",
            quantity=quantity,
            price=binance_price,
            position_side="LONG",
            pair_code=pair_code,
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "A侧下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]

        # Step 2: Monitor A-side order — routes by platform_id
        monitor_result = await self._monitor_a_side_order(
            binance_account,
            sym_a,
            binance_order_id,
            self.binance_timeout,
            spread_threshold=spread_threshold,
            compare_op='>=',  # Forward opening: spread >= threshold triggers opening
            strategy_type='forward_opening',
            pair_code=pair_code,
        )

        binance_filled_qty = monitor_result["filled_qty"]
        spread_cancelled = monitor_result["spread_cancelled"]
        binance_api_error = monitor_result.get("api_error", False)

        if binance_filled_qty == 0:
            if binance_api_error:
                logger.error(f"[FORWARD_OPENING] CRITICAL: Binance API outage detected for order {binance_order_id}, NOT cancelling order")
                return {
                    "success": False,
                    "binance_filled_qty": 0,
                    "bybit_filled_qty": 0,
                    "binance_order_id": binance_order_id,
                    "is_single_leg": False,
                    "binance_api_error": True,
                    "message": "Binance交易系统异常，无法查询订单状态，请立即人工检查！"
                }
            # Order already cancelled by monitor (timeout or spread breach)
            message = "点差不满足条件，订单已撤销" if spread_cancelled else "A侧未匹配到订单，取消策略执行，下次再试!"
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": message
            }

        # Step 3: Place Bybit market SELL order with Binance filled quantity (open SHORT position)
        bybit_quantity = _a_to_b(binance_filled_qty, pair_code) * hedge_multiplier
        bybit_filled_qty = await self._execute_bybit_market_sell(
            bybit_account,
            sym_b,
            bybit_quantity,
            close_position=False  # Open new SHORT position
        )

        # Check if Bybit order not filled at all
        if bybit_filled_qty == 0:
            return {
                "success": False,
                "error": "Bybit订单未成交",
                "binance_filled_qty": binance_filled_qty,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": True,
                "message": "Bybit订单已取消，等待下次重试",
                "single_leg_details": {
                    "binance_filled": binance_filled_qty,
                    "bybit_filled": 0,
                    "bybit_filled_xau": 0,
                    "unfilled_qty": binance_filled_qty
                }
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = _b_to_a(bybit_filled_qty, pair_code)
        # Only consider it single-leg if Bybit filled < 80% of Binance filled
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.80

        # 双边成交完成，立即通知前端恢复按钮（不等待持仓刷新）
        try:
            from app.services.strategy_status_pusher import status_pusher
            await status_pusher.push_orders_filled(
                strategy_id=0,
                action='opening',
                binance_filled=binance_filled_qty,
                bybit_filled=bybit_filled_xau,
                user_id=None
            )
            logger.info(f"[FORWARD_OPENING] ✓ Button restore notification sent")
        except Exception as e:
            logger.warning(f"[FORWARD_OPENING] Failed to push orders filled notification: {e}")

        # Trigger immediate position refresh after successful execution
        _trigger_position_refresh()

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_xau,  # 修复：使用XAU而不是Lot
                "bybit_filled_xau": bybit_filled_xau,
                "unfilled_qty": binance_filled_qty - bybit_filled_xau
            } if is_single_leg else None
        }

    async def execute_forward_closing(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: Optional[AsyncSession] = None,
        spread_threshold: float = None,
        pair_code: str = "XAU",
        hedge_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Execute forward closing (Binance short close, Bybit long close).

        Flow:
        1. Check Bybit SHORT position exists
        2. Binance limit SELL order (close long)
        3. Monitor Binance order (0.3s timeout)
        4. Bybit market BUY order (close short) with Binance filled quantity
        5. Monitor Bybit order (0.1s timeout)
        6. Chase Bybit if not fully filled (1 retry)
        """
        logger.info(f"[FORWARD_CLOSING] Starting execution: quantity={quantity}, binance_price={binance_price}, bybit_price={bybit_price}")

        # Step 0: Pre-check Bybit SHORT position before placing any orders
        sym_a, sym_b = _get_pair_symbols(pair_code)
        mt5_client = _get_mt5_client_for_account(bybit_account)

        # Check if SHORT position exists
        _pos_result = mt5_client.get_positions(sym_b)
        bybit_positions = (await _pos_result) if inspect.isawaitable(_pos_result) else _pos_result
        short_positions = [p for p in bybit_positions if p['type'] == 1]  # type=1 is SHORT

        logger.info(f"[FORWARD_CLOSING] Bybit positions check: total={len(bybit_positions)}, short={len(short_positions)}")

        if not short_positions:
            logger.error(f"[FORWARD_CLOSING] No SHORT position found to close")
            return {
                "success": False,
                "error": "Bybit没有SHORT持仓可以平仓",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "position_exhausted": True,
                "message": "Bybit没有SHORT持仓，无法执行正向平仓"
            }

        total_short_volume = sum(p['volume'] for p in short_positions)
        required_volume = _a_to_b(quantity, pair_code)

        logger.info(f"[FORWARD_CLOSING] Position check: total_short={total_short_volume} Lot, required={required_volume} Lot")

        if total_short_volume < required_volume:
            logger.error(f"[FORWARD_CLOSING] Insufficient SHORT position: {total_short_volume} < {required_volume}")
            return {
                "success": False,
                "error": f"Bybit SHORT持仓不足: 当前{total_short_volume} Lot, 需要{required_volume} Lot",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "position_exhausted": True,
                "message": f"Bybit SHORT持仓不足，无法执行正向平仓"
            }

        # Step 1: Place A-side SELL order (MAKER/PostOnly) — routes by platform_id
        logger.info(f"[FORWARD_CLOSING] Placing A-side SELL order: quantity={quantity}, price={binance_price}")
        binance_result = await self._place_a_side_order(
            account=binance_account,
            symbol=sym_a,
            side="SELL",
            quantity=quantity,
            price=binance_price,
            position_side="LONG",
            pair_code=pair_code,
        )

        if not binance_result["success"]:
            logger.error(f"[FORWARD_CLOSING] A-side order failed: {binance_result}")
            return {
                "success": False,
                "error": "A侧下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]
        logger.info(f"[FORWARD_CLOSING] A-side order placed: order_id={binance_order_id}")

        # Step 2: Monitor A-side order — routes by platform_id
        monitor_result = await self._monitor_a_side_order(
            binance_account,
            sym_a,
            binance_order_id,
            self.binance_timeout,
            spread_threshold=spread_threshold,
            compare_op='<=',  # Forward closing: spread <= threshold triggers closing
            strategy_type='forward_closing',
            pair_code=pair_code,
        )

        binance_filled_qty = monitor_result["filled_qty"]
        spread_cancelled = monitor_result["spread_cancelled"]
        binance_api_error = monitor_result.get("api_error", False)

        logger.info(f"[FORWARD_CLOSING] Binance filled: {binance_filled_qty} XAU")

        if binance_filled_qty == 0:
            if binance_api_error:
                logger.error(f"[FORWARD_CLOSING] CRITICAL: Binance API outage detected for order {binance_order_id}, NOT cancelling order")
                return {
                    "success": False,
                    "binance_filled_qty": 0,
                    "bybit_filled_qty": 0,
                    "binance_order_id": binance_order_id,
                    "is_single_leg": False,
                    "binance_api_error": True,
                    "message": "Binance交易系统异常，无法查询订单状态，请立即人工检查！"
                }
            # Order already cancelled by monitor (timeout or spread breach)
            logger.info(f"[FORWARD_CLOSING] A-side not filled, order already cancelled by monitor {binance_order_id}")
            message = "点差不满足条件，订单已撤销" if spread_cancelled else "A侧未匹配到订单，取消策略执行，下次再试!"
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": message
            }

        # Step 3: Place Bybit market BUY order with Binance filled quantity (close SHORT position)
        bybit_quantity = _a_to_b(binance_filled_qty, pair_code) * hedge_multiplier
        logger.info(f"[FORWARD_CLOSING] Placing Bybit BUY order: quantity={bybit_quantity} Lot (from {binance_filled_qty} XAU, multiplier={hedge_multiplier})")

        bybit_filled_qty = await self._execute_bybit_market_buy(
            bybit_account,
            sym_b,
            bybit_quantity,
            close_position=True  # Close existing SHORT position
        )

        logger.info(f"[FORWARD_CLOSING] Bybit filled: {bybit_filled_qty} Lot")

        # Check if Bybit order not filled at all
        if bybit_filled_qty == 0:
            logger.error(f"[FORWARD_CLOSING] SINGLE LEG DETECTED: Binance filled {binance_filled_qty} XAU, Bybit filled 0 Lot")
            return {
                "success": False,
                "error": "Bybit订单未成交",
                "binance_filled_qty": binance_filled_qty,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": True,
                "message": "Bybit订单已取消，等待下次重试",
                "single_leg_details": {
                    "binance_filled": binance_filled_qty,
                    "bybit_filled": 0,
                    "bybit_filled_xau": 0,
                    "unfilled_qty": binance_filled_qty
                }
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = _b_to_a(bybit_filled_qty, pair_code)
        # Only consider it single-leg if Bybit filled < 80% of Binance filled
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.80

        if is_single_leg:
            logger.warning(f"[FORWARD_CLOSING] PARTIAL SINGLE LEG: Binance={binance_filled_qty} XAU, Bybit={bybit_filled_xau} XAU ({bybit_filled_qty} Lot)")
        else:
            logger.info(f"[FORWARD_CLOSING] Execution completed successfully: Binance={binance_filled_qty} XAU, Bybit={bybit_filled_xau} XAU")

        # 双边成交完成，立即通知前端恢复按钮（不等待持仓刷新）
        try:
            from app.services.strategy_status_pusher import status_pusher
            await status_pusher.push_orders_filled(
                strategy_id=0,
                action='closing',
                binance_filled=binance_filled_qty,
                bybit_filled=bybit_filled_xau,
                user_id=None
            )
            logger.info(f"[FORWARD_CLOSING] ✓ Button restore notification sent")
        except Exception as e:
            logger.warning(f"[FORWARD_CLOSING] Failed to push orders filled notification: {e}")

        # Trigger immediate position refresh after successful execution
        _trigger_position_refresh()

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_xau,  # 修复：使用XAU而不是Lot，保持一致性
                "bybit_filled_xau": bybit_filled_xau,
                "unfilled_qty": binance_filled_qty - bybit_filled_xau
            } if is_single_leg else None
        }

    # ────────────────────────────────────────────────────────────────────────
    # BXAU Platform Router — A-side can be Binance (platform_id=1) OR
    # Bybit Linear Contract (platform_id=2).  All existing Binance interfaces
    # remain completely untouched; BXAU routing is additive-only.
    # ────────────────────────────────────────────────────────────────────────

    async def place_bybit_linear_order(
        self,
        account: Account,
        symbol: str,
        side: str,         # "Buy" | "Sell"
        quantity: float,
        price: float,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """Place a Post-Only Limit order on Bybit Linear (USDT Perpetual).

        Used for BXAU pair where side-A is a Bybit linear contract account
        instead of Binance.  Post-Only (timeInForce="PostOnly") guarantees
        Maker execution — same semantic as Binance priceMatch=QUEUE.

        Args:
            account:     The Bybit linear account (platform_id=2, is_mt5_account=False)
            symbol:      Bybit linear symbol, e.g. "XAUUSDT"
            side:        "Buy" (long open / short close) or "Sell" (short open / long close)
            quantity:    A-side units (e.g. XAU oz for gold)
            price:       Limit price (caller sets bid−tick or ask+tick for maker)
            reduce_only: True when closing an existing position
        """
        from app.services.bybit_client import BybitV5Client
        from app.core.proxy_utils import build_proxy_url

        client = BybitV5Client(
            api_key=account.api_key,
            api_secret=account.api_secret,
            proxy_url=build_proxy_url(account.proxy_config),
        )
        # Get price precision for the symbol from pair config
        specs = _get_pair_specs()
        price_prec = specs.get('price_prec_a', 2)
        qty_prec = specs.get('qty_prec_a', 3)
        price_str = str(round(price, price_prec))
        qty_str = str(round(quantity, qty_prec))

        try:
            resp = await client.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                order_type="Limit",
                qty=qty_str,
                price=price_str,
                time_in_force="PostOnly",   # Guaranteed Maker — rejected if would take
                reduce_only=reduce_only,
            )
            ret_code = resp.get("retCode", -1)
            if ret_code != 0:
                err_msg = resp.get("retMsg", "Unknown error")
                logger.error(f"[BYBIT_LINEAR] place_order failed: retCode={ret_code} msg={err_msg}")
                return {"success": False, "platform": "bybit_linear", "error": err_msg, "ret_code": ret_code}

            order_id = resp.get("result", {}).get("orderId")
            logger.info(f"[BYBIT_LINEAR] Order placed: symbol={symbol} side={side} qty={qty_str} price={price_str} orderId={order_id}")
            return {"success": True, "platform": "bybit_linear", "order_id": order_id, "data": resp}
        except Exception as e:
            logger.error(f"[BYBIT_LINEAR] place_order exception: {e}")
            return {"success": False, "platform": "bybit_linear", "error": str(e)}
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def _monitor_bybit_linear_order(
        self,
        account: Account,
        symbol: str,
        order_id: str,
        timeout: float,
        spread_threshold: float = None,
        compare_op: str = None,
        strategy_type: str = None,
        pair_code: str = "XAU",
    ) -> dict:
        """Monitor a Bybit Linear Post-Only limit order via REST polling.

        Logic mirrors _monitor_binance_order semantics:
        - Poll order status every order_check_interval seconds
        - Cancel if timeout or spread condition breached
        - Return dict: {filled_qty, spread_cancelled, api_error}

        Bybit PostOnly: if rejected (retCode=10004/order crosses), filled_qty=0
        immediately. If partially/fully filled, leavesQty < qty.
        """
        from app.services.bybit_client import BybitV5Client
        from app.core.proxy_utils import build_proxy_url

        client = BybitV5Client(
            api_key=account.api_key,
            api_secret=account.api_secret,
            proxy_url=build_proxy_url(account.proxy_config),
        )
        deadline = asyncio.get_event_loop().time() + timeout
        filled_qty = 0.0
        spread_cancelled = False
        api_error = False

        try:
            while True:
                now = asyncio.get_event_loop().time()
                if now >= deadline:
                    # Timeout — cancel and return what's filled
                    logger.warning(f"[BYBIT_LINEAR_MON] Timeout ({timeout}s) for order {order_id}, cancelling")
                    try:
                        await client.cancel_order(category="linear", symbol=symbol, order_id=order_id)
                    except Exception as ce:
                        logger.warning(f"[BYBIT_LINEAR_MON] Cancel error: {ce}")
                    # Final status check after cancel
                    await asyncio.sleep(0.2)
                    break

                # Poll order status
                try:
                    resp = await client.get_order(category="linear", symbol=symbol, order_id=order_id)
                    ret_code = resp.get("retCode", -1)
                    if ret_code != 0:
                        logger.error(f"[BYBIT_LINEAR_MON] get_order failed retCode={ret_code}")
                        api_error = True
                        break

                    items = resp.get("result", {}).get("list", [])
                    if not items:
                        # Order no longer open (filled or cancelled externally)
                        break

                    order = items[0]
                    order_status = order.get("orderStatus", "")
                    cum_exec_qty = float(order.get("cumExecQty", 0))
                    leaves_qty = float(order.get("leavesQty", 0))

                    if order_status in ("Filled", "Cancelled", "Rejected", "Deactivated"):
                        filled_qty = cum_exec_qty
                        logger.info(f"[BYBIT_LINEAR_MON] Order {order_id} terminal: status={order_status} filled={filled_qty}")
                        break

                    # Check spread condition while waiting
                    if spread_threshold is not None and compare_op and strategy_type:
                        from app.services.market_service import market_data_service
                        sym_a, sym_b, _ = _get_pair_config(pair_code)
                        market_data = await market_data_service.get_current_spread(
                            binance_symbol=sym_a, bybit_symbol=sym_b
                        )
                        spreads = market_data_service.calculate_spread(
                            market_data.binance_quote, market_data.bybit_quote
                        )
                        spread_map = {
                            'reverse_opening': spreads.reverse_entry_spread,
                            'reverse_closing': spreads.reverse_exit_spread,
                            'forward_opening': spreads.forward_entry_spread,
                            'forward_closing': spreads.forward_exit_spread,
                        }
                        current_spread = spread_map.get(strategy_type, 0.0)
                        tolerance = 0.5
                        spread_met = (
                            (compare_op == '>=' and current_spread >= spread_threshold - tolerance) or
                            (compare_op == '<=' and current_spread <= spread_threshold + tolerance)
                        )
                        if not spread_met:
                            logger.info(f"[BYBIT_LINEAR_MON] Spread breached ({current_spread} {compare_op} {spread_threshold}), cancelling {order_id}")
                            try:
                                await client.cancel_order(category="linear", symbol=symbol, order_id=order_id)
                                spread_cancelled = True
                                filled_qty = cum_exec_qty  # partial may have filled
                            except Exception as ce:
                                logger.warning(f"[BYBIT_LINEAR_MON] Spread-cancel error: {ce}")
                            break

                except Exception as poll_err:
                    logger.error(f"[BYBIT_LINEAR_MON] Poll error: {poll_err}")
                    api_error = True
                    break

                await asyncio.sleep(self.order_check_interval)

            # Final REST query to get definitive filled qty
            if not api_error:
                try:
                    resp = await client.get_order(category="linear", symbol=symbol, order_id=order_id)
                    items = resp.get("result", {}).get("list", [])
                    if items:
                        filled_qty = float(items[0].get("cumExecQty", filled_qty))
                except Exception:
                    pass

        finally:
            try:
                await client.close()
            except Exception:
                pass

        logger.info(f"[BYBIT_LINEAR_MON] Order {order_id} final: filled={filled_qty} spread_cancelled={spread_cancelled} api_error={api_error}")
        return {"filled_qty": filled_qty, "spread_cancelled": spread_cancelled, "api_error": api_error}

    async def _place_a_side_order(
        self,
        account: Account,
        symbol: str,
        side: str,          # Binance: "BUY"/"SELL"  →  Bybit: "Buy"/"Sell"
        quantity: float,
        price: float,
        position_side: str,  # Binance hedge-mode only: "LONG"/"SHORT"
        pair_code: str = "XAU",
    ) -> Dict[str, Any]:
        """Route A-side order to Binance or Bybit Linear based on account.platform_id.

        platform_id == 1 → Binance Futures MAKER (priceMatch=QUEUE, existing interface)
        platform_id == 2 → Bybit Linear PostOnly Limit (BXAU new interface)
        """
        if account.platform_id == 1:
            # Binance — use existing place_binance_order (unchanged)
            return await self.base_executor.place_binance_order(
                account=account,
                symbol=symbol,
                side=side.upper(),
                order_type="LIMIT",
                quantity=quantity,
                price=price,
                position_side=position_side,
                post_only=True,
            )
        elif account.platform_id == 2:
            # Bybit Linear Contract (BXAU)
            # Convert Binance-style side to Bybit-style
            bybit_side = "Buy" if side.upper() == "BUY" else "Sell"
            reduce_only = position_side in ("close_long", "close_short") if position_side else False
            return await self.place_bybit_linear_order(
                account=account,
                symbol=symbol,
                side=bybit_side,
                quantity=quantity,
                price=price,
                reduce_only=reduce_only,
            )
        else:
            return {
                "success": False,
                "error": f"Unsupported A-side platform_id: {account.platform_id}",
                "platform": f"unknown_{account.platform_id}",
            }

    async def _monitor_a_side_order(
        self,
        account: Account,
        symbol: str,
        order_id,           # int for Binance, str for Bybit
        timeout: float,
        spread_threshold: float = None,
        compare_op: str = None,
        strategy_type: str = None,
        pair_code: str = "XAU",
    ) -> dict:
        """Route A-side order monitoring to Binance or Bybit Linear."""
        if account.platform_id == 1:
            return await self._monitor_binance_order(
                account=account,
                symbol=symbol,
                order_id=int(order_id),
                timeout=timeout,
                spread_threshold=spread_threshold,
                compare_op=compare_op,
                strategy_type=strategy_type,
            )
        elif account.platform_id == 2:
            return await self._monitor_bybit_linear_order(
                account=account,
                symbol=symbol,
                order_id=str(order_id),
                timeout=timeout,
                spread_threshold=spread_threshold,
                compare_op=compare_op,
                strategy_type=strategy_type,
                pair_code=pair_code,
            )
        else:
            return {"filled_qty": 0.0, "spread_cancelled": False, "api_error": True}

    async def _check_a_side_positions(
        self,
        account: Account,
        symbol: str,
        position_type: str,  # "LONG" | "SHORT"
        pair_code: str = "XAU",
    ) -> float:
        """Get A-side open position volume (in A-side units).

        Returns total volume of LONG or SHORT positions for the symbol.
        Handles both Binance and Bybit Linear accounts.
        """
        if account.platform_id == 1:
            # Binance: use existing base_executor pattern
            from app.services.binance_client import BinanceFuturesClient
            from app.core.proxy_utils import build_proxy_url
            client = BinanceFuturesClient(
                account.api_key, account.api_secret,
                proxy_url=build_proxy_url(account.proxy_config)
            )
            try:
                positions = await client.get_position_risk(symbol=symbol)
                total = 0.0
                for p in (positions if isinstance(positions, list) else []):
                    pos_side = p.get("positionSide", "")
                    amt = abs(float(p.get("positionAmt", 0)))
                    if position_type == "LONG" and pos_side == "LONG" and amt > 0:
                        total += amt
                    elif position_type == "SHORT" and pos_side == "SHORT" and amt > 0:
                        total += amt
                return total
            except Exception as e:
                logger.error(f"[A_SIDE_POS] Binance position check error: {e}")
                return 0.0
            finally:
                await client.close()
        elif account.platform_id == 2:
            # Bybit Linear
            from app.services.bybit_client import BybitV5Client
            from app.core.proxy_utils import build_proxy_url
            client = BybitV5Client(
                api_key=account.api_key,
                api_secret=account.api_secret,
                proxy_url=build_proxy_url(account.proxy_config),
            )
            try:
                resp = await client.get_positions(category="linear", symbol=symbol)
                items = resp.get("result", {}).get("list", [])
                total = 0.0
                for p in items:
                    side = p.get("side", "")
                    size = abs(float(p.get("size", 0)))
                    if position_type == "LONG" and side == "Buy" and size > 0:
                        total += size
                    elif position_type == "SHORT" and side == "Sell" and size > 0:
                        total += size
                return total
            except Exception as e:
                logger.error(f"[A_SIDE_POS] Bybit Linear position check error: {e}")
                return 0.0
            finally:
                try:
                    await client.close()
                except Exception:
                    pass
        return 0.0

    async def _monitor_binance_order(
        self,
        account: Account,
        symbol: str,
        order_id: int,
        timeout: float,
        spread_threshold: float = None,
        compare_op: str = None,
        strategy_type: str = None
    ) -> dict:
        """
        Monitor Binance order via User Data Stream (ORDER_TRADE_UPDATE) — zero REST polling.

        Registers the order_id in the shared _order_fill_registry so that
        BinancePositionPusher._handle_message() can set the event on fill/cancel.
        Falls back to a single REST status check only on timeout.

        Args:
            spread_threshold: Spread threshold for real-time checking
            compare_op: Comparison operator ('>=' or '<=' etc.)
            strategy_type: Strategy type for spread calculation

        Returns:
            dict with 'filled_qty', 'spread_cancelled', and 'api_error' keys
        """
        from app.tasks.broadcast_tasks import (
            register_order_watch, unregister_order_watch, _order_fill_registry
        )

        fill_event = register_order_watch(order_id)
        spread_check_task = None

        try:
            # --- Spread check coroutine (runs concurrently, cancels order on breach) ---
            spread_cancelled = False
            spread_cancel_qty = 0.0

            async def _watch_spread():
                nonlocal spread_cancelled, spread_cancel_qty
                if spread_threshold is None or compare_op is None or strategy_type is None:
                    return
                from app.services.market_service import market_data_service
                tolerance = 0.5
                while not fill_event.is_set():
                    await asyncio.sleep(self.spread_check_interval)
                    if fill_event.is_set():
                        break
                    try:
                        market_data = await market_data_service.get_current_spread()
                        spreads = market_data_service.calculate_spread(
                            market_data.binance_quote,
                            market_data.bybit_quote
                        )
                        if strategy_type == 'reverse_closing':
                            current_spread = spreads.reverse_exit_spread
                        elif strategy_type == 'reverse_opening':
                            current_spread = spreads.reverse_entry_spread
                        elif strategy_type == 'forward_closing':
                            current_spread = spreads.forward_exit_spread
                        elif strategy_type == 'forward_opening':
                            current_spread = spreads.forward_entry_spread
                        else:
                            continue

                        spread_met = False
                        if compare_op == '>=':
                            spread_met = current_spread >= (spread_threshold - tolerance)
                        elif compare_op == '>':
                            spread_met = current_spread > (spread_threshold - tolerance)
                        elif compare_op == '<=':
                            spread_met = current_spread <= (spread_threshold + tolerance)

                        if not spread_met:
                            logger.info(
                                f"Spread condition no longer met (tolerance={tolerance}): "
                                f"{current_spread} {compare_op} {spread_threshold}, cancelling order {order_id}"
                            )
                            await self.base_executor.cancel_binance_order(account, symbol, order_id)
                            # Wait briefly for ORDER_TRADE_UPDATE to arrive via WS
                            try:
                                await asyncio.wait_for(fill_event.wait(), timeout=2.0)
                            except asyncio.TimeoutError:
                                pass
                            record = _order_fill_registry.get(order_id, {})
                            spread_cancel_qty = record.get("filled_qty", 0.0)
                            spread_cancelled = True
                            fill_event.set()  # wake main wait
                            return
                    except Exception as e:
                        logger.error(f"Error checking spread during order monitoring: {e}")

            if spread_threshold is not None:
                spread_check_task = asyncio.create_task(_watch_spread())

            # --- Main wait: block until WS event fires or timeout ---
            try:
                await asyncio.wait_for(fill_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                # Timeout: cancel order and rely on WebSocket to report final status
                logger.warning(f"[BINANCE_MONITOR] Timeout waiting for order {order_id} ({timeout}s), cancelling")
                try:
                    await self.base_executor.cancel_binance_order(account, symbol, order_id)
                    # Wait briefly for ORDER_TRADE_UPDATE to arrive via WebSocket
                    logger.info(f"[BINANCE_MONITOR] Waiting for WebSocket cancel confirmation for order {order_id}")
                    try:
                        await asyncio.wait_for(fill_event.wait(), timeout=3.0)
                        logger.info(f"[BINANCE_MONITOR] WebSocket cancel confirmation received for order {order_id}")
                    except asyncio.TimeoutError:
                        logger.warning(f"[BINANCE_MONITOR] WebSocket cancel confirmation timeout for order {order_id}")
                        pass
                except Exception as cancel_err:
                    # -2011 (already filled/expired) or network error — safe to ignore here
                    logger.warning(f"[BINANCE_MONITOR] cancel error (order may be filled/expired): {cancel_err}")

                # Read final status from WebSocket registry (no REST query)
                record = _order_fill_registry.get(order_id, {})
                filled_qty = record.get("filled_qty", 0.0)

                # Only fallback to REST if WebSocket completely failed to report
                if filled_qty == 0 and not record:
                    logger.error(
                        f"[BINANCE_MONITOR] CRITICAL: WebSocket failed to report order {order_id} status, "
                        f"falling back to single REST query"
                    )
                    final_status = await self.base_executor.check_binance_order_status(
                        account, symbol, order_id
                    )
                    return {
                        "filled_qty": final_status.get("filled_qty", 0) if final_status.get("success") else 0,
                        "spread_cancelled": False,
                        "api_error": not final_status.get("success", False)
                    }

                logger.info(
                    f"[BINANCE_MONITOR] Order {order_id} timeout handled via WebSocket: "
                    f"filled_qty={filled_qty}, status={record.get('status', 'UNKNOWN')}"
                )
                return {
                    "filled_qty": filled_qty,
                    "spread_cancelled": False,
                    "api_error": False
                }

            # Event was set — read result from registry
            record = _order_fill_registry.get(order_id, {})

            if spread_cancelled:
                return {
                    "filled_qty": spread_cancel_qty,
                    "spread_cancelled": True,
                    "api_error": False
                }

            return {
                "filled_qty": record.get("filled_qty", 0.0),
                "spread_cancelled": False,
                "api_error": False
            }

        finally:
            if spread_check_task and not spread_check_task.done():
                spread_check_task.cancel()
            unregister_order_watch(order_id)

    async def _execute_bybit_market_buy(
        self,
        account: Account,
        symbol: str,
        quantity: float,
        close_position: bool = True
    ) -> float:
        """
        Execute Bybit market BUY order with retry logic and volume verification.

        Args:
            close_position: If True, close existing SHORT position instead of opening new LONG

        Returns:
            Total filled quantity
        """
        logger.info(f"[BYBIT_BUY] Starting: quantity={quantity} Lot, close_position={close_position}")
        total_filled = 0
        remaining = round(quantity, 2)

        for attempt in range(self.max_retries + 1):  # Initial + 1 retry
            logger.info(f"[BYBIT_BUY] Attempt {attempt + 1}/{self.max_retries + 1}: remaining={remaining} Lot")

            # Place market order
            result = await self.base_executor.place_bybit_order(
                account=account,
                symbol=symbol,
                side="Buy",
                order_type="Market",
                quantity=str(round(remaining, 2)),
                close_position=close_position,
            )

            if not result["success"]:
                logger.error(f"[BYBIT_BUY] Order placement failed: {result.get('error')}")
                break

            order_id = result["order_id"]
            ticket = int(order_id)
            logger.info(f"[BYBIT_BUY] Order placed: ticket={ticket}")

            # Wait for Bybit timeout (initial delay for order to enter market)
            await asyncio.sleep(self.bybit_timeout)

            # ── 平仓快速路径 ────────────────────────────────────────────────────────
            # MT5 Bridge 平仓指令（close_position=True）HTTP 200 = 仓位已平。
            # 平仓不产生新持仓，deals history 字段不匹配导致查询始终返回 0，
            # 无需等待 3s polling + 1s recheck（合计 4 秒），直接视为成交。
            if close_position:
                actual_filled = remaining
                logger.info(
                    f"[BYBIT_BUY] 平仓快速路径：主文单成功，跳过 deals polling，"
                    f"直接采信 {actual_filled:.4f} Lot (ticket={ticket})"
                )
                total_filled += actual_filled
                break

            # ── 개창 확인: 포지션 목록 직접 조회（deals polling 완전 대체） ────────────
            # 문제: _check_mt5_filled_volume(deals history) 는 MT5 deal 레코드가
            # history에 반영되는 데 수초 걸려 polling 3s + recheck 1s 동안 항상 0 반환.
            # 해결: 주문 직후 MT5 포지션 목록을 직접 조회해 Long 포지션이 생겼는지 확인.
            # 포지션 목록은 즉시 반영되므로 0.3-0.5s 이내에 결과를 확인할 수 있음.
            actual_filled = 0
            is_partial = False
            check_count = 0
            max_wait = self.mt5_deal_sync_wait   # 최대 대기 (fallback 용, 기본 3s)
            elapsed = 0

            logger.info(f"[BYBIT_BUY] 开仓确认：通过持仓列表验证（取代 deals polling）")

            while elapsed < max_wait:
                await asyncio.sleep(self.mt5_poll_interval)
                elapsed += self.mt5_poll_interval
                check_count += 1

                try:
                    mt5_client = _get_mt5_client_for_account(account)
                    _pos_result = mt5_client.get_positions(symbol)
                    positions = (await _pos_result) if inspect.isawaitable(_pos_result) else _pos_result
                    pos_total = sum(
                        float(p.get('volume', 0))
                        for p in positions
                        if int(p.get('type', -1)) == 0  # 0=Long(Buy)
                    )
                    actual_filled = min(pos_total, remaining)  # 持仓量作为成交量
                    is_partial = actual_filled < remaining * self.partial_fill_threshold
                    logger.info(
                        f"[BYBIT_BUY] 持仓确认 #{check_count} ({elapsed:.1f}s): "
                        f"pos_long={pos_total:.4f}, filled={actual_filled}/{remaining} Lot"
                    )
                    if actual_filled >= remaining * self.partial_fill_threshold:
                        logger.info(f"[BYBIT_BUY] 持仓确认成交，早退出 ({elapsed:.1f}s)")
                        break
                except Exception as _pe:
                    logger.warning(f"[BYBIT_BUY] 持仓查询失败 #{check_count}: {_pe}")
                    # 查询失败不中断，继续等待下次轮询

            logger.info(f"[BYBIT_BUY] Ticket {ticket} final result: {actual_filled} Lot (partial={is_partial})")

            # ── 防连开/连平安全机制 ──────────────────────────────────────────────────
            # MT5 Bridge 市价单下单成功（HTTP 200）即代表实际成交，deals history 仅作二次校验。
            # 若 deals history 确认为 0（字段不匹配/查询延迟），不得直接进入 retry 重新下单，
            # 否则会对同一 Binance 成交量重复开/平 Bybit 仓位。
            #
            # 确认策略（按场景区分）：
            #   开仓 (close_position=False): 查新建多仓总量 ≥ required×90% → 视为成交
            #   平仓 (close_position=True):  买入平空仓 → 主文单成功即代表成交，直接采信
            #     （平仓不产生新持仓，且空仓减少后查Long仍为0，无法通过持仓量正向验证）
            if actual_filled == 0 and result.get("success"):
                logger.warning(
                    f"[BYBIT_BUY] deals确认为0但主文单成功(ticket={ticket}，"
                    f"close_position={close_position})，查询当前持仓作为最终确认..."
                )
                try:
                    if close_position:
                        # 平仓场景（买入平空）：主文单成功 = MT5 Bridge 已执行 → 直接采信
                        # 平仓成功后空仓减少，无法用持仓增加来正向验证，
                        # 但主文单 HTTP 200 已代表执行成功。
                        actual_filled = remaining
                        logger.info(
                            f"[BYBIT_BUY] 平仓场景：主文单成功，直接采信 "
                            f"{actual_filled:.4f} Lot 成交 (ticket={ticket})"
                        )
                    else:
                        # 开仓场景（买入开多）：查询多头持仓总量
                        mt5_client = _get_mt5_client_for_account(account)
                        _pos_result = mt5_client.get_positions(symbol)
                        positions = (await _pos_result) if inspect.isawaitable(_pos_result) else _pos_result
                        pos_total = sum(
                            float(p.get('volume', 0))
                            for p in positions
                            if int(p.get('type', -1)) == 0  # 0=Long(Buy)
                        )
                        if pos_total >= remaining * 0.9:
                            actual_filled = remaining
                            logger.info(
                                f"[BYBIT_BUY] 开仓持仓确认: pos_long={pos_total:.4f} ≥ "
                                f"{remaining*0.9:.4f}, 采信 {actual_filled:.4f} Lot (ticket={ticket})"
                            )
                        else:
                            logger.warning(
                                f"[BYBIT_BUY] 开仓持仓不足: pos_long={pos_total:.4f} < "
                                f"{remaining*0.9:.4f}, 判定真实未成交 (ticket={ticket})"
                            )
                except Exception as _pos_e:
                    logger.warning(f"[BYBIT_BUY] 持仓确认查询失败: {_pos_e}")

            if actual_filled > 0:
                total_filled += actual_filled

                # Send alert if partial fill detected
                if is_partial and actual_filled < remaining * 0.5:
                    await self._send_partial_fill_alert(
                        account.user_id,
                        symbol,
                        remaining,
                        actual_filled,
                        ticket
                    )
                    print(f"MT5 partial fill warning: {actual_filled}/{remaining} Lot (ticket: {ticket})")

                if actual_filled >= remaining * self.partial_fill_threshold:
                    # Consider 90%+ as fully filled (降低从95%)
                    logger.info(
                        f"[BYBIT_BUY] Order considered fully filled: "
                        f"{actual_filled}/{remaining} = {actual_filled/remaining*100:.1f}% "
                        f"(threshold: {self.partial_fill_threshold*100:.0f}%)"
                    )
                    break

                # Partially filled — update remaining and retry for the rest
                remaining = round(remaining - actual_filled, 2)

                if attempt == self.max_retries:
                    # Last attempt, log warning
                    logger.warning(f"[BYBIT_BUY] Not fully filled after {self.max_retries + 1} attempts. Filled: {total_filled} Lot, Remaining: {remaining} Lot")
            else:
                # No fill detected on this attempt — continue to next retry.
                # DO NOT break: MT5 bridge may lag or the order may fill on the next
                # attempt. Breaking here wastes the remaining {max_retries - attempt} retries.
                logger.warning(
                    f"[BYBIT_BUY] No fill detected for ticket {ticket} "
                    f"(attempt {attempt + 1}/{self.max_retries + 1}), "
                    f"{'last attempt' if attempt == self.max_retries else 'retrying with new order...'}"
                )
                if attempt == self.max_retries:
                    break  # Exhausted all retries, give up

        logger.info(f"[BYBIT_BUY] Completed: total_filled={total_filled} Lot")
        return total_filled

    async def _execute_bybit_market_sell(
        self,
        account: Account,
        symbol: str,
        quantity: float,
        close_position: bool = True
    ) -> float:
        """
        Execute Bybit market SELL order with retry logic and volume verification.

        Args:
            close_position: If True, close existing LONG position instead of opening new SHORT

        Returns:
            Total filled quantity
        """
        logger.info(f"[BYBIT_SELL] Starting: quantity={quantity} Lot, close_position={close_position}")
        total_filled = 0
        remaining = round(quantity, 2)

        for attempt in range(self.max_retries + 1):  # Initial + 1 retry
            logger.info(f"[BYBIT_SELL] Attempt {attempt + 1}/{self.max_retries + 1}: remaining={remaining} Lot")

            # Place market order
            result = await self.base_executor.place_bybit_order(
                account=account,
                symbol=symbol,
                side="Sell",
                order_type="Market",
                quantity=str(round(remaining, 2)),
                close_position=close_position,
            )

            if not result["success"]:
                logger.error(f"[BYBIT_SELL] Order placement failed: {result.get('error')}")
                break

            order_id = result["order_id"]
            ticket = int(order_id)
            logger.info(f"[BYBIT_SELL] Order placed: ticket={ticket}")

            # Wait for Bybit timeout
            await asyncio.sleep(self.bybit_timeout)

            # ── 平仓快速路径 ────────────────────────────────────────────────────────
            # MT5 Bridge 平仓指令（close_position=True）HTTP 200 = 仓位已平。
            # 平仓不产生新持仓，deals history 字段不匹配导致查询始终返回 0，
            # 无需等待 3s polling + 1s recheck（合计 4 秒），直接视为成交。
            if close_position:
                actual_filled = remaining
                logger.info(
                    f"[BYBIT_SELL] 平仓快速路径：主文单成功，跳过 deals polling，"
                    f"直接采信 {actual_filled:.4f} Lot (ticket={ticket})"
                )
                total_filled += actual_filled
                break

            # ── 开仓确认: 포지션 목록 직접 조회（deals polling 완전 대체） ────────────
            # deals history는 MT5 반영까지 수초 지연되어 항상 0 반환.
            # Short 포지션 목록은 즉시 반영되어 0.3~0.5s 이내 확인 가능.
            max_wait = self.mt5_deal_sync_wait
            elapsed = 0
            actual_filled = 0
            is_partial = False
            check_count = 0

            logger.info(f"[BYBIT_SELL] 开仓确认：通过持仓列表验证（取代 deals polling）")

            while elapsed < max_wait:
                await asyncio.sleep(self.mt5_poll_interval)
                elapsed += self.mt5_poll_interval
                check_count += 1

                try:
                    mt5_client = _get_mt5_client_for_account(account)
                    _pos_result = mt5_client.get_positions(symbol)
                    positions = (await _pos_result) if inspect.isawaitable(_pos_result) else _pos_result
                    pos_total = sum(
                        float(p.get('volume', 0))
                        for p in positions
                        if int(p.get('type', -1)) == 1  # 1=Short(Sell)
                    )
                    actual_filled = min(pos_total, remaining)
                    is_partial = actual_filled < remaining * self.partial_fill_threshold
                    logger.info(
                        f"[BYBIT_SELL] 持仓确认 #{check_count} ({elapsed:.1f}s): "
                        f"pos_short={pos_total:.4f}, filled={actual_filled}/{remaining} Lot"
                    )
                    if actual_filled >= remaining * self.partial_fill_threshold:
                        logger.info(f"[BYBIT_SELL] 持仓确认成交，早退出 ({elapsed:.1f}s)")
                        break
                except Exception as _pe:
                    logger.warning(f"[BYBIT_SELL] 持仓查询失败 #{check_count}: {_pe}")

            logger.info(f"[BYBIT_SELL] Ticket {ticket} filled: {actual_filled} Lot (partial={is_partial})")

            # ── 防连开/连平安全机制 ──────────────────────────────────────────────────
            # MT5 Bridge 市价单下单成功（HTTP 200）即代表实际成交，deals history 仅作二次校验。
            # 若 deals history 确认为 0，不得直接 retry 重新下单。
            #
            # 确认策略（按场景区分）：
            #   开仓 (close_position=False): 卖出开空 → 查空头持仓总量 ≥ required×90% → 采信
            #   平仓 (close_position=True):  卖出平多 → 主文单成功即代表成交，直接采信
            #     （平仓后多仓减少，无法通过持仓"增加"正向验证，主文单已足够）
            if actual_filled == 0 and result.get("success"):
                logger.warning(
                    f"[BYBIT_SELL] deals确认为0但主文单成功(ticket={ticket}，"
                    f"close_position={close_position})，查询当前持仓作为最终确认..."
                )
                try:
                    if close_position:
                        # 平仓场景（卖出平多）：主文单成功 = MT5 Bridge 已执行 → 直接采信
                        # 平仓后多仓减少，无法用持仓增加正向验证。
                        actual_filled = remaining
                        logger.info(
                            f"[BYBIT_SELL] 平仓场景：主文单成功，直接采信 "
                            f"{actual_filled:.4f} Lot 成交 (ticket={ticket})"
                        )
                    else:
                        # 开仓场景（卖出开空）：查询空头持仓总量
                        mt5_client = _get_mt5_client_for_account(account)
                        _pos_result = mt5_client.get_positions(symbol)
                        positions = (await _pos_result) if inspect.isawaitable(_pos_result) else _pos_result
                        pos_total = sum(
                            float(p.get('volume', 0))
                            for p in positions
                            if int(p.get('type', -1)) == 1  # 1=Short(Sell)
                        )
                        if pos_total >= remaining * 0.9:
                            actual_filled = remaining
                            logger.info(
                                f"[BYBIT_SELL] 开仓持仓确认: pos_short={pos_total:.4f} ≥ "
                                f"{remaining*0.9:.4f}, 采信 {actual_filled:.4f} Lot (ticket={ticket})"
                            )
                        else:
                            logger.warning(
                                f"[BYBIT_SELL] 开仓持仓不足: pos_short={pos_total:.4f} < "
                                f"{remaining*0.9:.4f}, 判定真实未成交 (ticket={ticket})"
                            )
                except Exception as _pos_e:
                    logger.warning(f"[BYBIT_SELL] 持仓确认查询失败: {_pos_e}")

            if actual_filled > 0:
                total_filled += actual_filled

                # Send alert if partial fill detected
                if is_partial and actual_filled < remaining * 0.5:
                    await self._send_partial_fill_alert(
                        account.user_id,
                        symbol,
                        remaining,
                        actual_filled,
                        ticket
                    )
                    print(f"MT5 partial fill warning: {actual_filled}/{remaining} Lot (ticket: {ticket})")

                if actual_filled >= remaining * self.partial_fill_threshold:
                    # Consider 90%+ as fully filled (降低从95%)
                    logger.info(
                        f"[BYBIT_SELL] Order considered fully filled: "
                        f"{actual_filled}/{remaining} = {actual_filled/remaining*100:.1f}% "
                        f"(threshold: {self.partial_fill_threshold*100:.0f}%)"
                    )
                    break

                # Partially filled — update remaining and retry for the rest
                remaining = round(remaining - actual_filled, 2)

                if attempt == self.max_retries:
                    # Last attempt, log warning
                    logger.warning(f"[BYBIT_SELL] Not fully filled after {self.max_retries + 1} attempts. Filled: {total_filled} Lot, Remaining: {remaining} Lot")
            else:
                # No fill detected on this attempt — continue to next retry.
                # DO NOT break: MT5 bridge may lag or the order may fill on the next
                # attempt. Breaking here wastes the remaining {max_retries - attempt} retries.
                logger.warning(
                    f"[BYBIT_SELL] No fill detected for ticket {ticket} "
                    f"(attempt {attempt + 1}/{self.max_retries + 1}), "
                    f"{'last attempt' if attempt == self.max_retries else 'retrying with new order...'}"
                )
                if attempt == self.max_retries:
                    break  # Exhausted all retries, give up

        logger.info(f"[BYBIT_SELL] Completed: total_filled={total_filled} Lot")
        return total_filled

    async def _check_mt5_filled_volume(
        self,
        account: Account,
        ticket: int,
        expected_volume: float
    ) -> Dict[str, Any]:
        """
        Check MT5 order actual filled volume and compare with expected.
        Queries the MT5 Bridge's history/deals endpoint filtered by order ticket.
        Retries up to 3 times (1s interval) if no deals found yet —
        MT5 deal propagation can lag 1-3s after a market order is placed.
        """
        MAX_DEAL_RETRIES = 3
        DEAL_RETRY_INTERVAL = 1.0  # seconds

        try:
            mt5_client = _get_mt5_client_for_account(account)

            deals = None
            for attempt in range(MAX_DEAL_RETRIES):
                # Use async method if available (MT5HttpClient), otherwise sync
                if hasattr(mt5_client, 'get_deals_by_ticket_async'):
                    deals = await mt5_client.get_deals_by_ticket_async(ticket)
                else:
                    deals = mt5_client.get_deals_by_ticket(ticket)
                if deals:
                    break
                if attempt < MAX_DEAL_RETRIES - 1:
                    logger.warning(
                        f"[MT5_DEAL_CHECK] ticket={ticket} no deals found "
                        f"(attempt {attempt+1}/{MAX_DEAL_RETRIES}), retrying in {DEAL_RETRY_INTERVAL}s"
                    )
                    await asyncio.sleep(DEAL_RETRY_INTERVAL)

            if not deals:
                logger.error(
                    f"[MT5_DEAL_CHECK] ticket={ticket} no deals after {MAX_DEAL_RETRIES} attempts — "
                    f"treating as 0 fill (possible MT5 sync issue)"
                )
                return {
                    "actual_filled": 0.0,
                    "expected": expected_volume,
                    "is_partial_fill": True,
                    "fill_ratio": 0.0,
                    "error": "No deals found for ticket after retries"
                }

            # Sum up all deal volumes
            actual_filled = sum(deal['volume'] for deal in deals)

            # Calculate fill ratio
            fill_ratio = actual_filled / expected_volume if expected_volume > 0 else 0.0
            is_partial_fill = actual_filled < expected_volume * 0.95  # Less than 95% filled

            return {
                "actual_filled": actual_filled,
                "expected": expected_volume,
                "is_partial_fill": is_partial_fill,
                "fill_ratio": fill_ratio,
                "deals_count": len(deals)
            }

        except Exception as e:
            return {
                "actual_filled": 0.0,
                "expected": expected_volume,
                "is_partial_fill": True,
                "fill_ratio": 0.0,
                "error": str(e)
            }

    async def _send_partial_fill_alert(
        self,
        user_id: UUID,
        symbol: str,
        expected_qty: float,
        actual_qty: float,
        ticket: int
    ):
        """
        Send alert for partial fill via WebSocket

        Args:
            user_id: User ID
            symbol: Trading symbol
            expected_qty: Expected quantity
            actual_qty: Actual filled quantity
            ticket: Order ticket
        """
        try:
            from app.websocket.manager import manager

            fill_ratio = (actual_qty / expected_qty * 100) if expected_qty > 0 else 0

            message = {
                "type": "mt5_partial_fill_alert",
                "data": {
                    "symbol": symbol,
                    "expected_qty": expected_qty,
                    "actual_qty": actual_qty,
                    "unfilled_qty": expected_qty - actual_qty,
                    "fill_ratio": round(fill_ratio, 2),
                    "ticket": ticket,
                    "timestamp": time.time()
                }
            }

            await manager.send_personal_message(message, str(user_id))

        except Exception as e:
            print(f"Failed to send partial fill alert: {e}")


# Global instance
order_executor_v2 = OrderExecutorV2()
