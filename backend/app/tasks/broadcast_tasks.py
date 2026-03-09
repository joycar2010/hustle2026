"""Background tasks for account balance and risk metrics streaming"""
import asyncio
from datetime import datetime
from uuid import UUID
from app.websocket.manager import manager
from app.core.database import get_db_context
from app.core.config import settings
from app.models.account import Account
from app.models.risk_settings import RiskSettings
from app.services.account_service import account_data_service
from app.services.risk_alert_service import RiskAlertService
from app.services.spread_alert_service import SpreadAlertService
from app.services.market_service import market_data_service
from sqlalchemy import select
import logging
import aiohttp

logger = logging.getLogger(__name__)


class AccountBalanceStreamer:
    """Background task for streaming account balance updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = settings.MARKET_DATA_UPDATE_INTERVAL  # Update interval in seconds (1s)
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
        logger.info(f"Account balance streamer started (interval: {self.interval}s)")

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
        logger.info("[BROADCAST] RiskMetricsStreamer _stream_loop started")
        while self.running:
            try:
                logger.info("[BROADCAST] RiskMetricsStreamer loop iteration starting")
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

                    # Broadcast to all connected clients (only if there are connections)
                    connection_count = manager.get_connection_count()
                    if connection_count > 0:
                        await manager.broadcast_risk_metrics(risk_data)
                        self.broadcast_count += 1
                        self.last_broadcast_time = datetime.now().isoformat()

                    # Always check risk alerts (independent of WebSocket connections)
                    logger.info(f"[BROADCAST] Calling _check_risk_alerts, active_accounts={len(active_accounts)}")
                    await self._check_risk_alerts(db, active_accounts, aggregated_data)

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in risk metrics stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval)

    async def _check_risk_alerts(self, db, active_accounts, aggregated_data):
        """Check risk alerts and send Feishu notifications"""
        logger.info(f"[BROADCAST] _check_risk_alerts called, active_accounts数量={len(active_accounts)}")
        try:
            # Group accounts by user
            user_accounts = {}
            for account in active_accounts:
                user_id = str(account.user_id)
                if user_id not in user_accounts:
                    user_accounts[user_id] = []
                user_accounts[user_id].append(account)

            # Check alerts for each user
            for user_id, accounts in user_accounts.items():
                try:
                    # Get user's risk settings
                    result = await db.execute(
                        select(RiskSettings).where(RiskSettings.user_id == UUID(user_id))
                    )
                    risk_settings = result.scalar_one_or_none()

                    if not risk_settings:
                        continue

                    # Initialize risk alert service
                    risk_alert_service = RiskAlertService(db)

                    # Get account data for this user
                    summary = aggregated_data.get("summary", {})

                    # Check Binance net asset
                    if risk_settings.binance_net_asset:
                        # Find Binance account in the aggregated data
                        binance_account = next(
                            (acc for acc in aggregated_data.get("accounts", [])
                             if acc.get("platform_id") == "binance"),
                            None
                        )
                        if binance_account:
                            binance_asset = binance_account["balance"]["net_assets"]
                            if binance_asset < risk_settings.binance_net_asset:
                                await risk_alert_service.check_binance_net_asset(
                                    user_id=user_id,
                                    current_asset=binance_asset,
                                    threshold=risk_settings.binance_net_asset,
                                    is_below=True
                                )

                    # Check Bybit net asset
                    if risk_settings.bybit_mt5_net_asset:
                        # Find Bybit/MT5 account in the aggregated data
                        bybit_account = next(
                            (acc for acc in aggregated_data.get("accounts", [])
                             if acc.get("platform_id") in ["bybit", "mt5"]),
                            None
                        )
                        if bybit_account:
                            bybit_asset = bybit_account["balance"]["net_assets"]
                            if bybit_asset < risk_settings.bybit_mt5_net_asset:
                                await risk_alert_service.check_bybit_net_asset(
                                    user_id=user_id,
                                    current_asset=bybit_asset,
                                    threshold=risk_settings.bybit_mt5_net_asset,
                                    is_below=True
                                )

                    # Check total net asset
                    if risk_settings.total_net_asset:
                        # Use net_assets from summary (this is the correct key)
                        total_asset = summary.get("net_assets", 0)
                        logger.info(f"[BROADCAST] Checking total net_assets: user_id={user_id}, total={total_asset}, threshold={risk_settings.total_net_asset}")
                        if total_asset < risk_settings.total_net_asset:
                            logger.info(f"[BROADCAST] Total asset below threshold, triggering alert")
                            await risk_alert_service.check_total_net_asset(
                                user_id=user_id,
                                current_asset=total_asset,
                                threshold=risk_settings.total_net_asset,
                                is_below=True
                            )

                    # Check Binance liquidation price
                    if risk_settings.binance_liquidation_price:
                        binance_liq = summary.get("binance_liquidation_price")
                        binance_price = summary.get("binance_current_price")
                        if binance_liq and binance_price:
                            distance = abs(binance_price - binance_liq)
                            # Alert if distance is less than 10% of liquidation price
                            if distance < binance_liq * 0.1:
                                status = "⚠️ 接近安全线" if distance < binance_liq * 0.05 else "注意价格变化"
                                await risk_alert_service.check_binance_liquidation(
                                    user_id=user_id,
                                    current_price=binance_price,
                                    liquidation_price=binance_liq,
                                    distance=distance,
                                    status=status
                                )

                    # Check Bybit liquidation price
                    if risk_settings.bybit_mt5_liquidation_price:
                        bybit_liq = summary.get("bybit_liquidation_price")
                        bybit_price = summary.get("bybit_current_price")
                        if bybit_liq and bybit_price:
                            distance = abs(bybit_price - bybit_liq)
                            # Alert if distance is less than 10% of liquidation price
                            if distance < bybit_liq * 0.1:
                                status = "⚠️ 接近安全线" if distance < bybit_liq * 0.05 else "注意价格变化"
                                await risk_alert_service.check_bybit_liquidation(
                                    user_id=user_id,
                                    current_price=bybit_price,
                                    liquidation_price=bybit_liq,
                                    distance=distance,
                                    status=status
                                )

                    # Check spread alerts (forward/reverse open/close)
                    try:
                        # Get current market data
                        market_data = await market_data_service.get_current_spread()

                        # Prepare alert settings
                        alert_settings = {
                            'forwardOpenPrice': risk_settings.forward_open_price,
                            'forwardClosePrice': risk_settings.forward_close_price,
                            'reverseOpenPrice': risk_settings.reverse_open_price,
                            'reverseClosePrice': risk_settings.reverse_close_price,
                        }

                        # Prepare market data dict
                        market_dict = {
                            'forward_spread': market_data.forward_entry_spread if hasattr(market_data, 'forward_entry_spread') else None,
                            'reverse_spread': market_data.reverse_entry_spread if hasattr(market_data, 'reverse_entry_spread') else None,
                        }

                        # Check spread alerts
                        spread_alert_service = SpreadAlertService()
                        await spread_alert_service.check_and_send_spread_alerts(
                            db=db,
                            user_id=user_id,
                            market_data=market_dict,
                            alert_settings=alert_settings
                        )
                    except Exception as e:
                        logger.error(f"Error checking spread alerts for user {user_id}: {e}")

                except Exception as e:
                    logger.error(f"Error checking risk alerts for user {user_id}: {e}")

        except Exception as e:
            logger.error(f"Error in _check_risk_alerts: {e}")


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

                # Check MT5 lag alerts for all users
                if mt5_status.get("connection_failures", 0) > 0:
                    await self._check_mt5_alerts(mt5_status)

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in MT5 connection stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval)

    async def _check_mt5_alerts(self, mt5_status):
        """Check MT5 lag alerts and send Feishu notifications"""
        try:
            async with get_db_context() as db:
                # Get all users with risk settings
                result = await db.execute(
                    select(RiskSettings).where(RiskSettings.mt5_lag_count.isnot(None))
                )
                risk_settings_list = result.scalars().all()

                for risk_settings in risk_settings_list:
                    try:
                        failure_count = mt5_status.get("connection_failures", 0)

                        # Check if failure count exceeds threshold
                        if failure_count >= risk_settings.mt5_lag_count:
                            risk_alert_service = RiskAlertService(db)
                            await risk_alert_service.check_mt5_lag(
                                user_id=str(risk_settings.user_id),
                                failure_count=failure_count,
                                last_response_time=mt5_status.get("last_check", "未知")
                            )
                    except Exception as e:
                        logger.error(f"Error checking MT5 alert for user {risk_settings.user_id}: {e}")

        except Exception as e:
            logger.error(f"Error in _check_mt5_alerts: {e}")

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
