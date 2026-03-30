"""Market data service for aggregating quotes from Binance and Bybit"""
import asyncio
import time
import logging
from typing import Dict, Any, Optional
import redis.asyncio as redis
import json
from app.core.config import settings
from app.services.binance_client import BinanceFuturesClient
from app.services.binance_ws_client import binance_ws
from app.services.mt5_client import MT5Client
from app.schemas.market import MarketQuote, SpreadData

logger = logging.getLogger(__name__)


class MarketDataService:
    """Service for fetching and aggregating market data"""

    def __init__(self):
        # Initialize clients with credentials from settings
        self.binance_client = BinanceFuturesClient(
            api_key=settings.BINANCE_API_KEY,
            api_secret=settings.BINANCE_API_SECRET
        )
        # MT5 client will be initialized lazily from database
        self.mt5_client: Optional[MT5Client] = None
        self._mt5_initialized = False
        self.redis_client: Optional[redis.Redis] = None
        self.cache_ttl = 1  # Cache TTL in seconds

    async def _ensure_mt5_client(self):
        """Ensure MT5 client is initialized from system service account"""
        if self._mt5_initialized and self.mt5_client:
            return

        try:
            # Import here to avoid circular dependency
            from app.core.database import async_session_maker
            from app.models.mt5_client import MT5Client as MT5ClientModel
            from sqlalchemy import select

            async with async_session_maker() as db:
                # Get system service MT5 client
                result = await db.execute(
                    select(MT5ClientModel)
                    .where(MT5ClientModel.is_system_service == True)
                    .where(MT5ClientModel.is_active == True)
                    .limit(1)
                )
                client = result.scalar_one_or_none()

                if client:
                    logger.info(f"Initializing MT5 client from system service account: {client.mt5_login}")
                    self.mt5_client = MT5Client(
                        login=int(client.mt5_login),
                        password=client.mt5_password,
                        server=client.mt5_server
                    )
                else:
                    # Fallback to environment variables
                    logger.warning("No system service account found, using environment variables")
                    self.mt5_client = MT5Client(
                        login=int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0,
                        password=settings.BYBIT_MT5_PASSWORD,
                        server=settings.BYBIT_MT5_SERVER
                    )

                self._mt5_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize MT5 client from database: {e}")
            # Fallback to environment variables
            self.mt5_client = MT5Client(
                login=int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0,
                password=settings.BYBIT_MT5_PASSWORD,
                server=settings.BYBIT_MT5_SERVER
            )
            self._mt5_initialized = True

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection"""
        if self.redis_client is None:
            self.redis_client = await redis.from_url(settings.REDIS_URL)
        return self.redis_client

    async def close(self):
        """Close all connections"""
        await self.binance_client.close()
        if self.mt5_client:
            self.mt5_client.disconnect()
        if self.redis_client:
            await self.redis_client.close()

    async def get_binance_quote(self, symbol: str = "XAUUSDT") -> MarketQuote:
        """Get Binance market quote from WebSocket stream (real-time)"""
        if binance_ws.connected and binance_ws.bid and binance_ws.ask:
            return MarketQuote(
                symbol=symbol,
                bid_price=binance_ws.bid,
                bid_qty=0,
                ask_price=binance_ws.ask,
                ask_qty=0,
                timestamp=binance_ws.timestamp or int(time.time() * 1000),
            )
        # Fallback: WebSocket not yet connected, use cached data or fail gracefully
        logger.warning(f"Binance WebSocket not connected (connected={binance_ws.connected}, bid={binance_ws.bid}, ask={binance_ws.ask})")
        raise Exception(f"Binance WebSocket not available, please wait for connection")

    async def get_bybit_quote(
        self,
        symbol: str = "XAUUSDT",
        category: str = "linear",
    ) -> MarketQuote:
        """Get Bybit market quote via MT5

        Note: Bybit MT5 uses XAUUSD+ for gold
        """
        try:
            # Map symbols for Bybit MT5
            mt5_symbol = "XAUUSD+" if symbol == "XAUUSDT" else symbol

            # MT5 operations are synchronous, run in executor
            loop = asyncio.get_event_loop()
            tick = await loop.run_in_executor(None, self.mt5_client.get_tick, mt5_symbol)

            if not tick:
                raise Exception(f"No ticker data for {mt5_symbol}")

            return MarketQuote(
                symbol=symbol,
                bid_price=float(tick["bid"]),
                bid_qty=0,  # MT5 doesn't provide quantity
                ask_price=float(tick["ask"]),
                ask_qty=0,
                timestamp=int(time.time() * 1000),
            )
        except Exception as e:
            raise Exception(f"Failed to fetch Bybit quote: {str(e)}")

    def calculate_spread(
        self,
        binance_quote: MarketQuote,
        bybit_quote: MarketQuote,
    ) -> SpreadData:
        """Calculate arbitrage spreads

        新公式：
        正向开仓 (binance做多点差): bybit_bid - binance_bid
        正向平仓 (binance平仓点差): bybit_ask - binance_ask
        反向开仓 (bybit做多点差): binance_ask - bybit_ask
        反向平仓 (bybit平仓点差): binance_bid - bybit_bid
        """
        # 正向套利
        forward_entry_spread = bybit_quote.bid_price - binance_quote.bid_price  # 正向开仓
        forward_exit_spread = bybit_quote.ask_price - binance_quote.ask_price   # 正向平仓

        # 反向套利
        reverse_entry_spread = binance_quote.ask_price - bybit_quote.ask_price  # 反向开仓
        reverse_exit_spread = binance_quote.bid_price - bybit_quote.bid_price   # 反向平仓

        return SpreadData(
            binance_quote=binance_quote,
            bybit_quote=bybit_quote,
            forward_entry_spread=forward_entry_spread,
            forward_exit_spread=forward_exit_spread,
            reverse_entry_spread=reverse_entry_spread,
            reverse_exit_spread=reverse_exit_spread,
            timestamp=int(time.time() * 1000),
        )

    async def get_current_spread(
        self,
        binance_symbol: str = "XAUUSDT",
        bybit_symbol: str = "XAUUSDT",  # Keep as XAUUSDT, will be mapped to XAUUSD+ internally
        bybit_category: str = "linear",  # Not used for MT5
        use_cache: bool = True,
    ) -> SpreadData:
        """Get current spread data with caching

        Note: For gold trading, Bybit MT5 uses XAUUSD+
        """
        cache_key = f"spread:{binance_symbol}:{bybit_symbol}"

        # Try to get from cache
        if use_cache:
            redis_client = await self._get_redis()
            cached_data = await redis_client.get(cache_key)

            if cached_data:
                data = json.loads(cached_data)
                return SpreadData(**data)

        # Fetch fresh data from both exchanges concurrently
        binance_quote, bybit_quote = await asyncio.gather(
            self.get_binance_quote(binance_symbol),
            self.get_bybit_quote(bybit_symbol, bybit_category),
        )

        # Calculate spread
        spread_data = self.calculate_spread(binance_quote, bybit_quote)

        # Cache the result
        if use_cache:
            redis_client = await self._get_redis()
            await redis_client.setex(
                cache_key,
                self.cache_ttl,
                spread_data.model_dump_json(),
            )

        return spread_data

    async def get_spread_history(
        self,
        limit: int = 100,
        binance_symbol: str = "XAUUSDT",
        bybit_symbol: str = "XAUUSDT",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list:
        """Get historical spread data from PostgreSQL database

        Args:
            limit: Maximum number of records to return (ignored if time filters are provided)
            binance_symbol: Binance trading symbol
            bybit_symbol: Bybit trading symbol
            start_time: Start time in ISO format (optional)
            end_time: End time in ISO format (optional)
        """
        from app.core.database import AsyncSessionLocal
        from app.models.market_data import SpreadRecord
        from sqlalchemy import select
        from datetime import datetime

        async with AsyncSessionLocal() as session:
            query = select(SpreadRecord).where(SpreadRecord.symbol == binance_symbol)

            # Add time filters if provided
            if start_time:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                # Remove timezone info to match database column (TIMESTAMP WITHOUT TIME ZONE)
                start_dt = start_dt.replace(tzinfo=None)
                query = query.where(SpreadRecord.timestamp >= start_dt)
            if end_time:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                # Remove timezone info to match database column (TIMESTAMP WITHOUT TIME ZONE)
                end_dt = end_dt.replace(tzinfo=None)
                query = query.where(SpreadRecord.timestamp <= end_dt)

            # Order by timestamp descending
            query = query.order_by(SpreadRecord.timestamp.desc())

            # Only apply limit if no time filters are provided
            # When time filters are provided, return all matching records
            if not start_time and not end_time:
                query = query.limit(limit)

            result = await session.execute(query)
            records = result.scalars().all()

            # Transform to response format
            return [
                {
                    "id": str(record.id),
                    "timestamp": record.timestamp.isoformat(),
                    "binance_quote": {
                        "bid": record.binance_bid,
                        "ask": record.binance_ask,
                    },
                    "bybit_quote": {
                        "bid": record.bybit_bid,
                        "ask": record.bybit_ask,
                    },
                    "forward_spread": record.forward_spread,
                    "reverse_spread": record.reverse_spread,
                }
                for record in records
            ]

    async def store_spread_history(
        self,
        spread_data: SpreadData,
        binance_symbol: str = "XAUUSDT",
        bybit_symbol: str = "XAUUSDT",
    ):
        """Store spread data in history (sorted set)"""
        redis_client = await self._get_redis()
        history_key = f"spread_history:{binance_symbol}:{bybit_symbol}"

        # Add to sorted set with timestamp as score
        await redis_client.zadd(
            history_key,
            {spread_data.model_dump_json(): spread_data.timestamp},
        )

        # Keep only last 1000 entries
        await redis_client.zremrangebyrank(history_key, 0, -1001)

        # Set expiry on the key (24 hours)
        await redis_client.expire(history_key, 86400)

    async def sync_server_time(self) -> Dict[str, int]:
        """Synchronize server time with Binance"""
        try:
            binance_time_data = await self.binance_client.get_server_time()
            binance_time = binance_time_data["serverTime"]
            local_time = int(time.time() * 1000)
            offset = binance_time - local_time

            # Store offset in Redis
            redis_client = await self._get_redis()
            await redis_client.set("time_offset", offset)

            return {
                "binance_time": binance_time,
                "local_time": local_time,
                "offset": offset,
            }
        except Exception as e:
            raise Exception(f"Failed to sync server time: {str(e)}")

    async def get_time_offset(self) -> int:
        """Get stored time offset"""
        redis_client = await self._get_redis()
        offset = await redis_client.get("time_offset")
        return int(offset) if offset else 0

    async def get_order_book(self) -> Dict[str, Any]:
        """
        Get order book data from both Binance and Bybit

        Returns:
            Dict with binance and bybit order book data
        """
        try:
            # Get Binance order book via API
            binance_book = await self._get_binance_order_book("XAUUSDT")

            # Get Bybit order book via API (MT5 doesn't support order book)
            bybit_book = await self._get_bybit_order_book("XAUUSDT")

            return {
                "binance": binance_book or {},
                "bybit": bybit_book or {},
                "timestamp": int(time.time() * 1000)
            }
        except Exception as e:
            logger.error(f"Failed to get order book: {e}")
            return {
                "binance": {},
                "bybit": {},
                "timestamp": int(time.time() * 1000),
                "error": str(e)
            }

    async def _get_binance_order_book(self, symbol: str = "XAUUSDT") -> Optional[Dict[str, Any]]:
        """
        Get Binance order book ticker (best bid/ask with volumes)

        Args:
            symbol: Trading symbol

        Returns:
            Dict with bid_price, bid_volume, ask_price, ask_volume
        """
        try:
            url = f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={symbol}"
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            'symbol': symbol,
                            'bid_price': round(float(data["bidPrice"]), 3),
                            'bid_volume': round(float(data["bidQty"]), 2),
                            'ask_price': round(float(data["askPrice"]), 3),
                            'ask_volume': round(float(data["askQty"]), 2),
                            'timestamp': int(time.time() * 1000)
                        }
                    else:
                        logger.error(f"Binance API error: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to get Binance order book: {e}")
            return None

    async def _get_bybit_order_book(self, symbol: str = "XAUUSDT") -> Optional[Dict[str, Any]]:
        """
        Get Bybit order book ticker (best bid/ask with volumes)

        Args:
            symbol: Trading symbol

        Returns:
            Dict with bid_price, bid_volume, ask_price, ask_volume
        """
        try:
            url = f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}&limit=1"
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("retCode") == 0 and data.get("result"):
                            result = data["result"]
                            bids = result.get("b", [])
                            asks = result.get("a", [])

                            if bids and asks:
                                # bids and asks are arrays of [price, size]
                                return {
                                    'symbol': symbol,
                                    'bid_price': round(float(bids[0][0]), 3),
                                    'bid_volume': round(float(bids[0][1]), 2),
                                    'ask_price': round(float(asks[0][0]), 3),
                                    'ask_volume': round(float(asks[0][1]), 2),
                                    'timestamp': int(time.time() * 1000)
                                }
                        logger.error(f"Bybit API returned error: {data}")
                        return None
                    else:
                        logger.error(f"Bybit API error: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to get Bybit order book: {e}")
            return None


# Global instance
market_data_service = MarketDataService()
