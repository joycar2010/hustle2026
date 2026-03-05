"""Background tasks for account balance and risk metrics streaming"""
import asyncio
from datetime import datetime
from app.websocket.manager import manager
from app.core.database import get_db_context
from app.models.account import Account
from app.services.account_service import account_data_service
from sqlalchemy import select
import logging
import aiohttp

logger = logging.getLogger(__name__)


class AccountBalanceStreamer:
    """Background task for streaming account balance updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 10  # Update interval in seconds (every 10s)
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    def update_interval(self, new_interval: int):
        """Update streaming interval (5s - 60s)"""
        if 5 <= new_interval <= 60:
            self.interval = new_interval
            return True
        return False

    async def start(self):
        """Start the account balance streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())
        logger.info("Account balance streamer started (interval: 10s)")

    async def stop(self):
        """Stop the account balance streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Account balance streamer stopped")

    async def _stream_loop(self):
        """Main streaming loop"""
        while self.running:
            try:
                # Only broadcast if there are active connections
                if manager.get_connection_count() == 0:
                    await asyncio.sleep(self.interval)
                    continue

                # Fetch all active accounts from database
                async with get_db_context() as db:
                    result = await db.execute(
                        select(Account).where(Account.is_active == True)
                    )
                    active_accounts = result.scalars().all()

                    if not active_accounts:
                        await asyncio.sleep(self.interval)
                        continue

                    # Fetch aggregated account data
                    aggregated_data = await account_data_service.get_aggregated_account_data(
                        list(active_accounts)
                    )

                    # Broadcast to all connected clients
                    await manager.broadcast_account_balance(aggregated_data)
                    self.broadcast_count += 1
                    self.last_broadcast_time = datetime.now().isoformat()

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in account balance stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval)


class RiskMetricsStreamer:
    """Background task for streaming risk metrics updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 30  # Update interval in seconds (every 30s)
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    def update_interval(self, new_interval: int):
        """Update streaming interval (10s - 120s)"""
        if 10 <= new_interval <= 120:
            self.interval = new_interval
            return True
        return False

    async def start(self):
        """Start the risk metrics streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())
        logger.info("Risk metrics streamer started (interval: 30s)")

    async def stop(self):
        """Stop the risk metrics streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Risk metrics streamer stopped")

    async def _stream_loop(self):
        """Main streaming loop"""
        while self.running:
            try:
                # Only broadcast if there are active connections
                if manager.get_connection_count() == 0:
                    await asyncio.sleep(self.interval)
                    continue

                # Fetch all active accounts from database
                async with get_db_context() as db:
                    result = await db.execute(
                        select(Account).where(Account.is_active == True)
                    )
                    active_accounts = result.scalars().all()

                    if not active_accounts:
                        await asyncio.sleep(self.interval)
                        continue

                    # Fetch aggregated account data for risk calculation
                    aggregated_data = await account_data_service.get_aggregated_account_data(
                        list(active_accounts)
                    )

                    # Extract risk metrics from aggregated data
                    risk_data = {
                        "summary": aggregated_data.get("summary", {}),
                        "positions": aggregated_data.get("positions", []),
                        "timestamp": aggregated_data.get("timestamp"),
                    }

                    # Broadcast to all connected clients
                    await manager.broadcast_risk_metrics(risk_data)
                    self.broadcast_count += 1
                    self.last_broadcast_time = datetime.now().isoformat()

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in risk metrics stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval)


class MT5ConnectionStreamer:
    """Background task for streaming MT5 connection status"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 30  # Update interval in seconds (every 30s)
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    def update_interval(self, new_interval: int):
        """Update streaming interval (10s - 120s)"""
        if 10 <= new_interval <= 120:
            self.interval = new_interval
            return True
        return False

    async def start(self):
        """Start the MT5 connection streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())
        logger.info("MT5 connection streamer started (interval: 30s)")

    async def stop(self):
        """Stop the MT5 connection streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("MT5 connection streamer stopped")

    async def _stream_loop(self):
        """Main streaming loop"""
        while self.running:
            try:
                # Only broadcast if there are active connections
                if manager.get_connection_count() == 0:
                    await asyncio.sleep(self.interval)
                    continue

                # Check MT5 connection status
                mt5_status = await self._check_mt5_status()

                # Broadcast to all connected clients
                await manager.broadcast({
                    "type": "mt5_connection_status",
                    "data": mt5_status
                })
                self.broadcast_count += 1
                self.last_broadcast_time = datetime.now().isoformat()

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in MT5 connection stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval)

    async def _check_mt5_status(self):
        """Check MT5 connection status"""
        try:
            # Try to call the MT5 status endpoint
            async with aiohttp.ClientSession() as session:
                async with session.get('http://localhost:8000/api/v1/market/connection/status', timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        mt5_data = data.get('mt5', {})
                        return {
                            "healthy": mt5_data.get('healthy', False),
                            "connection_failures": mt5_data.get('connection_failures', 0),
                            "last_check": datetime.utcnow().isoformat(),
                            "status": "connected" if mt5_data.get('healthy') else "disconnected"
                        }
        except Exception as e:
            logger.error(f"Failed to check MT5 status: {e}")

        return {
            "healthy": False,
            "connection_failures": 0,
            "last_check": datetime.utcnow().isoformat(),
            "status": "unknown"
        }


# Global streamer instances
account_balance_streamer = AccountBalanceStreamer()
risk_metrics_streamer = RiskMetricsStreamer()
mt5_connection_streamer = MT5ConnectionStreamer()
