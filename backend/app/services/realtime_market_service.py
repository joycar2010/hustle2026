"""
Real-time market data service
Fetches and stores real-time market data from Binance and Bybit
"""
import asyncio
import logging
from datetime import datetime, time
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.binance_client import BinanceFuturesClient
from app.services.binance_ws_client import binance_ws
from app.services.mt5_client import MT5Client
from app.models.market_data import MarketData, SpreadRecord
from app.models.account import Account
from app.models.platform import Platform

logger = logging.getLogger(__name__)


class RealTimeMarketDataService:
    """Service for fetching and storing real-time market data"""

    def __init__(self):
        # Initialize clients with credentials from settings
        self.binance_client = BinanceFuturesClient(
            api_key=settings.BINANCE_API_KEY,
            api_secret=settings.BINANCE_API_SECRET
        )
        self.mt5_client = MT5Client(
            login=int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0,
            password=settings.BYBIT_MT5_PASSWORD,
            server=settings.BYBIT_MT5_SERVER
        )
        self.running = False
        self.update_task: Optional[asyncio.Task] = None

    def check_active_accounts(self, db: Session) -> Dict[str, bool]:
        """Check if there are any enabled accounts for each platform

        Returns:
            Dict with platform names as keys and boolean values indicating if any account is enabled
        """
        try:
            # Query for enabled accounts grouped by platform
            # Join Account with Platform to filter by platform_name
            binance_enabled = db.query(Account).join(Platform).filter(
                Platform.platform_name == "binance",
                Account.is_active.is_(True)
            ).first() is not None

            bybit_enabled = db.query(Account).join(Platform).filter(
                Platform.platform_name == "bybit",
                Account.is_active.is_(True)
            ).first() is not None

            return {
                "binance": binance_enabled,
                "bybit": bybit_enabled
            }
        except Exception as e:
            logger.error(f"Error checking active accounts: {e}")
            # Return False for both platforms on error to avoid unnecessary API calls
            return {"binance": False, "bybit": False}

    def is_mt5_market_open(self) -> bool:
        """Check if MT5 market is open (traditional finance trading hours)

        MT5 follows traditional finance market hours:
        - Trading: Monday 00:00 UTC to Friday 23:59 UTC
        - Closed: Saturday and Sunday

        Returns:
            True if market is open, False if closed
        """
        try:
            now = datetime.utcnow()
            weekday = now.weekday()  # 0=Monday, 6=Sunday

            # Market is closed on Saturday (5) and Sunday (6)
            if weekday >= 5:
                logger.debug(f"MT5 market is closed (weekend): {now.strftime('%A')}")
                return False

            # Market is open Monday-Friday
            return True
        except Exception as e:
            logger.error(f"Error checking MT5 market hours: {e}")
            # Return False on error to avoid unnecessary API calls
            return False

    async def start(self):
        """Start the real-time market data service"""
        if self.running:
            logger.warning("Market data service is already running")
            return

        self.running = True
        self.update_task = asyncio.create_task(self._update_loop())
        logger.info("Real-time market data service started")

    async def stop(self):
        """Stop the real-time market data service"""
        self.running = False
        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass

        await self.binance_client.close()
        self.mt5_client.disconnect()
        logger.info("Real-time market data service stopped")

    async def _update_loop(self):
        """Main update loop for fetching market data"""
        while self.running:
            try:
                await self.fetch_and_store_market_data()
                await asyncio.sleep(settings.MARKET_DATA_UPDATE_INTERVAL)
            except Exception as e:
                logger.error(f"Error in market data update loop: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    async def fetch_binance_ticker(self, symbol: str = "XAUUSDT") -> Optional[Dict[str, Any]]:
        """Fetch ticker data from Binance WebSocket stream (no REST call)"""
        if binance_ws.connected and binance_ws.bid and binance_ws.ask:
            return {
                "bid_price": binance_ws.bid,
                "ask_price": binance_ws.ask,
                "bid_qty": 0,
                "ask_qty": 0,
            }
        # Fallback to REST if WS not yet connected
        try:
            ticker = await self.binance_client.get_book_ticker(symbol)
            return {
                "bid_price": float(ticker.get("bidPrice", 0)),
                "ask_price": float(ticker.get("askPrice", 0)),
                "bid_qty": float(ticker.get("bidQty", 0)),
                "ask_qty": float(ticker.get("askQty", 0)),
            }
        except Exception as e:
            logger.error(f"Error fetching Binance ticker for {symbol}: {e}")
            return None

    async def fetch_bybit_ticker(self, symbol: str = "XAUUSD.s") -> Optional[Dict[str, Any]]:
        """Fetch ticker data from Bybit MT5 (using XAUUSD.s for gold)"""
        try:
            # MT5 operations are synchronous, run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            tick = await loop.run_in_executor(None, self.mt5_client.get_tick, symbol)

            if tick:
                return {
                    "bid_price": float(tick.get("bid", 0)),
                    "ask_price": float(tick.get("ask", 0)),
                    "bid_qty": 0,  # MT5 doesn't provide quantity in tick
                    "ask_qty": 0,
                    "last_price": float(tick.get("last", 0)),
                }
            return None
        except Exception as e:
            logger.error(f"Error fetching Bybit MT5 ticker for {symbol}: {e}")
            return None

    async def fetch_and_store_market_data(self, symbol: str = "XAUUSDT"):
        """Fetch market data from both exchanges and store in database

        Note: Binance uses XAUUSDT, Bybit MT5 uses XAUUSD.s for gold
        """
        # Create database session for account checking
        db = SessionLocal()
        try:
            # Check which platforms have enabled accounts
            active_accounts = self.check_active_accounts(db)

            # Check if MT5 market is open
            mt5_market_open = self.is_mt5_market_open()

            # Determine which APIs to call
            should_call_binance = active_accounts["binance"]
            should_call_bybit = active_accounts["bybit"] and mt5_market_open

            # Log skipped API calls
            if not should_call_binance:
                logger.debug("Skipping Binance API call: no enabled accounts")
            if active_accounts["bybit"] and not mt5_market_open:
                logger.debug("Skipping Bybit MT5 API call: market is closed")
            elif not active_accounts["bybit"]:
                logger.debug("Skipping Bybit MT5 API call: no enabled accounts")

            # If no APIs should be called, return early
            if not should_call_binance and not should_call_bybit:
                logger.debug("No API calls needed: no enabled accounts or market closed")
                return

            # Map symbols for different exchanges
            bybit_symbol = "XAUUSD.s" if symbol == "XAUUSDT" else symbol

            # Fetch data only from platforms with enabled accounts
            binance_data = None
            bybit_data = None

            if should_call_binance and should_call_bybit:
                # Fetch from both platforms concurrently
                binance_data, bybit_data = await asyncio.gather(
                    self.fetch_binance_ticker(symbol),
                    self.fetch_bybit_ticker(bybit_symbol),
                    return_exceptions=True
                )
            elif should_call_binance:
                # Fetch only from Binance
                binance_data = await self.fetch_binance_ticker(symbol)
            elif should_call_bybit:
                # Fetch only from Bybit
                bybit_data = await self.fetch_bybit_ticker(bybit_symbol)

            # Handle exceptions
            if isinstance(binance_data, Exception):
                logger.error(f"Binance fetch error: {binance_data}")
                binance_data = None

            if isinstance(bybit_data, Exception):
                logger.error(f"Bybit fetch error: {bybit_data}")
                bybit_data = None

            # Store data in database
            timestamp = datetime.utcnow()

            # Store Binance data
            if binance_data:
                binance_mid = (binance_data["bid_price"] + binance_data["ask_price"]) / 2
                binance_market_data = MarketData(
                    symbol=symbol,
                    platform="binance",
                    bid_price=binance_data["bid_price"],
                    ask_price=binance_data["ask_price"],
                    mid_price=binance_mid,
                    timestamp=timestamp
                )
                db.add(binance_market_data)

            # Store Bybit data
            if bybit_data:
                bybit_mid = (bybit_data["bid_price"] + bybit_data["ask_price"]) / 2
                bybit_market_data = MarketData(
                    symbol=symbol,
                    platform="bybit",
                    bid_price=bybit_data["bid_price"],
                    ask_price=bybit_data["ask_price"],
                    mid_price=bybit_mid,
                    timestamp=timestamp
                )
                db.add(bybit_market_data)

            # Calculate and store spread if both data available
            if binance_data and bybit_data:
                forward_spread = bybit_data["bid_price"] - binance_data["ask_price"]
                reverse_spread = binance_data["bid_price"] - bybit_data["ask_price"]

                spread_record = SpreadRecord(
                    symbol=symbol,
                    binance_bid=binance_data["bid_price"],
                    binance_ask=binance_data["ask_price"],
                    bybit_bid=bybit_data["bid_price"],
                    bybit_ask=bybit_data["ask_price"],
                    forward_spread=forward_spread,
                    reverse_spread=reverse_spread,
                    timestamp=timestamp
                )
                db.add(spread_record)

            db.commit()
            logger.debug(f"Market data stored successfully for {symbol}")

        except Exception as e:
            logger.error(f"Error storing market data: {e}")
            db.rollback()
        finally:
            db.close()

    async def get_latest_market_data(self, symbol: str = "XAUUSDT") -> Optional[Dict[str, Any]]:
        """Get the latest market data from database"""
        db = SessionLocal()
        try:
            # Get latest data from both platforms
            binance_data = db.query(MarketData).filter(
                MarketData.symbol == symbol,
                MarketData.platform == "binance"
            ).order_by(MarketData.timestamp.desc()).first()

            bybit_data = db.query(MarketData).filter(
                MarketData.symbol == symbol,
                MarketData.platform == "bybit"
            ).order_by(MarketData.timestamp.desc()).first()

            if not binance_data or not bybit_data:
                return None

            # Calculate spreads
            forward_spread = bybit_data.bid_price - binance_data.ask_price
            reverse_spread = binance_data.bid_price - bybit_data.ask_price

            return {
                "binance_bid": binance_data.bid_price,
                "binance_ask": binance_data.ask_price,
                "binance_mid": binance_data.mid_price,
                "bybit_bid": bybit_data.bid_price,
                "bybit_ask": bybit_data.ask_price,
                "bybit_mid": bybit_data.mid_price,
                "forward_spread": forward_spread,
                "reverse_spread": reverse_spread,
                "timestamp": binance_data.timestamp.isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting latest market data: {e}")
            return None
        finally:
            db.close()


# Global instance
market_data_service = RealTimeMarketDataService()
