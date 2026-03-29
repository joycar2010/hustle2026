"""Binance Futures WebSocket client for real-time market data"""
import asyncio
import json
import time
import logging
from typing import Optional
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://fstream.binance.com/ws"


class BinanceWebSocketClient:
    """Subscribes to Binance Futures bookTicker stream and keeps latest bid/ask in memory."""

    def __init__(self, symbol: str = "xauusdt"):
        self.symbol = symbol.lower()
        self._bid: float = 0.0
        self._ask: float = 0.0
        self._timestamp: int = 0
        self._connected: bool = False
        self._task: Optional[asyncio.Task] = None

    @property
    def bid(self) -> float:
        return self._bid

    @property
    def ask(self) -> float:
        return self._ask

    @property
    def mid(self) -> float:
        if self._bid and self._ask:
            return (self._bid + self._ask) / 2
        return 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def timestamp(self) -> int:
        return self._timestamp

    def start(self):
        """Start the WebSocket listener as a background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        """Stop the WebSocket listener."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False

    async def _run(self):
        """Reconnect loop — keeps reconnecting on any error."""
        url = f"{BINANCE_WS_URL}/{self.symbol}@bookTicker"
        reconnect_count = 0
        while True:
            try:
                logger.info(f"Connecting to Binance WS: {url} (attempt #{reconnect_count + 1})")
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._connected = True
                    reconnect_count = 0  # Reset counter on successful connection
                    logger.info("Binance WS connected successfully")
                    async for raw in ws:
                        data = json.loads(raw)
                        # bookTicker payload: {"b": bid, "a": ask, ...}
                        b = data.get("b")
                        a = data.get("a")
                        if b and a:
                            self._bid = float(b)
                            self._ask = float(a)
                            self._timestamp = int(time.time() * 1000)
            except asyncio.CancelledError:
                logger.info("Binance WS task cancelled")
                break
            except (ConnectionClosed, OSError, Exception) as e:
                self._connected = False
                reconnect_count += 1
                logger.warning(f"Binance WS disconnected (attempt #{reconnect_count}): {e}, reconnecting in 5s")
                await asyncio.sleep(5)  # Increased from 2s to 5s to avoid aggressive reconnection


# Global instance
binance_ws = BinanceWebSocketClient(symbol="xauusdt")
