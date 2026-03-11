"""Order Executor V2.0 - Optimized with shorter timeouts"""
import asyncio
import time
import logging
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.account import Account
from app.services.order_executor import order_executor as base_executor
from app.utils.quantity_converter import quantity_converter

logger = logging.getLogger(__name__)


class OrderExecutorV2:
    """
    Optimized order executor with V2.0 specifications:
    - Binance timeout: 0.6 seconds (increased for better fill rate)
    - Bybit timeout: 0.1 seconds
    - Single retry for unfilled orders
    """

    def __init__(self):
        self.binance_timeout = 0.6  # 600ms (increased from 300ms)
        self.bybit_timeout = 0.1    # 100ms
        self.max_retries = 1        # Only 1 retry (循环一次)
        self.base_executor = base_executor

    async def execute_reverse_opening(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: Optional[AsyncSession] = None,
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
        # Step 1: Place Binance limit SELL order with POST_ONLY (force MAKER)
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="SHORT",
            post_only=True,  # Force MAKER mode
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]

        # Step 2: Monitor Binance order (0.2s timeout)
        binance_filled_qty = await self._monitor_binance_order(
            binance_account,
            "XAUUSDT",
            binance_order_id,
            self.binance_timeout
        )

        if binance_filled_qty == 0:
            # Binance order not filled at all, cancel and return success (will retry next time)
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": "Binance未匹配到订单，取消策略执行，下次再试!"
            }

        # Step 3: Place Bybit market BUY order with Binance filled quantity (open LONG position)
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_buy(
            bybit_account,
            "XAUUSD.s",
            bybit_quantity,
            close_position=False  # Open new LONG position
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
                "message": "Bybit订单已取消，等待下次重试"
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_qty)
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.95

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_qty,
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
        from app.services.market_service import market_data_service
        mt5_client = market_data_service.mt5_client

        # Check if LONG position exists
        bybit_positions = mt5_client.get_positions("XAUUSD.s")
        long_positions = [p for p in bybit_positions if p['type'] == 0]  # type=0 is LONG

        if not long_positions:
            return {
                "success": False,
                "error": "Bybit没有LONG持仓可以平仓",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "message": "Bybit没有LONG持仓，无法执行反向平仓"
            }

        total_long_volume = sum(p['volume'] for p in long_positions)
        required_volume = quantity_converter.xau_to_lot(quantity)

        if total_long_volume < required_volume:
            return {
                "success": False,
                "error": f"Bybit LONG持仓不足: 当前{total_long_volume} Lot, 需要{required_volume} Lot",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "message": f"Bybit LONG持仓不足，无法执行反向平仓"
            }

        # Step 1: Place Binance limit BUY order with POST_ONLY (force MAKER)
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="SHORT",
            post_only=True,  # Force MAKER mode
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]

        # Step 2: Monitor Binance order (0.2s timeout)
        binance_filled_qty = await self._monitor_binance_order(
            binance_account,
            "XAUUSDT",
            binance_order_id,
            self.binance_timeout
        )

        if binance_filled_qty == 0:
            # Binance order not filled at all, cancel and return success (will retry next time)
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": "Binance未匹配到订单，取消策略执行，下次再试!"
            }

        # Step 3: Place Bybit market SELL order with Binance filled quantity (close LONG position)
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_sell(
            bybit_account,
            "XAUUSD.s",
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
                "message": "Bybit订单已取消，等待下次重试"
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_qty)
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.95

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_qty,
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
        # Step 1: Place Binance limit BUY order with POST_ONLY (force MAKER)
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="LONG",
            post_only=True,  # Force MAKER mode
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]

        # Step 2: Monitor Binance order (0.2s timeout)
        binance_filled_qty = await self._monitor_binance_order(
            binance_account,
            "XAUUSDT",
            binance_order_id,
            self.binance_timeout
        )

        if binance_filled_qty == 0:
            # Binance order not filled at all, cancel and return success (will retry next time)
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": "Binance未匹配到订单，取消策略执行，下次再试!"
            }

        # Step 3: Place Bybit market SELL order with Binance filled quantity (open SHORT position)
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_sell(
            bybit_account,
            "XAUUSD.s",
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
                "message": "Bybit订单已取消，等待下次重试"
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_qty)
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.95

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_qty,
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
        from app.services.market_service import market_data_service
        mt5_client = market_data_service.mt5_client

        # Check if SHORT position exists
        bybit_positions = mt5_client.get_positions("XAUUSD.s")
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
                "message": "Bybit没有SHORT持仓，无法执行正向平仓"
            }

        total_short_volume = sum(p['volume'] for p in short_positions)
        required_volume = quantity_converter.xau_to_lot(quantity)

        logger.info(f"[FORWARD_CLOSING] Position check: total_short={total_short_volume} Lot, required={required_volume} Lot")

        if total_short_volume < required_volume:
            logger.error(f"[FORWARD_CLOSING] Insufficient SHORT position: {total_short_volume} < {required_volume}")
            return {
                "success": False,
                "error": f"Bybit SHORT持仓不足: 当前{total_short_volume} Lot, 需要{required_volume} Lot",
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "is_single_leg": False,
                "message": f"Bybit SHORT持仓不足，无法执行正向平仓"
            }

        # Step 1: Place Binance limit SELL order with POST_ONLY (force MAKER)
        logger.info(f"[FORWARD_CLOSING] Placing Binance SELL order: quantity={quantity}, price={binance_price}")
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="LONG",
            post_only=True,  # Force MAKER mode
        )

        if not binance_result["success"]:
            logger.error(f"[FORWARD_CLOSING] Binance order failed: {binance_result}")
            return {
                "success": False,
                "error": "Binance下单失败",
                "binance_result": binance_result,
            }

        binance_order_id = binance_result["order_id"]
        logger.info(f"[FORWARD_CLOSING] Binance order placed: order_id={binance_order_id}")

        # Step 2: Monitor Binance order (0.2s timeout)
        binance_filled_qty = await self._monitor_binance_order(
            binance_account,
            "XAUUSDT",
            binance_order_id,
            self.binance_timeout
        )

        logger.info(f"[FORWARD_CLOSING] Binance filled: {binance_filled_qty} XAU")

        if binance_filled_qty == 0:
            # Binance order not filled at all, cancel and return success (will retry next time)
            logger.info(f"[FORWARD_CLOSING] Binance not filled, cancelling order {binance_order_id}")
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": True,
                "binance_filled_qty": 0,
                "bybit_filled_qty": 0,
                "binance_order_id": binance_order_id,
                "is_single_leg": False,
                "message": "Binance未匹配到订单，取消策略执行，下次再试!"
            }

        # Step 3: Place Bybit market BUY order with Binance filled quantity (close SHORT position)
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        logger.info(f"[FORWARD_CLOSING] Placing Bybit BUY order: quantity={bybit_quantity} Lot (from {binance_filled_qty} XAU)")

        bybit_filled_qty = await self._execute_bybit_market_buy(
            bybit_account,
            "XAUUSD.s",
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
                "message": "Bybit订单已取消，等待下次重试"
            }

        # Check for single-leg scenario (convert Bybit Lot to XAU for comparison)
        bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_qty)
        is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.95

        if is_single_leg:
            logger.warning(f"[FORWARD_CLOSING] PARTIAL SINGLE LEG: Binance={binance_filled_qty} XAU, Bybit={bybit_filled_xau} XAU ({bybit_filled_qty} Lot)")
        else:
            logger.info(f"[FORWARD_CLOSING] Execution completed successfully: Binance={binance_filled_qty} XAU, Bybit={bybit_filled_xau} XAU")

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
            "is_single_leg": is_single_leg,
            "single_leg_details": {
                "binance_filled": binance_filled_qty,
                "bybit_filled": bybit_filled_qty,
                "bybit_filled_xau": bybit_filled_xau,
                "unfilled_qty": binance_filled_qty - bybit_filled_xau
            } if is_single_leg else None
        }

    async def _monitor_binance_order(
        self,
        account: Account,
        symbol: str,
        order_id: int,
        timeout: float
    ) -> float:
        """
        Monitor Binance order with timeout.

        Returns:
            Filled quantity (0 if not filled)
        """
        start_time = time.time()
        check_interval = 0.01  # 10ms check interval

        while time.time() - start_time < timeout:
            status = await self.base_executor.check_binance_order_status(
                account, symbol, order_id
            )

            if status.get("success") and status.get("filled"):
                return status.get("filled_qty", 0)

            await asyncio.sleep(check_interval)

        # Timeout reached, cancel order and return filled quantity
        await self.base_executor.cancel_binance_order(account, symbol, order_id)

        # Check final status after cancellation
        final_status = await self.base_executor.check_binance_order_status(
            account, symbol, order_id
        )

        return final_status.get("filled_qty", 0) if final_status.get("success") else 0

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
        remaining = quantity

        for attempt in range(self.max_retries + 1):  # Initial + 1 retry
            logger.info(f"[BYBIT_BUY] Attempt {attempt + 1}/{self.max_retries + 1}: remaining={remaining} Lot")

            # Place market order
            result = await self.base_executor.place_bybit_order(
                account=account,
                symbol=symbol,
                side="Buy",
                order_type="Market",
                quantity=str(remaining),
                close_position=close_position,
            )

            if not result["success"]:
                logger.error(f"[BYBIT_BUY] Order placement failed: {result.get('error')}")
                break

            order_id = result["order_id"]
            ticket = int(order_id)
            logger.info(f"[BYBIT_BUY] Order placed: ticket={ticket}")

            # Wait for Bybit timeout
            await asyncio.sleep(self.bybit_timeout)

            # Additional wait for MT5 to process deals
            await asyncio.sleep(0.3)

            # Check actual filled volume from MT5 deals
            volume_check = await self._check_mt5_filled_volume(
                account, ticket, remaining
            )

            actual_filled = volume_check["actual_filled"]
            is_partial = volume_check["is_partial_fill"]

            logger.info(f"[BYBIT_BUY] Ticket {ticket} filled: {actual_filled} Lot (partial={is_partial})")

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

                if actual_filled >= remaining * 0.95:
                    # Consider 95%+ as fully filled
                    break

                # Partially filled, update remaining
                remaining -= actual_filled

                if attempt == self.max_retries:
                    # Last attempt, log warning
                    logger.warning(f"[BYBIT_BUY] Not fully filled after {self.max_retries + 1} attempts. Filled: {total_filled} Lot, Remaining: {remaining} Lot")
            else:
                # No fill detected, break
                logger.warning(f"[BYBIT_BUY] No fill detected for ticket {ticket}, stopping retries")
                break

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
        total_filled = 0
        remaining = quantity

        for attempt in range(self.max_retries + 1):  # Initial + 1 retry
            # Place market order
            result = await self.base_executor.place_bybit_order(
                account=account,
                symbol=symbol,
                side="Sell",
                order_type="Market",
                quantity=str(remaining),
                close_position=close_position,
            )

            if not result["success"]:
                break

            order_id = result["order_id"]
            ticket = int(order_id)

            # Wait for Bybit timeout
            await asyncio.sleep(self.bybit_timeout)

            # Additional wait for MT5 to process deals
            await asyncio.sleep(0.3)

            # Check actual filled volume from MT5 deals
            volume_check = await self._check_mt5_filled_volume(
                account, ticket, remaining
            )

            actual_filled = volume_check["actual_filled"]
            is_partial = volume_check["is_partial_fill"]

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

                if actual_filled >= remaining * 0.95:
                    # Consider 95%+ as fully filled
                    break

                # Partially filled, update remaining
                remaining -= actual_filled

                if attempt == self.max_retries:
                    # Last attempt, log warning
                    logger.warning(f"[BYBIT_BUY] Not fully filled after {self.max_retries + 1} attempts. Filled: {total_filled} Lot, Remaining: {remaining} Lot")
            else:
                # No fill detected, break
                logger.warning(f"[BYBIT_BUY] No fill detected for ticket {ticket}, stopping retries")
                break

        logger.info(f"[BYBIT_BUY] Completed: total_filled={total_filled} Lot")
        return total_filled

    async def _check_mt5_filled_volume(
        self,
        account: Account,
        ticket: int,
        expected_volume: float
    ) -> Dict[str, Any]:
        """
        Check MT5 order actual filled volume and compare with expected

        Args:
            account: Bybit account with MT5 credentials
            ticket: MT5 order ticket number
            expected_volume: Expected fill volume

        Returns:
            Dict with actual_filled, expected, is_partial_fill, fill_ratio
        """
        from app.services.market_service import market_data_service

        try:
            mt5_client = market_data_service.mt5_client

            # Get deals for this ticket
            deals = mt5_client.get_deals_by_ticket(ticket)

            if not deals:
                return {
                    "actual_filled": 0.0,
                    "expected": expected_volume,
                    "is_partial_fill": True,
                    "fill_ratio": 0.0,
                    "error": "No deals found for ticket"
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
