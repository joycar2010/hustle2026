"""MetaTrader5 client for Bybit MT5 integration"""
import MetaTrader5 as mt5
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
        self.connection_timeout = 30  # Timeout for considering connection stale

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
            # Initialize MT5 connection with credentials
            terminal_path = str(self.path) if self.path else "C:/Program Files/MetaTrader 5/terminal64.exe"
            if not mt5.initialize(
                path=terminal_path,
                login=self.login,
                password=self.password,
                server=self.server,
            ):
                error = mt5.last_error()
                logger.error(f"MT5 initialize failed: {error}")
                self.connection_failures += 1
                return False

            self.connected = True
            self.connection_failures = 0  # Reset failure count on successful connection
            self.last_successful_request = datetime.utcnow()
            logger.info(f"MT5 connected successfully to account {self.login}")
            return True

        except Exception as e:
            logger.error(f"Error connecting to MT5: {e}")
            self.connection_failures += 1
            return False

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
            symbol: Trading symbol (e.g., "XAUUSD.s")

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

            return {
                'login': account_info.login,
                'balance': account_info.balance,
                'equity': account_info.equity,
                'margin': account_info.margin,
                'margin_free': account_info.margin_free,
                'margin_level': account_info.margin_level,
                'profit': account_info.profit
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
        comment: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Send trading order

        Args:
            symbol: Trading symbol
            order_type: Order type (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL)
            volume: Order volume
            price: Order price (for limit orders)
            sl: Stop loss price
            tp: Take profit price
            deviation: Maximum price deviation
            comment: Order comment

        Returns:
            Order result dict
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "deviation": deviation,
                "magic": self.login,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            if price is not None:
                request["price"] = price
            if sl is not None:
                request["sl"] = sl
            if tp is not None:
                request["tp"] = tp

            result = mt5.order_send(request)
            if result is None:
                logger.error(f"Order send failed: {mt5.last_error()}")
                return None

            return {
                'retcode': result.retcode,
                'deal': result.deal,
                'order': result.order,
                'volume': result.volume,
                'price': result.price,
                'comment': result.comment
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
                    'tp': pos.tp
                }
                for pos in positions
            ]

        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
