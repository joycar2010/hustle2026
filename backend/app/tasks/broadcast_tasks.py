"""Background tasks for account balance and risk metrics streaming"""
import asyncio
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
from app.services.spread_alert_service import SpreadAlertService, spread_alert_service
from app.services.market_service import market_data_service
from app.core.proxy_utils import build_proxy_url
from sqlalchemy import select
import logging
import aiohttp

logger = logging.getLogger(__name__)


def _get_pair_symbols():
    """Get symbol names from hedging pair config, with fallback"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair("XAU")
        if pair:
            return pair.symbol_a.symbol, pair.symbol_b.symbol
    except Exception:
        pass
    return "XAUUSDT", "XAUUSD+"


async def _get_spread_for_pair(pair_code: str):
    """Fetch spread data for a specific hedging pair, falling back to XAU.

    Resolves Binance/MT5 symbols from hedging_pair_service and calls
    market_data_service.get_current_spread() so that spread alerts for
    XAG, BZ, CL, NG etc. use the correct market data.
    """
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair(pair_code)
        if pair and pair.symbol_a and pair.symbol_b:
            return await market_data_service.get_current_spread(
                binance_symbol=pair.symbol_a.symbol,
                bybit_symbol=pair.symbol_b.symbol,
            )
    except Exception as e:
        logger.warning(f"[_get_spread_for_pair] pair={pair_code} error: {e}, fallback XAU")
    return await market_data_service.get_current_spread()



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
        self.interval = 300  # Safety-sync interval: 5 min.
        # Real-time updates come from Binance UserDataStream (ACCOUNT_UPDATE)
        # handled by BinancePositionPusher. REST poll is safety fallback only.
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

                # Note: do NOT skip when Python WS manager has 0 connections.
                # Frontend connects to Go /ws, not Python /api/v1/ws, so
                # manager.active_connections is always empty. We must still poll
                # Binance/MT5 here to feed PositionStreamer (which broadcasts via
                # Redis → Go Hub → actual WebSocket clients).

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

                # ── 按用户分组，为每个用户独立推送余额数据 ──
                user_accounts_map = {}
                for acc in active_accounts:
                    uid = str(acc.user_id)
                    if uid not in user_accounts_map:
                        user_accounts_map[uid] = []
                    user_accounts_map[uid].append(acc)

                for uid, user_accs in user_accounts_map.items():
                    try:
                        aggregated_data = await account_data_service.get_aggregated_account_data(
                            list(user_accs)
                        )

                        # ── 写入 account_snapshots（历史盈亏数据源，供 /profit 页面使用） ──
                        # 每次轮询（默认 300s）写一条快照，一天约 288 条，足够绘制收益曲线
                        try:
                            await _write_account_snapshots(aggregated_data.get("accounts", []))
                        except Exception as _snap_err:
                            logger.warning(f"[AccountBalanceStreamer] snapshot write error: {_snap_err}")

                        # 将 Binance 持仓同步到 PositionStreamer（仅本用户的）
                        try:
                            # 按 symbol 汇总 Binance 持仓 (支持多产品对)
                            all_positions = aggregated_data.get("positions", [])
                            logger.info(f"[AccountBalanceStreamer] user={uid} pos_count={len(all_positions)}")
                            sym_longs = {}
                            sym_shorts = {}
                            for pos in all_positions:
                                if pos.get("is_mt5_account"):
                                    continue
                                if pos.get("platform_id") != 1:
                                    continue
                                sym = pos.get("symbol", "")
                                side = pos.get("side", "").upper()
                                size = round(float(pos.get("size", 0)), 3)
                                if side in ("LONG", "BUY"):
                                    sym_longs[sym] = sym_longs.get(sym, 0.0) + size
                                elif side in ("SHORT", "SELL"):
                                    sym_shorts[sym] = sym_shorts.get(sym, 0.0) + size
                            # 更新每个 symbol 的持仓缓存
                            all_syms = set(list(sym_longs.keys()) + list(sym_shorts.keys()))
                            for sym in all_syms:
                                position_streamer.set_binance_positions(
                                    round(sym_longs.get(sym, 0.0), 3),
                                    round(sym_shorts.get(sym, 0.0), 3),
                                    user_id=uid,
                                    symbol=sym,
                                )
                            logger.info(f"[AccountBalanceStreamer] set_binance syms={list(all_syms)} uid={uid}")
                        except Exception as _pe:
                            logger.warning(f"[AccountBalanceStreamer] PositionStreamer sync error: {_pe}")

                        # 按用户推送，不再广播给所有人
                        await manager.send_to_user({
                            "type": "account_balance",
                            "data": aggregated_data,
                        }, uid)
                    except Exception as e:
                        logger.error(f"[AccountBalanceStreamer] user {uid} error: {e}")

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

                # Check spread alerts per user — pair-code-aware market data
                for user_id, accounts in user_accounts.items():
                    try:
                        risk_settings = risk_settings_map.get(user_id)
                        if not risk_settings:
                            continue

                        alert_settings = {
                            'forwardOpenPrice': risk_settings.forward_open_price,
                            'forwardClosePrice': risk_settings.forward_close_price,
                            'reverseOpenPrice': risk_settings.reverse_open_price,
                            'reverseClosePrice': risk_settings.reverse_close_price,
                            'forwardOpenSyncCount': risk_settings.forward_open_sync_count,
                            'forwardCloseSyncCount': risk_settings.forward_close_sync_count,
                            'reverseOpenSyncCount': risk_settings.reverse_open_sync_count,
                            'reverseCloseSyncCount': risk_settings.reverse_close_sync_count,
                        }

                        if not any(alert_settings.values()):
                            continue

                        # Fetch pair-aware spread data based on user's configured pair
                        pair_code = getattr(risk_settings, 'pair_code', 'XAU') or 'XAU'
                        market_data = await _get_spread_for_pair(pair_code)
                        market_dict = {
                            'forward_spread': market_data.forward_entry_spread if hasattr(market_data, 'forward_entry_spread') else None,
                            'reverse_spread': market_data.reverse_entry_spread if hasattr(market_data, 'reverse_entry_spread') else None,
                        }

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

                # ── 按用户分组，独立推送风险指标 ──
                user_accounts_map = {}
                for acc in active_accounts:
                    uid = str(acc.user_id)
                    if uid not in user_accounts_map:
                        user_accounts_map[uid] = []
                    user_accounts_map[uid].append(acc)

                for uid, user_accs in user_accounts_map.items():
                    try:
                        aggregated_data = await account_data_service.get_aggregated_account_data(
                            list(user_accs)
                        )
                        risk_data = {
                            "summary": aggregated_data.get("summary", {}),
                            "positions": aggregated_data.get("positions", []),
                            "timestamp": aggregated_data.get("timestamp"),
                        }
                        await manager.send_to_user({
                            "type": "risk_metrics",
                            "data": risk_data,
                        }, uid)
                    except Exception as e:
                        logger.error(f"[RiskMetricsStreamer] user {uid} error: {e}")

                self.broadcast_count += 1
                self.last_broadcast_time = datetime.now().isoformat()

                # Always check risk alerts (opens a new DB session internally)
                logger.info(f"[BROADCAST] Calling _check_risk_alerts, active_accounts={len(active_accounts)}")
                await self._check_risk_alerts(active_accounts, user_accounts_map)

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

    async def _check_risk_alerts(self, active_accounts, user_accounts_map):
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

                # Check alerts for each user using per-user aggregated data
                for user_id, accounts in user_accounts.items():
                    try:
                        risk_settings = risk_settings_map.get(user_id)
                        if not risk_settings:
                            continue

                        # Get per-user aggregated data
                        user_accs = user_accounts_map.get(user_id, accounts)
                        aggregated_data = await account_data_service.get_aggregated_account_data(
                            list(user_accs)
                        )

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

                        # Check spread alerts — pair-code-aware
                        try:
                            alert_settings = {
                                'forwardOpenPrice': risk_settings.forward_open_price,
                                'forwardClosePrice': risk_settings.forward_close_price,
                                'reverseOpenPrice': risk_settings.reverse_open_price,
                                'reverseClosePrice': risk_settings.reverse_close_price,
                                'forwardOpenSyncCount': risk_settings.forward_open_sync_count,
                                'forwardCloseSyncCount': risk_settings.forward_close_sync_count,
                                'reverseOpenSyncCount': risk_settings.reverse_open_sync_count,
                                'reverseCloseSyncCount': risk_settings.reverse_close_sync_count,
                            }
                            if any(alert_settings.values()):
                                pair_code = getattr(risk_settings, 'pair_code', 'XAU') or 'XAU'
                                market_data = await _get_spread_for_pair(pair_code)
                                market_dict = {
                                    'forward_spread': market_data.forward_entry_spread if hasattr(market_data, 'forward_entry_spread') else None,
                                    'reverse_spread': market_data.reverse_entry_spread if hasattr(market_data, 'reverse_entry_spread') else None,
                                }
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

                    # Get all Binance accounts from database, grouped by user
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(Account).where(Account.platform_id == 1, Account.is_active == True)
                        )
                        accounts = result.scalars().all()

                        # Group by user_id
                        user_accounts = {}
                        for account in accounts:
                            uid = str(account.user_id)
                            if uid not in user_accounts:
                                user_accounts[uid] = []
                            user_accounts[uid].append(account)

                        # Fetch and send per user
                        for uid, user_accs in user_accounts.items():
                            user_orders = []
                            for account in user_accs:
                                try:
                                    from app.core.proxy_utils import build_proxy_url
                                    client = BinanceFuturesClient(
                                        account.api_key, account.api_secret,
                                        proxy_url=build_proxy_url(account.proxy_config)
                                    )
                                    try:
                                        sym_a, _ = _get_pair_symbols()
                                        open_orders = await client.get_open_orders(symbol=sym_a)
                                        for order in open_orders:
                                            order_time = order.get("time", 0)
                                            beijing_time = utc_ms_to_beijing(order_time)
                                            user_orders.append({
                                                "id": str(order.get("orderId")),
                                                "timestamp": beijing_time,
                                                "exchange": "主账号",
                                                "side": order.get("side", "").lower(),
                                                "quantity": float(order.get("origQty", 0)),
                                                "price": float(order.get("price", 0)),
                                                "status": order.get("status", "").lower(),
                                                "symbol": order.get("symbol", ""),
                                                "source": "strategy"
                                            })
                                    finally:
                                        await client.close()
                                except Exception as e:
                                    logger.error(f"Failed to fetch orders for account {account.account_id}: {e}")

                            user_orders.sort(key=lambda x: x["timestamp"], reverse=True)
                            await manager.send_to_user({
                                "type": "pending_orders",
                                "data": user_orders[:8]
                            }, uid)
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


class MarketStateMonitor:
    """Monitor MT5 market open/close state changes and notify subscribed users.

    - Polls is_bybit_trading_hours() every 60 seconds.
    - Fires notification only when state CHANGES (open->close or close->open).
    - Only notifies users with risk_settings.market_close_notify = True.
    - Channel: Feishu card + WebSocket popup via Redis ws:user_event.
    - Cooldown: 3600s per template to avoid flapping.
    """

    def __init__(self):
        self.running = False
        self.task = None
        self.check_interval = 60
        self._last_state = None  # None=uninitialised, True=open, False=closed

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._monitor_loop())
        logger.info("[MarketStateMonitor] started (interval=60s)")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        from app.utils.trading_time import is_bybit_trading_hours, get_bybit_next_open_time
        while self.running:
            try:
                is_open, market_message = is_bybit_trading_hours()
                if self._last_state is not None and is_open != self._last_state:
                    logger.info(
                        f"[MarketStateMonitor] State changed: "
                        f"{'OPEN' if is_open else 'CLOSED'} ({market_message})"
                    )
                    tpl = "market_open" if is_open else "market_close"
                    await self._notify_users(tpl, {
                        "market_message": market_message,
                        "next_open_time": get_bybit_next_open_time() if not is_open else "当前为交易时间",
                        "open_time": market_message,
                    })
                self._last_state = is_open
            except Exception as e:
                logger.error(f"[MarketStateMonitor] loop error: {e}")
            await asyncio.sleep(self.check_interval)

    async def _notify_users(self, template_key: str, variables: dict):
        import json as _j
        from app.services.feishu_service import get_feishu_service
        from app.models.notification_config import NotificationTemplate, NotificationLog
        from app.models.user import User
        from app.models.risk_settings import RiskSettings
        from app.core.redis_client import redis_client as _rc
        from sqlalchemy import select as _sel, and_ as _and
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        def _bjt():
            return _dt.now(_ZI("Asia/Shanghai")).replace(tzinfo=None)

        try:
            async with AsyncSessionLocal() as db:
                tmpl_r = await db.execute(
                    _sel(NotificationTemplate).where(
                        _and(
                            NotificationTemplate.template_key == template_key,
                            NotificationTemplate.is_active == True,
                            NotificationTemplate.enable_feishu == True,
                        )
                    )
                )
                tmpl = tmpl_r.scalar_one_or_none()
                if not tmpl:
                    logger.warning(f"[MarketStateMonitor] template missing: {template_key}")
                    return

                # Global cooldown (one market, one state transition)
                from app.services.spread_alert_service import spread_alert_service as _sas
                cooldown = tmpl.cooldown_seconds or 3600
                ck = f"{template_key}_market_global"
                now = _bjt()
                if ck in _sas.last_alert_time:
                    elapsed = (now - _sas.last_alert_time[ck]).total_seconds()
                    if elapsed < cooldown:
                        logger.info(f"[MarketStateMonitor] {template_key} on cooldown ({elapsed:.0f}s)")
                        return
                _sas.last_alert_time[ck] = now

                class _SD(dict):
                    def __missing__(self, k): return "{" + k + "}"
                _v = _SD(variables)
                title = tmpl.title_template.format_map(_v)
                body = tmpl.content_template.format_map(_v)
                ptitle = (tmpl.popup_title_template or title).format_map(_v)
                pbody = (tmpl.popup_content_template or body).format_map(_v)

                rs_r = await db.execute(
                    _sel(RiskSettings).where(RiskSettings.market_close_notify == True)
                )
                settings = rs_r.scalars().all()
                if not settings:
                    logger.info("[MarketStateMonitor] No users subscribed to market notify")
                    return

                uid_list = [rs.user_id for rs in settings]
                u_r = await db.execute(_sel(User).where(User.user_id.in_(uid_list)))
                users = u_r.scalars().all()

                feishu = get_feishu_service()
                cmap = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
                color = cmap.get(tmpl.priority, "grey")

                for user in users:
                    uid_str = str(user.user_id)
                    try:
                        if feishu and user.feishu_open_id:
                            res = await feishu.send_card_message(
                                receive_id=user.feishu_open_id,
                                title=title, content=body,
                                receive_id_type="open_id", color=color,
                            )
                            db.add(NotificationLog(
                                user_id=user.user_id, template_key=template_key,
                                service_type="feishu", recipient=user.feishu_open_id,
                                title=title, content=body,
                                status="sent" if res.get("success") else "failed",
                                error_message=res.get("error"),
                                sent_at=_bjt() if res.get("success") else None,
                            ))
                        evt = {
                            "user_id": uid_str, "type": "risk_alert",
                            "data": {
                                "alert_type": template_key,
                                "level": "warning" if template_key == "market_close" else "info",
                                "title": title, "message": body,
                                "timestamp": _bjt().isoformat(),
                                "template_key": template_key,
                                "popup_config": {
                                    "title": ptitle, "content": pbody,
                                    "sound_file": tmpl.alert_sound_file or "/sounds/hello-moto.mp3",
                                    "sound_repeat": tmpl.alert_sound_repeat or 1,
                                },
                            },
                        }
                        await _rc.publish("ws:user_event", _j.dumps(evt))
                        logger.info(f"[MarketStateMonitor] Notified {uid_str} via {template_key}")
                    except Exception as ue:
                        logger.error(f"[MarketStateMonitor] user {user.user_id} error: {ue}")

                await db.commit()
        except Exception as e:
            logger.error(f"[MarketStateMonitor] _notify_users error: {e}", exc_info=True)


market_state_monitor = MarketStateMonitor()


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
    _bridge_url_cache: str = None   # 模块级缓存，避免每秒 DB 查询

    def __init__(self):
        self.running = False
        self.task = None
        # Binance 持仓缓存，按 user_id → symbol 双层隔离
        # 结构: {user_id: {symbol: (long, short)}}
        self._binance_positions: dict = {}

    def set_binance_positions(self, long_xau: float, short_xau: float,
                               user_id: str = None, symbol: str = None) -> None:
        """由 AccountBalanceStreamer / BinancePositionPusher 调用，更新指定用户+symbol的持仓缓存"""
        _symbol = symbol or _get_pair_symbols()[0]  # 默认 XAU A侧 symbol
        if user_id:
            if user_id not in self._binance_positions:
                self._binance_positions[user_id] = {}
            self._binance_positions[user_id][_symbol] = (long_xau, short_xau)
        else:
            if "_default" not in self._binance_positions:
                self._binance_positions["_default"] = {}
            self._binance_positions["_default"][_symbol] = (long_xau, short_xau)

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
        import json as _json
        from app.core.redis_client import redis_client as _rc
        loop = _aio.get_event_loop()

        while self.running:
            try:
                await asyncio.sleep(self.BROADCAST_INTERVAL)

                # 1. Read ALL MT5 positions by symbol
                mt5_by_symbol = await self._read_mt5_positions_all()

                # 2. Build pairs_map from active hedging pairs
                pairs_map = {}
                try:
                    from app.services.hedging_pair_service import hedging_pair_service
                    active_pairs = hedging_pair_service.list_active_pairs()
                    for pair in (active_pairs or []):
                        if not pair.is_active:
                            continue
                        sym_a = pair.symbol_a.symbol if pair.symbol_a else None
                        sym_b = pair.symbol_b.symbol if pair.symbol_b else None
                        if not sym_a or not sym_b:
                            continue
                        mt5_l, mt5_s = mt5_by_symbol.get(sym_b, (0.0, 0.0))
                        if mt5_l == 0.0 and mt5_s == 0.0:
                            alt = sym_b.replace("+", ".s")
                            mt5_l, mt5_s = mt5_by_symbol.get(alt, (0.0, 0.0))
                        pairs_map[pair.pair_code] = {
                            "sym_a": sym_a, "sym_b": sym_b,
                            "mt5_long": mt5_l, "mt5_short": mt5_s,
                        }
                except Exception as _pe:
                    logger.debug(f"[PositionStreamer] pairs_map error: {_pe}")

                # 3. Broadcast per-user
                for uid, sym_positions in self._binance_positions.items():
                    if uid == "_default":
                        continue
                    pairs_out = {}
                    for pair_code, pd in pairs_map.items():
                        sym_a = pd["sym_a"]
                        bn_l, bn_s = sym_positions.get(sym_a, (0.0, 0.0))
                        pairs_out[pair_code] = {
                            "mt5_long": pd["mt5_long"], "mt5_short": pd["mt5_short"],
                            "binance_long": bn_l, "binance_short": bn_s,
                        }
                    xau_pd = pairs_map.get("XAU", {})
                    xau_sym_a = xau_pd.get("sym_a", "")
                    bn_l_xau, bn_s_xau = sym_positions.get(xau_sym_a, (0.0, 0.0))
                    evt = {
                        "user_id": uid, "type": "position_snapshot",
                        "data": {
                            "bybit_long_lots":  xau_pd.get("mt5_long", 0.0),
                            "bybit_short_lots": xau_pd.get("mt5_short", 0.0),
                            "binance_long_xau": bn_l_xau,
                            "binance_short_xau": bn_s_xau,
                            "pairs": pairs_out,
                        }
                    }
                    await _rc.publish("ws:user_event", _json.dumps(evt))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PositionStreamer] loop error: {e}", exc_info=True)
                await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # MT5 持仓读取 — 无 symbol 过滤，返回所有持仓
    # ------------------------------------------------------------------
    async def _read_mt5_positions_all(self) -> dict:
        result = {}
        try:
            import httpx, os
            api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))
            headers = {"X-Api-Key": api_key} if api_key else {}
            if not PositionStreamer._bridge_url_cache:
                try:
                    from app.models.mt5_client import MT5Client as MT5ClientModel
                    from sqlalchemy import select as sa_select
                    async with AsyncSessionLocal() as _db:
                        mc = (await _db.execute(
                            sa_select(MT5ClientModel)
                            .where(MT5ClientModel.is_active == True)
                            .where(MT5ClientModel.is_system_service == False)
                            .order_by(MT5ClientModel.priority)
                            .limit(1)
                        )).scalar_one_or_none()
                        if mc and mc.bridge_service_port:
                            PositionStreamer._bridge_url_cache = f"http://172.31.14.113:{mc.bridge_service_port}"
                except Exception:
                    pass
            bridge_url = PositionStreamer._bridge_url_cache or os.getenv("MT5_BRIDGE_URL", "http://172.31.14.113:8002")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{bridge_url}/mt5/positions", headers=headers)
                if resp.status_code != 200:
                    return result
                positions = resp.json().get("positions", [])
            for p in positions:
                sym = p.get("symbol", "")
                if not sym:
                    continue
                vol = float(p.get("volume", 0))
                typ = p.get("type", -1)
                if sym not in result:
                    result[sym] = [0.0, 0.0]
                if typ == 0:
                    result[sym][0] += vol
                elif typ == 1:
                    result[sym][1] += vol
            return {sym: (round(v[0], 4), round(v[1], 4)) for sym, v in result.items()}
        except Exception as e:
            logger.debug(f"[PositionStreamer] MT5 read all error: {e}")
            return result

    # ------------------------------------------------------------------
    # MT5 持仓读取 — 通过交易账户的 MT5 Bridge HTTP API
    # ------------------------------------------------------------------
    async def _read_mt5_positions(self, loop) -> tuple:
        """Read MT5/Bybit positions from the TRADING bridge (not the system/data bridge).

        System bridge (8001) is for market data only — no trading positions.
        User bridge (8002) holds actual trading positions.
        Bridge URL is cached indefinitely — it changes only when the bridge is redeployed.
        """
        try:
            import httpx
            import os

            api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))
            headers = {"X-Api-Key": api_key} if api_key else {}

            # Find the trading bridge URL (non-system) — cached to avoid DB hit every second
            if not PositionStreamer._bridge_url_cache:
                try:
                    from app.models.mt5_client import MT5Client as MT5ClientModel
                    from sqlalchemy import select as sa_select
                    async with AsyncSessionLocal() as _db:
                        mc = (await _db.execute(
                            sa_select(MT5ClientModel)
                            .where(MT5ClientModel.is_active == True)
                            .where(MT5ClientModel.is_system_service == False)
                            .order_by(MT5ClientModel.priority)
                            .limit(1)
                        )).scalar_one_or_none()
                        if mc and mc.bridge_service_port:
                            PositionStreamer._bridge_url_cache = f"http://172.31.14.113:{mc.bridge_service_port}"
                except Exception:
                    pass

            bridge_url = PositionStreamer._bridge_url_cache or os.getenv("MT5_BRIDGE_URL", "http://172.31.14.113:8002")

            _, sym_b = _get_pair_symbols()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{bridge_url}/mt5/positions", params={"symbol": sym_b}, headers=headers)
                if resp.status_code != 200:
                    return 0.0, 0.0
                positions = resp.json().get("positions", [])

            long_l  = round(sum(float(p.get('volume', 0)) for p in positions if p.get('type') == 0), 2)
            short_l = round(sum(float(p.get('volume', 0)) for p in positions if p.get('type') == 1), 2)
            return long_l, short_l
        except Exception as e:
            logger.debug(f"[PositionStreamer] MT5 read error: {e}")
            return 0.0, 0.0

    # ------------------------------------------------------------------
    # Binance 持仓读取（已废弃REST轮询，改为被动接收AccountBalanceStreamer推送）
    # ------------------------------------------------------------------


position_streamer = PositionStreamer()


class BinancePositionPusher:
    """
    实时 Binance 持仓推送器 — 订阅 Binance Futures User Data Stream。

    当 ACCOUNT_UPDATE 事件到达（成交触发），立即更新 PositionStreamer 缓存，
    取代 AccountBalanceStreamer 30s REST 轮询驱动，实现 <100ms 持仓更新。

    协议：wss://fstream.binance.com/ws/{listenKey}
    listenKey 有效期 60min，每 25min 续期一次。
    """

    KEEPALIVE_SEC    = 25 * 60   # 25min 续期，确保 listenKey 不过期
    RECONNECT_DELAY  = 5         # 断线后等待秒数

    @staticmethod
    def _symbol():
        sym_a, _ = _get_pair_symbols()
        return sym_a

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
                    asyncio.create_task(self._account_stream_loop(api_key, api_secret, proxy_url, user_id))
                    for api_key, api_secret, proxy_url, user_id in accounts
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BinancePositionPusher] Manager loop error: {e}")
                await asyncio.sleep(self.RECONNECT_DELAY)

    async def _load_binance_accounts(self) -> list:
        """从 DB 加载所有活跃 Binance REST 账户（去重 api_key）。
        Returns list of (api_key, api_secret, proxy_url, user_id) tuples.
        """
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
                    proxy_url = build_proxy_url(acc.proxy_config) if acc.proxy_config else None
                    user_id = str(acc.user_id) if acc.user_id else None
                    out.append((acc.api_key, acc.api_secret, proxy_url, user_id))

            logger.info(f"[BinancePositionPusher] 加载 {len(out)} 个 Binance 账户")
            return out
        except Exception as e:
            logger.error(f"[BinancePositionPusher] 加载账户失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 单账户：创建 listenKey → 连 WS → 处理消息 → 断线重连
    # ------------------------------------------------------------------
    async def _account_stream_loop(self, api_key: str, api_secret: str, proxy_url: str = None, user_id: str = None):
        from app.services.binance_client import BinanceFuturesClient
        ws_base = "wss://fstream.binance.com/ws"

        while self.running:
            client  = BinanceFuturesClient(api_key, api_secret, proxy_url=proxy_url)
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
                                await self._handle_message(msg.json(), user_id)
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
    async def _handle_message(self, data: dict, user_id: str = None):
        event_type = data.get("e")

        # ── ORDER_TRADE_UPDATE: notify the order fill registry so
        # _monitor_binance_order's fill_event gets set in real-time.
        if event_type == "ORDER_TRADE_UPDATE":
            try:
                o = data.get("o", {})
                order_id = int(o.get("i", 0))
                filled_qty = float(o.get("z", 0))  # cumulative filled quantity
                status = o.get("X", "")             # FILLED / PARTIALLY_FILLED / CANCELED etc.
                if order_id:
                    notify_order_fill(order_id, filled_qty, status)
            except Exception as _e:
                logger.debug(f"[BinancePositionPusher] ORDER_TRADE_UPDATE parse error: {_e}")

        if event_type != "ACCOUNT_UPDATE":
            return

        # ACCOUNT_UPDATE.a.P 是仓位数组
        positions = data.get("a", {}).get("P", [])

        long_xau = 0.0
        short_xau = 0.0
        updated   = False

        for pos in positions:
            if pos.get("s") != self._symbol():
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

        # ── Parse B[] wallet balance (also in ACCOUNT_UPDATE) ──────────────
        # Binance pushes USDT wallet balance changes here in real-time,
        # eliminating the need for /fapi/v2/account REST polling for balance.
        for b in data.get("a", {}).get("B", []):
            if b.get("a") == "USDT":
                try:
                    _ws_balance_cache[user_id] = {
                        "available_balance": float(b.get("ab", 0)),
                        "wallet_balance":    float(b.get("cw", 0)),
                        "updated_at":        __import__("time").time(),
                    }
                    logger.info(
                        f"[BinancePositionPusher] BALANCE_UPDATE: "
                        f"wallet={b.get('cw')} avail={b.get('ab')} user={user_id}"
                    )
                except Exception:
                    pass
                break

        if updated:
            # Update PositionStreamer cache with user_id+symbol
            sym = self._symbol()
            position_streamer.set_binance_positions(long_xau, short_xau, user_id=user_id, symbol=sym)

            # Invalidate account_data_service cache so the NEXT AccountBalanceStreamer
            # cycle reads fresh data from Binance REST — prevents stale cache from
            # overwriting the correct WS-pushed position with an old value.
            try:
                from app.services.account_service import account_data_service
                account_data_service.invalidate_cache()
            except Exception:
                pass

            logger.info(
                f"[BinancePositionPusher] ACCOUNT_UPDATE → "
                f"long={long_xau} short={short_xau} user={user_id}"
            )

            # Immediately push a position_snapshot via Redis → Go Hub → frontend.
            # Don't wait for PositionStreamer's 1s cycle — user expects sub-second UI update.
            if user_id:
                try:
                    import json as _json
                    from app.core.redis_client import redis_client as _rc

                    # Read current MT5 positions from PositionStreamer cache for a complete snapshot
                    import inspect
                    mt5_client = market_data_service.mt5_client
                    bybit_long, bybit_short = 0.0, 0.0
                    if mt5_client:
                        _, sym_b = _get_pair_symbols()
                        _result = mt5_client.get_positions(sym_b)
                        _positions = (await _result) if inspect.isawaitable(_result) else _result
                        if _positions:
                            bybit_long = round(sum(float(p.get('volume', 0)) for p in _positions if p.get('type') == 0), 2)
                            bybit_short = round(sum(float(p.get('volume', 0)) for p in _positions if p.get('type') == 1), 2)

                    evt = {
                        "user_id": user_id,
                        "type": "position_snapshot",
                        "data": {
                            "bybit_long_lots": bybit_long,
                            "bybit_short_lots": bybit_short,
                            "binance_long_xau": long_xau,
                            "binance_short_xau": short_xau,
                        }
                    }
                    await _rc.publish("ws:user_event", _json.dumps(evt))
                    logger.info(f"[BinancePositionPusher] Instant snapshot pushed via Redis for user {user_id}")
                except Exception as push_err:
                    logger.warning(f"[BinancePositionPusher] Instant push failed: {push_err}")


binance_position_pusher = BinancePositionPusher()
# Real-time Binance wallet balance cache — populated by UserDataStream ACCOUNT_UPDATE.# Eliminates the need for /fapi/v2/account REST polling for wallet balance.# Keys: user_id  Values: {available_balance, wallet_balance, updated_at}_ws_balance_cache: dict = {}


# ── Account Snapshot Writer ───────────────────────────────────────────────────
# 每次 AccountBalanceStreamer 轮询后将账户余额写入 account_snapshots 表。
# 这是 /profit 页面（www.hustle2026.xyz）数据的唯一来源。
# Go profit.go 查询 account_snapshots.daily_pnl 按时间段聚合绘图。

async def _write_account_snapshots(accounts: list) -> None:
    """Write account balance snapshots to account_snapshots table.

    Called by AccountBalanceStreamer after each polling cycle (every 300s).
    Provides historical daily_pnl data for the /profit chart page.

    Args:
        accounts: List of account dicts from get_aggregated_account_data,
                  each containing account_id and balance fields.
    """
    if not accounts:
        return

    from app.models.account_snapshot import AccountSnapshot as AccountSnapshotModel
    from app.core.database import AsyncSessionLocal
    import uuid as _uuid
    from datetime import datetime as _dt

    try:
        async with AsyncSessionLocal() as _db:
            for acc in accounts:
                account_id = acc.get("account_id")
                balance = acc.get("balance") or {}
                if not account_id:
                    continue

                # daily_pnl: unrealized_pnl for MT5, daily_pnl field for Binance
                # Both are set by account_service and reflect the current floating P&L
                daily_pnl = float(balance.get("daily_pnl") or balance.get("unrealized_pnl") or 0)

                snap = AccountSnapshotModel(
                    snapshot_id=_uuid.uuid4(),
                    account_id=_uuid.UUID(account_id),
                    total_assets=float(balance.get("total_assets") or 0),
                    available_assets=float(balance.get("available_balance") or 0),
                    net_assets=float(balance.get("net_assets") or 0),
                    total_position=float(balance.get("total_positions") or 0),
                    frozen_assets=float(balance.get("frozen_assets") or 0),
                    margin_balance=float(balance.get("margin_balance") or 0),
                    margin_used=float(balance.get("frozen_assets") or 0),
                    margin_available=float(balance.get("available_balance") or 0),
                    unrealized_pnl=float(balance.get("unrealized_pnl") or 0),
                    daily_pnl=daily_pnl,
                    risk_ratio=float(balance.get("risk_ratio") or 0),
                    timestamp=_dt.utcnow(),
                )
                _db.add(snap)

            await _db.commit()
            logger.debug(f"[AccountBalanceStreamer] Wrote {len(accounts)} account snapshots")
    except Exception as e:
        logger.warning(f"[AccountBalanceStreamer] _write_account_snapshots failed: {e}")

# ── Order Fill Watch Registry ─────────────────────────────────────────────────
# Used by order_executor_v2._monitor_binance_order to await WS fill events.
import asyncio as _asyncio

_order_fill_events = {}       # order_id -> asyncio.Event
_order_fill_registry = {}     # order_id -> {"filled_qty": float, "status": str}


def register_order_watch(order_id):
    """Register an asyncio.Event for an order. Returns the event to await."""
    evt = _asyncio.Event()
    _order_fill_events[order_id] = evt
    _order_fill_registry[order_id] = {}
    return evt


def unregister_order_watch(order_id):
    """Clean up after order monitoring completes."""
    _order_fill_events.pop(order_id, None)
    _order_fill_registry.pop(order_id, None)


def notify_order_fill(order_id, filled_qty, status):
    """Called by Binance WS stream when ORDER_TRADE_UPDATE arrives."""
    _order_fill_registry[order_id] = {
        "filled_qty": filled_qty,
        "status": status,
    }
    evt = _order_fill_events.get(order_id)
    if evt:
        evt.set()
