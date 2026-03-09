"""Background tasks for market data streaming with dynamic frequency adjustment"""
import asyncio
import logging
from datetime import datetime
from app.services.market_service import market_data_service
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class MarketDataStreamer:
    """Background task for streaming market data with dynamic frequency"""

    def __init__(self):
        self.running = False
        self.task = None
        self.base_interval = 1.0  # Base interval when no strategies active (1 time/sec)
        self.active_interval = 0.25  # Active interval when strategies running (4 times/sec)
        self.current_interval = self.base_interval
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0
        self.active_strategies_count = 0
        self.last_strategy_check_time = None

    def update_interval(self, new_interval: float):
        """Update streaming interval (0.1s - 10s)"""
        if 0.1 <= new_interval <= 10:
            self.base_interval = new_interval
            return True
        return False

    async def _get_active_strategies_count(self) -> int:
        """Get count of currently enabled strategies"""
        try:
            from app.core.database import get_db_context
            from app.models.strategy import StrategyConfig
            from sqlalchemy import select

            async with get_db_context() as db:
                result = await db.execute(
                    select(StrategyConfig).where(
                        StrategyConfig.is_enabled == True
                    )
                )
                configs = result.scalars().all()
                return len(configs)
        except Exception as e:
            logger.error(f"Failed to get active strategies count: {e}")
            return 0

    def get_stats(self) -> dict:
        """Get streaming statistics"""
        return {
            "running": self.running,
            "current_interval": self.current_interval,
            "base_interval": self.base_interval,
            "active_interval": self.active_interval,
            "frequency": f"{1/self.current_interval:.1f} times/sec",
            "broadcast_count": self.broadcast_count,
            "error_count": self.error_count,
            "last_broadcast_time": self.last_broadcast_time,
            "active_strategies_count": self.active_strategies_count,
            "last_strategy_check_time": self.last_strategy_check_time
        }

    async def start(self):
        """Start the market data streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())
        logger.info("Market data streamer started with dynamic frequency adjustment")

    async def stop(self):
        """Stop the market data streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Market data streamer stopped")

    async def _stream_loop(self):
        """Main streaming loop with hybrid dynamic frequency adjustment"""
        logger.info("Market data streamer: Hybrid dynamic frequency mode enabled")
        logger.info(f"  - Active (with strategies): {1/self.active_interval:.1f} times/sec")
        logger.info(f"  - Idle (no strategies): {1/self.base_interval:.1f} times/sec")

        check_interval_counter = 0
        cached_active_count = 0

        while self.running:
            try:
                # Check strategy status every 10 loops to reduce DB load
                if check_interval_counter % 10 == 0:
                    cached_active_count = await self._get_active_strategies_count()
                    self.active_strategies_count = cached_active_count
                    self.last_strategy_check_time = datetime.now().isoformat()

                check_interval_counter += 1

                # Determine push frequency based on connection count and strategy status
                connection_count = manager.get_connection_count()

                if connection_count > 0 and cached_active_count > 0:
                    # Has connections AND has active strategies: High frequency
                    self.current_interval = self.active_interval  # 0.25s (4 times/sec)
                else:
                    # No connections OR no active strategies: Low frequency
                    self.current_interval = self.base_interval  # 1s (1 time/sec)

                # Fetch current spread data
                spread_data = await market_data_service.get_current_spread(
                    use_cache=False  # Always fetch fresh data for streaming
                )

                # Only store history when strategies are active (reduce DB load)
                if cached_active_count > 0:
                    await market_data_service.store_spread_history(spread_data)

                # Broadcast to all connected clients
                await manager.broadcast_market_data(spread_data.model_dump())
                self.broadcast_count += 1
                self.last_broadcast_time = datetime.now().isoformat()

                # Log frequency changes (only on change)
                if check_interval_counter % 40 == 1:  # Log every 40 loops
                    freq = 1 / self.current_interval
                    logger.debug(
                        f"Market data: {freq:.1f} times/sec "
                        f"(strategies: {cached_active_count}, connections: {connection_count})"
                    )

                # Wait for next interval
                await asyncio.sleep(self.current_interval)

            except Exception as e:
                logger.error(f"Error in market data stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.current_interval)


# Global streamer instance
market_streamer = MarketDataStreamer()
