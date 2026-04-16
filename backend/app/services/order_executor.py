"""Order executor service for placing and managing orders"""
import asyncio
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.binance_client import BinanceFuturesClient
from app.models.account import Account
from app.core.proxy_utils import build_proxy_url
from app.models.order import OrderRecord
from app.websocket.manager import manager
from app.utils.trading_time import is_bybit_trading_hours


def _get_pair_specs():
    """Get trading specs from hedging pair config, with fallback to XAU defaults"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair("XAU")
        if pair:
            return {
                'sym_a': pair.symbol_a.symbol,
                'sym_b': pair.symbol_b.symbol,
                'conv_factor': pair.conversion_factor,
                'qty_prec_a': pair.symbol_a.qty_precision,
                'qty_step_a': pair.symbol_a.qty_step,
                'min_qty_a': pair.symbol_a.min_qty,
                'qty_prec_b': pair.symbol_b.qty_precision,
                'qty_step_b': pair.symbol_b.qty_step,
                'min_qty_b': pair.symbol_b.min_qty,
                'price_prec_a': pair.symbol_a.price_precision,
                'price_prec_b': pair.symbol_b.price_precision,
                'unit_a': pair.symbol_a.qty_unit,
                'unit_b': pair.symbol_b.qty_unit,
            }
    except Exception:
        pass
    return {
        'sym_a': 'XAUUSDT', 'sym_b': 'XAUUSD+',
        'conv_factor': 100.0,
        'qty_prec_a': 3, 'qty_step_a': 0.001, 'min_qty_a': 0.001,
        'qty_prec_b': 2, 'qty_step_b': 0.01, 'min_qty_b': 0.01,
        'price_prec_a': 2, 'price_prec_b': 2,
        'unit_a': 'XAU', 'unit_b': 'lot',
    }


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
        post_only: bool = False,
    ) -> Dict[str, Any]:
        """Place order on Binance.

        When post_only=True, uses native priceMatch=QUEUE (Binance server-side BBO
        matching) instead of GTX + explicit price.  No +/- tick offset needed.
        """
        import logging
        from app.services.binance_client import BinanceIPBanError, BinanceTerminalError
        logger = logging.getLogger(__name__)

        # 强制精度：按产品配置步长截断，防 -1111
        specs = _get_pair_specs()
        quantity = round(quantity, specs['qty_prec_a'])

        client = BinanceFuturesClient(account.api_key, account.api_secret,
                                       proxy_url=build_proxy_url(account.proxy_config))

        try:
            if post_only and order_type.upper() == "LIMIT":
                # Use native priceMatch=QUEUE — guaranteed MAKER, no price param needed.
                logger.info(f"Binance MAKER下单(priceMatch=QUEUE) - symbol: {symbol}, side: {side}, qty: {quantity}, position_side: {position_side}")
                result = await client.place_maker_order(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    position_side=position_side,
                )
            else:
                # Log order parameters
                logger.info(f"Binance下单请求 - symbol: {symbol}, side: {side}, type: {order_type}, qty: {quantity}, price: {price}, position_side: {position_side}, post_only: {post_only}")
                result = await client.place_order(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    position_side=position_side,
                    post_only=post_only,
                )

            logger.info(f"Binance下单成功 - order_id: {result.get('orderId')}, status: {result.get('status')}, priceMatch: {result.get('priceMatch', 'N/A')}")

            return {
                "success": True,
                "platform": "binance",
                "order_id": result.get("orderId"),
                "client_order_id": result.get("clientOrderId"),
                "status": result.get("status"),
                "data": result,
            }
        except BinanceIPBanError as e:
            logger.error(f"Binance IP封禁 - {e.message}")
            asyncio.create_task(_trigger_ip_ban_alert(e))
            return {
                "success": False,
                "platform": "binance",
                "error": e.message,
                "terminal_error": True,
                "error_type": "ip_ban",
            }
        except BinanceTerminalError as e:
            logger.error(f"Binance终止性错误(不重试) code={e.code}: {e.message}")
            return {
                "success": False,
                "platform": "binance",
                "error": e.message,
                "terminal_error": True,
                "error_code": e.code,
            }
        except Exception as e:
            logger.error(f"Binance下单失败 - symbol: {symbol}, side: {side}, qty: {quantity}, price: {price}, error: {str(e)}")
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
        close_position: bool = False,
    ) -> Dict[str, Any]:
        """
        Place order on Bybit via MT5 Bridge HTTP API.

        On Linux the MetaTrader5 Python module is unavailable. All orders go through
        the Windows MT5 Bridge REST endpoint which the Go trading handler also uses:
          POST /mt5/order          — open new position
          POST /mt5/position/close — close existing position

        Args:
            close_position: If True, close existing position instead of opening new one
        """
        import logging
        import os
        logger = logging.getLogger(__name__)

        # Resolve MT5 Bridge URL (same env vars as Go)
        bridge_url = os.getenv("MT5_SERVICE_URL", "http://172.31.14.113:8001")
        api_key = os.getenv("MT5_API_KEY", "")

        # Determine correct bridge by checking mt5_clients table for this account
        try:
            from app.models.mt5_client import MT5Client as MT5ClientModel
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import select as sa_select
            async with AsyncSessionLocal() as _db:
                mc = (await _db.execute(
                    sa_select(MT5ClientModel)
                    .where(MT5ClientModel.account_id == account.account_id)
                    .where(MT5ClientModel.is_active == True)
                    .where(MT5ClientModel.is_system_service == False)  # exclude system accounts — they're for market data only
                    .order_by(MT5ClientModel.priority)
                    .limit(1)
                )).scalar_one_or_none()
                if mc and mc.bridge_url:
                    bridge_url = mc.bridge_url
                    logger.info(f"[BYBIT_ORDER] Using bridge {bridge_url} for account {account.account_id} (login={mc.mt5_login})")
                elif mc and mc.bridge_service_port:
                    bridge_url = f"http://172.31.14.113:{mc.bridge_service_port}"
                    logger.info(f"[BYBIT_ORDER] Using bridge port {mc.bridge_service_port} for account {account.account_id} (login={mc.mt5_login})")
        except Exception as e:
            logger.debug(f"[BYBIT_ORDER] MT5 client lookup: {e}, using default {bridge_url}")

        import httpx
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-Api-Key"] = api_key

        qty_val = round(float(quantity), 2)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if close_position:
                    # Close existing position: POST /mt5/position/close {symbol, side, volume}
                    # For close: "buy" closes SHORT, "sell" closes LONG
                    payload = {"symbol": symbol, "side": side.lower(), "volume": qty_val}
                    logger.info(f"[BYBIT_ORDER] Bridge close: {bridge_url}/mt5/position/close {payload}")
                    resp = await client.post(f"{bridge_url}/mt5/position/close", json=payload, headers=headers)
                else:
                    # Open new position: POST /mt5/order {symbol, volume, order_type}
                    # order_type must be "BUY" or "SELL" (not "Market")
                    ot = side.upper()  # "BUY" or "SELL"
                    payload = {"symbol": symbol, "volume": qty_val, "order_type": ot}
                    logger.info(f"[BYBIT_ORDER] Bridge order: {bridge_url}/mt5/order {payload}")
                    resp = await client.post(f"{bridge_url}/mt5/order", json=payload, headers=headers)

                data = resp.json()
                if resp.status_code == 200:
                    # Bridge returns order result directly
                    order_id = data.get("order", data.get("ticket", data.get("orderId", 0)))
                    logger.info(f"[BYBIT_ORDER] Success: ticket={order_id}, data={data}")
                    return {
                        "success": True,
                        "platform": "bybit",
                        "order_id": str(order_id),
                        "data": data,
                    }
                else:
                    error_msg = data.get("detail", str(data))
                    logger.error(f"[BYBIT_ORDER] Bridge error: {resp.status_code} {error_msg}")
                    return {
                        "success": False,
                        "platform": "bybit",
                        "error": error_msg,
                    }

        except Exception as e:
            logger.error(f"[BYBIT_ORDER] Bridge request failed: {e}")
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
        client = BinanceFuturesClient(account.api_key, account.api_secret,
                                       proxy_url=build_proxy_url(account.proxy_config))

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
        from app.services.mt5_client import MT5Client

        if account and getattr(account, 'mt5_id', None) and getattr(account, 'mt5_primary_pwd', None) and getattr(account, 'mt5_server', None):
            mt5_client = MT5Client(login=int(account.mt5_id), password=account.mt5_primary_pwd, server=account.mt5_server)
            if not mt5_client.connect():
                mt5_client = market_data_service.mt5_client
        else:
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
        client = BinanceFuturesClient(account.api_key, account.api_secret,
                                       proxy_url=build_proxy_url(account.proxy_config))

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
            bybit_symbol: Bybit symbol (e.g., XAUUSD+)
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
            Bybit XAUUSD+: 1 lot = 100 XAU (ounces)
            Therefore: bybit_quantity = binance_quantity / 100
        """
        # Load pair specs for dynamic precision/conversion
        specs = _get_pair_specs()
        conv_factor = specs['conv_factor']

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
                bybit_leverage = bybit_account.leverage or 100
                bybit_qty = bybit_quantity or (quantity / conv_factor)
                bybit_required_margin = (bybit_price or 2700) * bybit_qty * conv_factor / bybit_leverage

                if bybit_available < bybit_required_margin:
                    return {
                        "success": False,
                        "error": f"Bybit资金不足: 可用 {bybit_available:.2f} USDT < 所需保证金 {bybit_required_margin:.2f} USDT",
                    }
        except Exception as e:
            # If balance check fails, log warning but continue (don't block trading)
            print(f"Warning: Fund sufficiency check failed: {e}")

        # Calculate Bybit quantity if not provided (A-side units → B-side units)
        if bybit_quantity is None:
            bybit_quantity = quantity / conv_factor

        # Round quantities to correct precision (from pair config)
        quantity = round(quantity, specs['qty_prec_a'])
        bybit_quantity = round(bybit_quantity, specs['qty_prec_b'])

        # Validate minimum quantities
        if quantity < specs['min_qty_a']:
            return {
                "success": False,
                "error": f"Binance数量不足: {quantity} {specs['unit_a']} < {specs['min_qty_a']} {specs['unit_a']} (最小交易量)",
            }

        if bybit_quantity < specs['min_qty_b']:
            return {
                "success": False,
                "error": f"Bybit数量不足: {bybit_quantity} {specs['unit_b']} < {specs['min_qty_b']} {specs['unit_b']} (最小交易量)",
            }

        # Check Bybit trading hours
        is_open, time_message = is_bybit_trading_hours()
        if not is_open:
            return {
                "success": False,
                "error": f"Bybit交易时间限制: {time_message}",
            }

        # Round prices to correct precision
        if binance_price is not None:
            original_binance_price = binance_price
            binance_price = round(binance_price, specs['price_prec_a'])
            if original_binance_price != binance_price:
                print(f"WARNING: Binance price rounded from {original_binance_price} to {binance_price}")
        # Bybit price rounding
        if bybit_price is not None:
            original_bybit_price = bybit_price
            bybit_price = round(bybit_price, specs['price_prec_b'])
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


async def _trigger_ip_ban_alert(e) -> None:
    """异步触发Binance IP封禁飞书+弹窗告警，不阻塞主流程"""
    try:
        from app.services.risk_alert_service import risk_alert_service
        from app.database import get_db_session
        from sqlalchemy import select
        from app.models.user import User

        async with get_db_session(timeout=5.0) as db:
            result = await db.execute(select(User).where(User.is_active == True))
            users = result.scalars().all()

        for user in users:
            await risk_alert_service.check_binance_ip_ban(
                user_id=str(user.user_id),
                ip=e.ip,
                ban_until_ms=e.ban_until_ms,
                message=e.message,
            )
    except Exception as ex:
        import logging
        logging.getLogger(__name__).error(f"[IP封禁告警] 触发失败: {ex}")


# Global instance
order_executor = OrderExecutor()
