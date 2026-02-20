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
        """Fetch Binance Futures account balance using correct API mappings"""
        client = BinanceFuturesClient(api_key, api_secret)

        try:
            account_data = await client.get_account()

            # Extract balance data using correct Binance Futures API field names
            total_wallet_balance = float(account_data.get("totalWalletBalance", 0))
            total_unrealized_profit = float(account_data.get("totalUnrealizedProfit", 0))
            total_margin_balance = float(account_data.get("totalMarginBalance", 0))  # Net assets
            available_balance = float(account_data.get("availableBalance", 0))  # Available for trading

            # Calculate frozen assets: totalWalletBalance - availableBalance
            frozen_assets = total_wallet_balance - available_balance

            # Calculate risk ratio: totalMaintMargin / totalMarginBalance
            total_maint_margin = float(account_data.get("totalMaintMargin", 0))
            risk_ratio = (total_maint_margin / total_margin_balance * 100) if total_margin_balance > 0 else 0

            return AccountBalance(
                total_assets=total_wallet_balance,  # Total wallet balance
                available_balance=available_balance,  # Available balance
                net_assets=total_margin_balance,  # Total margin balance (net assets)
                frozen_assets=frozen_assets,  # Frozen = wallet - available
                margin_balance=total_margin_balance,  # Margin balance
                unrealized_pnl=total_unrealized_profit,  # Unrealized profit
                risk_ratio=risk_ratio,  # Risk ratio percentage
            )
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

            # 1. Get wallet balance from /v5/account/wallet-balance
            wallet_data = await client.get_wallet_balance(account_type)
            logger.info(f"Bybit wallet data received: {wallet_data}")

            account_list = wallet_data.get("list", [])
            if not account_list:
                logger.error("No account data found in Bybit response")
                raise Exception("No account data found")

            account = account_list[0]

            # Extract balance data using V5 API field names
            equity = float(account.get("totalEquity", 0))  # 总资产/净资产
            wallet_balance = float(account.get("totalWalletBalance", 0))
            available_to_trade = float(account.get("totalAvailableBalance", 0))  # 可用资产

            # Calculate frozen assets: walletBalance - availableToTrade
            frozen_assets = wallet_balance - available_to_trade  # 冻结资产

            # Get unrealized PnL from coin data
            coins = account.get("coin", [])
            unrealized_pnl = 0
            if coins:
                unrealized_pnl = float(coins[0].get("unrealisedPnl", 0))

            # 2. Get account info for margin balance and risk ratio from /v5/account/account-info
            margin_balance = 0
            risk_ratio = 0
            try:
                logger.info("Fetching Bybit account info")
                account_info = await client.get_account_info()
                logger.info(f"Bybit account info received: {account_info}")
                if isinstance(account_info, dict):
                    margin_balance = float(account_info.get("marginBalance", 0))  # 保证金余额
                    risk_ratio = float(account_info.get("riskRatio", 0))  # 风险率
            except Exception as e:
                logger.error(f"Failed to fetch Bybit account info: {str(e)}")

            # 3. Get total positions from /v5/position/list
            total_positions = 0
            try:
                logger.info("Fetching Bybit positions")
                positions_data = await client.get_positions(category=account_type.lower())
                if isinstance(positions_data, dict):
                    positions_list = positions_data.get("list", [])
                    # Sum up position values
                    for pos in positions_list:
                        size = float(pos.get("size", 0))
                        mark_price = float(pos.get("markPrice", 0))
                        total_positions += abs(size * mark_price)
                logger.info(f"Total positions calculated: {total_positions}")
            except Exception as e:
                logger.error(f"Failed to fetch Bybit positions: {str(e)}")

            # 4. Get daily P&L from /v5/account/profit-loss (today)
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
                    end_time=end_time
                )
                if isinstance(pnl_data, dict):
                    pnl_list = pnl_data.get("list", [])
                    for pnl in pnl_list:
                        daily_pnl += float(pnl.get("closedPnl", 0))
                logger.info(f"Daily P&L calculated: {daily_pnl}")
            except Exception as e:
                logger.error(f"Failed to fetch Bybit daily P&L: {str(e)}")

            # 5. Get funding fee from /v5/account/funding-fee (today)
            funding_fee = 0
            try:
                logger.info("Fetching Bybit funding fee")
                funding_data = await client.get_funding_fee(
                    category=account_type.lower(),
                    start_time=start_time,
                    end_time=end_time
                )
                if isinstance(funding_data, dict):
                    funding_list = funding_data.get("list", [])
                    for fee in funding_list:
                        funding_fee += float(fee.get("fundingFee", 0))
                logger.info(f"Funding fee calculated: {funding_fee}")
            except Exception as e:
                logger.error(f"Failed to fetch Bybit funding fee: {str(e)}")

            balance = AccountBalance(
                total_assets=equity,  # 总资产 = equity
                available_balance=available_to_trade,  # 可用资产
                net_assets=equity,  # 净资产 = equity
                frozen_assets=frozen_assets,  # 冻结资产
                margin_balance=margin_balance,  # 保证金余额 from account-info
                unrealized_pnl=unrealized_pnl,  # 未实现盈亏
                risk_ratio=risk_ratio,  # 风险率 from account-info
                total_positions=total_positions,  # 总持仓
                daily_pnl=daily_pnl,  # 当日盈亏
                funding_fee=funding_fee,  # 资金费
            )
            logger.info(f"Bybit balance calculated: {balance}")
            return balance
        except Exception as e:
            logger.error(f"Error fetching Bybit balance: {str(e)}", exc_info=True)
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
                failed_accounts.append({
                    "account_id": str(accounts[i].account_id),
                    "account_name": accounts[i].account_name,
                    "platform_id": accounts[i].platform_id,
                    "is_mt5_account": accounts[i].is_mt5_account,
                    "is_active": accounts[i].is_active,  # Include is_active status
                    "error": str(data),
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
