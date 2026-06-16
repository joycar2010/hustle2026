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
from app.core.platform import PlatformId, HEDGE_SIDE_IDS

async def _is_agent_active(db) -> bool:
    """Check if agent is active (not off/kill_switch). Risk alerts should only fire when agent is running."""
    try:
        from sqlalchemy import text
        row = (await db.execute(text("SELECT mode, kill_switch FROM agent_state WHERE id=1"))).first()
        if not row:
            return True
        mode, kill = row[0], row[1]
        if kill:
            return False
        if mode in ('off', None):
            return False
        return True
    except Exception:
        return True

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

                        # Binance 持仓同步已由 BinancePositionPusher WS 实时驱动，
                        # REST 轮询不再更新 PositionStreamer 缓存。

                        # 按用户推送 Python WS + Redis (Go WS)
                        _ab_msg = {"type": "account_balance", "data": aggregated_data}
                        await manager.send_to_user(_ab_msg, uid)
                        try:
                            from app.core.redis_client import redis_client as _rc_ab
                            if _rc_ab.client:
                                import json as _j_ab
                                await _rc_ab.publish("ws:user_event", _j_ab.dumps({
                                    "user_id": uid, **_ab_msg
                                }))
                        except Exception:
                            pass
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
                # Iterate each risk_settings row independently (one per user+pair_code)
                for risk_settings in risk_settings_list:
                    user_id = str(risk_settings.user_id)
                    pair_code = getattr(risk_settings, "pair_code", "XAU") or "XAU"
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

                        if not any(v is not None for v in alert_settings.values()):
                            continue

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
                        logger.error(f"Error checking spread alerts for user {user_id} pair {pair_code}: {e}")

        except asyncio.TimeoutError:
            logger.error(f"Timeout in _check_spread_alerts")
        except Exception as e:
            logger.error(f"Error in _check_spread_alerts: {e}")


