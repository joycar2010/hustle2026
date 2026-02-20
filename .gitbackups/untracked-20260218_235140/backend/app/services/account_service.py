"""Account data service for fetching account information from exchanges"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from app.services.binance_client import BinanceFuturesClient
from app.services.bybit_client import BybitV5Client
from app.models.account import Account
from app.schemas.account import AccountBalance, AccountPosition


class AccountDataService:
    """Service for fetching account data from exchanges"""

    async def get_binance_balance(self, api_key: str, api_secret: str) -> AccountBalance:
        """Fetch Binance account balance"""
        client = BinanceFuturesClient(api_key, api_secret)

        try:
            account_data = await client.get_account()

            # Extract balance data
            total_wallet_balance = float(account_data.get("totalWalletBalance", 0))
            total_unrealized_profit = float(account_data.get("totalUnrealizedProfit", 0))
            total_margin_balance = float(account_data.get("totalMarginBalance", 0))
            available_balance = float(account_data.get("availableBalance", 0))

            # Calculate frozen assets
            frozen_assets = total_wallet_balance - available_balance

            # Calculate risk ratio (maintenance margin / margin balance)
            total_maint_margin = float(account_data.get("totalMaintMargin", 0))
            risk_ratio = (total_maint_margin / total_margin_balance * 100) if total_margin_balance > 0 else 0

            return AccountBalance(
                total_assets=total_wallet_balance,
                available_balance=available_balance,
                net_assets=total_margin_balance,
                frozen_assets=frozen_assets,
                margin_balance=total_margin_balance,
                unrealized_pnl=total_unrealized_profit,
                risk_ratio=risk_ratio,
            )
        finally:
            await client.close()

    async def get_bybit_balance(
        self,
        api_key: str,
        api_secret: str,
        account_type: str = "UNIFIED",
    ) -> AccountBalance:
        """Fetch Bybit account balance"""
        client = BybitV5Client(api_key, api_secret)

        try:
            wallet_data = await client.get_wallet_balance(account_type)

            # Extract first account from list
            account_list = wallet_data.get("list", [])
            if not account_list:
                raise Exception("No account data found")

            account = account_list[0]

            # Extract balance data
            total_equity = float(account.get("totalEquity", 0))
            total_wallet_balance = float(account.get("totalWalletBalance", 0))
            total_margin_balance = float(account.get("totalMarginBalance", 0))
            available_balance = float(account.get("totalAvailableBalance", 0))

            # Get coin-specific data (usually USDT)
            coins = account.get("coin", [])
            unrealized_pnl = 0
            if coins:
                unrealized_pnl = float(coins[0].get("unrealisedPnl", 0))

            # Calculate frozen assets
            frozen_assets = total_wallet_balance - available_balance

            # Get account info for risk ratio
            try:
                account_info = await client.get_account_info()
                risk_ratio = float(account_info.get("marginMode", {}).get("riskRatio", 0))
            except:
                risk_ratio = None

            return AccountBalance(
                total_assets=total_wallet_balance,
                available_balance=available_balance,
                net_assets=total_equity,
                frozen_assets=frozen_assets,
                margin_balance=total_margin_balance,
                unrealized_pnl=unrealized_pnl,
                risk_ratio=risk_ratio,
            )
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
    ) -> List[AccountPosition]:
        """Fetch Bybit positions"""
        client = BybitV5Client(api_key, api_secret)

        try:
            positions_data = await client.get_positions(category, symbol)

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
        """Get comprehensive account data for a single account"""
        platform_id = account.platform_id

        try:
            if platform_id == 1:  # Binance
                balance, positions, daily_pnl = await asyncio.gather(
                    self.get_binance_balance(account.api_key, account.api_secret),
                    self.get_binance_positions(account.api_key, account.api_secret),
                    self.get_binance_daily_pnl(account.api_key, account.api_secret),
                )
            elif platform_id == 2:  # Bybit
                account_type = "UNIFIED" if not account.is_mt5_account else "CONTRACT"
                balance, positions, daily_pnl = await asyncio.gather(
                    self.get_bybit_balance(account.api_key, account.api_secret, account_type),
                    self.get_bybit_positions(account.api_key, account.api_secret),
                    self.get_bybit_daily_pnl(account.api_key, account.api_secret, account_type),
                )
            else:
                raise ValueError(f"Unknown platform_id: {platform_id}")

            return {
                "account_id": str(account.account_id),
                "account_name": account.account_name,
                "platform_id": platform_id,
                "is_mt5_account": account.is_mt5_account,
                "balance": balance.model_dump(),
                "positions": [pos.model_dump() for pos in positions],
                "daily_pnl": daily_pnl,
            }
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
