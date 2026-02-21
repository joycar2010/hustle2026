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
from app.models.account import Account
from app.schemas.account import AccountBalance, AccountPosition

logger = logging.getLogger(__name__)


class AccountDataService:
    """Service for fetching account data from exchanges"""

    def __init__(self):
        self._cache = {}
        self._cache_ttl = 30  # Cache for 30 seconds

    def _get_cache_key(self, account_id: str, data_type: str) -> str:
        """Generate cache key"""
        return f"{account_id}:{data_type}"

    def _get_cached_data(self, cache_key: str) -> Optional[Any]:
        """Get data from cache if not expired"""
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if (datetime.now() - timestamp).total_seconds() < self._cache_ttl:
                return data
        return None

    def _set_cached_data(self, cache_key: str, data: Any):
        """Store data in cache with timestamp"""
        self._cache[cache_key] = (data, datetime.now())

    async def get_binance_balance(self, api_key: str, api_secret: str) -> AccountBalance:
        """Fetch Binance account balance including spot, margin and futures data"""
        client = BinanceFuturesClient(api_key, api_secret)

        try:
            # Get today's start timestamp for daily calculations
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
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
                client.get_account(),           # USDT-M Futures
                client.get_position_risk(),     # Futures positions
                client.get_income(income_type="REALIZED_PNL", start_time=start_time, limit=1000),
                client.get_income(income_type="FUNDING_FEE", start_time=start_time, limit=1000),
                client.get_margin_account(),    # Cross Margin
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
            margin_account_data = results[4]

            # Build price map from individual price queries
            price_map = {}
            for i, asset in enumerate(assets_to_price[:10]):
                price_result = results[5 + i]
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

            # Calculate total positions from position risk
            total_positions = 0.0
            if not isinstance(position_risk_data, Exception):
                for pos in position_risk_data:
                    position_amt = float(pos.get("positionAmt", 0))
                    mark_price = float(pos.get("markPrice", 0))
                    if position_amt != 0:
                        total_positions += abs(position_amt * mark_price)
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

            # Calculate funding fees
            funding_fee = 0.0
            if not isinstance(funding_fee_data, Exception):
                funding_fee = sum(float(item.get("income", 0)) for item in funding_fee_data)
            else:
                logger.warning(f"Failed to fetch funding fee data: {funding_fee_data}")

            # Calculate final metrics according to Binance API documentation
            # 账户总资产 = 现货 + 杠杆(净资产) + 合约totalWalletBalance
            total_assets = spot_total_usdt + margin_total_usdt + futures_total_wallet_balance

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

                # Raise a custom exception with ban info
                raise Exception(f"RATE_LIMIT_BAN:{ban_until_ms if ban_until_ms else 0}")

            logger.error(f"Error fetching Binance balance: {error_msg}", exc_info=True)
            raise
        finally:
            await client.close()

    async def get_bybit_balance(
        self,
        api_key: str,
        api_secret: str,
        account_type: str = "UNIFIED",
    ) -> AccountBalance:
        """Fetch Bybit account balance using V5 API mappings per requirements"""
        client = BybitV5Client(api_key, api_secret)

        try:
            logger.info(f"Fetching Bybit wallet balance for account_type: {account_type}")

            # 1. Get wallet balance from /v5/account/wallet-balance?coin=USDT
            wallet_data = await client.get_wallet_balance(account_type, coin="USDT")
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
                positions_data = await client.get_positions(category=account_type.lower(), settle_coin="USDT")
                if isinstance(positions_data, dict):
                    positions_list = positions_data.get("list", [])
                    # Sum up position values and unrealized PnL
                    for pos in positions_list:
                        size = float(pos.get("size", 0))
                        mark_price = float(pos.get("markPrice", 0))
                        total_positions += abs(size * mark_price)
                        total_unrealized_pnl += float(pos.get("unrealisedPnl", 0))
                logger.info(f"Total positions calculated: {total_positions}, unrealized PnL: {total_unrealized_pnl}")
            except Exception as e:
                logger.error(f"Failed to fetch Bybit positions: {str(e)}")

            # 3. Get daily P&L from /v5/position/closed-pnl?settleCoin=USDT (today)
            daily_pnl = 0
            try:
                from datetime import datetime, timedelta
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                start_time = int(today_start.timestamp() * 1000)
                end_time = int(datetime.utcnow().timestamp() * 1000)

                logger.info(f"Fetching Bybit daily P&L from {start_time} to {end_time}")
                pnl_data = await client.get_profit_loss(
                    category=account_type.lower(),
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
            try:
                logger.info("Fetching Bybit funding fee")
                funding_data = await client.get_funding_fee(
                    category=account_type.lower(),
                    start_time=start_time,
                    end_time=end_time,
                    settle_coin="USDT"
                )
                if isinstance(funding_data, dict) and funding_data.get("list"):
                    funding_list = funding_data.get("list", [])
                    for fee in funding_list:
                        funding_fee += float(fee.get("fundingFee", 0))
                logger.info(f"Funding fee calculated: {funding_fee}")
            except Exception as e:
                logger.error(f"Failed to fetch Bybit funding fee: {str(e)}")
                # Don't fail the entire request if funding fee fetch fails
                funding_fee = 0
            except Exception as e:
                logger.error(f"Failed to fetch Bybit funding fee: {str(e)}")

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
            )
            logger.info(f"Bybit balance calculated: {balance}")
            return balance
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
                raise Exception(f"RATE_LIMIT_BAN:{ban_until_ms if ban_until_ms else 0}")

            raise
        finally:
            await client.close()

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
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
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
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
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
                balance, positions, daily_pnl = await asyncio.gather(
                    self.get_bybit_balance(account.api_key, account.api_secret, account_type),
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
                "is_active": account.is_active,  # Include is_active status
                "balance": balance.model_dump(),
                "positions": [pos.model_dump() for pos in positions],
                "daily_pnl": daily_pnl,
            }

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

        # Fetch data from all accounts concurrently
        account_data_list = await asyncio.gather(
            *[self.get_account_data(account) for account in accounts],
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
                    "account_id": str(accounts[i].account_id),
                    "account_name": accounts[i].account_name,
                    "platform_id": accounts[i].platform_id,
                    "is_mt5_account": accounts[i].is_mt5_account,
                    "is_active": accounts[i].is_active,  # Include is_active status
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

        # Aggregate positions
        all_positions = []
        for acc in successful_accounts:
            for pos in acc["positions"]:
                pos["account_id"] = acc["account_id"]
                pos["account_name"] = acc["account_name"]
                all_positions.append(pos)

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