class RiskMetricsStreamer:
    """Background task for streaming risk metrics updates"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 60  # 30->60 降频防币安限频
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
                        _rm_msg = {"type": "risk_metrics", "data": risk_data}
                        await manager.send_to_user(_rm_msg, uid)
                        try:
                            from app.core.redis_client import redis_client as _rc_rm
                            if _rc_rm.client:
                                import json as _j_rm
                                await _rc_rm.publish("ws:user_event", _j_rm.dumps({
                                    "user_id": uid, **_rm_msg
                                }))
                        except Exception:
                            pass
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

            # 连接池护栏：先在会话外完成各用户聚合（数秒级交易所/MT5 I/O，且通常命中
            # account_data_service 缓存），再开短会话做 risk_settings 查询与告警写入，
            # 避免持有 DB 连接跨网络 I/O（idle-in-transaction 打爆连接池）。
            agg_by_user = {}
            for _uid, _accs in user_accounts.items():
                try:
                    _user_accs = user_accounts_map.get(_uid, _accs)
                    agg_by_user[_uid] = await account_data_service.get_aggregated_account_data(list(_user_accs))
                except Exception as _agg_e:
                    logger.warning(f"[BROADCAST] risk-alert aggregate failed for {_uid}: {_agg_e}")

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

                        # 聚合数据已在会话外预取（见上），直接取用，避免持有 DB 连接跨网络 I/O
                        aggregated_data = agg_by_user.get(user_id)
                        if not aggregated_data:
                            continue

                        # Initialize risk alert service
                        risk_alert_service = RiskAlertService(db)

                        # Get account data for this user
                        summary = aggregated_data.get("summary", {})

                        # Detect failed accounts — skip alerts for platforms with fetch failures
                        _failed_platforms = set()
                        for _fa in aggregated_data.get("failed_accounts", []):
                            _fa_pid = _fa.get("platform_id")
                            if _fa_pid:
                                _failed_platforms.add(_fa_pid)
                        if _failed_platforms:
                            logger.warning(f"[BROADCAST] user={user_id} has failed account fetches on platforms={_failed_platforms}, skipping those alerts")

                        # Check Binance net asset
                        if risk_settings.binance_net_asset:
                            if 1 in _failed_platforms:
                                logger.info(f"[BROADCAST] user={user_id} skipping binance_net_asset alert — Binance data fetch failed (proxy/network)")
                            else:
                                # Find Binance account in the aggregated data
                                binance_account = next(
                                    (acc for acc in aggregated_data.get("accounts", [])
                                     if PlatformId.from_key(acc.get("platform_id")) == PlatformId.BINANCE),
                                    None
                                )
                                if binance_account:
                                    binance_asset = binance_account["balance"]["net_assets"]
                                    logger.info(f"[BROADCAST] Checking binance net_assets: user_id={user_id}, binance={binance_asset}, threshold={risk_settings.binance_net_asset}")
                                    if binance_asset < risk_settings.binance_net_asset:
                                        await risk_alert_service.check_binance_net_asset(
                                            user_id=user_id,
                                            current_asset=binance_asset,
                                            threshold=risk_settings.binance_net_asset,
                                            is_below=True
                                        )
                                else:
                                    logger.warning(f"[BROADCAST] user={user_id} binance 阈值已配置(={risk_settings.binance_net_asset}) 但聚合数据中未找到 Binance 账户,告警无法触发")

                        # Check Bybit net asset
                        if risk_settings.bybit_mt5_net_asset:
                            _hedge_failed = any(pid in _failed_platforms for pid in HEDGE_SIDE_IDS)
                            if _hedge_failed:
                                logger.info(f"[BROADCAST] user={user_id} skipping bybit_net_asset alert — hedge-side data fetch failed")
                            else:
                                # Find Bybit/MT5-hedge account in the aggregated data
                                bybit_account = next(
                                    (acc for acc in aggregated_data.get("accounts", [])
                                     if (PlatformId.from_key(acc.get("platform_id")) or 0) in HEDGE_SIDE_IDS),
                                    None
                                )
                                if bybit_account:
                                    bybit_asset = bybit_account["balance"]["net_assets"]
                                    logger.info(f"[BROADCAST] Checking bybit/mt5 net_assets: user_id={user_id}, bybit={bybit_asset}, threshold={risk_settings.bybit_mt5_net_asset}")
                                    if bybit_asset < risk_settings.bybit_mt5_net_asset:
                                        await risk_alert_service.check_bybit_net_asset(
                                            user_id=user_id,
                                            current_asset=bybit_asset,
                                            threshold=risk_settings.bybit_mt5_net_asset,
                                            is_below=True
                                        )
                                else:
                                    logger.warning(f"[BROADCAST] user={user_id} bybit/mt5 阈值已配置(={risk_settings.bybit_mt5_net_asset}) 但聚合数据中未找到对冲账户,告警无法触发")

                        # Check total net asset
                        if risk_settings.total_net_asset:
                            if _failed_platforms:
                                logger.info(f"[BROADCAST] user={user_id} skipping total_net_asset alert — partial data (failed platforms={_failed_platforms})")
                            else:
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

                        # Per-account liquidation proximity alert with per-pair isolation
                        # Read user-configured threshold from risk_settings (default 1.5%)
                        _DEFAULT_LIQ_PCT = 0.015
                        try:
                            _rs_result = await db.execute(
                                select(RiskSettings).where(RiskSettings.user_id == uid)
                            )
                            _all_rs = {rs.pair_code: rs for rs in _rs_result.scalars().all()}
                        except Exception:
                            _all_rs = {}

                        # Check each account's liquidation prices against market
                        for _acc_data in aggregated_data.get("accounts", []):
                            _acc_bal = _acc_data.get("balance", {})
                            _acc_pair = _acc_data.get("pair_code")
                            if not _acc_pair:
                                continue
                            _acc_pid = _acc_data.get("platform_id")
                            _is_binance = _acc_pid == 1
                            _is_mt5 = _acc_data.get("is_mt5_account") and _acc_pid in (2, 3)
                            if not _is_binance and not _is_mt5:
                                continue

                            _plat_label = f"主账号(Binance)" if _is_binance else f"对冲账号(MT5)"
                            _market_price = summary.get("binance_current_price" if _is_binance else "bybit_current_price")
                            if not _market_price or _market_price <= 0:
                                continue

                            # Get threshold from risk_settings for this pair
                            _rs = _all_rs.get(_acc_pair)
                            if _is_binance and _rs and _rs.binance_liquidation_price and _rs.binance_liquidation_price > 0:
                                _threshold = _rs.binance_liquidation_price / 100.0
                            elif _is_mt5 and _rs and _rs.bybit_mt5_liquidation_price and _rs.bybit_mt5_liquidation_price > 0:
                                _threshold = _rs.bybit_mt5_liquidation_price / 100.0
                            else:
                                _threshold = _DEFAULT_LIQ_PCT

                            for _dir, _liq_key in [("多头", "long_liquidation_price"), ("空头", "short_liquidation_price")]:
                                _liq = _acc_bal.get(_liq_key, 0)
                                if not _liq or _liq <= 0:
                                    continue
                                _dist = abs(_market_price - _liq) / _market_price
                                if _dist < _threshold:
                                    _pct = round(_dist * 100, 2)
                                    _thr_pct = round(_threshold * 100, 1)
                                    logger.critical(
                                        f"[LIQUIDATION DANGER] user={uid} pair={_acc_pair} {_plat_label} {_dir}: "
                                        f"price={_market_price:.2f}, liq={_liq:.2f}, distance={_pct}% < {_thr_pct}%"
                                    )
                                    try:
                                        from app.services.agent.feishu_broadcast import broadcast as _fb
                                        await _fb(
                                            db,
                                            level='critical',
                                            category='liquidation_danger_system',
                                            message=(
                                                f"⚠️ 市场接近危险！\n"
                                                f"产品对: {_acc_pair}\n"
                                                f"{_plat_label} {_dir}强平价距离仅 {_pct}%\n"
                                                f"当前价: {_market_price:.2f}\n"
                                                f"强平价: {_liq:.2f}\n"
                                                f"阈值设定: {_thr_pct}%\n"
                                                f"请立即检查仓位风险！"
                                            ),
                                            owner_user_id=uid,
                                            pair_code=_acc_pair,
                                            cooldown_s=120,
                                        )
                                    except Exception as _fe:
                                        logger.error(f"[LIQUIDATION DANGER] feishu broadcast error: {_fe}")

                        # Check funding/overnight alerts — iterate ALL pair_code rows
                        # (risk_settings_map only contains one row per user, but the
                        # underlying list may have multiple per pair. Re-query from list.)
                        _all_user_settings = [_rs for _rs in risk_settings_list if str(_rs.user_id) == user_id]
                        for _rs_pair in _all_user_settings:
                            _pair = getattr(_rs_pair, 'pair_code', 'XAU') or 'XAU'
                            _f_short = getattr(_rs_pair, 'funding_rate_threshold', None)
                            _f_long = getattr(_rs_pair, 'funding_rate_threshold_long', None)
                            if _f_short is not None or _f_long is not None:
                                try:
                                    await risk_alert_service.check_funding_rate(
                                        user_id=user_id,
                                        threshold_short=_f_short,
                                        threshold_long=_f_long,
                                        pair_code=_pair,
                                    )
                                except Exception as e:
                                    logger.error(f"[BROADCAST] funding_rate alert error user={user_id} pair={_pair}: {e}")

                            _o_short = getattr(_rs_pair, 'overnight_fee_threshold', None)
                            _o_long = getattr(_rs_pair, 'overnight_fee_threshold_long', None)
                            if _o_short is not None or _o_long is not None:
                                try:
                                    await risk_alert_service.check_overnight_fee(
                                        user_id=user_id,
                                        threshold_short=_o_short,
                                        threshold_long=_o_long,
                                        pair_code=_pair,
                                    )
                                except Exception as e:
                                    logger.error(f"[BROADCAST] overnight_fee alert error user={user_id} pair={_pair}: {e}")

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
        self.interval = 60  # 30->60 降频防币安限频
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
                # Check MT5 connection status
                mt5_status = await self._check_mt5_status()

                _msg = {"type": "mt5_connection_status", "data": mt5_status}
                # Broadcast to Python WS clients (if any)
                if manager.get_connection_count() > 0:
                    await manager.broadcast(_msg)
                # Always publish to Redis for Go WS clients
                try:
                    from app.core.redis_client import redis_client as _rc_mt5
                    if _rc_mt5.client:
                        import json as _j_mt5
                        await _rc_mt5.publish("ws:broadcast", _j_mt5.dumps(_msg))
                except Exception:
                    pass
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
        self.interval = 10  # 2->10 降频防币安限频
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    def update_interval(self, new_interval):
        if 1 <= new_interval <= 30:
            self.interval = new_interval
            return True
        return False

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
                # Fetch pending orders across all REST-capable platforms
                # (binance/bybit/gateio/okx). IC Markets (MT5-only) pending
                # orders flow through the position stream, not this one.
                try:
                    from app.models.account import Account
                    from app.core.database import AsyncSessionLocal
                    from app.services.binance_client import BinanceFuturesClient
                    from app.services.bybit_client import BybitV5Client
                    from app.services.gateio_client import GateioFuturesClient
                    from app.services.okx_client import OKXClient
                    from app.utils.time_utils import utc_ms_to_beijing
                    from app.core.proxy_utils import build_proxy_url
                    from sqlalchemy import select

                    # Query every active REST-capable account.
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(Account).where(
                                Account.platform_id.in_([1, 2, 4, 5]),
                                Account.is_active == True,
                            )
                        )
                        accounts = result.scalars().all()
                        # 连接池护栏：db 仅用于上面的账户查询；下面是逐账户交易所 REST 拉取(慢)。
                        # 立即归还连接，避免持有跨网络 I/O 超过 PG idle_in_transaction_session_timeout(2min)
                        # 被杀（"connection is closed"）。__aexit__ 再次 close 幂等无害；
                        # expire_on_commit=False，关闭后账户 ORM 已加载列仍可安全读取。
                        await db.close()

                        # Skip MT5 accounts even if platform_id==2 (Bybit row
                        # occasionally used as the MT5 parent row).
                        accounts = [a for a in accounts if not getattr(a, "is_mt5_account", False)]

                        # Group by user_id
                        user_accounts: dict = {}
                        for account in accounts:
                            uid = str(account.user_id)
                            user_accounts.setdefault(uid, []).append(account)

                        async def _fetch_binance(account):
                            out = []
                            client = BinanceFuturesClient(
                                account.api_key, account.api_secret,
                                proxy_url=build_proxy_url(account.proxy_config)
                            )
                            try:
                                sym_a, _ = _get_pair_symbols()
                                open_orders = await client.get_open_orders(symbol=sym_a)
                                for order in open_orders:
                                    out.append({
                                        "id": str(order.get("orderId")),
                                        "timestamp": utc_ms_to_beijing(order.get("time", 0) or 0),
                                        "exchange": "主账号",
                                        "platform": "binance",
                                        "side": str(order.get("side", "")).lower(),
                                        "quantity": float(order.get("origQty", 0) or 0),
                                        "price": float(order.get("price", 0) or 0),
                                        "status": str(order.get("status", "")).lower(),
                                        "symbol": order.get("symbol", ""),
                                        "source": "strategy",
                                    })
                            finally:
                                await client.close()
                            return out

                        async def _fetch_bybit(account):
                            out = []
                            client = BybitV5Client(
                                account.api_key, account.api_secret,
                                proxy_url=build_proxy_url(account.proxy_config)
                            )
                            try:
                                resp = await client.get_open_orders(category="linear", limit=50)
                                rows = (resp or {}).get("result", {}).get("list", []) or []
                                for order in rows:
                                    try:
                                        ct = int(order.get("createdTime") or 0)
                                    except (TypeError, ValueError):
                                        ct = 0
                                    out.append({
                                        "id": str(order.get("orderId", "")),
                                        "timestamp": utc_ms_to_beijing(ct),
                                        "exchange": "主账号",
                                        "platform": "bybit",
                                        "side": str(order.get("side", "")).lower(),
                                        "quantity": float(order.get("qty", 0) or 0),
                                        "price": float(order.get("price", 0) or 0),
                                        "status": str(order.get("orderStatus", "")).lower(),
                                        "symbol": order.get("symbol", ""),
                                        "source": "strategy",
                                    })
                            finally:
                                await client.close()
                            return out

                        async def _fetch_gateio(account):
                            out = []
                            client = GateioFuturesClient(
                                api_key=account.api_key, api_secret=account.api_secret,
                                proxy_url=build_proxy_url(account.proxy_config),
                            )
                            try:
                                rows = await client.list_open_orders(contract=None, limit=100)
                                for order in rows or []:
                                    ct = int(order.get("create_time", 0) or 0) * 1000
                                    size_raw = order.get("size", 0)
                                    try:
                                        sz = float(size_raw)
                                    except (TypeError, ValueError):
                                        sz = 0.0
                                    side = "buy" if sz > 0 else "sell" if sz < 0 else ""
                                    out.append({
                                        "id": str(order.get("id", "")),
                                        "timestamp": utc_ms_to_beijing(ct),
                                        "exchange": "主账号",
                                        "platform": "gateio",
                                        "side": side,
                                        "quantity": abs(sz),
                                        "price": float(order.get("price", 0) or 0),
                                        "status": str(order.get("status", "")).lower(),
                                        "symbol": order.get("contract", ""),
                                        "source": "strategy",
                                    })
                            finally:
                                await client.close()
                            return out

                        async def _fetch_okx(account):
                            out = []
                            passphrase = getattr(account, "passphrase", None) or ""
                            client = OKXClient(
                                account.api_key, account.api_secret, passphrase,
                                proxy_url=build_proxy_url(account.proxy_config),
                            )
                            try:
                                rows = []
                                for inst_type in ("SWAP", "FUTURES"):
                                    chunk = await client.get_open_orders(
                                        inst_id=None, inst_type=inst_type, limit=100
                                    )
                                    rows.extend(chunk)
                                for order in rows:
                                    try:
                                        ct_ms = int(order.get("cTime", 0) or 0)
                                    except (TypeError, ValueError):
                                        ct_ms = 0
                                    out.append({
                                        "id": str(order.get("ordId", "")),
                                        "timestamp": utc_ms_to_beijing(ct_ms),
                                        "exchange": "主账号",
                                        "platform": "okx",
                                        "side": str(order.get("side", "")).lower(),
                                        "quantity": float(order.get("sz", 0) or 0),
                                        "price": float(order.get("px", 0) or 0),
                                        "status": str(order.get("state", "")).lower(),
                                        "symbol": order.get("instId", ""),
                                        "source": "strategy",
                                    })
                            finally:
                                await client.close()
                            return out

                        _DISPATCH = {1: _fetch_binance, 2: _fetch_bybit,
                                     4: _fetch_gateio, 5: _fetch_okx}

                        for uid, user_accs in user_accounts.items():
                            user_orders = []
                            for account in user_accs:
                                fetcher = _DISPATCH.get(account.platform_id)
                                if not fetcher:
                                    continue
                                try:
                                    user_orders.extend(await fetcher(account))
                                except Exception as e:
                                    logger.error(
                                        f"Failed to fetch orders for account "
                                        f"{account.account_id} (pid={account.platform_id}): {e}"
                                    )
                            user_orders.sort(key=lambda x: x["timestamp"], reverse=True)
                            _po_msg = {
                                "type": "pending_orders",
                                "data": user_orders[:20],
                            }
                            if manager.get_connection_count() > 0:
                                await manager.send_to_user(_po_msg, uid)
                            try:
                                from app.core.redis_client import redis_client as _rc_po
                                if _rc_po.client:
                                    import json as _j_po
                                    await _rc_po.publish("ws:user_event", _j_po.dumps({
                                        "user_id": uid, **_po_msg
                                    }))
                            except Exception:
                                pass
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


class PnlFastStreamer:
    """高频推送浮动盈亏(平台权威)+ 当日返佣后净利润, 供 MarketCards 实时刷新(WS, 前端零REST)。
    浮盈每 interval(默认5s);净利润每 net_every 轮(≈10s)重算并缓存。"""
    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 15  # 5->15 降频防币安限频
        self.net_every = 2
        self._net_cache = {}
        self._cycle = 0

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info(f"PnlFastStreamer started (interval: {self.interval}s, net every {self.net_every} cycles)")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self.running:
            try:
                await asyncio.sleep(self.interval)
                self._cycle += 1
                do_net = (self._cycle % self.net_every == 1)
                async with get_db_session(timeout=5.0) as db:
                    _res = await asyncio.wait_for(db.execute(select(Account).where(Account.is_active == True)), timeout=3.0)
                    active_accounts = _res.scalars().all()
                if not active_accounts:
                    continue
                user_map = {}
                for acc in active_accounts:
                    user_map.setdefault(str(acc.user_id), []).append(acc)
                for uid, accs in user_map.items():
                    try:
                        # 绕过 60s 缓存: 仅失效本用户账户缓存(其他用户不受影响), 取真·当前平台浮盈
                        for _a in accs:
                            try:
                                account_data_service.invalidate_cache(str(_a.account_id))
                            except Exception:
                                pass
                        agg = await account_data_service.get_aggregated_account_data(list(accs))
                        upbp = {}
                        for a in (agg.get('accounts') or []):
                            pid = a.get('platform_id')
                            up = (a.get('balance') or {}).get('unrealized_pnl')
                            if pid is not None and up is not None:
                                upbp[str(pid)] = round(float(upbp.get(str(pid), 0.0)) + float(up), 4)
                        if do_net:
                            try:
                                from app.api.v1.trading import compute_daily_net_profit
                                async with get_db_session(timeout=8.0) as _db2:
                                    _net = await compute_daily_net_profit(list(accs), 'XAU', _db2)
                                self._net_cache[uid] = _net
                            except Exception as _ne:
                                logger.debug(f"[PnlFast] net calc {uid} skip: {_ne}")
                            try:
                                from app.api.v1.trading import reconcile_open_ledger_spreads
                                async with get_db_session(timeout=10.0) as _db3:
                                    await reconcile_open_ledger_spreads(list(accs), 'XAU', _db3)
                            except Exception as _re:
                                logger.debug(f"[PnlFast] ledger reconcile {uid} skip: {_re}")
                        msg = {'type': 'pnl_fast', 'data': {
                            'unrealized_by_platform': upbp,
                            'daily_net_profit': self._net_cache.get(uid),
                            'pair_code': 'XAU',
                        }}
                        await manager.send_to_user(msg, uid)
                        try:
                            from app.core.redis_client import redis_client as _rc_pf
                            if _rc_pf.client:
                                import json as _j_pf
                                await _rc_pf.publish('ws:user_event', _j_pf.dumps({'user_id': uid, **msg}))
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"[PnlFast] user {uid} error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PnlFast] loop error: {e}")
                await asyncio.sleep(self.interval)


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
    _user_bridges_cache: list = None   # [(user_id, bridge_url), ...]
    _user_bridges_cache_at: float = 0.0
    USER_BRIDGES_CACHE_TTL: float = 30.0  # seconds

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = self.BROADCAST_INTERVAL
        self.broadcast_count = 0
        self.error_count = 0
        self.last_broadcast_time = None
        # Binance 持仓缓存，按 user_id → symbol 双层隔离
        # 结构: {user_id: {symbol: (long, short)}}
        self._binance_positions: dict = {}
        # MT5 last-known-good cache: prevents flicker when bridge read times out.
        # Structure same as _binance_positions: {user_id: {symbol: (long, short)}}
        self._mt5_lkg: dict = {}

    def get_stats(self):
        return {
            "running": self.running,
            "interval": self.interval,
            "broadcast_count": self.broadcast_count,
            "error_count": self.error_count,
            "last_broadcast_time": self.last_broadcast_time,
        }

    def update_interval(self, new_interval):
        if 0.1 <= new_interval <= 30.0:
            self.BROADCAST_INTERVAL = new_interval
            self.interval = new_interval
            return True
        return False

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

    def set_mt5_positions(self, long_lots: float, short_lots: float,
                           user_id: str = None, symbol: str = None) -> None:
        """Inject MT5 positions into LKG cache (called by continuous_executor after trade)."""
        if user_id and symbol:
            if user_id not in self._mt5_lkg:
                self._mt5_lkg[user_id] = {}
            self._mt5_lkg[user_id][symbol] = (long_lots, short_lots)

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

                # 1. Read MT5 positions per-user: {user_id: {symbol: (long, short)}}
                mt5_by_user_raw = await self._read_mt5_positions_all()
                # Merge with last-known-good: if a user had data before but
                # this read returned empty (bridge timeout), keep the old values.
                # This prevents 0-flicker on transient failures.
                for _uid, _syms in mt5_by_user_raw.items():
                    if _syms is not None:
                        self._mt5_lkg[_uid] = dict(_syms)
                mt5_by_user = {}
                for _uid in set(list(mt5_by_user_raw.keys()) + list(self._mt5_lkg.keys())):
                    raw = mt5_by_user_raw.get(_uid)
                    lkg = self._mt5_lkg.get(_uid, {})
                    mt5_by_user[_uid] = raw if raw is not None else lkg

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
                        pairs_map[pair.pair_code] = {"sym_a": sym_a, "sym_b": sym_b}
                except Exception as _pe:
                    logger.debug(f"[PositionStreamer] pairs_map error: {_pe}")

                # 3. Union of all known users (Binance cache OR MT5 owners)
                all_uids = set(self._binance_positions.keys()) | set(mt5_by_user.keys())
                all_uids.discard("_default")

                # 4. Per-user, per-pair payload — strict isolation by user_id + pair_code
                for uid in all_uids:
                    bn_syms = self._binance_positions.get(uid, {})
                    mt5_syms = mt5_by_user.get(uid, {})
                    pairs_out = {}
                    for pair_code, pd in pairs_map.items():
                        sym_a = pd["sym_a"]
                        sym_b = pd["sym_b"]
                        bn_l, bn_s = bn_syms.get(sym_a, (0.0, 0.0))
                        mt5_l, mt5_s = mt5_syms.get(sym_b, (0.0, 0.0))
                        if mt5_l == 0.0 and mt5_s == 0.0:
                            alt = sym_b.replace("+", ".s")
                            mt5_l, mt5_s = mt5_syms.get(alt, (0.0, 0.0))
                        if mt5_l == 0.0 and mt5_s == 0.0 and "+" in sym_b:
                            mt5_l, mt5_s = mt5_syms.get(sym_b.replace("+", ""), (0.0, 0.0))
                        pairs_out[pair_code] = {
                            "mt5_long": mt5_l, "mt5_short": mt5_s,
                            "binance_long": bn_l, "binance_short": bn_s,
                        }
                    _primary_pd = {}
                    for _pc, _pd in pairs_out.items():
                        if _pd.get("binance_long", 0) != 0 or _pd.get("binance_short", 0) != 0:
                            _primary_pd = _pd
                            break
                    if not _primary_pd and pairs_out:
                        _primary_pd = next(iter(pairs_out.values()))
                    evt = {
                        "user_id": uid, "type": "position_snapshot",
                        "data": {
                            "bybit_long_lots":  _primary_pd.get("mt5_long", 0.0),
                            "bybit_short_lots": _primary_pd.get("mt5_short", 0.0),
                            "binance_long_xau": _primary_pd.get("binance_long", 0.0),
                            "binance_short_xau": _primary_pd.get("binance_short", 0.0),
                            "pairs": pairs_out,
                        }
                    }
                    await _rc.publish("ws:user_event", _json.dumps(evt))

                from datetime import datetime as _dt_pos
                self.broadcast_count += 1
                self.last_broadcast_time = _dt_pos.now().isoformat()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_count += 1
                logger.error(f"[PositionStreamer] loop error: {e}", exc_info=True)
                await asyncio.sleep(2)


    async def push_snapshot_for_user(self, user_id: str) -> None:
        """Push a fresh per-user position_snapshot via Redis on demand.

        Called by snapshot_request_listener when the Go Hub forwards a
        client-initiated `request_snapshot` command. Reads MT5 from THIS
        user\'s bridges only — strict user_id isolation.
        """
        if not user_id:
            return
        user_id = str(user_id)
        try:
            import json as _json
            from app.core.redis_client import redis_client as _rc

            mt5_by_user = await self._read_mt5_positions_all()
            mt5_syms = mt5_by_user.get(user_id, {})
            bn_syms = self._binance_positions.get(user_id, {})

            pairs_meta = {}
            try:
                from app.services.hedging_pair_service import hedging_pair_service
                for pair in (hedging_pair_service.list_active_pairs() or []):
                    if not pair.is_active:
                        continue
                    sa = pair.symbol_a.symbol if pair.symbol_a else None
                    sb = pair.symbol_b.symbol if pair.symbol_b else None
                    if sa and sb:
                        pairs_meta[pair.pair_code] = {"sym_a": sa, "sym_b": sb}
            except Exception:
                pass

            pairs_out = {}
            for pc, meta in pairs_meta.items():
                sa, sb = meta["sym_a"], meta["sym_b"]
                bn_l, bn_s = bn_syms.get(sa, (0.0, 0.0))
                mt5_l, mt5_s = mt5_syms.get(sb, (0.0, 0.0))
                if mt5_l == 0.0 and mt5_s == 0.0:
                    alt = sb.replace("+", ".s")
                    mt5_l, mt5_s = mt5_syms.get(alt, (0.0, 0.0))
                if mt5_l == 0.0 and mt5_s == 0.0 and "+" in sb:
                    mt5_l, mt5_s = mt5_syms.get(sb.replace("+", ""), (0.0, 0.0))
                pairs_out[pc] = {
                    "mt5_long": mt5_l, "mt5_short": mt5_s,
                    "binance_long": bn_l, "binance_short": bn_s,
                }

            _primary_pd = {}
            for _pc, _pd in pairs_out.items():
                if _pd.get("binance_long", 0) != 0 or _pd.get("binance_short", 0) != 0:
                    _primary_pd = _pd
                    break
            if not _primary_pd and pairs_out:
                _primary_pd = next(iter(pairs_out.values()))
            evt = {
                "user_id": user_id, "type": "position_snapshot",
                "data": {
                    "bybit_long_lots":  _primary_pd.get("mt5_long", 0.0),
                    "bybit_short_lots": _primary_pd.get("mt5_short", 0.0),
                    "binance_long_xau": _primary_pd.get("binance_long", 0.0),
                    "binance_short_xau": _primary_pd.get("binance_short", 0.0),
                    "pairs": pairs_out,
                }
            }
            await _rc.publish("ws:user_event", _json.dumps(evt))
            logger.info(f"[PositionStreamer] On-demand snapshot pushed user={user_id}")
        except Exception as e:
            logger.warning(f"[PositionStreamer] push_snapshot_for_user error: {e}")

    # ------------------------------------------------------------------
    # MT5 持仓读取 — 无 symbol 过滤，返回所有持仓
    # ------------------------------------------------------------------
    async def _read_mt5_positions_all(self) -> dict:
        """Read positions from each active MT5 bridge, grouped by user_id.

        Returns: {user_id: {symbol: (long, short)}}

        Each non-system mt5_clients row maps 1:1 to a trading account, and the
        owning user_id is resolved via accounts.user_id. This guarantees per-user
        isolation — no user can ever see another user's MT5 positions.
        """
        result: dict = {}
        try:
            import httpx, os
            api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))
            headers = {"X-Api-Key": api_key} if api_key else {}

            # (user_id, bridge_url) tuples — every active non-system bridge.
            # Cached for 30s to avoid hammering the DB every second; the bridge
            # set only changes when accounts are added/removed.
            import time as _time
            now = _time.monotonic()
            if (PositionStreamer._user_bridges_cache is not None and
                    now - PositionStreamer._user_bridges_cache_at < PositionStreamer.USER_BRIDGES_CACHE_TTL):
                bridges = list(PositionStreamer._user_bridges_cache)
            else:
                bridges = []
                try:
                    from sqlalchemy import text as _text
                    async with AsyncSessionLocal() as _db:
                        rows = await _db.execute(_text(
                            "SELECT a.user_id::text, mc.bridge_url, mc.bridge_service_port "
                            "FROM mt5_clients mc JOIN accounts a ON mc.account_id = a.account_id "
                            "WHERE mc.is_active = true AND mc.is_system_service = false"
                        ))
                        for row in rows.fetchall():
                            uid = row[0]
                            url = row[1] or (f"http://172.31.14.113:{row[2]}" if row[2] else None)
                            if uid and url:
                                bridges.append((uid, url))
                    PositionStreamer._user_bridges_cache = list(bridges)
                    PositionStreamer._user_bridges_cache_at = now
                except Exception as e:
                    logger.debug(f"[PositionStreamer] bridge query error: {e}")

            if not bridges:
                return result

            async def _fetch_one(uid: str, url: str):
                try:
                    # 复用共享 AsyncClient(防每秒×N桥反复构建SSL上下文阻塞事件循环)
                    from app.core.shared_http import get_shared_async_client
                    cli = get_shared_async_client()
                    resp = await cli.get(f"{url}/mt5/positions", headers=headers, timeout=3.0)
                    if resp.status_code != 200:
                        return uid, None  # bridge error → signal LKG fallback
                    positions = resp.json().get("positions", [])
                except Exception as e:
                    logger.debug(f"[PositionStreamer] Bridge {url} (user {uid}) error: {e}")
                    return uid, None
                acc: dict = {}
                for p in positions:
                    sym = p.get("symbol", "")
                    if not sym:
                        continue
                    vol = float(p.get("volume", 0))
                    typ = p.get("type", -1)
                    if sym not in acc:
                        acc[sym] = [0.0, 0.0]
                    if typ == 0:
                        acc[sym][0] += vol
                    elif typ == 1:
                        acc[sym][1] += vol
                return uid, {s: (round(v[0], 4), round(v[1], 4)) for s, v in acc.items()}

            # Concurrent fetch across all user bridges
            results = await asyncio.gather(
                *[_fetch_one(u, url) for u, url in bridges],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    continue
                uid, syms = r
                if syms is None:
                    # Bridge error — mark uid present but with None so LKG logic can distinguish
                    if uid not in result:
                        result[uid] = None
                    continue
                if result.get(uid) is None:
                    result[uid] = {}
                if uid not in result:
                    result[uid] = {}
                # Merge — a user may own multiple bridges (multiple MT5 accounts)
                for s, (l, sh) in syms.items():
                    if s in result[uid]:
                        prev_l, prev_s = result[uid][s]
                        result[uid][s] = (round(prev_l + l, 4), round(prev_s + sh, 4))
                    else:
                        result[uid][s] = (l, sh)
            return result
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
            from app.core.shared_http import get_shared_async_client
            client = get_shared_async_client()
            if True:
                resp = await client.get(f"{bridge_url}/mt5/positions", params={"symbol": sym_b}, headers=headers, timeout=5.0)
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



class MarketRateStreamer:
    """每 10 秒广播资金费率 + 过夜费率到所有客户端 (ws:broadcast)"""

    INTERVAL = 10.0

    def __init__(self):
        self.running = False
        self._task = None

    async def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[MarketRateStreamer] started (interval={self.INTERVAL}s)")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[MarketRateStreamer] stopped")

    async def _fetch_funding_rate(self):
        try:
            from app.services.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient("", "")
            try:
                data = await client.get_premium_index("XAUUSDT")
            finally:
                await client.close()
            fr = float(data.get("lastFundingRate", 0))
            mp = float(data.get("markPrice", 0))
            cpl = round(fr * mp, 4)
            return {
                "funding_rate": fr,
                "funding_rate_pct": round(fr * 100, 6),
                "mark_price": mp,
                "next_funding_time": int(data.get("nextFundingTime", 0)),
                "long_cost_per_lot": cpl,
                "short_cost_per_lot": -cpl,
            }
        except Exception as e:
            logger.warning(f"[MarketRateStreamer] funding rate error: {e}")
            return None

    async def _fetch_swap_rate(self):
        try:
            from app.core.shared_http import get_shared_async_client
            client = get_shared_async_client()
            if True:
                resp = await client.get(
                    "http://172.31.14.113:8001/mt5/symbol_info/XAUUSD+",
                    headers={"X-API-Key": "OQ6bUimHZDmXEZzJKE"},
                    timeout=5.0,
                )
                if resp.status_code != 200:
                    logger.warning(f"[MarketRateStreamer] swap rate HTTP {resp.status_code}")
                    return None
                info = resp.json()
                swap_long = info.get("swap_long", 0)
                swap_short = info.get("swap_short", 0)
                return {
                    "long_swap_per_lot": round(swap_long / 100, 4),
                    "short_swap_per_lot": round(swap_short / 100, 4),
                }
        except Exception as e:
            logger.warning(f"[MarketRateStreamer] swap rate error: {e}")
            return None

    async def _loop(self):
        from app.core.redis_client import redis_client as _rc
        import json as _json

        await asyncio.sleep(2)  # let other services init
        while self.running:
            try:
                funding = await self._fetch_funding_rate()
                swap = await self._fetch_swap_rate()
                evt = {
                    "type": "market_rates",
                    "data": {
                        "funding": funding,
                        "swap": swap,
                    }
                }
                await _rc.publish("ws:broadcast", _json.dumps(evt))
            except Exception as e:
                logger.error(f"[MarketRateStreamer] loop error: {e}")
            await asyncio.sleep(self.INTERVAL)


market_rate_streamer = MarketRateStreamer()
pnl_fast_streamer = PnlFastStreamer()


class QuoteDivergenceMonitor:
    """实时比对 ICMarkets XAUUSD 与 Bybit XAUUSD+ 中间价；背离>=trip 暂停下单、<=recover 恢复。
    迟滞状态机；写 Redis quote_divergence:state（executor 软暂停闸门读取）+ 广播 ws:broadcast。"""

    _CFG_PATH = '/data/hustle2026/backend/config/quote_divergence.json'
    _DEFAULTS = {
        "enabled": True,
        "ic_url": "http://172.31.14.113:8021", "ic_symbol": "XAUUSD",
        "ref_url": "http://172.31.14.113:8001", "ref_symbol": "XAUUSD+",
        "api_key": "OQ6bUimHZDmXEZzJKE",
        "trip": 0.7, "recover": 0.3,
        "poll_sec": 0.5, "stale_sec": 5, "heartbeat_sec": 3.0,
    }

    def __init__(self):
        self.running = False
        self._task = None
        self.diverged = False
        self._last_broadcast = 0.0

    def _load_cfg(self):
        import json as _json
        c = dict(self._DEFAULTS)
        try:
            with open(self._CFG_PATH, "r", encoding="utf-8") as f:
                data = _json.load(f)
                if isinstance(data, dict):
                    c.update(data)
        except Exception:
            pass
        return c

    async def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[QuoteDivergenceMonitor] started")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[QuoteDivergenceMonitor] stopped")

    async def _fetch_mid(self, client, url, symbol, api_key):
        resp = await client.get(f"{url}/mt5/tick/{symbol}", headers={"X-API-Key": api_key})
        if resp.status_code != 200:
            return None
        d = resp.json()
        bid = float(d.get("bid") or 0)
        ask = float(d.get("ask") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        last = float(d.get("last") or 0)
        return last if last > 0 else None

    async def _loop(self):
        from app.core.redis_client import redis_client as _rc
        import httpx, json as _json, time as _time
        await asyncio.sleep(3)  # let services init
        while self.running:
            cfg = self._load_cfg()
            poll = float(cfg.get("poll_sec", 0.5))
            if not cfg.get("enabled", True):
                try:
                    await _rc.set("quote_divergence:state",
                                  _json.dumps({"diverged": False, "disabled": True, "ts": _time.time()}), ex=10)
                except Exception:
                    pass
                await asyncio.sleep(max(1.0, poll))
                continue
            try:
                trip = float(cfg.get("trip", 0.7))
                recover = float(cfg.get("recover", 0.3))
                api_key = cfg.get("api_key", "OQ6bUimHZDmXEZzJKE")
                from app.core.shared_http import get_shared_async_client
                client = get_shared_async_client()
                if True:
                    ic_mid, ref_mid = await asyncio.gather(
                        self._fetch_mid(client, cfg["ic_url"], cfg["ic_symbol"], api_key),
                        self._fetch_mid(client, cfg["ref_url"], cfg["ref_symbol"], api_key),
                    )
                if ic_mid is None or ref_mid is None:
                    logger.warning(f"[QuoteDivergenceMonitor] tick miss ic={ic_mid} ref={ref_mid}, hold diverged={self.diverged}")
                    await asyncio.sleep(poll)
                    continue
                diff = abs(ic_mid - ref_mid)
                prev = self.diverged
                if self.diverged:
                    if diff <= recover:
                        self.diverged = False
                else:
                    if diff >= trip:
                        self.diverged = True
                now = _time.time()
                state = {"diverged": self.diverged, "diff": round(diff, 4),
                         "ic": round(ic_mid, 3), "ref": round(ref_mid, 3),
                         "trip": trip, "recover": recover, "ts": now}
                try:
                    await _rc.set("quote_divergence:state", _json.dumps(state), ex=int(cfg.get("stale_sec", 5)) * 2)
                except Exception as e:
                    logger.warning(f"[QuoteDivergenceMonitor] redis set err: {e}")
                changed = (prev != self.diverged)
                if changed or (now - self._last_broadcast) >= float(cfg.get("heartbeat_sec", 3.0)):
                    self._last_broadcast = now
                    try:
                        await _rc.publish("ws:broadcast", _json.dumps({"type": "quote_divergence", "data": state}))
                    except Exception as e:
                        logger.warning(f"[QuoteDivergenceMonitor] publish err: {e}")
                    if changed:
                        logger.info(f"[QuoteDivergenceMonitor] {'DIVERGED' if self.diverged else 'NORMAL'} diff={diff:.3f} ic={ic_mid:.3f} ref={ref_mid:.3f}")
            except Exception as e:
                logger.error(f"[QuoteDivergenceMonitor] loop error: {e}")
            await asyncio.sleep(poll)


quote_divergence_monitor = QuoteDivergenceMonitor()


position_streamer = PositionStreamer()


# ── On-demand snapshot listener ───────────────────────────────────────────────
# Subscribes to ws:snapshot_request (published by Go Hub when a client sends
# `request_snapshot`) and triggers PositionStreamer.push_snapshot_for_user.
# This bypasses the 1s broadcast cycle so the UI gets sub-second feedback after
# a manual refresh or an order fill.
class SnapshotRequestListener:
    def __init__(self):
        self.running = False
        self.task = None

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("SnapshotRequestListener started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        import json as _json
        from app.core.redis_client import redis_client as _rc
        while self.running:
            pubsub = None
            try:
                if not _rc.client:
                    await asyncio.sleep(2)
                    continue
                pubsub = _rc.client.pubsub()
                await pubsub.subscribe("ws:snapshot_request")
                async for msg in pubsub.listen():
                    if not self.running:
                        break
                    if msg.get("type") != "message":
                        continue
                    try:
                        data = _json.loads(msg.get("data") or "{}")
                        uid = data.get("user_id")
                        if uid:
                            asyncio.create_task(position_streamer.push_snapshot_for_user(uid))
                    except Exception as e:
                        logger.debug(f"[SnapshotRequestListener] msg parse error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SnapshotRequestListener] loop error: {e}")
                await asyncio.sleep(2)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe()
                        await pubsub.close()
                    except Exception:
                        pass


snapshot_request_listener = SnapshotRequestListener()


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
                # Run a periodic REST sync alongside WS streams. Binance UserDataStream
                # has been observed to silently stop delivering events on this setup
                # (total_msgs=0 with active trading). REST sync guarantees max ~4s
                # position staleness regardless of WS health. WS still wins when
                # working (sub-second), REST is the floor.
                tasks.append(asyncio.create_task(self._periodic_rest_sync_loop(accounts)))
                await asyncio.gather(*tasks, return_exceptions=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BinancePositionPusher] Manager loop error: {e}")
                await asyncio.sleep(self.RECONNECT_DELAY)

    # ------------------------------------------------------------------
    # 主动 REST 同步循环 — 作为 WS 不可靠时的兜底
    # ------------------------------------------------------------------
    async def _periodic_rest_sync_loop(self, accounts: list):
        # Polls every SYNC_INTERVAL seconds for each account; refreshes
        # position_streamer._binance_positions cache via REST. The 1s
        # PositionStreamer broadcast picks up the fresh cache, so end-to-end
        # latency = SYNC_INTERVAL + ~1s.
        from app.services.binance_client import BinanceFuturesClient
        SYNC_INTERVAL = 15.0  # 3s->15s 降频防币安限频(WS为主, REST仅floor)
        # Stagger across accounts to spread API load
        await asyncio.sleep(1.0)
        while self.running:
            for api_key, api_secret, proxy_url, user_id in accounts:
                if not self.running:
                    break
                if not user_id:
                    continue
                try:
                    client = BinanceFuturesClient(api_key, api_secret, proxy_url=proxy_url)
                    try:
                        await self._bootstrap_positions_via_rest(client, user_id, api_key)
                    finally:
                        await client.close()
                except Exception as e:
                    logger.debug(
                        f"[BinancePositionPusher] REST sync error {api_key[:8]}…: {e}"
                    )
            await asyncio.sleep(SYNC_INTERVAL)

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

                # Build session + ws_connect kwargs — SOCKS5 needs ProxyConnector
                _ws_url = f"{ws_base}/{listen_key}"
                _ws_kwargs = dict(heartbeat=30)
                if proxy_url and proxy_url.startswith(('socks5://', 'socks4://', 'socks://')):
                    from aiohttp_socks import ProxyConnector
                    _connector = ProxyConnector.from_url(proxy_url)
                    session = aiohttp.ClientSession(connector=_connector)
                else:
                    session = aiohttp.ClientSession()
                    if proxy_url:
                        from urllib.parse import urlparse as _urlparse
                        _parsed = _urlparse(proxy_url)
                        if _parsed.username and _parsed.password:
                            _ws_kwargs["proxy"] = f"{_parsed.scheme}://{_parsed.hostname}:{_parsed.port}"
                            _ws_kwargs["proxy_auth"] = aiohttp.BasicAuth(_parsed.username, _parsed.password)
                        else:
                            _ws_kwargs["proxy"] = proxy_url

                async with session.ws_connect(_ws_url, **_ws_kwargs) as ws:
                    _proxy_tag = f"via {proxy_url.split('@')[-1]}" if proxy_url else "direct"
                    _proxy_type = "socks5" if proxy_url and "socks" in proxy_url else ("http-proxy" if proxy_url else "direct")
                    logger.info(f"[BinancePositionPusher] User Data Stream 已连接: {api_key[:8]}… ({_proxy_tag}, {_proxy_type})")

                    # Bootstrap: REST snapshot once per (re)connect to seed the
                    # cache with pre-existing positions (WS only pushes deltas).
                    try:
                        await self._bootstrap_positions_via_rest(client, user_id, api_key)
                    except Exception as _be:
                        logger.warning(f"[BinancePositionPusher] bootstrap failed {api_key[:8]}…: {_be}")

                    # Shared state for health monitoring in _keepalive_loop
                    _ws_msg_count = [0]
                    _ws_last_msg_ts = [__import__('time').time()]

                    keepalive_task = asyncio.create_task(
                        self._keepalive_loop(client, listen_key, api_key=api_key,
                                             msg_count=_ws_msg_count, last_msg_ts=_ws_last_msg_ts,
                                             ws=ws)
                    )
                    try:
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                _ws_msg_count[0] += 1
                                _ws_last_msg_ts[0] = __import__('time').time()
                                await self._handle_message(msg.json(), user_id)
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.warning(f"[BinancePositionPusher] WS closed by server: {api_key[:8]}… data={msg.data}")
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"[BinancePositionPusher] WS error: {api_key[:8]}… err={ws.exception()}")
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

    async def _keepalive_loop(self, client, listen_key: str, api_key: str = "",
                            msg_count: list = None, last_msg_ts: list = None,
                            ws=None):
        # Renew listenKey every KEEPALIVE_SEC (25min) — Binance requirement.
        # Plus silent-death detection: if no events for IDLE_THRESHOLD seconds
        # AND REST shows position changed vs our cache, force-close WS so the
        # outer loop reconnects. REST cross-check avoids false-positive
        # reconnects when account is legitimately quiet.
        import time as _time
        _tag = api_key[:8] if api_key else listen_key[:8]
        IDLE_THRESHOLD       = 300   # 5min no events triggers REST verify
        IDLE_CHECK_INTERVAL  = 60    # verify every 60s
        HEALTH_LOG_INTERVAL  = 300   # log health every 5min

        now0 = _time.time()
        last_renew_ts      = now0
        last_health_log_ts = now0

        while True:
            await asyncio.sleep(IDLE_CHECK_INTERVAL)
            now = _time.time()

            # listenKey renewal (every 25min)
            if now - last_renew_ts >= self.KEEPALIVE_SEC:
                try:
                    await client.keepalive_futures_listen_key(listen_key)
                    logger.info(f"[BinancePositionPusher] listenKey 续期成功: {_tag}…")
                except Exception as e:
                    logger.warning(f"[BinancePositionPusher] listenKey 续期失败 {_tag}…: {e}")
                last_renew_ts = now

            # Periodic health log (every 5min)
            if msg_count is not None and now - last_health_log_ts >= HEALTH_LOG_INTERVAL:
                idle_s = int(now - last_msg_ts[0]) if last_msg_ts else 0
                logger.info(
                    f"[BinancePositionPusher] health: {_tag}… "
                    f"total_msgs={msg_count[0]} idle={idle_s}s"
                )
                last_health_log_ts = now

            # Silent-death detection + force reconnect
            if last_msg_ts is not None and ws is not None and not ws.closed:
                idle_s = now - last_msg_ts[0]
                if idle_s >= IDLE_THRESHOLD:
                    silent_death = False
                    try:
                        rows = await client.get_position_risk(symbol=None)
                        if isinstance(rows, list):
                            rest_by_sym = {}
                            for r in rows:
                                sym = r.get("symbol")
                                if not sym:
                                    continue
                                amt = float(r.get("positionAmt") or 0)
                                side = (r.get("positionSide") or "BOTH").upper()
                                l, s = rest_by_sym.get(sym, (0.0, 0.0))
                                if side == "LONG":
                                    l += max(0.0, amt)
                                elif side == "SHORT":
                                    s += max(0.0, abs(amt))
                                else:
                                    if amt > 0: l += amt
                                    elif amt < 0: s += abs(amt)
                                rest_by_sym[sym] = (round(l, 3), round(s, 3))
                            # Compare with cache for this account
                            cache = position_streamer._binance_positions
                            for uid, syms in cache.items():
                                for sym, (cl, cs) in syms.items():
                                    rl, rs = rest_by_sym.get(sym, (0.0, 0.0))
                                    if abs(cl - rl) > 0.001 or abs(cs - rs) > 0.001:
                                        silent_death = True
                                        logger.warning(
                                            f"[BinancePositionPusher] WS silent-death {_tag}…: "
                                            f"sym={sym} cache=({cl},{cs}) rest=({rl},{rs}) "
                                            f"idle={int(idle_s)}s"
                                        )
                                        break
                                if silent_death:
                                    break
                    except Exception as e:
                        logger.debug(f"[BinancePositionPusher] idle REST verify error {_tag}…: {e}")

                    if silent_death:
                        try:
                            await ws.close(code=1000, message=b"idle silent-death")
                            logger.warning(
                                f"[BinancePositionPusher] forced WS reconnect {_tag}… "
                                f"(idle={int(idle_s)}s)"
                            )
                        except Exception:
                            pass
                        return  # exit keepalive; outer loop reconnects

    # ------------------------------------------------------------------
    # 消息处理：ACCOUNT_UPDATE → 立即更新 PositionStreamer
    # ------------------------------------------------------------------
    async def _handle_message(self, data: dict, user_id: str = None):
        event_type = data.get("e")
        if event_type:
            logger.info(f"[BinancePositionPusher] WS event: {event_type} user={user_id or '?'}")

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

        # ACCOUNT_UPDATE.a.P 是仓位数组 — 处理所有 symbol，不再过滤单一品种
        positions = data.get("a", {}).get("P", [])

        updated_symbols = {}

        for pos in positions:
            sym = pos.get("s")
            if not sym:
                continue

            ps  = pos.get("ps", "BOTH")
            pa  = float(pos.get("pa", 0))
            long_v, short_v = updated_symbols.get(sym, (0.0, 0.0))

            if ps == "LONG":
                long_v = round(max(0.0, pa), 3)
            elif ps == "SHORT":
                short_v = round(max(0.0, abs(pa)), 3)
            else:  # BOTH
                if pa > 0:
                    long_v, short_v = round(pa, 3), 0.0
                elif pa < 0:
                    long_v, short_v = 0.0, round(abs(pa), 3)
                else:
                    long_v, short_v = 0.0, 0.0

            updated_symbols[sym] = (long_v, short_v)

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

        if updated_symbols:
            for sym, (long_v, short_v) in updated_symbols.items():
                position_streamer.set_binance_positions(long_v, short_v, user_id=user_id, symbol=sym)

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
                f"{updated_symbols} user={user_id}"
            )

            # Immediately push a full per-user position_snapshot via Redis → Go Hub → frontend.
            # Don\'t wait for PositionStreamer\'s 1s cycle — user expects sub-second UI update.
            # Reads THIS user\'s MT5 bridges (not the shared system bridge) and emits a
            # complete `pairs` map matching Publisher A format, so the frontend store can
            # replace the entire snapshot rather than partially patch.
            if user_id:
                try:
                    import json as _json
                    from app.core.redis_client import redis_client as _rc

                    mt5_by_user = await position_streamer._read_mt5_positions_all()
                    mt5_syms = mt5_by_user.get(user_id, {})
                    bn_syms = dict(position_streamer._binance_positions.get(user_id, {}))
                    for sym, (long_v, short_v) in updated_symbols.items():
                        bn_syms[sym] = (long_v, short_v)

                    # Build pairs map from active hedging pairs
                    pairs_meta = {}
                    try:
                        from app.services.hedging_pair_service import hedging_pair_service
                        for pair in (hedging_pair_service.list_active_pairs() or []):
                            if not pair.is_active:
                                continue
                            sa = pair.symbol_a.symbol if pair.symbol_a else None
                            sb = pair.symbol_b.symbol if pair.symbol_b else None
                            if sa and sb:
                                pairs_meta[pair.pair_code] = {"sym_a": sa, "sym_b": sb}
                    except Exception:
                        pass

                    pairs_out = {}
                    for pc, meta in pairs_meta.items():
                        sa, sb = meta["sym_a"], meta["sym_b"]
                        bn_l, bn_s = bn_syms.get(sa, (0.0, 0.0))
                        mt5_l, mt5_s = mt5_syms.get(sb, (0.0, 0.0))
                        if mt5_l == 0.0 and mt5_s == 0.0:
                            alt = sb.replace("+", ".s")
                            mt5_l, mt5_s = mt5_syms.get(alt, (0.0, 0.0))
                        if mt5_l == 0.0 and mt5_s == 0.0 and "+" in sb:
                            mt5_l, mt5_s = mt5_syms.get(sb.replace("+", ""), (0.0, 0.0))
                        pairs_out[pc] = {
                            "mt5_long": mt5_l, "mt5_short": mt5_s,
                            "binance_long": bn_l, "binance_short": bn_s,
                        }

                    primary_pd = {}
                    for _pc, _pd in pairs_out.items():
                        if _pd.get("binance_long", 0) != 0 or _pd.get("binance_short", 0) != 0:
                            primary_pd = _pd
                            break
                    if not primary_pd and pairs_out:
                        primary_pd = next(iter(pairs_out.values()))
                    evt = {
                        "user_id": user_id,
                        "type": "position_snapshot",
                        "data": {
                            "bybit_long_lots":  primary_pd.get("mt5_long", 0.0),
                            "bybit_short_lots": primary_pd.get("mt5_short", 0.0),
                            "binance_long_xau": primary_pd.get("binance_long", 0.0),
                            "binance_short_xau": primary_pd.get("binance_short", 0.0),
                            "pairs": pairs_out,
                        }
                    }
                    await _rc.publish("ws:user_event", _json.dumps(evt))
                    logger.info(f"[BinancePositionPusher] Instant snapshot pushed user={user_id} pairs={list(pairs_out.keys())}")
                except Exception as push_err:
                    logger.warning(f"[BinancePositionPusher] Instant push failed: {push_err}")


    async def _bootstrap_positions_via_rest(self, client, user_id: str, api_key: str) -> None:
        """One-shot REST snapshot on WS (re)connect to seed
        position_streamer._binance_positions with all currently-open positions.
        Subsequent updates come from the User Data Stream ACCOUNT_UPDATE
        event — REST is used only to fill the cold-start gap.
        """
        if not user_id:
            return
        try:
            rows = await client.get_position_risk(symbol=None)
        except Exception as e:
            logger.warning(f"[BinancePositionPusher] bootstrap REST error {api_key[:8]}…: {e}")
            return
        if not rows or not isinstance(rows, list):
            logger.info(f"[BinancePositionPusher] bootstrap {api_key[:8]}…: no positions")
            return

        by_symbol: dict = {}
        for r in rows:
            try:
                sym = r.get("symbol")
                if not sym:
                    continue
                amt = float(r.get("positionAmt") or 0)
                side = (r.get("positionSide") or "BOTH").upper()
                long_v, short_v = by_symbol.get(sym, (0.0, 0.0))
                if side == "LONG":
                    long_v += max(0.0, amt)
                elif side == "SHORT":
                    short_v += max(0.0, abs(amt))
                else:  # BOTH (one-way mode): sign of amt decides
                    if amt > 0:
                        long_v += amt
                    elif amt < 0:
                        short_v += abs(amt)
                by_symbol[sym] = (round(long_v, 3), round(short_v, 3))
            except Exception:
                continue

        non_zero = {s: v for s, v in by_symbol.items() if v != (0.0, 0.0)}

        # Reconcile cache vs this authoritative REST snapshot (symbol=None ->
        # ALL open positions). A cached non-zero symbol absent from non_zero was
        # closed (here, externally, or while a WS ACCOUNT_UPDATE was missed) ->
        # zero it, but only after 2 consecutive absent REST cycles (~6s) so a
        # freshly-opened position missed by an in-flight pre-open REST snapshot
        # is not wrongly zeroed (it reappears next cycle, resetting the count).
        # Without this a stale non-zero (e.g. 主多仓 5 -> 全平) never returns to 0;
        # the 3s REST loop is the floor, WS ACCOUNT_UPDATE is sub-second.
        if not hasattr(self, "_rest_absent_count"):
            self._rest_absent_count = {}
        prev = position_streamer._binance_positions.get(user_id, {}) if user_id else {}
        _stale_zeroed = []
        for _sym, _pv in list(prev.items()):
            _k = (user_id, _sym)
            if _pv != (0.0, 0.0) and _sym not in non_zero:
                _c = self._rest_absent_count.get(_k, 0) + 1
                if _c >= 2:
                    position_streamer.set_binance_positions(0.0, 0.0, user_id=user_id, symbol=_sym)
                    _stale_zeroed.append(_sym)
                    self._rest_absent_count.pop(_k, None)
                else:
                    self._rest_absent_count[_k] = _c
            else:
                self._rest_absent_count.pop(_k, None)

        if not non_zero:
            if _stale_zeroed:
                logger.info(
                    f"[BinancePositionPusher] REST reconcile {api_key[:8]}… user={user_id} "
                    f"-> cleared stale {_stale_zeroed}; all positions 0"
                )
            return

        # Compare with cache BEFORE overwriting — only log when position actually changed
        _changed = False
        try:
            for _s, _v in non_zero.items():
                _pv = prev.get(_s, (0.0, 0.0))
                if abs(_pv[0] - _v[0]) > 0.001 or abs(_pv[1] - _v[1]) > 0.001:
                    _changed = True
                    break
        except Exception:
            _changed = True
        for sym, (long_v, short_v) in non_zero.items():
            position_streamer.set_binance_positions(long_v, short_v, user_id=user_id, symbol=sym)
        if _changed or _stale_zeroed:
            logger.info(
                f"[BinancePositionPusher] bootstrap {api_key[:8]}… user={user_id} "
                f"symbols={list(non_zero.keys())} counts={non_zero}"
                + (f" cleared_stale={_stale_zeroed}" if _stale_zeroed else "")
            )


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


def notify_order_fill(order_id, filled_qty, status, avg_price=0.0):
    """Called by Binance WS stream when ORDER_TRADE_UPDATE arrives.
    
    Only set the event for terminal states (FILLED, PARTIALLY_FILLED, CANCELED, EXPIRED).
    The NEW status is just an order acknowledgement — setting the event on NEW causes
    the monitor to return immediately with filled_qty=0, breaking the entire hedge flow.

    avg_price: Binance ORDER_TRADE_UPDATE.o.ap — average fill price for slippage calc.
    """
    _order_fill_registry[order_id] = {
        "filled_qty": filled_qty,
        "status": status,
        "avg_price": avg_price,
    }
    # Only wake the monitor on TERMINAL states — NOT on PARTIALLY_FILLED.
    # PARTIALLY_FILLED means more fills may follow; waking now causes the monitor
    # to return a partial filled_qty, leaving the remainder un-hedged (single-leg).
    # The monitor's timeout will handle the case where no FILLED arrives.
    if status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
        evt = _order_fill_events.get(order_id)
        if evt:
            evt.set()
