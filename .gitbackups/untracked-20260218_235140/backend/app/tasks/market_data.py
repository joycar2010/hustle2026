"""Background tasks for market data streaming"""
import asyncio
from app.services.market_service import market_data_service
from app.websocket.manager import manager


class MarketDataStreamer:
    """Background task for streaming market data"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 1  # Update interval in seconds

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

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                print(f"Error in market data stream: {str(e)}")
                await asyncio.sleep(self.interval)


# Global streamer instance
market_streamer = MarketDataStreamer()
