"""Background tasks for market data streaming"""
import asyncio
from datetime import datetime
from app.services.market_service import market_data_service
from app.websocket.manager import manager


class MarketDataStreamer:
    """Background task for streaming market data"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 1  # Update interval in seconds
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    def update_interval(self, new_interval: float):
        """Update streaming interval (0.1s - 10s)"""
        if 0.1 <= new_interval <= 10:
            self.interval = new_interval
            return True
        return False

    async def start(self):
        """Start the market data streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())

    async def stop(self):
        """Stop the market data streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _stream_loop(self):
        """Main streaming loop"""
        print("Market data streamer started")
        while self.running:
            try:
                # Fetch current spread data
                spread_data = await market_data_service.get_current_spread(
                    use_cache=False  # Always fetch fresh data for streaming
                )

                # Store in history
                await market_data_service.store_spread_history(spread_data)

                # Broadcast to all connected clients
                await manager.broadcast_market_data(spread_data.model_dump())
                self.broadcast_count += 1
                self.last_broadcast_time = datetime.now().isoformat()
                print(f"Broadcasted market data: {spread_data.binance_quote.bid_price}")

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                print(f"Error in market data stream: {str(e)}")
                import traceback
                traceback.print_exc()
                self.error_count += 1
                await asyncio.sleep(self.interval)


# Global streamer instance
market_streamer = MarketDataStreamer()
