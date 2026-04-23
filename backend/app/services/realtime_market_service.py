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
from app.core.platform import PlatformId
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
                Platform.platform_name == PlatformId.BINANCE.key,
                Account.is_active.is_(True)
            ).first() is not None

            bybit_enabled = db.query(Account).join(Platform).filter(
                Platform.platform_name == PlatformId.BYBIT.key,
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

    async def fetch_bybit_ticker(self, symbol: str = "XAUUSD+") -> Optional[Dict[str, Any]]:
        """Fetch ticker data from Bybit MT5 (using XAUUSD+ for gold)"""
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
        """Fetch spread via the shared market_data_service (MT5 HTTP bridge path)
        and persist a ``SpreadRecord`` row.

        Previously this method rolled its own Binance WS + local MT5 DLL calls,
        which no longer works on the Linux host (no DLL). We now delegate to
        ``market_service.market_data_service.get_current_spread`` — the same
        path used by the WebSocket broadcaster, which already routes through
        the MT5 HTTP bridge with multi-bridge failover. The broadcast stream
        and the persisted history thus share one data source.

        Scope: only the default (XAU) pair is persisted, matching existing
        semantics. Other active pairs are broadcast live but not written here.
        """
        bybit_symbol = "XAUUSD+"
        try:
            from app.services.hedging_pair_service import hedging_pair_service
            pair = hedging_pair_service.get_default_pair()
            if pair and pair.is_active:
                symbol = pair.symbol_a.symbol
                bybit_symbol = pair.symbol_b.symbol
            elif pair and not pair.is_active:
                logger.debug("Default XAU pair is disabled; skipping spread persistence")
                return
            else:
                bybit_symbol = "XAUUSD+" if symbol == "XAUUSDT" else symbol
        except Exception:
            bybit_symbol = "XAUUSD+" if symbol == "XAUUSDT" else symbol

        db = SessionLocal()
        try:
            active_accounts = self.check_active_accounts(db)
            mt5_market_open = self.is_mt5_market_open()
            should_call_binance = active_accounts["binance"]
            should_call_bybit = active_accounts["bybit"] and mt5_market_open

            if not should_call_binance and not should_call_bybit:
                logger.debug("No API calls needed: no enabled accounts or market closed")
                return
            if active_accounts["bybit"] and not mt5_market_open:
                logger.debug("MT5 market closed; skipping spread persistence")
                return
            if not (should_call_binance and should_call_bybit):
                logger.debug("Only one side enabled; spread cannot be computed, skipping")
                return

            from app.services.market_service import market_data_service as _mds
            try:
                spread_data = await _mds.get_current_spread(
                    binance_symbol=symbol,
                    bybit_symbol=bybit_symbol,
                    use_cache=False,
                )
            except Exception as fetch_err:
                logger.warning(f"Spread fetch failed for {symbol}/{bybit_symbol}: {fetch_err}")
                return

            bq = spread_data.binance_quote
            yq = spread_data.bybit_quote
            forward_spread = yq.bid_price - bq.bid_price
            reverse_spread = bq.ask_price - yq.ask_price
            timestamp = datetime.utcnow()

            db.add(SpreadRecord(
                symbol=symbol,
                binance_bid=bq.bid_price,
                binance_ask=bq.ask_price,
                bybit_bid=yq.bid_price,
                bybit_ask=yq.ask_price,
                forward_spread=forward_spread,
                reverse_spread=reverse_spread,
                timestamp=timestamp,
            ))

            from datetime import timedelta
            cutoff_time = timestamp - timedelta(days=2)
            deleted_count = db.query(SpreadRecord).filter(
                SpreadRecord.timestamp < cutoff_time
            ).delete(synchronize_session=False)
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old spread records (>48h)")

            db.commit()
            logger.debug(f"Spread data stored successfully for {symbol}")

        except Exception as e:
            logger.error(f"Error storing spread data: {e}")
            db.rollback()
        finally:
            db.close()

    async def get_latest_market_data(self, symbol: str = "XAUUSDT") -> Optional[Dict[str, Any]]:
        """Get the latest market data from database (spread records only)

        Note: Market data is no longer stored in database.
        This method now reads from spread_records table only.
        """
        db = SessionLocal()
        try:
            # Get latest spread record
            spread_record = db.query(SpreadRecord).filter(
                SpreadRecord.symbol == symbol
            ).order_by(SpreadRecord.timestamp.desc()).first()

            if not spread_record:
                return None

            # Calculate mid prices
            binance_mid = (spread_record.binance_bid + spread_record.binance_ask) / 2
            bybit_mid = (spread_record.bybit_bid + spread_record.bybit_ask) / 2

            return {
                "binance_bid": spread_record.binance_bid,
                "binance_ask": spread_record.binance_ask,
                "binance_mid": binance_mid,
                "bybit_bid": spread_record.bybit_bid,
                "bybit_ask": spread_record.bybit_ask,
                "bybit_mid": bybit_mid,
                "forward_spread": spread_record.forward_spread,
                "reverse_spread": spread_record.reverse_spread,
                "timestamp": spread_record.timestamp.isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting latest market data: {e}")
            return None
        finally:
            db.close()


# Global instance
market_data_service = RealTimeMarketDataService()
