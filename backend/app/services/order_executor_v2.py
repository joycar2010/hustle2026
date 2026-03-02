"""Order Executor V2.0 - Optimized with shorter timeouts"""
import asyncio
import time
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.account import Account
from app.services.order_executor import order_executor as base_executor
from app.utils.quantity_converter import quantity_converter


class OrderExecutorV2:
    """
    Optimized order executor with V2.0 specifications:
    - Binance timeout: 0.2 seconds
    - Bybit timeout: 0.1 seconds
    - Single retry for unfilled orders
    """

    def __init__(self):
        self.binance_timeout = 0.2  # 200ms
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
        2. Monitor Binance order (0.2s timeout)
        3. Bybit market BUY order (open long) with Binance filled quantity
        4. Monitor Bybit order (0.1s timeout)
        5. Chase Bybit if not fully filled (1 retry)
        """
        # Step 1: Place Binance limit SELL order
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="SHORT",
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance order failed",
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
            # Binance order not filled at all, cancel and return
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": False,
                "error": "Binance order not filled within 0.2s",
                "binance_filled_qty": 0,
            }

        # Step 3: Place Bybit market BUY order with Binance filled quantity
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_buy(
            bybit_account,
            "XAUUSD.s",
            bybit_quantity
        )

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
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
        1. Binance limit BUY order (close short)
        2. Monitor Binance order (0.2s timeout)
        3. Bybit market SELL order (close long) with Binance filled quantity
        4. Monitor Bybit order (0.1s timeout)
        5. Chase Bybit if not fully filled (1 retry)
        """
        # Step 1: Place Binance limit BUY order
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="SHORT",
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance order failed",
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
            # Binance order not filled at all, cancel and return
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": False,
                "error": "Binance order not filled within 0.2s",
                "binance_filled_qty": 0,
            }

        # Step 3: Place Bybit market SELL order with Binance filled quantity
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_sell(
            bybit_account,
            "XAUUSD.s",
            bybit_quantity
        )

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
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
        2. Monitor Binance order (0.2s timeout)
        3. Bybit market SELL order (open short) with Binance filled quantity
        4. Monitor Bybit order (0.1s timeout)
        5. Chase Bybit if not fully filled (1 retry)
        """
        # Step 1: Place Binance limit BUY order
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="LONG",
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance order failed",
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
            # Binance order not filled at all, cancel and return
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": False,
                "error": "Binance order not filled within 0.2s",
                "binance_filled_qty": 0,
            }

        # Step 3: Place Bybit market SELL order with Binance filled quantity
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_sell(
            bybit_account,
            "XAUUSD.s",
            bybit_quantity
        )

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
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
        1. Binance limit SELL order (close long)
        2. Monitor Binance order (0.2s timeout)
        3. Bybit market BUY order (close short) with Binance filled quantity
        4. Monitor Bybit order (0.1s timeout)
        5. Chase Bybit if not fully filled (1 retry)
        """
        # Step 1: Place Binance limit SELL order
        binance_result = await self.base_executor.place_binance_order(
            account=binance_account,
            symbol="XAUUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=quantity,
            price=binance_price,
            position_side="LONG",
        )

        if not binance_result["success"]:
            return {
                "success": False,
                "error": "Binance order failed",
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
            # Binance order not filled at all, cancel and return
            await self.base_executor.cancel_binance_order(
                binance_account, "XAUUSDT", binance_order_id
            )
            return {
                "success": False,
                "error": "Binance order not filled within 0.2s",
                "binance_filled_qty": 0,
            }

        # Step 3: Place Bybit market BUY order with Binance filled quantity
        bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
        bybit_filled_qty = await self._execute_bybit_market_buy(
            bybit_account,
            "XAUUSD.s",
            bybit_quantity
        )

        return {
            "success": True,
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": bybit_filled_qty,
            "binance_order_id": binance_order_id,
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
        quantity: float
    ) -> float:
        """
        Execute Bybit market BUY order with retry logic.

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
                side="Buy",
                order_type="Market",
                quantity=str(remaining),
            )

            if not result["success"]:
                break

            order_id = result["order_id"]

            # Wait for Bybit timeout
            await asyncio.sleep(self.bybit_timeout)

            # Check order status
            status = await self.base_executor.check_bybit_order_status(
                account, symbol, order_id
            )

            if status.get("success"):
                filled_qty = status.get("filled_qty", 0)
                total_filled += filled_qty

                if filled_qty >= remaining:
                    # Fully filled
                    break

                # Partially filled, cancel and retry with remaining
                await self.base_executor.cancel_bybit_order(account, symbol, order_id)
                remaining -= filled_qty

                if attempt == self.max_retries:
                    # Last attempt, log warning
                    print(f"Warning: Bybit order not fully filled after {self.max_retries + 1} attempts. "
                          f"Filled: {total_filled}, Remaining: {remaining}")

        return total_filled

    async def _execute_bybit_market_sell(
        self,
        account: Account,
        symbol: str,
        quantity: float
    ) -> float:
        """
        Execute Bybit market SELL order with retry logic.

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
            )

            if not result["success"]:
                break

            order_id = result["order_id"]

            # Wait for Bybit timeout
            await asyncio.sleep(self.bybit_timeout)

            # Check order status
            status = await self.base_executor.check_bybit_order_status(
                account, symbol, order_id
            )

            if status.get("success"):
                filled_qty = status.get("filled_qty", 0)
                total_filled += filled_qty

                if filled_qty >= remaining:
                    # Fully filled
                    break

                # Partially filled, cancel and retry with remaining
                await self.base_executor.cancel_bybit_order(account, symbol, order_id)
                remaining -= filled_qty

                if attempt == self.max_retries:
                    # Last attempt, log warning
                    print(f"Warning: Bybit order not fully filled after {self.max_retries + 1} attempts. "
                          f"Filled: {total_filled}, Remaining: {remaining}")

        return total_filled


# Global instance
order_executor_v2 = OrderExecutorV2()
