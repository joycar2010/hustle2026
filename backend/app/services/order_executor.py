"""Order executor service for placing and managing orders"""
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.binance_client import BinanceFuturesClient
from app.services.bybit_client import BybitV5Client
from app.models.account import Account
from app.models.order import OrderRecord
from app.websocket.manager import manager


class OrderExecutor:
    """Service for executing orders on exchanges"""

    async def place_binance_order(
        self,
        account: Account,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place order on Binance"""
        client = BinanceFuturesClient(account.api_key, account.api_secret)

        try:
            result = await client.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
            )
            return {
                "success": True,
                "platform": "binance",
                "order_id": result.get("orderId"),
                "client_order_id": result.get("clientOrderId"),
                "status": result.get("status"),
                "data": result,
            }
        except Exception as e:
            return {
                "success": False,
                "platform": "binance",
                "error": str(e),
            }
        finally:
            await client.close()

    async def place_bybit_order(
        self,
        account: Account,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: Optional[str] = None,
        category: str = "linear",
    ) -> Dict[str, Any]:
        """Place order on Bybit"""
        client = BybitV5Client(account.api_key, account.api_secret)

        try:
            result = await client.place_order(
                category=category,
                symbol=symbol,
                side=side,
                order_type=order_type,
                qty=quantity,
                price=price,
            )
            return {
                "success": True,
                "platform": "bybit",
                "order_id": result.get("orderId"),
                "order_link_id": result.get("orderLinkId"),
                "data": result,
            }
        except Exception as e:
            return {
                "success": False,
                "platform": "bybit",
                "error": str(e),
            }
        finally:
            await client.close()

    async def check_binance_order_status(
        self,
        account: Account,
        symbol: str,
        order_id: int,
    ) -> Dict[str, Any]:
        """Check Binance order status"""
        client = BinanceFuturesClient(account.api_key, account.api_secret)

        try:
            result = await client.get_order(symbol, order_id)
            status = result.get("status")
            filled_qty = float(result.get("executedQty", 0))
            total_qty = float(result.get("origQty", 0))

            return {
                "success": True,
                "status": status,
                "filled": status == "FILLED",
                "partially_filled": filled_qty > 0 and filled_qty < total_qty,
                "filled_qty": filled_qty,
                "total_qty": total_qty,
                "data": result,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            await client.close()

    async def check_bybit_order_status(
        self,
        account: Account,
        symbol: str,
        order_id: str,
        category: str = "linear",
    ) -> Dict[str, Any]:
        """Check Bybit order status"""
        client = BybitV5Client(account.api_key, account.api_secret)

        try:
            result = await client.get_order(
                category=category,
                symbol=symbol,
                order_id=order_id,
            )

            # Extract order from list
            order_list = result.get("list", [])
            if not order_list:
                return {
                    "success": False,
                    "error": "Order not found",
                }

            order = order_list[0]
            status = order.get("orderStatus")
            filled_qty = float(order.get("cumExecQty", 0))
            total_qty = float(order.get("qty", 0))

            return {
                "success": True,
                "status": status,
                "filled": status == "Filled",
                "partially_filled": filled_qty > 0 and filled_qty < total_qty,
                "filled_qty": filled_qty,
                "total_qty": total_qty,
                "data": order,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            await client.close()

    async def cancel_binance_order(
        self,
        account: Account,
        symbol: str,
        order_id: int,
    ) -> Dict[str, Any]:
        """Cancel Binance order"""
        client = BinanceFuturesClient(account.api_key, account.api_secret)

        try:
            result = await client.cancel_order(symbol, order_id)
            return {
                "success": True,
                "data": result,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            await client.close()

    async def cancel_bybit_order(
        self,
        account: Account,
        symbol: str,
        order_id: str,
        category: str = "linear",
    ) -> Dict[str, Any]:
        """Cancel Bybit order"""
        client = BybitV5Client(account.api_key, account.api_secret)

        try:
            result = await client.cancel_order(
                category=category,
                symbol=symbol,
                order_id=order_id,
            )
            return {
                "success": True,
                "data": result,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            await client.close()

    async def execute_dual_order(
        self,
        binance_account: Account,
        bybit_account: Account,
        binance_symbol: str,
        bybit_symbol: str,
        binance_side: str,
        bybit_side: str,
        quantity: float,
        binance_price: Optional[float] = None,
        bybit_price: Optional[float] = None,
        order_type: str = "LIMIT",
        max_retries: int = 3,
        retry_delay: int = 3,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Execute dual orders on both exchanges with chase logic

        Args:
            binance_account: Binance account
            bybit_account: Bybit account
            binance_symbol: Binance symbol (e.g., XAUUSDT)
            bybit_symbol: Bybit symbol (e.g., XAUUSDT)
            binance_side: Binance order side (BUY/SELL)
            bybit_side: Bybit order side (Buy/Sell)
            quantity: Order quantity
            binance_price: Binance order price (for LIMIT orders)
            bybit_price: Bybit order price (for LIMIT orders)
            order_type: Order type (LIMIT/MARKET)
            max_retries: Maximum retry attempts
            retry_delay: Delay between retries in seconds
            db: Database session for order persistence

        Returns:
            Dict with execution results
        """
        # Step 1: Place initial orders on both exchanges
        binance_result, bybit_result = await asyncio.gather(
            self.place_binance_order(
                binance_account,
                binance_symbol,
                binance_side,
                order_type,
                quantity,
                binance_price,
            ),
            self.place_bybit_order(
                bybit_account,
                bybit_symbol,
                bybit_side,
                "Limit" if order_type == "LIMIT" else "Market",
                str(quantity),
                str(bybit_price) if bybit_price else None,
            ),
        )

        if not binance_result["success"] or not bybit_result["success"]:
            return {
                "success": False,
                "error": "Failed to place initial orders",
                "binance_result": binance_result,
                "bybit_result": bybit_result,
            }

        binance_order_id = binance_result["order_id"]
        bybit_order_id = bybit_result["order_id"]

        # Store orders in database if session provided
        if db:
            await self._store_orders(
                db,
                binance_account,
                bybit_account,
                binance_symbol,
                bybit_symbol,
                binance_side,
                bybit_side,
                quantity,
                binance_price or 0,
                bybit_price or 0,
                binance_order_id,
                bybit_order_id,
            )

        # Step 2: Wait and check if both orders filled
        await asyncio.sleep(retry_delay)

        binance_status, bybit_status = await asyncio.gather(
            self.check_binance_order_status(binance_account, binance_symbol, binance_order_id),
            self.check_bybit_order_status(bybit_account, bybit_symbol, bybit_order_id),
        )

        binance_filled = binance_status.get("filled", False)
        bybit_filled = bybit_status.get("filled", False)

        # Step 3: Chase unfilled orders
        retry_count = 0

        while retry_count < max_retries and not (binance_filled and bybit_filled):
            # Get filled quantities
            binance_filled_qty = binance_status.get("filled_qty", 0)
            bybit_filled_qty = bybit_status.get("filled_qty", 0)

            # Calculate remaining quantities
            binance_remaining = quantity - binance_filled_qty
            bybit_remaining = quantity - bybit_filled_qty

            # Determine chase quantity based on the filled side
            # If one side is fully filled, chase the remaining quantity on the other side
            # If both sides are partially filled, use the max filled quantity as target
            if binance_filled and not bybit_filled:
                # Binance fully filled, chase Bybit with Binance's filled quantity
                chase_qty = min(binance_filled_qty, quantity)
            elif bybit_filled and not binance_filled:
                # Bybit fully filled, chase Binance with Bybit's filled quantity
                chase_qty = min(bybit_filled_qty, quantity)
            elif binance_filled_qty > 0 or bybit_filled_qty > 0:
                # Both partially filled, use max filled quantity as target
                target_qty = max(binance_filled_qty, bybit_filled_qty)
                chase_qty = target_qty
            else:
                # Neither filled, use original quantity
                chase_qty = quantity

            # Cancel and retry unfilled orders with market orders
            tasks = []

            if not binance_filled:
                binance_chase_qty = chase_qty if bybit_filled or bybit_filled_qty > 0 else quantity
                tasks.append(self._chase_binance_order(
                    binance_account,
                    binance_symbol,
                    binance_side,
                    binance_chase_qty,
                    binance_order_id,
                ))

            if not bybit_filled:
                bybit_chase_qty = chase_qty if binance_filled or binance_filled_qty > 0 else quantity
                tasks.append(self._chase_bybit_order(
                    bybit_account,
                    bybit_symbol,
                    bybit_side,
                    bybit_chase_qty,
                    bybit_order_id,
                ))

            chase_results = await asyncio.gather(*tasks)

            # Update order IDs if new orders placed
            if not binance_filled and len(chase_results) > 0:
                if chase_results[0]["success"]:
                    binance_order_id = chase_results[0]["order_id"]

            if not bybit_filled:
                chase_idx = 1 if not binance_filled else 0
                if len(chase_results) > chase_idx and chase_results[chase_idx]["success"]:
                    bybit_order_id = chase_results[chase_idx]["order_id"]

            # Wait and check status again
            await asyncio.sleep(retry_delay)

            binance_status, bybit_status = await asyncio.gather(
                self.check_binance_order_status(binance_account, binance_symbol, binance_order_id),
                self.check_bybit_order_status(bybit_account, bybit_symbol, bybit_order_id),
            )

            binance_filled = binance_status.get("filled", False)
            bybit_filled = bybit_status.get("filled", False)

            retry_count += 1

        # Step 4: Return final status
        return {
            "success": binance_filled and bybit_filled,
            "binance_filled": binance_filled,
            "bybit_filled": bybit_filled,
            "binance_order_id": binance_order_id,
            "bybit_order_id": bybit_order_id,
            "binance_status": binance_status,
            "bybit_status": bybit_status,
            "retries": retry_count,
        }

    async def _chase_binance_order(
        self,
        account: Account,
        symbol: str,
        side: str,
        quantity: float,
        old_order_id: int,
    ) -> Dict[str, Any]:
        """Chase Binance order by canceling and placing market order"""
        # Cancel old order
        await self.cancel_binance_order(account, symbol, old_order_id)

        # Place market order for priority fill
        return await self.place_binance_order(
            account,
            symbol,
            side,
            "MARKET",
            quantity,
        )

    async def _chase_bybit_order(
        self,
        account: Account,
        symbol: str,
        side: str,
        quantity: float,
        old_order_id: str,
    ) -> Dict[str, Any]:
        """Chase Bybit order by canceling and placing market order"""
        # Cancel old order
        await self.cancel_bybit_order(account, symbol, old_order_id)

        # Place market order for priority fill
        return await self.place_bybit_order(
            account,
            symbol,
            side,
            "Market",
            str(quantity),
        )

    async def _store_orders(
        self,
        db: AsyncSession,
        binance_account: Account,
        bybit_account: Account,
        binance_symbol: str,
        bybit_symbol: str,
        binance_side: str,
        bybit_side: str,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        binance_order_id: int,
        bybit_order_id: str,
    ):
        """Store orders in database"""
        # Create Binance order record
        binance_order = OrderRecord(
            account_id=binance_account.account_id,
            symbol=binance_symbol,
            order_side=binance_side.lower(),
            order_type="limit",
            price=binance_price,
            qty=quantity,
            status="new",
            platform_order_id=str(binance_order_id),
        )

        # Create Bybit order record
        bybit_order = OrderRecord(
            account_id=bybit_account.account_id,
            symbol=bybit_symbol,
            order_side=bybit_side.lower(),
            order_type="limit",
            price=bybit_price,
            qty=quantity,
            status="new",
            platform_order_id=bybit_order_id,
        )

        db.add(binance_order)
        db.add(bybit_order)
        await db.commit()


# Global instance
order_executor = OrderExecutor()
