"""Order executor service for placing and managing orders"""
import asyncio
import MetaTrader5 as mt5
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.binance_client import BinanceFuturesClient
from app.models.account import Account
from app.models.order import OrderRecord
from app.websocket.manager import manager
from app.utils.trading_time import is_bybit_trading_hours


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
        position_side: Optional[str] = None,
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
                position_side=position_side,
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
        category: str = "inverse",
    ) -> Dict[str, Any]:
        """Place order on Bybit via MT5 terminal"""
        from app.services.market_service import market_data_service
        import logging
        logger = logging.getLogger(__name__)

        mt5_client = market_data_service.mt5_client

        try:
            # Map side to MT5 order type
            if side.lower() == "buy":
                mt5_order_type = mt5.ORDER_TYPE_BUY_LIMIT if order_type.lower() == "limit" else mt5.ORDER_TYPE_BUY
            else:
                mt5_order_type = mt5.ORDER_TYPE_SELL_LIMIT if order_type.lower() == "limit" else mt5.ORDER_TYPE_SELL

            price_val = float(price) if price else None
            qty_val = float(quantity)

            # 添加详细日志
            logger.info(f"Bybit order params BEFORE MT5: symbol={symbol}, side={side}, type={order_type}, "
                       f"quantity={quantity}, price={price}, price_val={price_val}, qty_val={qty_val}")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: mt5_client.send_order(
                    symbol=symbol,
                    order_type=mt5_order_type,
                    volume=qty_val,
                    price=price_val,
                )
            )

            if result is None:
                return {
                    "success": False,
                    "platform": "bybit",
                    "error": "MT5 order failed: no result returned",
                }

            if result.get("retcode") != mt5.TRADE_RETCODE_DONE:
                return {
                    "success": False,
                    "platform": "bybit",
                    "error": f"MT5 order error: retcode={result.get('retcode')}, comment={result.get('comment')}",
                }

            return {
                "success": True,
                "platform": "bybit",
                "order_id": str(result.get("order")),
                "data": result,
            }
        except Exception as e:
            return {
                "success": False,
                "platform": "bybit",
                "error": str(e),
            }

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
        category: str = "inverse",
    ) -> Dict[str, Any]:
        """Check Bybit order status via MT5"""
        from app.services.market_service import market_data_service

        mt5_client = market_data_service.mt5_client

        try:
            ticket = int(order_id)
            loop = asyncio.get_event_loop()

            # Check open orders first
            orders = await loop.run_in_executor(
                None,
                lambda: mt5.orders_get(ticket=ticket)
            )

            if orders:
                order = orders[0]
                # Order still open/pending
                return {
                    "success": True,
                    "status": "open",
                    "filled": False,
                    "partially_filled": False,
                    "filled_qty": 0,
                    "total_qty": order.volume_current,
                    "data": {"ticket": ticket},
                }

            # Check positions (order filled and became a position)
            positions = await loop.run_in_executor(
                None,
                lambda: mt5.positions_get(symbol=symbol)
            )

            if positions:
                for pos in positions:
                    if pos.ticket == ticket:
                        return {
                            "success": True,
                            "status": "Filled",
                            "filled": True,
                            "partially_filled": False,
                            "filled_qty": pos.volume,
                            "total_qty": pos.volume,
                            "data": {"ticket": ticket},
                        }

            # Order filled and closed (history)
            history = await loop.run_in_executor(
                None,
                lambda: mt5.history_orders_get(ticket=ticket)
            )

            if history:
                order = history[0]
                filled = order.state == mt5.ORDER_STATE_FILLED
                return {
                    "success": True,
                    "status": "Filled" if filled else "cancelled",
                    "filled": filled,
                    "partially_filled": False,
                    "filled_qty": order.volume_current if filled else 0,
                    "total_qty": order.volume_initial,
                    "data": {"ticket": ticket},
                }

            return {
                "success": False,
                "error": f"Order {order_id} not found in MT5",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

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
        category: str = "inverse",
    ) -> Dict[str, Any]:
        """Cancel Bybit order via MT5"""
        try:
            ticket = int(order_id)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: mt5.order_cancel(ticket)
            )
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return {"success": True, "data": {"ticket": ticket}}
            return {
                "success": False,
                "error": f"MT5 cancel failed: retcode={result.retcode if result else 'None'}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }


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
        bybit_quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute dual orders on both exchanges with chase logic

        Args:
            binance_account: Binance account
            bybit_account: Bybit account
            binance_symbol: Binance symbol (e.g., XAUUSDT)
            bybit_symbol: Bybit symbol (e.g., XAUUSD.s)
            binance_side: Binance order side (BUY/SELL)
            bybit_side: Bybit order side (Buy/Sell)
            quantity: Binance order quantity (in contracts)
            binance_price: Binance order price (for LIMIT orders)
            bybit_price: Bybit order price (for LIMIT orders)
            order_type: Order type (LIMIT/MARKET)
            max_retries: Maximum retry attempts
            retry_delay: Delay between retries in seconds
            db: Database session for order persistence
            bybit_quantity: Bybit order quantity (in lots). If None, calculated as quantity/100

        Returns:
            Dict with execution results

        Note:
            Binance XAUUSDT: 1 contract = 1 XAU (ounce)
            Bybit XAUUSD.s: 1 lot = 100 XAU (ounces)
            Therefore: bybit_quantity = binance_quantity / 100
        """
        # Check fund sufficiency before placing orders
        try:
            from app.services.account_service import account_data_service

            # Get Binance account balance
            binance_balance_data = await account_data_service.get_account_balance(binance_account)
            if binance_balance_data:
                binance_available = binance_balance_data.get("available_balance", 0)
                # Estimate required margin: price * quantity / leverage
                binance_leverage = binance_account.leverage or 20
                binance_required_margin = (binance_price or 2700) * quantity / binance_leverage

                if binance_available < binance_required_margin:
                    return {
                        "success": False,
                        "error": f"Binance资金不足: 可用 {binance_available:.2f} USDT < 所需保证金 {binance_required_margin:.2f} USDT",
                    }

            # Get Bybit account balance
            bybit_balance_data = await account_data_service.get_account_balance(bybit_account)
            if bybit_balance_data:
                bybit_available = bybit_balance_data.get("available_balance", 0)
                # Estimate required margin: price * quantity * 100 / leverage (convert lots to XAU)
                bybit_leverage = bybit_account.leverage or 100
                bybit_qty = bybit_quantity or (quantity / 100.0)
                bybit_required_margin = (bybit_price or 2700) * bybit_qty * 100 / bybit_leverage

                if bybit_available < bybit_required_margin:
                    return {
                        "success": False,
                        "error": f"Bybit资金不足: 可用 {bybit_available:.2f} USDT < 所需保证金 {bybit_required_margin:.2f} USDT",
                    }
        except Exception as e:
            # If balance check fails, log warning but continue (don't block trading)
            print(f"Warning: Fund sufficiency check failed: {e}")

        # Calculate Bybit quantity if not provided
        # Binance XAUUSDT: 1 contract = 1 XAU; Bybit XAUUSD.s: 1 lot = 100 XAU
        if bybit_quantity is None:
            bybit_quantity = quantity / 100.0

        # Round quantities to correct precision
        # Binance XAUUSDT: min 0.001, step 0.001 → 3 decimal places
        quantity = round(quantity, 3)
        # Bybit MT5 XAUUSD.s: min 0.01 lot, step 0.01 → 2 decimal places
        bybit_quantity = round(bybit_quantity, 2)

        # Validate minimum quantities
        # Binance XAUUSDT: minimum 0.001 XAU
        if quantity < 0.001:
            return {
                "success": False,
                "error": f"Binance数量不足: {quantity} XAU < 0.001 XAU (最小交易量)",
            }

        # Bybit MT5 XAUUSD.s: minimum 0.01 Lot
        if bybit_quantity < 0.01:
            return {
                "success": False,
                "error": f"Bybit数量不足: {bybit_quantity} Lot < 0.01 Lot (最小交易量)",
            }

        # Check Bybit trading hours
        is_open, time_message = is_bybit_trading_hours()
        if not is_open:
            return {
                "success": False,
                "error": f"Bybit交易时间限制: {time_message}",
            }

        # Round prices to correct precision
        # Binance XAUUSDT: 2 decimal places
        if binance_price is not None:
            original_binance_price = binance_price
            binance_price = round(binance_price, 2)
            if original_binance_price != binance_price:
                print(f"WARNING: Binance price rounded from {original_binance_price} to {binance_price}")
        # Bybit MT5 XAUUSD.s: 2 decimal places (强制精度处理，防止浮点数精度问题)
        if bybit_price is not None:
            original_bybit_price = bybit_price
            bybit_price = round(bybit_price, 2)
            if original_bybit_price != bybit_price:
                print(f"WARNING: Bybit price rounded from {original_bybit_price} to {bybit_price}")

        print(f"DEBUG: execute_dual_order prices AFTER rounding: binance_price={binance_price}, bybit_price={bybit_price}")

        # Derive positionSide for Binance hedge mode accounts
        # BUY opens/closes LONG side; SELL opens/closes SHORT side
        binance_position_side = "LONG" if binance_side.upper() == "BUY" else "SHORT"

        # Step 1: Place initial orders on both exchanges
        # Binance: LIMIT (Maker), Bybit: MARKET (Taker)
        binance_result, bybit_result = await asyncio.gather(
            self.place_binance_order(
                binance_account,
                binance_symbol,
                binance_side,
                order_type,
                quantity,
                binance_price,
                position_side=binance_position_side,
            ),
            self.place_bybit_order(
                bybit_account,
                bybit_symbol,
                bybit_side,
                "Market",  # Always use Market orders for Bybit (Taker)
                str(bybit_quantity),
                None,  # Market orders don't need price
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

        # Return final status (no chase logic, pure maker orders)
        return {
            "success": binance_result["success"] and bybit_result["success"],
            "binance_filled": False,  # Status unknown without checking
            "bybit_filled": False,  # Status unknown without checking
            "binance_order_id": binance_order_id,
            "bybit_order_id": bybit_order_id,
            "binance_result": binance_result,
            "bybit_result": bybit_result,
            "retries": 0,
        }

    async def _chase_binance_order(
        self,
        account: Account,
        symbol: str,
        side: str,
        quantity: float,
        old_order_id: int,
        position_side: Optional[str] = None,
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
            position_side=position_side,
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
            source="strategy",
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
            source="strategy",
            platform_order_id=bybit_order_id,
        )

        db.add(binance_order)
        db.add(bybit_order)
        await db.commit()


# Global instance
order_executor = OrderExecutor()
