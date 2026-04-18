"""Account data service for fetching account information from exchanges"""
import asyncio
import logging
import re
import time as _time_module
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from app.services.binance_client import BinanceFuturesClient
from app.services.bybit_client import BybitV5Client
from app.services.mt5_client import MT5Client
from app.services.mt5_http_client import MT5HttpClient
from app.models.account import Account
from app.schemas.account import AccountBalance, AccountPosition
from app.core.proxy_utils import build_proxy_url

logger = logging.getLogger(__name__)


def _get_pair_config():
    """Get symbol names and conversion factor from hedging pair config"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair("XAU")
        if pair:
            return pair.symbol_a.symbol, pair.symbol_b.symbol, pair.conversion_factor
    except Exception:
        pass
    return "XAUUSDT", "XAUUSD+", 100.0

# commission_rate 本地内存缓存（24小时有效，weight=20权重只在冷启动时消耗一次）
_commission_rate_cache: Dict[str, Dict] = {}  # api_key[:16] -> {"data": ..., "ts": float}


class AccountDataService:
    """Service for fetching account data from exchanges"""

    def __init__(self):
        self._cache = {}
        self._cache_ttl = 60  # Cache for 60 seconds (increased to reduce API calls)

    def _get_cache_key(self, account_id: str, data_type: str) -> str:
        """Generate cache key"""
        return f"{account_id}:{data_type}"

    def _get_cached_data(self, cache_key: str) -> Optional[Any]:
        """Get data from cache if not expired"""
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if (datetime.utcnow() - timestamp).total_seconds() < self._cache_ttl:
                return data
        return None

    def _set_cached_data(self, cache_key: str, data: Any):
        """Store data in cache with timestamp"""
        self._cache[cache_key] = (data, datetime.utcnow())

    def invalidate_cache(self, account_id: str = None):
        """Invalidate account data cache so the next streamer cycle fetches fresh data.

        Called after order execution to prevent 60s stale position display.
        If account_id given, only that account; otherwise clear all.
        """
        if account_id:
            keys_to_remove = [k for k in self._cache if k.startswith(account_id)]
            for k in keys_to_remove:
                del self._cache[k]
        else:
            self._cache.clear()

    async def get_binance_balance(self, api_key: str, api_secret: str, proxy_url: str = None) -> AccountBalance:
        """Fetch Binance account balance including spot, margin and futures data"""
        client = BinanceFuturesClient(api_key, api_secret, proxy_url=proxy_url)

        try:
            # Get today's start timestamp for daily calculations
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = int(today_start.timestamp() * 1000)

            # First, fetch spot account to see which assets we need prices for
            spot_account_data = await client.get_spot_account()

            # Collect assets that need price conversion
            assets_to_price = []
            if not isinstance(spot_account_data, Exception):
                balances = spot_account_data.get("balances", [])
                for balance in balances:
                    asset = balance.get("asset", "")
                    total = float(balance.get("free", 0)) + float(balance.get("locked", 0))
                    if total > 0 and asset != "USDT":
                        assets_to_price.append(asset)

            # Fetch all account data concurrently
            # commission_rate (weight=20) 使用24小时内存缓存，避免频繁消耗权重
            async def _cached_commission_rate(data):
                return data

            _cr_cache_key = api_key[:16] if api_key else "unknown"
            _cr_cached = _commission_rate_cache.get(_cr_cache_key)
            _sym_a, _, _ = _get_pair_config()
            _commission_rate_task = (
                _cached_commission_rate(_cr_cached["data"])
                if _cr_cached and (_time_module.monotonic() - _cr_cached["ts"]) < 86400
                else client.get_commission_rate(_sym_a)
            )

            fetch_tasks = [
                client.get_account(),           # USDT-M Futures  [0]
                client.get_position_risk(),     # Futures positions [1]
                client.get_income(income_type="REALIZED_PNL", start_time=start_time, limit=1000),  # [2]
                client.get_income(income_type="FUNDING_FEE", start_time=start_time, limit=1000),   # [3]
                client.get_income(income_type="COMMISSION", start_time=start_time, limit=1000),    # [4]
                client.get_margin_account(),    # Cross Margin     [5]
                _commission_rate_task,          # Maker/taker fee rate [6] (24h cached)
                client.get_spot_price("BNBUSDT"),       # BNB/USDT price for fee conversion [7]
                client.get_balance(),           # Futures wallet balances (includes BNB) [8]
                client.get_premium_index(_sym_a),    # Mark price + lastFundingRate [9]
                client.get_funding_asset(),          # Funding wallet balances [10]
            ]

            # Only fetch prices for assets we actually hold
            for asset in assets_to_price[:10]:  # Limit to 10 assets to avoid rate limits
                fetch_tasks.append(client.get_spot_price(f"{asset}USDT"))

            # Dynamic price results start at index 11 (after funding_asset at [10])

            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Unpack results
            futures_account_data = results[0]
            position_risk_data = results[1]
            daily_pnl_data = results[2]
            funding_fee_data = results[3]
            commission_fee_data = results[4]
            margin_account_data = results[5]
            commission_rate_data = results[6]
            bnb_price_data = results[7]
            futures_balance_data = results[8]
            premium_index_data = results[9]
            funding_asset_data = results[10]

            # commission_rate 成功返回时写入本地缓存（24h有效，weight=20每天只消耗一次）
            if not isinstance(commission_rate_data, Exception) and commission_rate_data:
                _commission_rate_cache[_cr_cache_key] = {
                    "data": commission_rate_data,
                    "ts": _time_module.monotonic(),
                }

            # BNB/USDT price for commission conversion (when BNB fee discount is enabled)
            bnb_usdt_price = 1.0
            if not isinstance(bnb_price_data, Exception):
                bnb_usdt_price = float(bnb_price_data.get("price", 1.0)) or 1.0

            # XAUUSDT mark price + current funding rate for predicted funding fee calculation
            xauusdt_mark_price = 0.0
            xauusdt_funding_rate = 0.0
            if not isinstance(premium_index_data, Exception) and premium_index_data:
                try:
                    xauusdt_mark_price = float(premium_index_data.get("markPrice", 0) or 0)
                    xauusdt_funding_rate = float(premium_index_data.get("lastFundingRate", 0) or 0)
                except (TypeError, ValueError):
                    logger.warning(f"Failed to parse premiumIndex for XAUUSDT: {premium_index_data}")
            else:
                logger.warning(f"Failed to fetch XAUUSDT premiumIndex: {premium_index_data}")

            # Build price map from individual price queries (now offset by 10)
            price_map = {}
            for i, asset in enumerate(assets_to_price[:10]):
                price_result = results[11 + i]
                if not isinstance(price_result, Exception):
                    price_map[f"{asset}USDT"] = float(price_result.get("price", 0))

            # Process spot account data
            spot_total_usdt = 0.0
            spot_free_usdt = 0.0
            spot_locked_usdt = 0.0

            if not isinstance(spot_account_data, Exception):
                # Calculate spot assets in USDT
                balances = spot_account_data.get("balances", [])
                for balance in balances:
                    asset = balance.get("asset", "")
                    free = float(balance.get("free", 0))
                    locked = float(balance.get("locked", 0))
                    total = free + locked

                    if total > 0:
                        # Convert to USDT
                        if asset == "USDT":
                            usdt_value = total
                            free_usdt = free
                            locked_usdt = locked
                        else:
                            # Try to find USDT price
                            symbol = f"{asset}USDT"
                            if symbol in price_map:
                                price = price_map[symbol]
                                usdt_value = total * price
                                free_usdt = free * price
                                locked_usdt = locked * price
                            else:
                                # Skip if no USDT pair found
                                logger.debug(f"No price found for {symbol}, skipping")
                                continue

                        spot_total_usdt += usdt_value
                        spot_free_usdt += free_usdt
                        spot_locked_usdt += locked_usdt
            else:
                logger.warning(f"Failed to fetch spot account data: {spot_account_data}")

            # Process futures account data
            futures_total_wallet_balance = 0.0
            futures_available_balance = 0.0
            futures_total_margin_balance = 0.0
            futures_margin_balance = 0.0
            futures_unrealized_pnl = 0.0
            futures_risk_ratio = 0.0

            if not isinstance(futures_account_data, Exception):
                futures_total_wallet_balance = float(futures_account_data.get("totalWalletBalance", 0))
                futures_available_balance = float(futures_account_data.get("availableBalance", 0))
                futures_total_margin_balance = float(futures_account_data.get("totalMarginBalance", 0))
                futures_unrealized_pnl = float(futures_account_data.get("totalUnrealizedProfit", 0))

                # Get margin balance from assets
                assets = futures_account_data.get("assets", [])
                for asset in assets:
                    if asset.get("asset") == "USDT":
                        futures_margin_balance = float(asset.get("marginBalance", 0))
                        break

                # Calculate risk ratio
                total_maint_margin = float(futures_account_data.get("totalMaintMargin", 0))
                futures_risk_ratio = (total_maint_margin / futures_total_margin_balance * 100) if futures_total_margin_balance > 0 else 0
            else:
                logger.warning(f"Failed to fetch futures account data: {futures_account_data}")

            # Process cross margin account data
            margin_total_usdt = 0.0
            margin_free_usdt = 0.0
            margin_locked_usdt = 0.0

            if not isinstance(margin_account_data, Exception):
                # totalNetAssetOfBtc is the total net asset in BTC, but we use USDT assets directly
                user_assets = margin_account_data.get("userAssets", [])
                for asset in user_assets:
                    if asset.get("asset") == "USDT":
                        net = float(asset.get("netAsset", 0))
                        free = float(asset.get("free", 0))
                        locked = float(asset.get("locked", 0))
                        if net > 0:
                            margin_total_usdt = net
                            margin_free_usdt = free
                            margin_locked_usdt = locked
                        break
                logger.info(f"Margin account USDT: total={margin_total_usdt}, free={margin_free_usdt}")
            else:
                logger.warning(f"Failed to fetch margin account data: {margin_account_data}")

            # Process funding wallet data
            funding_total_usdt = 0.0
            if not isinstance(funding_asset_data, Exception):
                funding_list = funding_asset_data if isinstance(funding_asset_data, list) else []
                for item in funding_list:
                    asset = item.get("asset", "")
                    free = float(item.get("free", 0))
                    locked = float(item.get("locked", 0))
                    total = free + locked
                    if total > 0:
                        if asset == "USDT":
                            funding_total_usdt += total
                        elif asset == "BNB" and bnb_usdt_price > 0:
                            funding_total_usdt += total * bnb_usdt_price
                        elif f"{asset}USDT" in price_map:
                            funding_total_usdt += total * price_map[f"{asset}USDT"]
                logger.info(f"Funding wallet USDT equivalent: {funding_total_usdt:.2f}")
            else:
                logger.warning(f"Failed to fetch funding wallet data: {funding_asset_data}")

            # Calculate total positions from position risk (sum of position quantities)
            # Also get entry price, leverage, and liquidation prices
            total_positions = 0.0
            avg_entry_price = 0.0
            total_volume_weighted = 0.0
            leverage = 0
            long_liquidation_price = 0.0
            short_liquidation_price = 0.0
            # Track XAUUSDT long/short quantities separately for predicted funding fee calculation
            long_qty_xauusdt = 0.0
            short_qty_xauusdt = 0.0

            if not isinstance(position_risk_data, Exception):
                for pos in position_risk_data:
                    position_amt = float(pos.get("positionAmt", 0))
                    if position_amt != 0:
                        entry_price = float(pos.get("entryPrice", 0))
                        abs_amt = abs(position_amt)
                        total_positions += abs_amt
                        total_volume_weighted += abs_amt * entry_price
                        if leverage == 0:
                            leverage = int(pos.get("leverage", 0))

                        position_side = pos.get("positionSide", "BOTH")
                        is_long = position_side == "LONG" or (position_side == "BOTH" and position_amt > 0)
                        is_short = position_side == "SHORT" or (position_side == "BOTH" and position_amt < 0)

                        # Accumulate long/short qty for predicted funding fee (only primary symbol has markPrice fetched)
                        if pos.get("symbol") == _sym_a:
                            if is_long:
                                long_qty_xauusdt += abs_amt
                            elif is_short:
                                short_qty_xauusdt += abs_amt

                        # Prefer native liquidationPrice from API (most accurate, already accounts for isolated wallet)
                        liq_price = float(pos.get("liquidationPrice", 0))
                        if liq_price > 0:
                            if is_long:
                                long_liquidation_price = liq_price
                            elif is_short:
                                short_liquidation_price = liq_price
                        else:
                            # Fallback: precise isolated-margin formula
                            # Long:  liq = (entry * qty - isolated_wallet) / (qty * (1 - maint_margin_ratio))
                            # Short: liq = (entry * qty + isolated_wallet) / (qty * (1 + maint_margin_ratio))
                            isolated_wallet = float(pos.get("isolatedWallet", 0))
                            maint_margin_ratio = float(pos.get("maintMarginRatio", 0.005))
                            if abs_amt > 0 and entry_price > 0:
                                if is_long:
                                    long_liquidation_price = round(
                                        (entry_price * abs_amt - isolated_wallet) / (abs_amt * (1 - maint_margin_ratio)), 2
                                    )
                                elif is_short:
                                    short_liquidation_price = round(
                                        (entry_price * abs_amt + isolated_wallet) / (abs_amt * (1 + maint_margin_ratio)), 2
                                    )

                if total_positions > 0:
                    avg_entry_price = total_volume_weighted / total_positions
            else:
                logger.warning(f"Failed to fetch position risk data: {position_risk_data}")

            # Calculate daily P&L (realized + unrealized)
            daily_pnl = 0.0
            if not isinstance(daily_pnl_data, Exception):
                daily_pnl = sum(float(item.get("income", 0)) for item in daily_pnl_data)
            else:
                logger.warning(f"Failed to fetch daily P&L data: {daily_pnl_data}")

            # Add unrealized PnL to daily PnL as per Binance documentation
            daily_pnl += futures_unrealized_pnl

            # Today's total realized funding fee (all symbols, for reporting only)
            funding_fee = 0.0
            if not isinstance(funding_fee_data, Exception):
                for item in funding_fee_data:
                    funding_fee += float(item.get("income", 0))
            else:
                logger.warning(f"Failed to fetch funding fee data: {funding_fee_data}")

            # Predicted next-period funding fee per side, per the formula:
            #   仓位价值 × 资金费率 = 资金费用
            #   仓位价值 = 合约数 × 币价 (标记价格)
            #
            # Sign convention matches Binance cash-flow direction:
            #   long  holder: positive rate → pays    → negative  → -long_qty  * mark * rate
            #   short holder: positive rate → receives → positive → +short_qty * mark * rate
            #
            # Field names kept as *_funding_rate for frontend compatibility, but now carry the predicted fee in USDT.
            long_funding_rate = -(long_qty_xauusdt * xauusdt_mark_price * xauusdt_funding_rate)
            short_funding_rate = short_qty_xauusdt * xauusdt_mark_price * xauusdt_funding_rate

            # 当日手续费汇总（USDT等值）
            # COMMISSION income 为负值，asset 字段标明币种
            # 若开启 BNB 手续费折扣，asset="BNB"，需乘以 BNB/USDT 价格换算
            commission_fee = 0.0
            if not isinstance(commission_fee_data, Exception):
                for item in commission_fee_data:
                    amount = abs(float(item.get("income", 0)))
                    asset = item.get("asset", "USDT")
                    if asset == "BNB":
                        commission_fee += amount * bnb_usdt_price
                    else:
                        commission_fee += amount  # USDT or other stablecoins
            else:
                logger.warning(f"Failed to fetch commission fee data: {commission_fee_data}")

            # Extract BNB holdings from futures wallet balance (/fapi/v2/balance returns all assets)
            # /fapi/v2/account assets[] only shows assets with margin activity; /fapi/v2/balance is comprehensive
            bnb_balance = 0.0
            if not isinstance(futures_balance_data, Exception):
                for item in futures_balance_data:
                    if item.get("asset") == "BNB":
                        bnb_balance = float(item.get("balance", 0))
                        break
            elif not isinstance(futures_account_data, Exception):
                # Fallback: try assets array from account info
                for asset in futures_account_data.get("assets", []):
                    if asset.get("asset") == "BNB":
                        bnb_balance = float(asset.get("walletBalance", 0))
                        break

            # Extract maker/taker commission rates
            maker_commission_rate = None
            taker_commission_rate = None
            if not isinstance(commission_rate_data, Exception):
                maker_commission_rate = float(commission_rate_data.get("makerCommissionRate", 0))
                taker_commission_rate = float(commission_rate_data.get("takerCommissionRate", 0))
            else:
                logger.warning(f"Failed to fetch commission rate: {commission_rate_data}")

            # Calculate final metrics according to Binance API documentation
            # 账户总资产 = 现货 + 杠杆(净资产) + 合约totalMarginBalance (含未实现盈亏) + 资金账户
            total_assets = spot_total_usdt + margin_total_usdt + futures_total_margin_balance + funding_total_usdt

            # 可用总资产 = 现货free + 杠杆free + 合约availableBalance + 资金账户
            available_balance = spot_free_usdt + margin_free_usdt + futures_available_balance + funding_total_usdt

            # 净资产 = 合约totalWalletBalance (钱包余额，不含未实现盈亏)
            net_assets = futures_total_wallet_balance

            # 冻结资产 = 现货locked + 杠杆locked + (合约totalWalletBalance - availableBalance)
            frozen_assets = spot_locked_usdt + margin_locked_usdt + (futures_total_wallet_balance - futures_available_balance)

            # 保证金余额 = 合约marginBalance (from USDT asset)
            margin_balance = futures_margin_balance

            # 风险率 = (totalMaintMargin / totalMarginBalance) × 100
            risk_ratio = futures_risk_ratio

            return AccountBalance(
                total_assets=total_assets,
                available_balance=available_balance,
                net_assets=net_assets,
                frozen_assets=frozen_assets,
                margin_balance=margin_balance,
                unrealized_pnl=futures_unrealized_pnl,
                risk_ratio=risk_ratio,
                total_positions=total_positions,
                daily_pnl=daily_pnl,
                funding_fee=funding_fee,
                long_funding_rate=long_funding_rate,
                short_funding_rate=short_funding_rate,
                commission_fee=commission_fee,
                bnb_balance=bnb_balance,
                maker_commission_rate=maker_commission_rate,
                taker_commission_rate=taker_commission_rate,
                # Position data for liquidation price calculation
                entry_price=avg_entry_price,  # 开仓均价
                leverage=leverage,  # 杠杆倍数
                # Binance native liquidation prices from positionRisk API
                long_liquidation_price=long_liquidation_price,
                short_liquidation_price=short_liquidation_price,
            )
        except Exception as e:
            from app.services.binance_client import BinanceIPBanError
            import re as _re
            if isinstance(e, BinanceIPBanError):
                logger.error(f"[Binance IP封禁] {e.message}")
                # 异步触发飞书+弹窗告警（asyncio已在模块顶部导入，不在此重复import）
                asyncio.create_task(_trigger_binance_ban_alert_all_users(e))
                raise Exception(f"RATE_LIMIT_BAN:{e.ban_until_ms}")

            error_msg = str(e)
            # 兼容旧版异常格式
            if "banned until" in error_msg and ("banned" in error_msg or "rate limit" in error_msg.lower()):
                logger.warning(f"Binance rate limit exceeded: {error_msg}")
                ban_until_match = _re.search(r'banned until (\d+)', error_msg)
                ban_until_ms = int(ban_until_match.group(1)) if ban_until_match else 0
                raise Exception(f"RATE_LIMIT_BAN:{ban_until_ms}")

            logger.error(f"Error fetching Binance balance: {error_msg}", exc_info=True)
            raise
        finally:
            await client.close()

    async def get_bybit_balance(
        self,
        api_key: str,
        api_secret: str,
        account_type: str = "UNIFIED",
        mt5_id: int = None,
        mt5_password: str = None,
        mt5_server: str = None,
        proxy_url: str = None,
    ) -> AccountBalance:
        """Fetch Bybit account balance.
        - For Unified accounts: Use V5 API (/v5/account/...)
        - MT5 accounts are now handled by Bridge HTTP upstream; this always uses Unified API.
        """
        client = BybitV5Client(api_key, api_secret, proxy_url=proxy_url)

        try:
            logger.info(f"Fetching Bybit Unified account balance")
            return await self._get_bybit_unified_balance(client)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching Bybit balance: {error_msg}", exc_info=True)

            # Check for rate limit errors
            if "rate limit" in error_msg.lower() or "banned" in error_msg.lower() or "10006" in error_msg:
                logger.warning(f"Bybit rate limit exceeded: {error_msg}")

                # Try to extract ban timestamp from error message
                import re
                ban_until_match = re.search(r'banned until (\d+)', error_msg)
                ban_until_ms = None
                if ban_until_match:
                    ban_until_ms = int(ban_until_match.group(1))

                # Raise a custom exception with ban info
                raise Exception(f"RATE_LIMIT:{ban_until_ms if ban_until_ms else 0}")

            raise
        finally:
            await client.close()

    async def _get_bybit_mt5_balance_direct(
        self,
        mt5_id: int,
        mt5_password: str,
        mt5_server: str,
    ) -> AccountBalance:
        """Fetch Bybit MT5 account balance using direct MT5 connection"""
        from datetime import datetime

        mt5_info = None
        mt5_positions = []
        mt5_deals = []

        try:
            logger.info(f"Connecting to MT5 account {mt5_id}")
            # Use shared MT5 client from realtime_market_service to avoid connection conflicts
            from app.services.realtime_market_service import market_data_service
            mt5 = market_data_service.mt5_client

            if mt5 and mt5.connected:
                logger.info("Using shared MT5 client")
                mt5_info = mt5.get_account_info()
                if mt5_info:
                    mt5_positions = mt5.get_positions()
                    # Get today's deals history for fees
                    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                    mt5_deals = mt5.get_deals_history(date_from=today_start)
                    logger.info(f"Got {len(mt5_deals)} deals from MT5 history")
                else:
                    logger.warning("Shared MT5 client returned None for account info, trying temporary client")

            # If shared client failed or not available, use temporary client
            if not mt5_info:
                logger.info("Creating temporary MT5 client")
                temp_mt5 = MT5Client(
                    login=int(mt5_id),
                    password=mt5_password,
                    server=mt5_server
                )
                if temp_mt5.connect():
                    logger.info("Temporary MT5 client connected successfully")
                    mt5_info = temp_mt5.get_account_info()
                    if mt5_info:
                        mt5_positions = temp_mt5.get_positions()
                        # Get today's deals history for fees
                        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                        mt5_deals = temp_mt5.get_deals_history(date_from=today_start)
                        logger.info(f"Got {len(mt5_deals)} deals from MT5 history")
                    else:
                        logger.error("Temporary MT5 client get_account_info() returned None")
                    temp_mt5.disconnect()
                else:
                    logger.error("Failed to connect temporary MT5 client")
                    raise Exception("Failed to connect to MT5")

            if not mt5_info:
                logger.error("Failed to get MT5 account info from both shared and temporary clients")
                raise Exception("Failed to get MT5 account info")

            # Log MT5 info for debugging
            logger.info(f"MT5 account info received: login={mt5_info.get('login')}, balance={mt5_info.get('balance')}, swap={mt5_info.get('swap')}")

            # Extract balance fields from MT5
            balance = float(mt5_info.get("balance", 0))  # 账户总资产
            equity = float(mt5_info.get("equity", 0))  # 净资产
            free_margin = float(mt5_info.get("margin_free", 0))  # 可用总资产
            margin_used = float(mt5_info.get("margin", 0))  # 冻结资产（已用保证金）
            margin_balance = equity  # 保证金余额 = 净值
            unrealized_pnl = equity - balance  # 未实现盈亏 = 净值 - 余额
            account_profit = float(mt5_info.get("profit", 0))  # 累计已实现盈亏（从MT5 API获取）
            account_total_swap = float(mt5_info.get("swap", 0))  # 账户累计总过夜费（包含已平仓+未平仓）

            logger.info(f"Extracted account_total_swap: {account_total_swap}")

            # Calculate margin level (risk ratio)
            # 风险率(%) = (账户权益 / 已用保证金) × 100
            margin_level = 0.0
            if margin_used > 0.01:  # 已用保证金必须大于0.01才计算，避免异常值
                margin_level = (equity / margin_used) * 100
                # 限制最大值为10000%，避免显示异常
                if margin_level > 10000:
                    margin_level = 0.0
            else:
                # 无持仓或保证金极小时，风险率设为0
                margin_level = 0.0

            # Calculate total positions (sum of volumes) and get entry price and liquidation prices
            from app.core.bybit_mt5_config import get_symbol_config

            total_positions = 0.0
            avg_entry_price = 0.0
            total_volume_weighted = 0.0
            long_liquidation_price = 0.0
            short_liquidation_price = 0.0

            # Accumulators for liquidation price calculation (account-level cross-margin)
            long_volume_total = 0.0
            long_price_weighted = 0.0
            long_margin_total = 0.0
            short_volume_total = 0.0
            short_price_weighted = 0.0
            short_margin_total = 0.0

            # Get account leverage for liquidation price calculation
            account_leverage = int(mt5_info.get("leverage", 1))

            for pos in mt5_positions:
                volume = float(pos.get("volume", 0))
                price_open = float(pos.get("price_open", 0))
                pos_type = pos.get("type", 0)  # 0=Buy(Long), 1=Sell(Short)
                pos_margin = float(pos.get("margin", 0))

                total_positions += abs(volume)
                total_volume_weighted += abs(volume) * price_open

                if pos_type == 0:  # Long
                    long_volume_total += volume
                    long_price_weighted += volume * price_open
                    long_margin_total += pos_margin
                else:  # Short
                    short_volume_total += volume
                    short_price_weighted += volume * price_open
                    short_margin_total += pos_margin

            # Bybit Tradfi MT5 全仓模式强平价公式（官方规则）：
            # 触发条件：账户净值 ≤ 全部已用保证金 × 50%（stop-out level = 50%）
            # 全仓模式下，强平价使用账户级别的 margin_used（mt5_info.margin），而非单方向保证金
            #
            #   Long  liq = avg_entry_long  - (equity - margin_used × 0.50) / (100 × long_lots)
            #   Short liq = avg_entry_short + (equity - margin_used × 0.50) / (100 × short_lots)
            #
            # 注意：MT5 原生 price_liquidation 字段按单仓孤立模式计算，全仓模式下不准确，不使用。
            _, _, _conv = _get_pair_config()
            CONTRACT_UNIT = _conv   # Bybit: 1 lot = CONTRACT_UNIT oz
            LIQ_THRESHOLD = 0.50  # Bybit MT5 stop-out level = 50%

            # 安全垫 = 净值 - 全部已用保证金 × 50%（全仓共享）
            safety_buffer = equity - margin_used * LIQ_THRESHOLD

            if long_volume_total > 0:
                long_avg_entry = long_price_weighted / long_volume_total
                long_liquidation_price = round(
                    long_avg_entry - safety_buffer / (CONTRACT_UNIT * long_volume_total),
                    2
                )

            if short_volume_total > 0:
                short_avg_entry = short_price_weighted / short_volume_total
                short_liquidation_price = round(
                    short_avg_entry + safety_buffer / (CONTRACT_UNIT * short_volume_total),
                    2
                )

            # Calculate weighted average entry price
            if total_positions > 0:
                avg_entry_price = total_volume_weighted / total_positions

            # Calculate fees and realized PnL from deals history
            commission_fee = 0.0
            long_swap_fee = 0.0
            short_swap_fee = 0.0
            realized_pnl_from_deals = 0.0  # 当日已实现盈亏（平仓盈亏）

            for deal in mt5_deals:
                # Commission fees (always negative in MT5)
                commission_fee += abs(float(deal.get("commission", 0)))

                # Swap fees (overnight interest)
                swap = float(deal.get("swap", 0))
                deal_type = deal.get("type", 0)  # 0=Buy, 1=Sell

                # Separate swap by position type
                if deal_type == 0:  # Buy (Long)
                    long_swap_fee += swap
                elif deal_type == 1:  # Sell (Short)
                    short_swap_fee += swap

                # Realized PnL from closed positions
                # MT5 SDK 直连: entry=1 表示平仓 (Out)
                # MT5 HTTP Bridge: entry 字段可能为 None，改用 profit!=0 判断
                #   开仓 deal 的 profit 始终为 0，平仓 deal 的 profit 为实现盈亏
                deal_entry = deal.get("entry")
                deal_profit = float(deal.get("profit", 0))
                if deal_entry == 1 or (deal_entry is None and deal_profit != 0):
                    realized_pnl_from_deals += deal_profit

            # Daily P&L = 当日已实现平仓盈亏 + 当日未实现盈亏（浮动盈亏）
            # account_profit = mt5_info.profit = 当前所有持仓浮动盈亏之和（未实现盈亏）
            # realized_pnl_from_deals = 今日所有平仓交易的已实现盈亏之和
            # unrealized_pnl = equity - balance = 当前浮动盈亏
            daily_pnl = realized_pnl_from_deals + unrealized_pnl

            logger.info(f"MT5 balance: balance={balance}, equity={equity}, free_margin={free_margin}, "
                       f"margin_used={margin_used}, positions={total_positions}, "
                       f"commission={commission_fee}, long_swap={long_swap_fee}, short_swap={short_swap_fee}, "
                       f"account_total_swap={account_total_swap}, "
                       f"realized_pnl={realized_pnl_from_deals}, unrealized_pnl={unrealized_pnl}, daily_pnl={daily_pnl}, "
                       f"long_liquidation={long_liquidation_price}, short_liquidation={short_liquidation_price}")

            return AccountBalance(
                total_assets=balance,  # 账户总资产
                available_balance=free_margin,  # 可用总资产
                net_assets=equity,  # 净资产
                frozen_assets=margin_used,  # 冻结资产
                margin_balance=margin_balance,  # 保证金余额
                unrealized_pnl=unrealized_pnl,  # 未实现盈亏
                risk_ratio=margin_level,  # 风险率
                total_positions=total_positions,  # 总持仓 (数量)
                daily_pnl=daily_pnl,  # 当日盈亏
                funding_fee=account_total_swap,  # MT5过夜费：使用账户累计总过夜费（包含已平仓+未平仓）
                long_swap_fee=long_swap_fee,  # 做多掉期费（今日）
                short_swap_fee=short_swap_fee,  # 做空掉期费（今日）
                commission_fee=commission_fee,  # 手续费
                # Position data for liquidation price calculation
                entry_price=avg_entry_price,  # 开仓均价
                leverage=int(mt5_info.get("leverage", 0)),  # 杠杆倍数
                volume=total_positions,  # 持仓手数
                equity=equity,  # 账户权益
                # MT5 native liquidation prices from Bybit
                long_liquidation_price=long_liquidation_price,  # 多头强平价
                short_liquidation_price=short_liquidation_price,  # 空头强平价
            )
        except Exception as e:
            logger.error(f"Failed to fetch MT5 balance: {str(e)}")
            raise

    async def _get_bybit_unified_balance(
        self,
        client: "BybitV5Client",
    ) -> AccountBalance:
        """Fetch Bybit Unified account balance using V5 API"""
        from datetime import datetime

        # 1. Get wallet balance from /v5/account/wallet-balance?coin=USDT
        wallet_data = await client.get_wallet_balance("UNIFIED", coin="USDT")
        logger.info(f"Bybit wallet data received: {wallet_data}")

        account_list = wallet_data.get("list", [])
        if not account_list:
            logger.error("No account data found in Bybit response")
            raise Exception("No account data found")

        account = account_list[0]

        # Extract balance data using V5 API field names per Bybit V5 documentation
        total_equity = float(account.get("totalEquity", 0))  # 总资产 (账户总权益)
        total_wallet_balance = float(account.get("totalWalletBalance", 0))  # 净资产 (钱包余额)
        total_available_balance = float(account.get("totalAvailableBalance", 0))  # 可用资产
        total_initial_margin = float(account.get("totalInitialMargin", 0))  # 冻结资产 (初始保证金)
        total_margin_balance = float(account.get("totalMarginBalance", 0))  # 保证金余额
        total_maintenance_margin = float(account.get("totalMaintenanceMargin", 0))  # 维持保证金

        # Calculate risk ratio: (totalMaintenanceMargin / totalMarginBalance) × 100
        risk_ratio = 0
        if total_margin_balance > 0:
            risk_ratio = (total_maintenance_margin / total_margin_balance) * 100

        # Get unrealized PnL from coin data
        coins = account.get("coin", [])
        unrealized_pnl = 0
        if coins:
            unrealized_pnl = float(coins[0].get("unrealisedPnl", 0))

        # 2. Get total positions from /v5/position/list?settleCoin=USDT
        total_positions = 0
        total_unrealized_pnl = 0  # Track unrealized PnL from positions
        try:
            logger.info("Fetching Bybit positions")
            positions_data = await client.get_positions(category="linear", settle_coin="USDT")
            if isinstance(positions_data, dict):
                positions_list = positions_data.get("list", [])
                # Sum up position quantities (not values) and unrealized PnL
                for pos in positions_list:
                    size = float(pos.get("size", 0))
                    # Bybit XAUUSD: 1 contract = 0.01 oz, convert to actual oz
                    # For example: 77 contracts = 77 * 0.01 = 0.77 oz
                    actual_size = abs(size) * 0.01
                    total_positions += actual_size
                    total_unrealized_pnl += float(pos.get("unrealisedPnl", 0))
            logger.info(f"Total positions calculated: {total_positions} (oz), unrealized PnL: {total_unrealized_pnl}")
        except Exception as e:
            logger.error(f"Failed to fetch Bybit positions: {str(e)}")

        # 3. Get daily P&L from /v5/position/closed-pnl?settleCoin=USDT (today)
        daily_pnl = 0
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(today_start.timestamp() * 1000)
        end_time = int(datetime.utcnow().timestamp() * 1000)

        try:
            logger.info(f"Fetching Bybit daily P&L from {start_time} to {end_time}")
            pnl_data = await client.get_profit_loss(
                category="linear",
                start_time=start_time,
                end_time=end_time,
                settle_coin="USDT"
            )
            if isinstance(pnl_data, dict):
                pnl_list = pnl_data.get("list", [])
                for pnl in pnl_list:
                    daily_pnl += float(pnl.get("closedPnl", 0))
            # Add unrealized PnL to daily PnL as per requirements
            daily_pnl += total_unrealized_pnl
            logger.info(f"Daily P&L calculated: {daily_pnl} (closed: {daily_pnl - total_unrealized_pnl}, unrealized: {total_unrealized_pnl})")
        except Exception as e:
            logger.error(f"Failed to fetch Bybit daily P&L: {str(e)}")

        # 4. Get funding fee from /v5/account/funding-fee?settleCoin=USDT (today)
        funding_fee = 0
        long_swap_fee = 0
        short_swap_fee = 0
        commission_fee = 0
        try:
            logger.info("Fetching Bybit funding fee")
            funding_data = await client.get_funding_fee(
                category="linear",
                start_time=start_time,
                end_time=end_time,
                settle_coin="USDT"
            )
            if isinstance(funding_data, dict) and funding_data.get("list"):
                funding_list = funding_data.get("list", [])
                for fee in funding_list:
                    fee_amount = float(fee.get("fundingFee", 0))
                    funding_fee += fee_amount
                    # Separate long and short swap fees
                    # Positive funding fee means paying (short position)
                    # Negative funding fee means receiving (long position)
                    if fee_amount > 0:
                        short_swap_fee += fee_amount
                    else:
                        long_swap_fee += fee_amount
            logger.info(f"Funding fee calculated: {funding_fee}, long: {long_swap_fee}, short: {short_swap_fee}")
        except Exception as e:
            logger.error(f"Failed to fetch Bybit funding fee: {str(e)}")
            # Don't fail the entire request if funding fee fetch fails
            funding_fee = 0

        balance = AccountBalance(
            total_assets=total_equity,  # 总资产 = totalEquity
            available_balance=total_available_balance,  # 可用资产 = totalAvailableBalance
            net_assets=total_wallet_balance,  # 净资产 = totalWalletBalance
            frozen_assets=total_initial_margin,  # 冻结资产 = totalInitialMargin
            margin_balance=total_margin_balance,  # 保证金余额 = totalMarginBalance
            unrealized_pnl=unrealized_pnl,  # 未实现盈亏
            risk_ratio=risk_ratio,  # 风险率 = (totalMaintenanceMargin / totalMarginBalance) × 100
            total_positions=total_positions,  # 总持仓
            daily_pnl=daily_pnl,  # 当日盈亏 (closedPnl + unrealizedPnl)
            funding_fee=funding_fee,  # 资金费
            long_swap_fee=long_swap_fee,  # 做多掉期费
            short_swap_fee=short_swap_fee,  # 做空掉期费
            commission_fee=commission_fee,  # 手续费(佣金) - placeholder for now
        )
        logger.info(f"Bybit balance calculated: {balance}")
        return balance

    async def get_binance_positions(
        self,
        api_key: str,
        api_secret: str,
        symbol: Optional[str] = None,
        proxy_url: str = None,
    ) -> List[AccountPosition]:
        """Fetch Binance positions"""
        client = BinanceFuturesClient(api_key, api_secret, proxy_url=proxy_url)

        try:
            positions_data = await client.get_position_risk(symbol)

            positions = []
            for pos in positions_data:
                position_amt = float(pos.get("positionAmt", 0))

                # Skip positions with zero amount
                if position_amt == 0:
                    continue

                positions.append(
                    AccountPosition(
                        symbol=pos.get("symbol"),
                        side="Buy" if position_amt > 0 else "Sell",
                        size=abs(position_amt),
                        entry_price=float(pos.get("entryPrice", 0)),
                        mark_price=float(pos.get("markPrice", 0)),
                        unrealized_pnl=float(pos.get("unRealizedProfit", 0)),
                        leverage=int(pos.get("leverage", 1)),
                    )
                )

            return positions
        finally:
            await client.close()

    async def get_bybit_positions(
        self,
        api_key: str,
        api_secret: str,
        category: str = "linear",
        symbol: Optional[str] = None,
        settle_coin: str = "USDT",
        proxy_url: str = None,
    ) -> List[AccountPosition]:
        """Fetch Bybit positions"""
        client = BybitV5Client(api_key, api_secret, proxy_url=proxy_url)

        try:
            positions_data = await client.get_positions(category, symbol, settle_coin)

            positions = []
            position_list = positions_data.get("list", [])

            for pos in position_list:
                size = float(pos.get("size", 0))

                # Skip positions with zero size
                if size == 0:
                    continue

                positions.append(
                    AccountPosition(
                        symbol=pos.get("symbol"),
                        side=pos.get("side"),
                        size=size,
                        entry_price=float(pos.get("avgPrice", 0)),
                        mark_price=float(pos.get("markPrice", 0)),
                        unrealized_pnl=float(pos.get("unrealisedPnl", 0)),
                        leverage=int(pos.get("leverage", 1)),
                    )
                )

            return positions
        finally:
            await client.close()

    async def get_mt5_positions(
        self,
        mt5_id: int,
        mt5_password: str,
        mt5_server: str,
        symbol: Optional[str] = None,
    ) -> List[AccountPosition]:
        """Fetch MT5 positions using MT5 client"""
        try:
            logger.info(f"Fetching MT5 positions for account {mt5_id}")
            # Use shared MT5 client from realtime_market_service to avoid connection conflicts
            from app.services.realtime_market_service import market_data_service
            mt5 = market_data_service.mt5_client

            positions_data = []
            if mt5 and mt5.connected:
                positions_data = mt5.get_positions(symbol)
            else:
                # Fallback: create temporary client
                temp_mt5 = MT5Client(
                    login=int(mt5_id),
                    password=mt5_password,
                    server=mt5_server
                )
                if temp_mt5.connect():
                    positions_data = temp_mt5.get_positions(symbol)
                    temp_mt5.disconnect()

            positions = []
            for pos in positions_data:
                volume = float(pos.get("volume", 0))

                # Skip positions with zero volume
                if volume == 0:
                    continue

                # MT5 position type: 0=Buy, 1=Sell
                pos_type = pos.get("type", 0)
                side = "Buy" if pos_type == 0 else "Sell"

                positions.append(
                    AccountPosition(
                        symbol=pos.get("symbol"),
                        side=side,
                        size=volume,
                        entry_price=float(pos.get("price_open", 0)),
                        mark_price=float(pos.get("price_current", 0)),
                        unrealized_pnl=float(pos.get("profit", 0)),
                        leverage=1,
                        ticket=pos.get("ticket"),
                    )
                )

            logger.info(f"MT5 positions fetched: {len(positions)} positions")
            return positions

        except Exception as e:
            logger.error(f"Failed to fetch MT5 positions: {str(e)}")
            return []

    async def get_binance_daily_pnl(
        self,
        api_key: str,
        api_secret: str,
        symbol: Optional[str] = None,
        proxy_url: str = None,
    ) -> float:
        """Calculate Binance daily P&L from income history"""
        client = BinanceFuturesClient(api_key, api_secret, proxy_url=proxy_url)

        try:
            # Get today's start timestamp
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = int(today_start.timestamp() * 1000)

            # Fetch realized P&L for today
            income_data = await client.get_income(
                symbol=symbol,
                income_type="REALIZED_PNL",
                start_time=start_time,
                limit=1000,
            )

            # Sum up all realized P&L
            total_pnl = sum(float(item.get("income", 0)) for item in income_data)

            return total_pnl
        finally:
            await client.close()

    async def get_bybit_daily_pnl(
        self,
        api_key: str,
        api_secret: str,
        account_type: str = "UNIFIED",
        category: str = "linear",
        proxy_url: str = None,
    ) -> float:
        """Calculate Bybit daily P&L from transaction log"""
        client = BybitV5Client(api_key, api_secret, proxy_url=proxy_url)

        try:
            # Get today's start timestamp
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = int(today_start.timestamp() * 1000)

            # Fetch transaction log for today
            transaction_data = await client.get_transaction_log(
                account_type=account_type,
                category=category,
                start_time=start_time,
                limit=200,
            )

            # Sum up realized P&L from transactions
            total_pnl = 0
            transaction_list = transaction_data.get("list", [])

            for tx in transaction_list:
                tx_type = tx.get("type", "")
                if "REALIZED_PNL" in tx_type or "TRADE" in tx_type:
                    total_pnl += float(tx.get("cashFlow", 0))

            return total_pnl
        finally:
            await client.close()

    async def get_account_data(
        self,
        account: Account,
    ) -> Dict[str, Any]:
        """Get comprehensive account data for a single account with caching"""
        platform_id = account.platform_id
        account_id_str = str(account.account_id)

        # Check cache first
        cache_key = self._get_cache_key(account_id_str, "account_data")
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            logger.debug(f"Returning cached account data for {account_id_str}")
            return cached_data

        try:
            # Build proxy URL from account's proxy_config
            proxy_url = build_proxy_url(account.proxy_config)
            if proxy_url:
                logger.info(f"Account {account_id_str} using proxy: {account.proxy_config.get('host')}:{account.proxy_config.get('port')}")

            if platform_id == 1:  # Binance
                balance, positions, daily_pnl = await asyncio.gather(
                    self.get_binance_balance(account.api_key, account.api_secret, proxy_url=proxy_url),
                    self.get_binance_positions(account.api_key, account.api_secret, proxy_url=proxy_url),
                    self.get_binance_daily_pnl(account.api_key, account.api_secret, proxy_url=proxy_url),
                )
            elif platform_id == 2:  # Bybit
                # Bybit V5 API only supports UNIFIED account type
                account_type = "UNIFIED"

                if account.is_mt5_account:
                    # MT5 账户：统一通过 MT5 HTTP Bridge 获取余额和持仓
                    # （Linux 服务器无法运行 MetaTrader5 直连，始终走 Bridge）
                    import os
                    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
                    bridge_url = os.getenv("MT5_BRIDGE_URL", f"{bridge_host}:8001")
                    try:
                        from app.models.mt5_client import MT5Client as MT5ClientModel
                        from app.core.database import AsyncSessionLocal
                        async with AsyncSessionLocal() as _db:
                            mc_result = await _db.execute(
                                select(MT5ClientModel)
                                .where(MT5ClientModel.account_id == account.account_id)
                                .where(MT5ClientModel.is_active == True)
                                .order_by(MT5ClientModel.priority)
                                .limit(1)
                            )
                            mc = mc_result.scalar_one_or_none()
                            if mc:
                                # 优先用 bridge_service_port（部署时写入的正确端口）
                                if mc.bridge_service_port:
                                    bridge_url = f"{bridge_host}:{mc.bridge_service_port}"
                                elif mc.bridge_url:
                                    bridge_url = mc.bridge_url
                                logger.info(f"MT5 account {account_id_str} bridge={bridge_url} (login={mc.mt5_login})")
                    except Exception as e:
                        logger.warning(f"MT5 client lookup failed for {account_id_str}: {e}")

                    mt5_http = MT5HttpClient(base_url=bridge_url)
                    async def _noop_pnl():
                        return 0
                    _bybit_pnl_coro = self.get_bybit_daily_pnl(account.api_key, account.api_secret, account_type, proxy_url=proxy_url) if account.api_key else _noop_pnl()
                    mt5_info, mt5_positions_raw, mt5_deals_raw, daily_pnl = await asyncio.gather(
                        mt5_http.get_account_info(),
                        mt5_http.get_positions(),
                        mt5_http.get_deals_history(),
                        _bybit_pnl_coro,
                    )
                    # Convert MT5 Bridge response to AccountBalance
                    if mt5_info:
                        # 从仓位列表统计总持仓手数和浮动盈亏
                        _positions_raw = mt5_positions_raw or []
                        _total_positions = sum(abs(float(p.get('volume', 0))) for p in _positions_raw)
                        _floating_pnl = float(mt5_info.get('profit', 0))  # info.profit = 所有持仓浮动盈亏之和

                        # 计算当日已实现盈亏（从 deals history 中平仓交易的 profit 字段）
                        # HTTP Bridge 返回的 deals 中 entry 字段可能为 None
                        # 开仓 deal 的 profit 始终为 0，平仓 deal 的 profit 为实现盈亏
                        _realized_pnl = 0.0
                        for _deal in (mt5_deals_raw or []):
                            _deal_entry = _deal.get('entry')
                            _deal_profit = float(_deal.get('profit', 0))
                            if _deal_entry == 1 or (_deal_entry is None and _deal_profit != 0):
                                _realized_pnl += _deal_profit

                        # 计算 margin_level（风险率）
                        _margin = float(mt5_info.get('margin', 0))
                        _equity = float(mt5_info.get('equity', 0))
                        _margin_level = (_equity / _margin * 100) if _margin > 0.01 else 0.0

                        # ── 强平价计算（Bybit MT5 全仓账户官方逻辑）────────────────
                        # Bybit MT5 全仓（Portfolio Margin）止损规则：
                        #   当账户净值（Equity）≤ 已用保证金（Used Margin）× 50% 时强平
                        #   → stop-out level = 50% of initial margin
                        #
                        # 全仓模式下所有仓位共享保证金，强平价由账户整体净值/保证金决定。
                        # MT5 终端原生 p.price_liquidation 按逐仓（Isolated）模式计算且
                        # 在全仓模式下返回 0，不可使用。
                        #
                        # 推导过程：
                        #   强平触发条件: equity_liq = margin_used × 0.50
                        #   equity_liq = equity + pnl_at_liq
                        #   pnl_at_liq = (liq_price - entry) × lots × 100 [空头取负]
                        #
                        # Long:  liq_price = entry - (equity - margin×0.5) / (lots×100)
                        # Short: liq_price = entry + (equity - margin×0.5) / (lots×100)
                        #
                        # 其中 100 = Bybit XAUUSD+ 合约乘数（每手 = 100 盎司黄金）
                        #
                        # 验证（当前数据）：
                        #   equity=453.5, margin=9.49, safety_buffer=453.5-4.745=448.755
                        #   short_avg_entry=4747.49, short_lots=0.01
                        #   short_liq = 4747.49 + 448.755/(0.01×100) = 4747.49+448.755 ≈ 5196
                        _, _, _conv2 = _get_pair_config()
                        _CONTRACT_SIZE = _conv2   # Bybit: 1 lot = _CONTRACT_SIZE oz
                        _STOP_OUT_PCT  = 0.50  # Bybit MT5 全仓止损线 = 50% 初始保证金

                        # 安全垫 = 净值减去维持保证金（触发强平时还剩多少亏损空间）
                        _safety_buffer = _equity - _margin * _STOP_OUT_PCT

                        _long_vol, _long_wprice   = 0.0, 0.0
                        _short_vol, _short_wprice = 0.0, 0.0
                        for _p in _positions_raw:
                            _vol   = abs(float(_p.get('volume', 0)))
                            _entry = float(_p.get('price_open', 0))
                            if _vol <= 0 or _entry <= 0:
                                continue
                            if int(_p.get('type', 0)) == 0:  # Buy = Long
                                _long_vol   += _vol
                                _long_wprice += _vol * _entry
                            else:                              # Sell = Short
                                _short_vol   += _vol
                                _short_wprice += _vol * _entry

                        _long_liq  = 0.0
                        _short_liq = 0.0
                        if _long_vol > 0:
                            _long_avg = _long_wprice / _long_vol
                            _raw_liq  = _long_avg - _safety_buffer / (_long_vol * _CONTRACT_SIZE)
                            _long_liq = round(_raw_liq, 2) if _raw_liq > 0 else 0.0
                        if _short_vol > 0:
                            _short_avg = _short_wprice / _short_vol
                            _raw_liq   = _short_avg + _safety_buffer / (_short_vol * _CONTRACT_SIZE)
                            # 强平价必须高于开仓均价（空头才合理）
                            _short_liq = round(_raw_liq, 2) if _raw_liq > _short_avg else 0.0

                        logger.info(
                            f"[MT5_BRIDGE_LIQ] equity={_equity:.2f} margin={_margin:.2f} "
                            f"buffer={_safety_buffer:.2f} "
                            f"short_vol={_short_vol} short_liq={_short_liq} "
                            f"long_vol={_long_vol} long_liq={_long_liq}"
                        )

                        balance = AccountBalance(
                            total_assets=float(mt5_info.get('balance', 0)),  # 账户余额（不含浮动）
                            available_balance=float(mt5_info.get('margin_free', 0)),
                            net_assets=_equity,                              # 净值 = balance + floating pnl
                            frozen_assets=_margin,
                            margin_balance=_equity,
                            unrealized_pnl=_floating_pnl,                   # equity - balance
                            risk_ratio=_margin_level,
                            total_positions=_total_positions,                # 总持仓手数
                            daily_pnl=_realized_pnl + _floating_pnl,        # 当日盈亏 = 已实现平仓盈亏 + 未实现浮动盈亏
                            funding_fee=float(mt5_info.get('swap', 0)),      # 累计过夜费（持仓+历史）
                            commission_fee=0.0,                              # HTTP bridge 路径暂无 deals 历史，默认0
                            long_liquidation_price=_long_liq,               # 多头强平价
                            short_liquidation_price=_short_liq,             # 空头强平价
                        )
                    else:
                        balance = AccountBalance(
                            total_assets=0, available_balance=0, net_assets=0,
                            frozen_assets=0, margin_balance=0, unrealized_pnl=0,
                            total_positions=0, daily_pnl=0, funding_fee=0, commission_fee=0,
                        )
                    # Convert MT5 positions
                    positions = []
                    for p in (mt5_positions_raw or []):
                        positions.append(AccountPosition(
                            symbol=p.get('symbol', ''),
                            side='buy' if p.get('type', 0) == 0 else 'sell',
                            size=abs(p.get('volume', 0)),
                            entry_price=p.get('price_open', 0),
                            mark_price=p.get('price_current', 0),
                            unrealized_pnl=p.get('profit', 0),
                            leverage=p.get('leverage', 500),
                            ticket=p.get('ticket'),
                        ))
                else:
                    # 普通 Bybit 账户 — 用 V5 API
                    balance, positions, daily_pnl = await asyncio.gather(
                        self.get_bybit_balance(
                            account.api_key,
                            account.api_secret,
                            account_type,
                            proxy_url=proxy_url,
                        ),
                        self.get_bybit_positions(account.api_key, account.api_secret, proxy_url=proxy_url),
                        self.get_bybit_daily_pnl(account.api_key, account.api_secret, account_type, proxy_url=proxy_url),
                    )
            elif platform_id == 3:  # IC Markets (MT5-only broker)
                # IC Markets 只使用 MT5，通过 MT5 HTTP Bridge 获取数据
                import os
                bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
                bridge_url = os.getenv("MT5_BRIDGE_URL", f"{bridge_host}:8001")
                try:
                    from app.models.mt5_client import MT5Client as MT5ClientModel
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as _db:
                        mc_result = await _db.execute(
                            select(MT5ClientModel)
                            .where(MT5ClientModel.account_id == account.account_id)
                            .where(MT5ClientModel.is_active == True)
                            .order_by(MT5ClientModel.priority)
                            .limit(1)
                        )
                        mc = mc_result.scalar_one_or_none()
                        if mc:
                            port = mc.bridge_service_port or 8001
                            bridge_url = f"{bridge_host}:{port}"
                            logger.info(f"IC Markets account {account_id_str} bridge={bridge_url} (login={mc.mt5_login})")
                except Exception as e:
                    logger.warning(f"MT5 client lookup failed for IC Markets {account_id_str}: {e}")

                mt5_http = MT5HttpClient(base_url=bridge_url)
                mt5_info, mt5_positions_raw, mt5_deals_raw = await asyncio.gather(
                    mt5_http.get_account_info(),
                    mt5_http.get_positions(),
                    mt5_http.get_deals_history(),
                )

                if mt5_info:
                    _positions_raw = mt5_positions_raw or []
                    _total_positions = sum(abs(float(p.get('volume', 0))) for p in _positions_raw)
                    _floating_pnl = float(mt5_info.get('profit', 0))

                    # 已实现盈亏
                    _realized_pnl = 0.0
                    for _deal in (mt5_deals_raw or []):
                        _deal_entry = _deal.get('entry')
                        _deal_profit = float(_deal.get('profit', 0))
                        if _deal_entry == 1 or (_deal_entry is None and _deal_profit != 0):
                            _realized_pnl += _deal_profit

                    _margin = float(mt5_info.get('margin', 0))
                    _equity = float(mt5_info.get('equity', 0))
                    _margin_level = (_equity / _margin * 100) if _margin > 0.01 else 0.0

                    # IC Markets 强平价计算（标准 MT5 全仓, stop-out = 50%）
                    _CONTRACT_SIZE = 100.0  # IC Markets XAUUSD: 1 lot = 100 oz
                    _STOP_OUT_PCT = 0.50
                    _safety_buffer = _equity - _margin * _STOP_OUT_PCT

                    _long_vol, _long_wprice = 0.0, 0.0
                    _short_vol, _short_wprice = 0.0, 0.0
                    for _p in _positions_raw:
                        _vol = abs(float(_p.get('volume', 0)))
                        _entry = float(_p.get('price_open', 0))
                        if _vol <= 0 or _entry <= 0:
                            continue
                        if int(_p.get('type', 0)) == 0:
                            _long_vol += _vol
                            _long_wprice += _vol * _entry
                        else:
                            _short_vol += _vol
                            _short_wprice += _vol * _entry

                    _long_liq = 0.0
                    _short_liq = 0.0
                    if _long_vol > 0:
                        _long_avg = _long_wprice / _long_vol
                        _raw_liq = _long_avg - _safety_buffer / (_long_vol * _CONTRACT_SIZE)
                        _long_liq = round(_raw_liq, 2) if _raw_liq > 0 else 0.0
                    if _short_vol > 0:
                        _short_avg = _short_wprice / _short_vol
                        _raw_liq = _short_avg + _safety_buffer / (_short_vol * _CONTRACT_SIZE)
                        _short_liq = round(_raw_liq, 2) if _raw_liq > _short_avg else 0.0

                    balance = AccountBalance(
                        total_assets=float(mt5_info.get('balance', 0)),
                        available_balance=float(mt5_info.get('margin_free', 0)),
                        net_assets=_equity,
                        frozen_assets=_margin,
                        margin_balance=_equity,
                        unrealized_pnl=_floating_pnl,
                        risk_ratio=_margin_level,
                        total_positions=_total_positions,
                        daily_pnl=_realized_pnl + _floating_pnl,
                        funding_fee=float(mt5_info.get('swap', 0)),
                        commission_fee=0.0,
                        long_liquidation_price=_long_liq,
                        short_liquidation_price=_short_liq,
                    )
                else:
                    balance = AccountBalance(
                        total_assets=0, available_balance=0, net_assets=0,
                        frozen_assets=0, margin_balance=0, unrealized_pnl=0,
                        total_positions=0, daily_pnl=0, funding_fee=0, commission_fee=0,
                    )

                positions = []
                for p in (mt5_positions_raw or []):
                    positions.append(AccountPosition(
                        symbol=p.get('symbol', ''),
                        side='buy' if p.get('type', 0) == 0 else 'sell',
                        size=abs(p.get('volume', 0)),
                        entry_price=p.get('price_open', 0),
                        mark_price=p.get('price_current', 0),
                        unrealized_pnl=p.get('profit', 0),
                        leverage=p.get('leverage', 500),
                        ticket=p.get('ticket'),
                    ))
                daily_pnl = balance.daily_pnl or 0
            elif platform_id == 4:  # Gate.io Futures
                from app.services.gateio_client import GateioFuturesClient
                from app.core.proxy_utils import build_proxy_url as _bpu
                _gclient = GateioFuturesClient(
                    api_key=account.api_key,
                    api_secret=account.api_secret,
                    proxy_url=_bpu(account.proxy_config),
                )
                try:
                    acc_data, positions_raw = await asyncio.gather(
                        _gclient.get_account(),
                        _gclient.get_positions(),
                    )
                    # Gate 统一保证金模式 (margin_mode_name=single_currency) 下 total/available/position_margin
                    # 都只反映 classic 子账户；真实权益在 cross_* 字段。优先用 cross_*，否则回退 classic。
                    _cross_avail = float(acc_data.get("cross_available", 0) or 0)
                    _cross_im = float(acc_data.get("cross_initial_margin", 0) or 0)
                    _cross_upnl = float(acc_data.get("cross_unrealised_pnl", 0) or 0)
                    _classic_total = float(acc_data.get("total", 0) or 0)
                    _classic_avail = float(acc_data.get("available", 0) or 0)
                    _classic_margin = float(acc_data.get("position_margin", 0) or 0)
                    _classic_upnl = float(acc_data.get("unrealised_pnl", 0) or 0)
                    _is_unified = (acc_data.get("margin_mode_name") == "single_currency") or _classic_total == 0
                    if _is_unified and (_cross_avail or _cross_im or _cross_upnl):
                        _equity = _cross_avail + _cross_im + _cross_upnl
                        _avail = _cross_avail
                        _margin = _cross_im
                        _upnl = _cross_upnl
                    else:
                        _equity = _classic_total
                        _avail = _classic_avail
                        _margin = _classic_margin
                        _upnl = _classic_upnl
                    balance = AccountBalance(
                        total_assets=_equity,
                        available_balance=_avail,
                        net_assets=_equity,
                        frozen_assets=_margin,
                        margin_balance=_equity,
                        unrealized_pnl=_upnl,
                        total_positions=len(positions_raw),
                        daily_pnl=_upnl,
                        funding_fee=0.0,
                        commission_fee=0.0,
                    )
                    positions = []
                    for p in positions_raw:
                        size = float(p.get("size", 0))
                        positions.append(AccountPosition(
                            symbol=p.get("contract", ""),
                            side="buy" if size > 0 else "sell",
                            size=abs(size),
                            entry_price=float(p.get("entry_price", 0)),
                            mark_price=float(p.get("mark_price", 0)),
                            unrealized_pnl=float(p.get("unrealised_pnl", 0)),
                            leverage=int(p.get("leverage", 0)),
                        ))
                    daily_pnl = _upnl
                except Exception as _ge:
                    logger.error(f"Gate.io account data failed for {account_id_str}: {_ge}")
                    balance = AccountBalance(
                        total_assets=0, available_balance=0, net_assets=0,
                        frozen_assets=0, margin_balance=0, unrealized_pnl=0,
                        total_positions=0, daily_pnl=0, funding_fee=0, commission_fee=0,
                    )
                    positions = []
                    daily_pnl = 0.0
                finally:
                    await _gclient.close()
            else:
                raise ValueError(f"Unknown platform_id: {platform_id}")

            result = {
                "account_id": account_id_str,
                "user_id": str(account.user_id) if account.user_id else None,
                "account_name": account.account_name,
                "platform_id": platform_id,
                "is_mt5_account": account.is_mt5_account,
                "mt5_id": account.mt5_id,  # Used for MT5 position deduplication across duplicate DB accounts
                "is_active": account.is_active,
                "account_role": getattr(account, 'account_role', None),
                "proxy_config": account.proxy_config,
                "balance": balance.model_dump(),
                "positions": [pos.model_dump() for pos in positions],
                # 优先使用 balance.daily_pnl（已包含 realized + unrealized）
                # 对于 Binance: balance.daily_pnl = REALIZED_PNL income + totalUnrealizedProfit
                # 对于 MT5:     balance.daily_pnl = deals realized PnL + floating PnL (equity - balance)
                "daily_pnl": balance.daily_pnl if balance.daily_pnl != 0 else daily_pnl,
            }

            # Log balance data for debugging
            logger.info(f"Account {account_id_str} balance data: funding_fee={balance.funding_fee}, total_assets={balance.total_assets}, daily_pnl={balance.daily_pnl}, unrealized_pnl={balance.unrealized_pnl}")

            # Cache the result
            self._set_cached_data(cache_key, result)
            return result
        except Exception as e:
            raise Exception(f"Failed to fetch account data: {str(e)}")

    async def get_aggregated_account_data(
        self,
        accounts: List[Account],
    ) -> Dict[str, Any]:
        """Aggregate data from multiple accounts"""
        import asyncio

        # Deduplicate accounts — same physical exchange account may be registered under multiple users
        seen = set()
        seen_names = set()  # Secondary dedup by (platform_id, account_name) for same-name accounts
        unique_accounts = []
        for account in accounts:
            # MT5: deduplicate by mt5_id
            if account.is_mt5_account and account.mt5_id:
                key = (account.platform_id, 'mt5', account.mt5_id)
            # REST accounts: deduplicate by api_key
            elif account.api_key:
                key = (account.platform_id, account.api_key)
            else:
                key = (account.platform_id, account.account_name or account.account_id)

            # Also deduplicate by account_name within same platform (catches same account with different API keys)
            name_key = (account.platform_id, (account.account_name or '').strip())

            if key not in seen and name_key not in seen_names:
                seen.add(key)
                if name_key[1]:  # Only track non-empty names
                    seen_names.add(name_key)
                unique_accounts.append(account)
            else:
                logger.warning(f"Skipping duplicate account: {account.account_name} (ID: {account.account_id})")

        # Fetch data from all unique accounts concurrently
        account_data_list = await asyncio.gather(
            *[self.get_account_data(account) for account in unique_accounts],
            return_exceptions=True,
        )

        # Separate successful and failed fetches
        successful_accounts = []
        failed_accounts = []

        for i, data in enumerate(account_data_list):
            if isinstance(data, Exception):
                error_msg = str(data)
                # Check if it's a rate limit ban with timestamp
                if error_msg.startswith("RATE_LIMIT_BAN:"):
                    ban_until_ms = error_msg.split(":")[1]
                    error_msg = f"RATE_LIMIT:{ban_until_ms}"

                failed_accounts.append({
                    "account_id": str(unique_accounts[i].account_id),
                    "account_name": unique_accounts[i].account_name,
                    "platform_id": unique_accounts[i].platform_id,
                    "is_mt5_account": unique_accounts[i].is_mt5_account,
                    "is_active": unique_accounts[i].is_active,  # Include is_active status
                    "account_role": getattr(unique_accounts[i], 'account_role', None),
                    "proxy_config": unique_accounts[i].proxy_config,
                    "error": error_msg,
                })
            else:
                successful_accounts.append(data)

        # Aggregate balances
        total_assets = sum(acc["balance"]["total_assets"] for acc in successful_accounts)
        total_available = sum(acc["balance"]["available_balance"] for acc in successful_accounts)
        total_net_assets = sum(acc["balance"]["net_assets"] for acc in successful_accounts)
        total_frozen = sum(acc["balance"]["frozen_assets"] for acc in successful_accounts)
        total_margin = sum(acc["balance"]["margin_balance"] for acc in successful_accounts)
        total_unrealized_pnl = sum(acc["balance"]["unrealized_pnl"] for acc in successful_accounts)
        total_daily_pnl = sum(acc["daily_pnl"] for acc in successful_accounts)

        # Aggregate positions with deduplication
        all_positions = []
        seen_positions = set()  # Deduplicate by (platform_id, ticket) for MT5, or (account_id, symbol, side) for Binance

        for acc in successful_accounts:
            for pos in acc["positions"]:
                # MT5: deduplicate by (platform_id + mt5_id + ticket) — same physical MT5 account may appear under multiple DB accounts
                # Binance: deduplicate by (account_id + symbol + side) — hedge mode has one position per side
                ticket = pos.get("ticket")
                if ticket and acc.get("is_mt5_account"):
                    mt5_id = acc.get("mt5_id", acc["account_id"])
                    pos_key = (acc["platform_id"], mt5_id, ticket)
                else:
                    pos_key = (
                        acc["account_id"],
                        pos.get("symbol", ""),
                        pos.get("side", ""),
                        round(float(pos.get("size", 0)), 6),
                        round(float(pos.get("entry_price", 0)), 2)
                    )

                # Only add if not seen before
                if pos_key not in seen_positions:
                    seen_positions.add(pos_key)
                    pos["account_id"] = acc["account_id"]
                    pos["account_name"] = acc["account_name"]
                    pos["platform_id"] = acc["platform_id"]
                    pos["is_mt5_account"] = acc["is_mt5_account"]
                    all_positions.append(pos)
                else:
                    logger.warning(f"Skipping duplicate position: {acc['account_name']} {pos.get('symbol')} {pos.get('side')} {pos.get('size')} @ {pos.get('entry_price')}")

        # Calculate average risk ratio (weighted by margin balance)
        total_risk_weighted = 0
        total_margin_for_risk = 0

        for acc in successful_accounts:
            risk_ratio = acc["balance"].get("risk_ratio")
            margin = acc["balance"]["margin_balance"]

            if risk_ratio is not None and margin > 0:
                total_risk_weighted += risk_ratio * margin
                total_margin_for_risk += margin

        avg_risk_ratio = (total_risk_weighted / total_margin_for_risk) if total_margin_for_risk > 0 else None

        return {
            "summary": {
                "total_assets": total_assets,
                "available_balance": total_available,
                "net_assets": total_net_assets,
                "frozen_assets": total_frozen,
                "margin_balance": total_margin,
                "unrealized_pnl": total_unrealized_pnl,
                "daily_pnl": total_daily_pnl,
                "risk_ratio": avg_risk_ratio,
                "account_count": len(successful_accounts),
                "position_count": len(all_positions),
            },
            "accounts": successful_accounts,
            "positions": all_positions,
            "failed_accounts": failed_accounts,
        }


# Global instance
account_data_service = AccountDataService()


async def _trigger_binance_ban_alert_all_users(e) -> None:
    """Binance IP封禁时向所有活跃用户推送飞书+弹窗告警"""
    try:
        from app.services.risk_alert_service import risk_alert_service
        from app.database import get_db_session
        from sqlalchemy import select
        from app.models.user import User

        async with get_db_session(timeout=5.0) as db:
            result = await db.execute(select(User).where(User.is_active == True))
            users = result.scalars().all()

        for user in users:
            try:
                await risk_alert_service.check_binance_ip_ban(
                    user_id=str(user.user_id),
                    ip=e.ip,
                    ban_until_ms=e.ban_until_ms,
                    message=e.message,
                )
            except Exception as _ue:
                logger.debug(f"[IP封禁告警] user {user.user_id} 推送失败: {_ue}")
    except Exception as ex:
        logger.error(f"[IP封禁告警] 全局推送失败: {ex}")
