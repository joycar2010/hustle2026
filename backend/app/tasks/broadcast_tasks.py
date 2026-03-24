"""Background tasks for account balance and risk metrics streaming"""
import asyncio
from typing import Dict
from datetime import datetime
from uuid import UUID
from contextlib import asynccontextmanager
from app.websocket.manager import manager
from app.core.database import get_db_context, AsyncSessionLocal
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

# Global semaphore to limit concurrent database connections (max 10 simultaneous)
# Increased from 5 to allow more concurrency while still preventing pool exhaustion
STREAM_SEMAPHORE = asyncio.Semaphore(10)

@asynccontextmanager
async def get_db_session(timeout: float = 5.0):
    """
    Context manager for database sessions with timeout control and semaphore
    Ensures automatic connection cleanup and limits concurrent connections
    """
    # Acquire semaphore with timeout
    try:
        await asyncio.wait_for(STREAM_SEMAPHORE.acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"Semaphore acquisition timeout after {timeout}s")
        raise

    session = None
    try:
        session = AsyncSessionLocal()
        yield session
    except Exception as e:
        logger.error(f"Database session error: {e}")
        raise
    finally:
        if session:
            await session.close()
        STREAM_SEMAPHORE.release()  # Always release semaphore


class AccountBalanceStreamer:
    """Background task for streaming account balance updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 30  # Update interval: 30 seconds (increased to reduce API calls)
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0
        self._immediate_refresh = asyncio.Event()  # Set to trigger an out-of-cycle broadcast

    def update_interval(self, new_interval: int):
        """Update streaming interval (5s - 60s)"""
        if 5 <= new_interval <= 60:
            self.interval = new_interval
            return True
        return False

    def trigger_immediate_refresh(self):
        """Signal the stream loop to broadcast immediately, skipping the remaining wait interval."""
        try:
            self._immediate_refresh.set()
        except Exception:
            pass

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

    async def _wait_for_event(self):
        """Wait until immediate refresh is signalled."""
        await self._immediate_refresh.wait()

    async def _stream_loop(self):
        """Main streaming loop with connection pool optimization"""
        while self.running:
            try:
                # Wait for either the normal interval OR an immediate-refresh signal
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._wait_for_event()),
                        timeout=self.interval
                    )
                except asyncio.TimeoutError:
                    pass  # Normal interval elapsed

                self._immediate_refresh.clear()

                # Only broadcast if there are active connections
                if manager.get_connection_count() == 0:
                    continue

                # Fetch all active accounts from database with timeout control
                # IMPORTANT: Close session immediately after getting account list
                active_accounts = None
                async with get_db_session(timeout=5.0) as db:
                    # Query with timeout
                    result = await asyncio.wait_for(
                        db.execute(select(Account).where(Account.is_active == True)),
                        timeout=3.0
                    )
                    active_accounts = result.scalars().all()
                # Session is now closed, safe to make external API calls

                if not active_accounts:
                    continue

                # Fetch aggregated account data (makes external API calls, no DB connection held)
                aggregated_data = await account_data_service.get_aggregated_account_data(
                    list(active_accounts)
                )

                # 将 Binance 持仓同步到 PositionStreamer（替代其 REST 轮询，零额外API调用）
                try:
                    binance_long_xau = 0.0
                    binance_short_xau = 0.0
                    for pos in aggregated_data.get("positions", []):
                        if pos.get("is_mt5_account"):
                            continue
                        if pos.get("platform_id") != 1:  # 1 = Binance
                            continue
                        side = pos.get("side", "").upper()
                        size = round(float(pos.get("size", 0)), 3)
                        # AccountPosition.side = "Buy"/"Sell" (Binance REST) 或 "LONG"/"SHORT"
                        if side in ("LONG", "BUY"):
                            binance_long_xau += size
                        elif side in ("SHORT", "SELL"):
                            binance_short_xau += size
                    position_streamer.set_binance_positions(
                        round(binance_long_xau, 3),
                        round(binance_short_xau, 3),
                    )
                except Exception as _pe:
                    logger.debug(f"[AccountBalanceStreamer] PositionStreamer sync error: {_pe}")

                # Broadcast to all connected clients
                await manager.broadcast_account_balance(aggregated_data)
                self.broadcast_count += 1
                self.last_broadcast_time = datetime.now().isoformat()

                # Check spread alerts every 20 seconds
                await self._check_spread_alerts(active_accounts)

            except asyncio.TimeoutError:
                logger.error(f"Account balance stream timeout, extending retry interval")
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)  # Extended retry on timeout
            except Exception as e:
                logger.error(f"Error in account balance stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)  # Extended retry on error

    async def _check_spread_alerts(self, active_accounts):
        """Check spread alerts for all active users (every 20 seconds)"""
        try:
            # Group accounts by user
            user_accounts = {}
            user_ids = []
            for account in active_accounts:
                user_id = str(account.user_id)
                if user_id not in user_accounts:
                    user_accounts[user_id] = []
                    user_ids.append(UUID(user_id))
                user_accounts[user_id].append(account)

            if not user_ids:
                return

            # Open a new database session for risk settings query
            async with get_db_session(timeout=5.0) as db:
                # Batch query: Get all risk settings for active users
                result = await asyncio.wait_for(
                    db.execute(
                        select(RiskSettings).where(RiskSettings.user_id.in_(user_ids))
                    ),
                    timeout=3.0
                )
                risk_settings_list = result.scalars().all()

                # Create a mapping of user_id -> risk_settings
                risk_settings_map = {str(rs.user_id): rs for rs in risk_settings_list}

                # Get current market data once for all users
                market_data = await market_data_service.get_current_spread()

                # Check spread alerts for each user
                for user_id, accounts in user_accounts.items():
                    try:
                        risk_settings = risk_settings_map.get(user_id)
                        if not risk_settings:
                            continue

                        # Prepare alert settings
                        alert_settings = {
                            'forwardOpenPrice': risk_settings.forward_open_price,
                            'forwardClosePrice': risk_settings.forward_close_price,
                            'reverseOpenPrice': risk_settings.reverse_open_price,
                            'reverseClosePrice': risk_settings.reverse_close_price,
                        }

                        # Skip if no spread alerts configured
                        if not any(alert_settings.values()):
                            continue

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

        except asyncio.TimeoutError:
            logger.error(f"Timeout in _check_spread_alerts")
        except Exception as e:
            logger.error(f"Error in _check_spread_alerts: {e}")


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
        """Main streaming loop with connection pool optimization"""
        logger.info("[BROADCAST] RiskMetricsStreamer _stream_loop started")
        while self.running:
            try:
                logger.info("[BROADCAST] RiskMetricsStreamer loop iteration starting")

                # Fetch all active accounts from database with timeout control
                # IMPORTANT: Close session immediately after getting account list
                active_accounts = None
                async with get_db_session(timeout=5.0) as db:
                    # Query with timeout
                    result = await asyncio.wait_for(
                        db.execute(select(Account).where(Account.is_active == True)),
                        timeout=3.0
                    )
                    active_accounts = result.scalars().all()
                # Session is now closed, safe to make external API calls

                if not active_accounts:
                    await asyncio.sleep(self.interval)
                    continue

                # Fetch aggregated account data for risk calculation (makes external API calls, no DB connection held)
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

                # Always check risk alerts (opens a new DB session internally)
                logger.info(f"[BROADCAST] Calling _check_risk_alerts, active_accounts={len(active_accounts)}")
                await self._check_risk_alerts(active_accounts, aggregated_data)

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except asyncio.TimeoutError:
                logger.error(f"Risk metrics stream timeout, extending retry interval")
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)  # Extended retry on timeout
            except Exception as e:
                logger.error(f"Error in risk metrics stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)  # Extended retry on error

    async def _check_risk_alerts(self, active_accounts, aggregated_data):
        """Check risk alerts and send Feishu notifications with batch queries"""
        logger.info(f"[BROADCAST] _check_risk_alerts called, active_accounts数量={len(active_accounts)}")
        try:
            # Group accounts by user
            user_accounts = {}
            user_ids = []
            for account in active_accounts:
                user_id = str(account.user_id)
                if user_id not in user_accounts:
                    user_accounts[user_id] = []
                    user_ids.append(UUID(user_id))
                user_accounts[user_id].append(account)

            if not user_ids:
                return

            # Open a new database session for risk settings query
            async with get_db_session(timeout=5.0) as db:
                # Batch query: Get all risk settings for active users in one query
                result = await asyncio.wait_for(
                    db.execute(
                        select(RiskSettings).where(RiskSettings.user_id.in_(user_ids))
                    ),
                    timeout=3.0
                )
                risk_settings_list = result.scalars().all()

                # Create a mapping of user_id -> risk_settings for fast lookup
                risk_settings_map = {str(rs.user_id): rs for rs in risk_settings_list}

                # Check alerts for each user (now using pre-fetched data)
                for user_id, accounts in user_accounts.items():
                    try:
                        risk_settings = risk_settings_map.get(user_id)
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
                                # Use user-configured distance percentage (stored in binance_liquidation_price field)
                                # Field stores percentage value (e.g., 10 means 10%)
                                distance_threshold_pct = risk_settings.binance_liquidation_price / 100.0
                                distance_threshold = binance_liq * distance_threshold_pct

                                if distance < distance_threshold:
                                    # Critical if within half of threshold
                                    status = "⚠️ 接近安全线" if distance < distance_threshold * 0.5 else "注意价格变化"
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
                                # Use user-configured distance percentage (stored in bybit_mt5_liquidation_price field)
                                # Field stores percentage value (e.g., 10 means 10%)
                                distance_threshold_pct = risk_settings.bybit_mt5_liquidation_price / 100.0
                                distance_threshold = bybit_liq * distance_threshold_pct

                                if distance < distance_threshold:
                                    # Critical if within half of threshold
                                    status = "⚠️ 接近安全线" if distance < distance_threshold * 0.5 else "注意价格变化"
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

        except asyncio.TimeoutError:
            logger.error(f"Timeout in _check_risk_alerts batch query")
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
        """Main streaming loop with connection pool optimization"""
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

            except asyncio.TimeoutError:
                logger.error(f"MT5 connection stream timeout, extending retry interval")
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)  # Extended retry on timeout
            except Exception as e:
                logger.error(f"Error in MT5 connection stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)  # Extended retry on error

    async def _check_mt5_alerts(self, mt5_status):
        """Check MT5 lag alerts and send Feishu notifications with optimized connection handling"""
        try:
            async with get_db_session(timeout=5.0) as db:
                # Batch query: Get all users with risk settings in one query
                result = await asyncio.wait_for(
                    db.execute(
                        select(RiskSettings).where(RiskSettings.mt5_lag_count.isnot(None))
                    ),
                    timeout=3.0
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

        except asyncio.TimeoutError:
            logger.error(f"Timeout in _check_mt5_alerts batch query")
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




class PendingOrdersStreamer:
    """Background task for streaming pending orders updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 2  # Update interval: 2 seconds
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    async def start(self):
        """Start the pending orders streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())
        logger.info(f"Pending orders streamer started (interval: {self.interval}s)")

    async def stop(self):
        """Stop the pending orders streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Pending orders streamer stopped")

    async def _stream_loop(self):
        """Main streaming loop"""
        while self.running:
            try:
                # Only broadcast if there are active connections
                if manager.get_connection_count() == 0:
                    await asyncio.sleep(self.interval)
                    continue

                # Fetch pending orders directly from Binance API
                try:
                    from app.models.account import Account
                    from app.core.database import AsyncSessionLocal
                    from app.services.binance_client import BinanceFuturesClient
                    from app.utils.time_utils import utc_ms_to_beijing
                    from sqlalchemy import select

                    pending_orders = []

                    # Get all Binance accounts from database
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(Account).where(Account.platform_id == 1)  # Binance
                        )
                        accounts = result.scalars().all()

                        # Fetch open orders for each account
                        for account in accounts:
                            try:
                                client = BinanceFuturesClient(account.api_key, account.api_secret)
                                try:
                                    # Get all open orders for XAUUSDT
                                    open_orders = await client.get_open_orders(symbol="XAUUSDT")

                                    for order in open_orders:
                                        # Convert time to Beijing time
                                        order_time = order.get("time", 0)
                                        beijing_time = utc_ms_to_beijing(order_time)

                                        pending_orders.append({
                                            "id": str(order.get("orderId")),
                                            "timestamp": beijing_time,
                                            "exchange": "Binance",
                                            "side": order.get("side", "").lower(),
                                            "quantity": float(order.get("origQty", 0)),
                                            "price": float(order.get("price", 0)),
                                            "status": order.get("status", "").lower(),
                                            "symbol": order.get("symbol", ""),
                                            "source": "strategy"  # Default to strategy
                                        })
                                finally:
                                    await client.close()
                            except Exception as e:
                                logger.error(f"Failed to fetch orders for account {account.account_id}: {e}")

                    # Sort by timestamp descending
                    pending_orders.sort(key=lambda x: x["timestamp"], reverse=True)

                    # Broadcast to all connected clients
                    await manager.broadcast({
                        "type": "pending_orders",
                        "data": pending_orders[:8]  # Limit to 8 most recent orders
                    })
                    self.broadcast_count += 1
                    self.last_broadcast_time = datetime.now().isoformat()

                except Exception as e:
                    logger.error(f"Failed to fetch pending orders: {e}")

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in pending orders stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)


