"""Background tasks for account balance and risk metrics streaming"""
import asyncio
from app.websocket.manager import manager
from app.database import get_db_context
from app.models.account import Account
from app.services.account_service import account_data_service
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)


class AccountBalanceStreamer:
    """Background task for streaming account balance updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 10  # Update interval in seconds (every 10s)

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

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in account balance stream: {str(e)}", exc_info=True)
                await asyncio.sleep(self.interval)


class RiskMetricsStreamer:
    """Background task for streaming risk metrics updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 30  # Update interval in seconds (every 30s)

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

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in risk metrics stream: {str(e)}", exc_info=True)
                await asyncio.sleep(self.interval)


# Global streamer instances
account_balance_streamer = AccountBalanceStreamer()
risk_metrics_streamer = RiskMetricsStreamer()
