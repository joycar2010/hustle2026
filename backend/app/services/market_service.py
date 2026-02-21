"""Market data service for aggregating quotes from Binance and Bybit"""
import asyncio
import time
from typing import Dict, Any, Optional
import redis.asyncio as redis
import json
from app.core.config import settings
from app.services.binance_client import BinanceFuturesClient
from app.services.binance_ws_client import binance_ws
from app.services.mt5_client import MT5Client
from app.schemas.market import MarketQuote, SpreadData


class MarketDataService:
    """Service for fetching and aggregating market data"""

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
        self.redis_client: Optional[redis.Redis] = None
        self.cache_ttl = 1  # Cache TTL in seconds

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection"""
        if self.redis_client is None:
            self.redis_client = await redis.from_url(settings.REDIS_URL)
        return self.redis_client

    async def close(self):
        """Close all connections"""
        await self.binance_client.close()
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
        # Fallback: WebSocket not yet connected, use REST once
        try:
            data = await self.binance_client.get_book_ticker(symbol)
            return MarketQuote(
                symbol=symbol,
                bid_price=float(data["bidPrice"]),
                bid_qty=float(data["bidQty"]),
                ask_price=float(data["askPrice"]),
                ask_qty=float(data["askQty"]),
                timestamp=int(time.time() * 1000),
            )
        except Exception as e:
            raise Exception(f"Failed to fetch Binance quote: {str(e)}")

    async def get_bybit_quote(
        self,
        symbol: str = "XAUUSDT",
        category: str = "linear",
    ) -> MarketQuote:
        """Get Bybit market quote via MT5

        Note: Bybit MT5 uses XAUUSD.s for gold
        """
        try:
            # Map symbols for Bybit MT5
            mt5_symbol = "XAUUSD.s" if symbol == "XAUUSDT" else symbol

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

        Forward arbitrage (long Binance):
        - Entry: Sell Bybit (bybit_ask) - Buy Binance (binance_bid)
        - Exit: Sell Binance (binance_ask) - Buy Bybit (bybit_bid)

        Reverse arbitrage (long Bybit):
        - Entry: Sell Binance (binance_ask) - Buy Bybit (bybit_bid)
        - Exit: Sell Bybit (bybit_ask) - Buy Binance (binance_bid)
        """
        forward_entry_spread = bybit_quote.ask_price - binance_quote.bid_price
        forward_exit_spread = binance_quote.ask_price - bybit_quote.bid_price

        reverse_entry_spread = binance_quote.ask_price - bybit_quote.bid_price
        reverse_exit_spread = bybit_quote.ask_price - binance_quote.bid_price

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
        bybit_symbol: str = "XAUUSDT",  # Keep as XAUUSDT, will be mapped to XAUUSD.s internally
        bybit_category: str = "linear",  # Not used for MT5
        use_cache: bool = True,
    ) -> SpreadData:
        """Get current spread data with caching

        Note: For gold trading, Bybit MT5 uses XAUUSD.s
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


# Global instance
market_data_service = MarketDataService()
