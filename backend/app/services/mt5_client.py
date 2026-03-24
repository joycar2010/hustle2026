"""MetaTrader5 client for Bybit MT5 integration"""
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
from typing import Dict, Any, Optional
from pathlib import Path
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MT5Client:
    """Client for connecting to MetaTrader5 instance with auto-reconnection"""

    def __init__(self, login: int, password: str, server: str, path: Optional[str] = None):
        """
        Initialize MT5 client

        Args:
            login: MT5 account login
            password: MT5 account password
            server: MT5 server name
            path: Optional path to MT5 terminal
        """
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.connected = False

        # Connection monitoring
        self.last_successful_request = None
        self.last_connection_attempt = None
        self.connection_failures = 0
        self.max_connection_failures = 5

        # Reconnection strategy
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.connection_timeout = 30  # Timeout for considering connection stale (30 seconds)

    def is_connection_healthy(self) -> bool:
        """Check if connection is healthy based on last successful request"""
        if not self.connected:
            return False

        if self.last_successful_request is None:
            return False

        # Check if connection is stale (no successful requests in timeout period)
        time_since_last_request = (datetime.utcnow() - self.last_successful_request).total_seconds()
        if time_since_last_request > self.connection_timeout:
            logger.warning(f"MT5 connection appears stale (no activity for {time_since_last_request:.1f}s)")
            return False

        return True

    def _calculate_reconnect_delay(self) -> float:
        """Calculate reconnection delay with exponential backoff"""
        delay = min(self.reconnect_delay * (2 ** self.connection_failures), self.max_reconnect_delay)
        return delay

    def _should_attempt_reconnect(self) -> bool:
        """Check if we should attempt reconnection"""
        if self.connection_failures >= self.max_connection_failures:
            logger.error(f"Max connection failures ({self.max_connection_failures}) reached")
            return False

        if self.last_connection_attempt:
            time_since_attempt = (datetime.utcnow() - self.last_connection_attempt).total_seconds()
            required_delay = self._calculate_reconnect_delay()

            if time_since_attempt < required_delay:
                return False

        return True

    def connect(self) -> bool:
        """Connect to MT5 terminal with retry logic"""
        self.last_connection_attempt = datetime.utcnow()

        try:
            # Step 1: Initialize MT5 terminal (connect to running MT5)
            terminal_path = str(self.path) if self.path else "C:/Program Files/MetaTrader 5/terminal64.exe"
            if not mt5.initialize(path=terminal_path):
                error = mt5.last_error()
                logger.error(f"MT5 initialize failed: {error}")
                self.connection_failures += 1
                return False

            # Step 2: Check if already logged in to correct account
            account_info = mt5.account_info()
            if account_info and account_info.login == self.login:
                # Already logged in to the correct account
                self.connected = True
                self.connection_failures = 0
                self.last_successful_request = datetime.utcnow()
                logger.info(f"MT5 already connected to account {self.login}")
                self._initialize_default_symbols()
                return True

            # Step 3: Login if not connected or wrong account
            logger.info(f"Attempting to login to MT5 account {self.login}")
            if not mt5.login(
                login=self.login,
                password=self.password,
                server=self.server,
                timeout=10000  # 10 second timeout
            ):
                error = mt5.last_error()
                logger.error(f"MT5 login failed: {error}")
                mt5.shutdown()
                self.connection_failures += 1
                return False

            self.connected = True
            self.connection_failures = 0  # Reset failure count on successful connection
            self.last_successful_request = datetime.utcnow()
            logger.info(f"MT5 connected successfully to account {self.login}")

            # Initialize default symbols (ensure XAUUSD+ is visible and ready)
            self._initialize_default_symbols()

            return True

        except Exception as e:
            logger.error(f"Error connecting to MT5: {e}")
            self.connection_failures += 1
            return False

    def _initialize_default_symbols(self):
        """Initialize and activate default trading symbols"""
        from app.core.config import settings

        default_symbols = settings.MT5_DEFAULT_SYMBOLS
        logger.info(f"Initializing default MT5 symbols: {default_symbols}")

        for symbol in default_symbols:
            try:
                # Check if symbol exists
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Symbol {symbol} not found in MT5")
                    continue

                # Ensure symbol is visible
                if not symbol_info.visible:
                    if mt5.symbol_select(symbol, True):
                        logger.info(f"Symbol {symbol} activated successfully")
                    else:
                        logger.error(f"Failed to activate symbol {symbol}: {mt5.last_error()}")
                else:
                    logger.info(f"Symbol {symbol} already visible")

                # Subscribe to market data
                if not mt5.market_book_add(symbol):
                    logger.warning(f"Failed to subscribe to market book for {symbol}: {mt5.last_error()}")

            except Exception as e:
                logger.error(f"Error initializing symbol {symbol}: {e}")

    def ensure_connection(self) -> bool:
        """Ensure connection is active, reconnect if necessary"""
        # If already connected and healthy, return True
        if self.connected and self.is_connection_healthy():
            return True

        # If connection is unhealthy, disconnect first
        if self.connected and not self.is_connection_healthy():
            logger.warning("MT5 connection unhealthy, attempting reconnection")
            self.disconnect()

        # Check if we should attempt reconnection
        if not self._should_attempt_reconnect():
            delay = self._calculate_reconnect_delay()
            logger.warning(f"Waiting {delay:.1f}s before next reconnection attempt")
            return False

        # Attempt to connect
        logger.info("Attempting to connect to MT5...")
        return self.connect()

    def disconnect(self):
        """Disconnect from MT5 terminal"""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 disconnected")

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get latest tick data for symbol with auto-reconnection

        Args:
            symbol: Trading symbol (e.g., "XAUUSD+")

        Returns:
            Dict with bid, ask, time, etc.
        """
        if not self.ensure_connection():
            return None

        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                error = mt5.last_error()
                logger.error(f"Failed to get tick for {symbol}: {error}")

                # Mark connection as potentially unhealthy
                self.connected = False
                return None

            # Update last successful request timestamp
            self.last_successful_request = datetime.utcnow()

            return {
                'symbol': symbol,
                'bid': tick.bid,
                'ask': tick.ask,
                'last': tick.last,
                'volume': tick.volume,
                'time': tick.time,
                'time_msc': tick.time_msc
            }

        except Exception as e:
            logger.error(f"Error getting tick for {symbol}: {e}")
            # Mark connection as potentially unhealthy
            self.connected = False
            return None

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Get account information with auto-reconnection"""
        if not self.ensure_connection():
            return None

        try:
            account_info = mt5.account_info()
            if account_info is None:
                error = mt5.last_error()
                logger.error(f"Failed to get account info: {error}")
                self.connected = False
                return None

            # Update last successful request timestamp
            self.last_successful_request = datetime.utcnow()

            # Calculate total swap from positions and history
            total_swap = 0.0
            position_swap = 0.0
            deal_swap = 0.0

            # Get swap from open positions
            positions = mt5.positions_get()
            if positions:
                logger.info(f"Found {len(positions)} open positions")
                for pos in positions:
                    position_swap += pos.swap
                    logger.debug(f"Position {pos.ticket}: swap={pos.swap}")
                total_swap += position_swap
            else:
                logger.info("No open positions found")

            # Get swap from historical deals (last 30 days)
            from_date = datetime.utcnow() - timedelta(days=30)
            deals = mt5.history_deals_get(from_date, datetime.utcnow())
            if deals:
                logger.info(f"Found {len(deals)} historical deals in last 30 days")
                deal_count_with_swap = 0
                for deal in deals:
                    if hasattr(deal, 'swap') and deal.swap != 0:
                        deal_swap += deal.swap
                        deal_count_with_swap += 1
                        logger.debug(f"Deal {deal.ticket}: swap={deal.swap}")
                total_swap += deal_swap
                logger.info(f"Deals with swap: {deal_count_with_swap}, total deal swap: {deal_swap}")
            else:
                logger.info("No historical deals found")

            logger.info(f"Total swap calculation: position_swap={position_swap}, deal_swap={deal_swap}, total={total_swap}")

            return {
                'login': account_info.login,
                'balance': account_info.balance,
                'equity': account_info.equity,
                'margin': account_info.margin,
                'margin_free': account_info.margin_free,
                'margin_level': account_info.margin_level,
                'profit': account_info.profit,
                'swap': total_swap  # 账户累计总过夜费（包含已平仓+未平仓）
            }

        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            self.connected = False
            return None

    def get_connection_status(self) -> Dict[str, Any]:
        """Get detailed connection status information"""
        status = {
            "connected": self.connected,
            "healthy": self.is_connection_healthy(),
            "connection_failures": self.connection_failures,
            "max_failures": self.max_connection_failures,
            "last_successful_request": self.last_successful_request.isoformat() if self.last_successful_request else None,
            "last_connection_attempt": self.last_connection_attempt.isoformat() if self.last_connection_attempt else None,
        }

        if self.last_successful_request:
            time_since_last = (datetime.now() - self.last_successful_request).total_seconds()
            status["seconds_since_last_request"] = round(time_since_last, 2)

        if self.connection_failures > 0:
            status["next_reconnect_delay"] = round(self._calculate_reconnect_delay(), 2)

        return status

    def reset_connection_failures(self):
        """Reset connection failure counter (useful for manual recovery)"""
        self.connection_failures = 0
        logger.info("Connection failure counter reset")

    def send_order(
        self,
        symbol: str,
        order_type: int,
        volume: float,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        deviation: int = 10,
        comment: str = "",
        max_retry: int = 2,
        position_ticket: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Send trading order with enhanced validation and retry logic

        Args:
            symbol: Trading symbol
            order_type: Order type (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL)
            volume: Order volume (raw, will be normalized)
            price: Order price (for limit orders, raw, will be normalized)
            sl: Stop loss price
            tp: Take profit price
            deviation: Maximum price deviation
            comment: Order comment
            max_retry: Maximum retry attempts for recoverable errors
            position_ticket: Position ticket to close (for closing orders)

        Returns:
            Order result dict with retcode, order, volume, price, comment
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            # ========== Step 1: Get and validate symbol info ==========
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.error(f"Failed to get symbol info for {symbol}: {mt5.last_error()}")
                return None

            # Ensure symbol is visible (XAUUSD+ may be hidden by default)
            if not symbol_info.visible:
                if not mt5.symbol_select(symbol, True):
                    logger.error(f"Failed to activate symbol {symbol}: {mt5.last_error()}")
                    return None
                # Refresh symbol info after activation
                symbol_info = mt5.symbol_info(symbol)

            digits = symbol_info.digits
            point = symbol_info.point
            volume_min = symbol_info.volume_min
            volume_max = symbol_info.volume_max
            volume_step = symbol_info.volume_step

            logger.info(f"MT5 symbol_info for {symbol}: digits={digits}, point={point}, "
                       f"volume_min={volume_min}, volume_max={volume_max}, volume_step={volume_step}")

            # ========== Step 2: Normalize volume ==========
            # Align to volume_step and enforce min constraint
            normalized_volume = round(volume / volume_step) * volume_step
            normalized_volume = max(normalized_volume, volume_min)

            # volume_max: 不再静默截断，调用方（order_executor）已按持仓量拆单
            # 若仍超出则报警并截断，防止 MT5 retcode 10014，同时让上层感知
            if normalized_volume > volume_max:
                logger.error(
                    f"[MT5_ORDER] volume {normalized_volume} exceeds volume_max {volume_max} "
                    f"for {symbol}. Capping to volume_max. "
                    f"Caller should have split the order — check place_bybit_order logic."
                )
                normalized_volume = volume_max

            if abs(volume - normalized_volume) > volume_step * 0.01:
                logger.warning(f"Volume normalized: {volume} -> {normalized_volume}")

            # ========== Step 3: Normalize and validate price ==========
            if price is not None:
                original_price = price
                normalized_price = round(price, digits)

                # XAUUSD+ specific validation: price range 1000-5000
                if symbol.upper() == "XAUUSD.S":
                    if normalized_price < 1000 or normalized_price > 5000:
                        logger.error(f"XAUUSD+ price out of valid range: {normalized_price}")
                        return {
                            'retcode': 10015,  # Invalid price
                            'deal': 0,
                            'order': 0,
                            'volume': 0,
                            'price': 0,
                            'comment': f'Price out of range: {normalized_price}'
                        }

                if abs(original_price - normalized_price) > point * 0.1:
                    logger.warning(f"Price normalized: {original_price} -> {normalized_price}")

                price = normalized_price

            # ========== Step 4: Determine trade action and filling type ==========
            if order_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
                             mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP,
                             mt5.ORDER_TYPE_BUY_STOP_LIMIT, mt5.ORDER_TYPE_SELL_STOP_LIMIT]:
                trade_action = mt5.TRADE_ACTION_PENDING
                # CRITICAL FIX: For pending limit orders, MUST use RETURN
                # FOK (Fill or Kill) is incompatible with TRADE_ACTION_PENDING
                # Using FOK causes MT5 retcode=10015 (Invalid price) error
                # RETURN allows partial fills and keeps remaining order in book
                type_filling = mt5.ORDER_FILLING_RETURN
            else:
                trade_action = mt5.TRADE_ACTION_DEAL
                # For market orders, use IOC (Immediate or Cancel)
                type_filling = mt5.ORDER_FILLING_IOC

            # ========== Step 5: Build request ==========
            request = {
                "action": trade_action,
                "symbol": symbol,
                "volume": normalized_volume,
                "type": order_type,
                "deviation": deviation,
                "magic": self.login,
                "comment": comment[:255],  # MT5 limits comment to 255 chars
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": type_filling,
            }

            # Add position ticket for closing orders
            if position_ticket is not None:
                request["position"] = position_ticket
                logger.info(f"Closing position ticket: {position_ticket}")

            if price is not None:
                request["price"] = price
            if sl is not None:
                request["sl"] = round(sl, digits)
            if tp is not None:
                request["tp"] = round(tp, digits)

            # ========== Step 6: Send order with retry logic ==========
            retry_count = 0
            while retry_count < max_retry:
                result = mt5.order_send(request)

                if result is None:
                    logger.error(f"Order send failed: {mt5.last_error()}")
                    return None

                # Success
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Order sent successfully | Symbol: {symbol} | Type: {order_type} | "
                               f"Price: {price} | Volume: {normalized_volume} | Order ID: {result.order}")
                    return {
                        'retcode': result.retcode,
                        'deal': result.deal,
                        'order': result.order,
                        'volume': result.volume,
                        'price': result.price,
                        'comment': result.comment
                    }

                # Recoverable errors: requote (10030), insufficient liquidity (10018)
                retry_errors = [10030, 10018]
                if result.retcode in retry_errors and retry_count < max_retry - 1:
                    retry_count += 1
                    logger.warning(f"Order failed with recoverable error | Retry: {retry_count}/{max_retry} | "
                                 f"retcode: {result.retcode} | error: {mt5.last_error()}")
                    continue

                # Non-recoverable error
                logger.error(f"Order failed | retcode: {result.retcode} | error: {mt5.last_error()} | "
                           f"request: {request}")
                return {
                    'retcode': result.retcode,
                    'deal': result.deal,
                    'order': result.order,
                    'volume': result.volume,
                    'price': result.price,
                    'comment': result.comment
                }

            # Retry exhausted
            logger.error(f"Order retry exhausted ({max_retry} attempts) | Symbol: {symbol} | "
                        f"Price: {price} | Volume: {normalized_volume}")
            return {
                'retcode': -2,  # Custom code for retry exhausted
                'deal': 0,
                'order': 0,
                'volume': 0,
                'price': 0,
                'comment': f'Retry exhausted after {max_retry} attempts'
            }

        except Exception as e:
            logger.error(f"Error sending order: {e}")
            return None

    def get_positions(self, symbol: Optional[str] = None) -> list:
        """Get open positions"""
        if not self.connected:
            if not self.connect():
                return []

        try:
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()

            if positions is None:
                return []

            return [
                {
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'type': pos.type,
                    'volume': pos.volume,
                    'price_open': pos.price_open,
                    'price_current': pos.price_current,
                    'profit': pos.profit,
                    'sl': pos.sl,
                    'tp': pos.tp,
                    'margin': getattr(pos, 'margin', 0.0),  # Position margin (for liquidation calculation)
                    'price_liquidation': getattr(pos, 'price_liquidation', 0.0)  # Bybit MT5 liquidation price
                }
                for pos in positions
            ]
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def get_market_book(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get market book (order book) data for symbol

        Args:
            symbol: Trading symbol (e.g., "XAUUSD+")

        Returns:
            Dict with bid_price, bid_volume, ask_price, ask_volume, or None if failed
        """
        if not self.ensure_connection():
            return None

        try:
            # Get market book data
            book = mt5.market_book_get(symbol)
            if book is None:
                error = mt5.last_error()
                logger.error(f"Failed to get market book for {symbol}: {error}")
                return None

            # Filter bid and ask orders
            # BOOK_TYPE_BUY (2) = Buy orders (BID side)
            # BOOK_TYPE_SELL (1) = Sell orders (ASK side)
            bid_book = [b for b in book if b.type == mt5.BOOK_TYPE_BUY]   # Buy orders (BID)
            ask_book = [b for b in book if b.type == mt5.BOOK_TYPE_SELL]  # Sell orders (ASK)

            if not bid_book or not ask_book:
                logger.warning(f"Market book has no data for {symbol}")
                return None

            # Get best bid (highest buy price) and best ask (lowest sell price)
            bid_best = max(bid_book, key=lambda x: x.price)
            ask_best = min(ask_book, key=lambda x: x.price)

            # Update last successful request timestamp
            self.last_successful_request = datetime.utcnow()

            return {
                'symbol': symbol,
                'bid_price': round(bid_best.price, 3),
                'bid_volume': round(bid_best.volume, 2),  # Volume in lots (1 lot = 100 oz for XAUUSD+)
                'ask_price': round(ask_best.price, 3),
                'ask_volume': round(ask_best.volume, 2),
                'timestamp': int(time.time() * 1000)
            }

        except Exception as e:
            logger.error(f"Error getting market book for {symbol}: {e}")
            return None

    def find_position_to_close(
        self, symbol: str, side: str, required_volume: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        """
        Find a position to close based on symbol and side.

        Args:
            symbol: Trading symbol
            side: 'Buy' to close SHORT positions, 'Sell' to close LONG positions
            required_volume: Minimum volume needed (in lots). When > 0, prefer positions
                             with sufficient volume; fall back to largest if none qualify.

        Returns:
            Dict with 'ticket' and 'volume', or None if no matching position found.
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            positions = mt5.positions_get(symbol=symbol)

            if positions is None or len(positions) == 0:
                logger.warning(f"No positions found for {symbol}")
                return None

            # MT5 position types: 0=BUY(LONG), 1=SELL(SHORT)
            # To close LONG position, we SELL; to close SHORT position, we BUY
            target_type = 1 if side.lower() == 'buy' else 0

            matching_positions = [pos for pos in positions if pos.type == target_type]

            if not matching_positions:
                logger.warning(f"No {['LONG', 'SHORT'][target_type]} positions found for {symbol}")
                return None

            # Prefer a position whose volume >= required_volume (exact fit first)
            if required_volume > 0:
                sufficient = [p for p in matching_positions if p.volume >= required_volume]
                if sufficient:
                    # Among sufficient positions, pick the one closest to required_volume
                    selected_pos = min(sufficient, key=lambda p: p.volume - required_volume)
                else:
                    # No single position covers the full amount — pick the largest available
                    selected_pos = max(matching_positions, key=lambda p: p.volume)
                    logger.warning(
                        f"No position with volume >= {required_volume} lots for {symbol}. "
                        f"Using largest available: ticket={selected_pos.ticket}, volume={selected_pos.volume}"
                    )
            else:
                # No volume requirement — use oldest position (first in list)
                selected_pos = matching_positions[0]

            logger.info(
                f"Found position to close: ticket={selected_pos.ticket}, "
                f"type={['LONG', 'SHORT'][selected_pos.type]}, "
                f"volume={selected_pos.volume}, required={required_volume}"
            )
            return {"ticket": selected_pos.ticket, "volume": selected_pos.volume}

        except Exception as e:
            logger.error(f"Failed to find position to close: {e}")
            return None

    def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get latest tick data for a symbol

        Args:
            symbol: Trading symbol

        Returns:
            Dict with bid, ask, last prices and timestamp, or None if failed
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error(f"Failed to get tick for {symbol}: {mt5.last_error()}")
                return None

            return {
                'symbol': symbol,
                'bid': tick.bid,
                'ask': tick.ask,
                'last': tick.last,
                'time': datetime.fromtimestamp(tick.time),
                'volume': tick.volume
            }
        except Exception as e:
            logger.error(f"Failed to get latest tick for {symbol}: {e}")
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get latest last price for a symbol (convenience method)

        Args:
            symbol: Trading symbol

        Returns:
            Latest last price, or None if failed
        """
        tick = self.get_latest_tick(symbol)
        if tick:
            return tick['last']
        return None

    def get_default_symbol(self) -> str:
        """
        Get the default trading symbol from configuration

        Returns:
            Default symbol string (e.g., "XAUUSD+")
        """
        from app.core.config import settings
        return settings.MT5_DEFAULT_SYMBOL

    def get_default_symbol_info(self) -> Optional[Dict[str, Any]]:
        """
        Get symbol info for the default trading symbol

        Returns:
            Dict with symbol information, or None if failed
        """
        default_symbol = self.get_default_symbol()
        if not self.connected:
            if not self.connect():
                return None

        try:
            symbol_info = mt5.symbol_info(default_symbol)
            if symbol_info is None:
                logger.error(f"Failed to get info for default symbol {default_symbol}: {mt5.last_error()}")
                return None

            return {
                'symbol': default_symbol,
                'digits': symbol_info.digits,
                'point': symbol_info.point,
                'volume_min': symbol_info.volume_min,
                'volume_max': symbol_info.volume_max,
                'volume_step': symbol_info.volume_step,
                'contract_size': symbol_info.trade_contract_size,
                'visible': symbol_info.visible,
                'spread': symbol_info.spread
            }
        except Exception as e:
            logger.error(f"Error getting default symbol info: {e}")
            return None

    def get_deals_by_ticket(self, ticket: int) -> list:
        """
        Get deals for a specific order ticket (for volume verification)

        Args:
            ticket: Order ticket number

        Returns:
            List of deals associated with this ticket
        """
        if not self.connected:
            if not self.connect():
                return []

        try:
            # Get deals from last 5 minutes (should be enough for recent orders)
            date_from = datetime.utcnow() - timedelta(minutes=5)
            date_to = datetime.utcnow()

            deals = mt5.history_deals_get(date_from, date_to)
            if deals is None:
                return []

            # Filter deals by order ticket
            # MT5: for closing orders, deal.order matches the close order ticket
            # but deal.position_id matches the original position ticket
            # We check both to handle all cases
            result = []
            for deal in deals:
                if deal.order == ticket or deal.position_id == ticket:
                    result.append({
                        'ticket': deal.ticket,
                        'order': deal.order,
                        'position_id': deal.position_id,
                        'time': datetime.fromtimestamp(deal.time),
                        'type': deal.type,
                        'volume': deal.volume,
                        'price': deal.price,
                        'symbol': deal.symbol
                    })

            return result

        except Exception as e:
            logger.error(f"Failed to get deals by ticket {ticket}: {e}")
            return []

    def get_deals_history(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        symbol: Optional[str] = None
    ) -> list:
        """
        Get deals history (executed trades) with commission and swap fees

        Args:
            date_from: Start date for history (default: today 00:00)
            date_to: End date for history (default: now)
            symbol: Optional symbol filter

        Returns:
            List of deals with commission and swap information
        """
        if not self.connected:
            if not self.connect():
                return []

        try:
            # Default to today if not specified
            if date_from is None:
                date_from = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            if date_to is None:
                date_to = datetime.utcnow()

            # Get deals history
            if symbol:
                deals = mt5.history_deals_get(date_from, date_to, group=symbol)
            else:
                deals = mt5.history_deals_get(date_from, date_to)

            if deals is None:
                logger.warning(f"No deals found or error: {mt5.last_error()}")
                return []

            result = []
            for deal in deals:
                result.append({
                    'ticket': deal.ticket,
                    'order': deal.order,
                    'time': datetime.fromtimestamp(deal.time),
                    'type': deal.type,  # 0=Buy, 1=Sell
                    'entry': deal.entry,  # 0=In, 1=Out, 2=InOut, 3=OutBy
                    'symbol': deal.symbol,
                    'volume': deal.volume,
                    'price': deal.price,
                    'commission': deal.commission,  # Commission fee
                    'swap': deal.swap,  # Swap fee (overnight interest)
                    'profit': deal.profit,
                    'comment': deal.comment
                })

            return result

        except Exception as e:
            logger.error(f"Failed to get deals history: {e}")
            return []

    def get_history_orders(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        symbol: Optional[str] = None
    ) -> list:
        """
        Get orders history

        Args:
            date_from: Start date for history (default: today 00:00)
            date_to: End date for history (default: now)
            symbol: Optional symbol filter

        Returns:
            List of historical orders
        """
        if not self.connected:
            if not self.connect():
                return []

        try:
            # Default to today if not specified
            if date_from is None:
                date_from = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            if date_to is None:
                date_to = datetime.utcnow()

            # Get orders history
            if symbol:
                orders = mt5.history_orders_get(date_from, date_to, group=symbol)
            else:
                orders = mt5.history_orders_get(date_from, date_to)

            if orders is None:
                logger.warning(f"No orders found or error: {mt5.last_error()}")
                return []

            result = []
            for order in orders:
                result.append({
                    'ticket': order.ticket,
                    'time_setup': datetime.fromtimestamp(order.time_setup),
                    'time_done': datetime.fromtimestamp(order.time_done) if order.time_done > 0 else None,
                    'type': order.type,
                    'state': order.state,
                    'symbol': order.symbol,
                    'volume_initial': order.volume_initial,
                    'volume_current': order.volume_current,
                    'price_open': order.price_open,
                    'price_current': order.price_current,
                    'comment': order.comment
                })

            return result

        except Exception as e:
            logger.error(f"Failed to get orders history: {e}")
            return []

    def get_positions_swap(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        获取当前持仓的实时Swap（过夜费）

        Args:
            symbol: 可选的品种过滤，如 "XAUUSD+"

        Returns:
            {
                "total_swap": 所有持仓的累计过夜费总和,
                "positions": [
                    {
                        "ticket": 持仓ID,
                        "symbol": 品种,
                        "side": 方向（BUY/SELL）,
                        "volume": 持仓手数,
                        "swap": 该持仓的累计过夜费,
                        "open_time": 开仓时间
                    }
                ]
            }
        """
        if not self.ensure_connection():
            return {"total_swap": 0.0, "positions": []}

        try:
            # 获取持仓
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()

            if not positions:
                return {"total_swap": 0.0, "positions": []}

            # 提取Swap数据
            total_swap = 0.0
            position_list = []

            for pos in positions:
                side = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                swap_value = round(pos.swap, 3)
                total_swap += swap_value

                position_list.append({
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "side": side,
                    "volume": pos.volume,
                    "swap": swap_value,
                    "open_time": datetime.fromtimestamp(pos.time),
                    "profit": pos.profit
                })

            self.last_successful_request = datetime.utcnow()

            return {
                "total_swap": round(total_swap, 3),
                "positions": position_list
            }

        except Exception as e:
            logger.error(f"Failed to get positions swap: {e}")
            self.connected = False
            return {"total_swap": 0.0, "positions": []}

    def get_history_swap_summary(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取历史平仓订单的Swap统计（用于统计面板）

        Args:
            date_from: 开始日期（默认：今天00:00）
            date_to: 结束日期（默认：现在）
            symbol: 可选的品种过滤

        Returns:
            {
                "total_swap": 历史订单的总过夜费,
                "deal_count": 有过夜费的订单数量,
                "deals": [
                    {
                        "ticket": 成交ID,
                        "symbol": 品种,
                        "swap": 过夜费,
                        "volume": 手数,
                        "time": 平仓时间,
                        "profit": 盈亏
                    }
                ]
            }
        """
        if not self.ensure_connection():
            return {"total_swap": 0.0, "deal_count": 0, "deals": []}

        try:
            # 默认时间范围
            if date_from is None:
                date_from = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            if date_to is None:
                date_to = datetime.utcnow()

            # 获取历史成交
            if symbol:
                deals = mt5.history_deals_get(date_from, date_to, group=symbol)
            else:
                deals = mt5.history_deals_get(date_from, date_to)

            if not deals:
                return {"total_swap": 0.0, "deal_count": 0, "deals": []}

            # 筛选有Swap的成交记录
            total_swap = 0.0
            swap_deals = []

            for deal in deals:
                if deal.swap != 0:  # 只统计有过夜费的记录
                    swap_value = round(deal.swap, 3)
                    total_swap += swap_value

                    swap_deals.append({
                        "ticket": deal.ticket,
                        "order": deal.order,
                        "symbol": deal.symbol,
                        "swap": swap_value,
                        "volume": deal.volume,
                        "time": datetime.fromtimestamp(deal.time),
                        "profit": deal.profit,
                        "commission": deal.commission
                    })

            self.last_successful_request = datetime.utcnow()

            return {
                "total_swap": round(total_swap, 3),
                "deal_count": len(swap_deals),
                "deals": swap_deals
            }

        except Exception as e:
            logger.error(f"Failed to get history swap summary: {e}")
            self.connected = False
            return {"total_swap": 0.0, "deal_count": 0, "deals": []}