class RedisStatusStreamer:
    """Background task for streaming Redis status updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 30  # Update interval: 30 seconds
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    async def start(self):
        """Start the Redis status streaming task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._stream_loop())
        logger.info(f"Redis status streamer started (interval: {self.interval}s)")

    async def stop(self):
        """Stop the Redis status streaming task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Redis status streamer stopped")

    async def _stream_loop(self):
        """Main streaming loop"""
        while self.running:
            try:
                # Only broadcast if there are active connections
                if manager.get_connection_count() == 0:
                    await asyncio.sleep(self.interval)
                    continue

                # Fetch Redis status from API
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get('http://localhost:8000/api/v1/system/redis/status', timeout=5) as response:
                            if response.status == 200:
                                redis_data = await response.json()

                                # Broadcast to all connected clients
                                await manager.broadcast({
                                    "type": "redis_status",
                                    "data": redis_data
                                })
                                self.broadcast_count += 1
                                self.last_broadcast_time = datetime.now().isoformat()
                except Exception as e:
                    logger.error(f"Failed to fetch Redis status: {e}")

                # Wait for next interval
                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in Redis status stream: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval * 2)


# Global streamer instances
account_balance_streamer = AccountBalanceStreamer()
risk_metrics_streamer = RiskMetricsStreamer()
mt5_connection_streamer = MT5ConnectionStreamer()
pending_orders_streamer = PendingOrdersStreamer()
redis_status_streamer = RedisStatusStreamer()


class PositionStreamer:
    """
    实时持仓广播器 — 每1秒向所有已连接客户端广播 position_snapshot。

    数据源：
    - Bybit/MT5：直接读共享 MT5 客户端内存中的持仓，无额外 API 开销，延迟 < 1ms
    - Binance  ：完全依赖 AccountBalanceStreamer 推送（每30s由账户刷新驱动），零API开销

    设计原则（量化工程）：
    - 不对 Binance 发起任何 REST 请求，彻底消除频率超限风险
    - 只在有 WebSocket 连接时广播，空载时跳过
    - MT5 读取在 executor 线程池中执行，不阻塞事件循环
    """

    BROADCAST_INTERVAL = 1.0  # 每秒广播一次

    def __init__(self):
        self.running = False
        self.task = None
        # Binance 持仓（由 AccountBalanceStreamer 主动推送，PositionStreamer 只读缓存）
        self._binance_long_xau: float = 0.0
        self._binance_short_xau: float = 0.0

    def set_binance_positions(self, long_xau: float, short_xau: float) -> None:
        """由 AccountBalanceStreamer 调用，更新 Binance 持仓缓存（无锁，主事件循环内安全）"""
        self._binance_long_xau = long_xau
        self._binance_short_xau = short_xau

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("PositionStreamer started (interval=1s, binance_cache=5s)")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("PositionStreamer stopped")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    async def _loop(self):
        import asyncio as _aio
        loop = _aio.get_event_loop()

        while self.running:
            try:
                await asyncio.sleep(self.BROADCAST_INTERVAL)

                # 无连接时跳过广播，节省资源
                if manager.get_connection_count() == 0:
                    continue

                # 1. 读 MT5 持仓（线程池，非阻塞）
                long_lots, short_lots = await self._read_mt5_positions(loop)

                # 2. Binance 持仓直接使用缓存值（由 AccountBalanceStreamer 推送，无REST调用）
                binance_long = self._binance_long_xau
                binance_short = self._binance_short_xau

                # 3. 广播
                await manager.broadcast({
                    "type": "position_snapshot",
                    "data": {
                        "bybit_long_lots":  long_lots,
                        "bybit_short_lots": short_lots,
                        "binance_long_xau": binance_long,
                        "binance_short_xau": binance_short,
                    }
                })

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PositionStreamer] loop error: {e}", exc_info=True)
                await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # MT5 持仓读取（共享客户端，无 API 调用）
    # ------------------------------------------------------------------
    async def _read_mt5_positions(self, loop) -> tuple:
        try:
            mt5_client = market_data_service.mt5_client
            if mt5_client is None or not mt5_client.connected:
                return 0.0, 0.0

            def _get():
                positions = mt5_client.get_positions("XAUUSD+")
                long_l  = round(sum(p['volume'] for p in positions if p.get('type') == 0), 2)
                short_l = round(sum(p['volume'] for p in positions if p.get('type') == 1), 2)
                return long_l, short_l

            return await loop.run_in_executor(None, _get)
        except Exception as e:
            logger.debug(f"[PositionStreamer] MT5 read error: {e}")
            return 0.0, 0.0

    # ------------------------------------------------------------------
    # Binance 持仓读取（已废弃REST轮询，改为被动接收AccountBalanceStreamer推送）
    # ------------------------------------------------------------------


position_streamer = PositionStreamer()


# ---------------------------------------------------------------------------
# 全局订单成交事件注册表 — 供 _monitor_binance_order() 使用
# key: binance order_id (int)
# value: {"event": asyncio.Event, "filled_qty": float, "status": str}
# ---------------------------------------------------------------------------
_order_fill_registry: Dict[int, dict] = {}


def register_order_watch(order_id: int) -> asyncio.Event:
    """注册一个订单监听。返回 asyncio.Event，成交/取消时会被 set()。"""
    ev = asyncio.Event()
    _order_fill_registry[order_id] = {"event": ev, "filled_qty": 0.0, "status": "NEW"}
    logger.debug(f"[OrderWatch] Registered order {order_id}")
    return ev


def unregister_order_watch(order_id: int):
    """注销订单监听，释放内存。"""
    _order_fill_registry.pop(order_id, None)
    logger.debug(f"[OrderWatch] Unregistered order {order_id}")


class BinancePositionPusher:
    """
    实时 Binance 持仓推送器 — 订阅 Binance Futures User Data Stream。

    当 ACCOUNT_UPDATE 事件到达（成交触发），立即更新 PositionStreamer 缓存，
    取代 AccountBalanceStreamer 30s REST 轮询驱动，实现 <100ms 持仓更新。

    同时处理 ORDER_TRADE_UPDATE 事件，通过 _order_fill_registry 通知
    _monitor_binance_order() 协程，彻底消除 REST 轮询。

    协议：wss://fstream.binance.com/ws/{listenKey}
    listenKey 有效期 60min，每 25min 续期一次。
    """

    SYMBOL           = "XAUUSDT"
    KEEPALIVE_SEC    = 25 * 60   # 25min 续期，确保 listenKey 不过期
    RECONNECT_DELAY  = 5         # 断线后等待秒数

    def __init__(self):
        self.running = False
        self.task    = None

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._manager_loop())
        logger.info("[BinancePositionPusher] Started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("[BinancePositionPusher] Stopped")

    # ------------------------------------------------------------------
    # 外层：加载账户并为每个账户启动独立 stream
    # ------------------------------------------------------------------
    async def _manager_loop(self):
        while self.running:
            try:
                accounts = await self._load_binance_accounts()
                if not accounts:
                    logger.warning("[BinancePositionPusher] 无活跃 Binance 账户，60s 后重试")
                    await asyncio.sleep(60)
                    continue

                tasks = [
                    asyncio.create_task(self._account_stream_loop(api_key, api_secret))
                    for api_key, api_secret in accounts
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BinancePositionPusher] Manager loop error: {e}")
                await asyncio.sleep(self.RECONNECT_DELAY)

    async def _load_binance_accounts(self) -> list:
        """从 DB 加载所有活跃 Binance REST 账户（去重 api_key）"""
        try:
            async with get_db_session(timeout=10.0) as db:
                result = await db.execute(
                    select(Account).where(
                        Account.is_active    == True,
                        Account.platform_id  == 1,
                        Account.api_key      != None,
                        Account.api_secret   != None,
                    )
                )
                rows = result.scalars().all()

            seen, out = set(), []
            for acc in rows:
                if acc.api_key and acc.api_key not in seen:
                    seen.add(acc.api_key)
                    out.append((acc.api_key, acc.api_secret))

            logger.info(f"[BinancePositionPusher] 加载 {len(out)} 个 Binance 账户")
            return out
        except Exception as e:
            logger.error(f"[BinancePositionPusher] 加载账户失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 单账户：创建 listenKey → 连 WS → 处理消息 → 断线重连
    # ------------------------------------------------------------------
    async def _account_stream_loop(self, api_key: str, api_secret: str):
        from app.services.binance_client import BinanceFuturesClient
        ws_base = "wss://fstream.binance.com/ws"

        while self.running:
            client  = BinanceFuturesClient(api_key, api_secret)
            session = None
            try:
                listen_key = await client.create_futures_listen_key()
                if not listen_key:
                    logger.error(f"[BinancePositionPusher] listenKey 获取失败: {api_key[:8]}…")
                    await asyncio.sleep(self.RECONNECT_DELAY)
                    continue

                logger.info(f"[BinancePositionPusher] listenKey 已创建: {api_key[:8]}…")
                session = aiohttp.ClientSession()

                async with session.ws_connect(
                    f"{ws_base}/{listen_key}", heartbeat=30
                ) as ws:
                    logger.info(f"[BinancePositionPusher] User Data Stream 已连接: {api_key[:8]}…")

                    keepalive_task = asyncio.create_task(
                        self._keepalive_loop(client, listen_key)
                    )
                    try:
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_message(msg.json())
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BinancePositionPusher] Stream 错误 ({api_key[:8]}…): {e}")
            finally:
                if session and not session.closed:
                    await session.close()
                await client.close()

            if self.running:
                logger.info(f"[BinancePositionPusher] {self.RECONNECT_DELAY}s 后重连…")
                await asyncio.sleep(self.RECONNECT_DELAY)

    async def _keepalive_loop(self, client, listen_key: str):
        """每 25min 续期 listenKey"""
        while True:
            await asyncio.sleep(self.KEEPALIVE_SEC)
            try:
                await client.keepalive_futures_listen_key(listen_key)
                logger.debug("[BinancePositionPusher] listenKey 续期成功")
            except Exception as e:
                logger.warning(f"[BinancePositionPusher] listenKey 续期失败: {e}")

    # ------------------------------------------------------------------
    # 消息处理：ACCOUNT_UPDATE → 立即更新 PositionStreamer
    # ------------------------------------------------------------------
    async def _handle_message(self, data: dict):
        event_type = data.get("e")

        # ------------------------------------------------------------------
        # ORDER_TRADE_UPDATE → 通知 _monitor_binance_order() 协程
        # ------------------------------------------------------------------
        if event_type == "ORDER_TRADE_UPDATE":
            order = data.get("o", {})
            oid = order.get("i")          # orderId (int)
            status = order.get("X", "")  # FILLED / PARTIALLY_FILLED / CANCELED / EXPIRED / REJECTED
            cum_qty = float(order.get("z", 0))  # cumulativeFilledQty

            record = _order_fill_registry.get(oid)
            if record is not None:
                record["filled_qty"] = cum_qty
                record["status"] = status
                if status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                    record["event"].set()
                    logger.info(
                        f"[OrderWatch] ORDER_TRADE_UPDATE order={oid} "
                        f"status={status} filled={cum_qty}"
                    )
            return

        if event_type != "ACCOUNT_UPDATE":
            return

        # ACCOUNT_UPDATE.a.P 是仓位数组
        positions = data.get("a", {}).get("P", [])

        # 以当前缓存值为基准，只覆盖 XAUUSDT 相关字段
        long_xau  = position_streamer._binance_long_xau
        short_xau = position_streamer._binance_short_xau
        updated   = False

        for pos in positions:
            if pos.get("s") != self.SYMBOL:
                continue

            updated  = True
            ps       = pos.get("ps", "BOTH")    # positionSide: LONG / SHORT / BOTH
            pa       = float(pos.get("pa", 0))  # positionAmt（有符号）

            if ps == "LONG":
                long_xau  = round(max(0.0, pa), 3)
            elif ps == "SHORT":
                # SHORT side: pa 为负值，取绝对值
                short_xau = round(max(0.0, abs(pa)), 3)
            else:  # BOTH（单向持仓模式）
                if pa > 0:
                    long_xau, short_xau = round(pa, 3), 0.0
                elif pa < 0:
                    long_xau, short_xau = 0.0, round(abs(pa), 3)
                else:
                    long_xau, short_xau = 0.0, 0.0

        if updated:
            position_streamer.set_binance_positions(long_xau, short_xau)
            logger.info(
                f"[BinancePositionPusher] ACCOUNT_UPDATE → "
                f"long={long_xau} short={short_xau}"
            )


binance_position_pusher = BinancePositionPusher()
