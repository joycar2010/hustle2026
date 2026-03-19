"""Account data service for fetching account information from exchanges"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from app.services.binance_client import BinanceFuturesClient
from app.services.bybit_client import BybitV5Client
from app.services.mt5_client import MT5Client
from app.models.account import Account
from app.schemas.account import AccountBalance, AccountPosition

logger = logging.getLogger(__name__)


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

    async def get_binance_balance(self, api_key: str, api_secret: str) -> AccountBalance:
        """Fetch Binance account balance including spot, margin and futures data"""
        client = BinanceFuturesClient(api_key, api_secret)

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
            fetch_tasks = [
                client.get_account(),           # USDT-M Futures  [0]
                client.get_position_risk(),     # Futures positions [1]
                client.get_income(income_type="REALIZED_PNL", start_time=start_time, limit=1000),  # [2]
                client.get_income(income_type="FUNDING_FEE", start_time=start_time, limit=1000),   # [3]
                client.get_income(income_type="COMMISSION", start_time=start_time, limit=1000),    # [4]
                client.get_margin_account(),    # Cross Margin     [5]
                client.get_commission_rate("XAUUSDT"),  # Maker/taker fee rate [6]
                client.get_spot_price("BNBUSDT"),       # BNB/USDT price for fee conversion [7]
                client.get_balance(),           # Futures wallet balances (includes BNB) [8]
            ]

            # Only fetch prices for assets we actually hold
            for asset in assets_to_price[:10]:  # Limit to 10 assets to avoid rate limits
                fetch_tasks.append(client.get_spot_price(f"{asset}USDT"))

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

            # BNB/USDT price for commission conversion (when BNB fee discount is enabled)
            bnb_usdt_price = 1.0
            if not isinstance(bnb_price_data, Exception):
                bnb_usdt_price = float(bnb_price_data.get("price", 1.0)) or 1.0

            # Build price map from individual price queries (now offset by 9)
            price_map = {}
            for i, asset in enumerate(assets_to_price[:10]):
                price_result = results[9 + i]
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

            # Calculate total positions from position risk (sum of position quantities)
            # Also get entry price, leverage, and liquidation prices
            total_positions = 0.0
            avg_entry_price = 0.0
            total_volume_weighted = 0.0
            leverage = 0
            long_liquidation_price = 0.0
            short_liquidation_price = 0.0

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

            # Calculate funding fees (separate long and short based on positionSide)
            funding_fee = 0.0
            long_funding_rate = 0.0
            short_funding_rate = 0.0
            if not isinstance(funding_fee_data, Exception):
                for item in funding_fee_data:
                    fee_amount = float(item.get("income", 0))
                    position_side = item.get("positionSide", "")
                    funding_fee += fee_amount
                    # Separate by position side (LONG/SHORT)
                    if position_side == "LONG":
                        long_funding_rate += fee_amount
                    elif position_side == "SHORT":
                        short_funding_rate += fee_amount
                    else:
                        # For BOTH mode or unspecified, use amount sign as fallback
                        if fee_amount > 0:
                            short_funding_rate += fee_amount
                        else:
                            long_funding_rate += fee_amount
            else:
                logger.warning(f"Failed to fetch funding fee data: {funding_fee_data}")

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
            # 账户总资产 = 现货 + 杠杆(净资产) + 合约totalMarginBalance (含未实现盈亏)
            total_assets = spot_total_usdt + margin_total_usdt + futures_total_margin_balance

            # 可用总资产 = 现货free + 杠杆free + 合约availableBalance
            available_balance = spot_free_usdt + margin_free_usdt + futures_available_balance

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
            error_msg = str(e)
            # Check if it's a rate limit error and extract ban timestamp
            if "banned" in error_msg.lower() or "rate limit" in error_msg.lower() or "-1003" in error_msg:
                logger.warning(f"Binance rate limit exceeded: {error_msg}")

                # Try to extract ban timestamp from error message
                import re
                ban_until_match = re.search(r'banned until (\d+)', error_msg)
                ban_until_ms = None
                if ban_until_match:
                    ban_until_ms = int(ban_until_match.group(1))
                    logger.info(f"IP banned until timestamp: {ban_until_ms} ({ban_until_ms/1000})")

                # Raise a custom exception with ban info
                raise Exception(f"RATE_LIMIT:{ban_until_ms if ban_until_ms else 0}")

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
    ) -> AccountBalance:
        """Fetch Bybit account balance.
        - For MT5 accounts: Use direct MT5 connection (MT5Client)
        - For Unified accounts: Use V5 API (/v5/account/...)
        """
        client = BybitV5Client(api_key, api_secret)

        try:
            # Check if this is an MT5 account
            if mt5_id:
                logger.info(f"Fetching Bybit MT5 account balance for account {mt5_id} using direct MT5 connection")
                return await self._get_bybit_mt5_balance_direct(mt5_id, mt5_password, mt5_server)
            else:
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
            CONTRACT_UNIT = 100   # Bybit XAUUSD+: 1 lot = 100 oz
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

            # Calculate fees from deals history
            commission_fee = 0.0
            long_swap_fee = 0.0
            short_swap_fee = 0.0

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

            # Daily P&L = account total profit (from MT5 API)
            # account.profit represents cumulative realized P&L from all closed positions
            # This matches the "账户总盈亏" from user's documentation
            daily_pnl = account_profit

            logger.info(f"MT5 balance: balance={balance}, equity={equity}, free_margin={free_margin}, "
                       f"margin_used={margin_used}, positions={total_positions}, "
                       f"commission={commission_fee}, long_swap={long_swap_fee}, short_swap={short_swap_fee}, "
                       f"account_total_swap={account_total_swap}, "
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
    ) -> List[AccountPosition]:
        """Fetch Binance positions"""
        client = BinanceFuturesClient(api_key, api_secret)

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
    ) -> List[AccountPosition]:
        """Fetch Bybit positions"""
        client = BybitV5Client(api_key, api_secret)

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
    ) -> float:
        """Calculate Binance daily P&L from income history"""
        client = BinanceFuturesClient(api_key, api_secret)

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
    ) -> float:
        """Calculate Bybit daily P&L from transaction log"""
        client = BybitV5Client(api_key, api_secret)

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
            if platform_id == 1:  # Binance
                balance, positions, daily_pnl = await asyncio.gather(
                    self.get_binance_balance(account.api_key, account.api_secret),
                    self.get_binance_positions(account.api_key, account.api_secret),
                    self.get_binance_daily_pnl(account.api_key, account.api_secret),
                )
            elif platform_id == 2:  # Bybit
                # Bybit V5 API only supports UNIFIED account type
                account_type = "UNIFIED"

                # For MT5 accounts, get positions from MT5 directly
                if account.is_mt5_account and account.mt5_id and account.mt5_primary_pwd and account.mt5_server:
                    balance, positions, daily_pnl = await asyncio.gather(
                        self.get_bybit_balance(
                            account.api_key,
                            account.api_secret,
                            account_type,
                            mt5_id=account.mt5_id,
                            mt5_password=account.mt5_primary_pwd,
                            mt5_server=account.mt5_server,
                        ),
                        self.get_mt5_positions(
                            mt5_id=account.mt5_id,
                            mt5_password=account.mt5_primary_pwd,
                            mt5_server=account.mt5_server,
                        ),
                        self.get_bybit_daily_pnl(account.api_key, account.api_secret, account_type),
                    )
                else:
                    # For regular Bybit accounts, use V5 API
                    balance, positions, daily_pnl = await asyncio.gather(
                        self.get_bybit_balance(
                            account.api_key,
                            account.api_secret,
                            account_type,
                        ),
                        self.get_bybit_positions(account.api_key, account.api_secret),
                        self.get_bybit_daily_pnl(account.api_key, account.api_secret, account_type),
                    )
            else:
                raise ValueError(f"Unknown platform_id: {platform_id}")

            result = {
                "account_id": account_id_str,
                "account_name": account.account_name,
                "platform_id": platform_id,
                "is_mt5_account": account.is_mt5_account,
                "mt5_id": account.mt5_id,  # Used for MT5 position deduplication across duplicate DB accounts
                "is_active": account.is_active,
                "balance": balance.model_dump(),
                "positions": [pos.model_dump() for pos in positions],
                "daily_pnl": daily_pnl,
            }

            # Log balance data for debugging
            logger.info(f"Account {account_id_str} balance data: funding_fee={balance.funding_fee}, total_assets={balance.total_assets}")

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
