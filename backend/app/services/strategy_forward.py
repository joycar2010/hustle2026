"""Forward arbitrage strategy (long Binance, short Bybit)"""
from typing import Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.account import Account
from app.models.strategy import StrategyConfig
from app.services.strategy_base import BaseStrategy
from app.services.order_executor import order_executor


class ForwardArbitrageStrategy(BaseStrategy):
    """Forward arbitrage strategy: Buy Binance, Sell Bybit

    Entry condition: bybit_ask - binance_bid >= target_spread
    Entry execution: Sell Bybit (ask - 0.01), Buy Binance (bid + 0.01)

    Exit condition: binance_ask - bybit_bid <= close_spread
    Exit execution: Sell Binance (ask - 0.01), Buy Bybit (bid + 0.01)
    """

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self.strategy_type = "forward"

    async def check_entry_condition(self, spread_data: Dict[str, Any]) -> bool:
        """Check if forward arbitrage entry condition is met

        Entry spread = bybit_ask - binance_bid
        """
        forward_entry_spread = spread_data.get("forward_entry_spread", 0)
        return forward_entry_spread >= self.config.target_spread

    async def check_exit_condition(self, spread_data: Dict[str, Any]) -> bool:
        """Check if forward arbitrage exit condition is met

        Exit spread = binance_ask - bybit_bid
        """
        forward_exit_spread = spread_data.get("forward_exit_spread", 0)
        # Exit when spread narrows (profitable to close)
        return forward_exit_spread <= 0

    async def execute_entry(
        self,
        binance_account: Account,
        bybit_account: Account,
        spread_data: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute forward arbitrage entry

        Buy Binance at bid + 0.01
        Sell Bybit at ask - 0.01
        """
        binance_quote = spread_data.get("binance_quote", {})
        bybit_quote = spread_data.get("bybit_quote", {})

        binance_bid = binance_quote.get("bid_price", 0)
        bybit_ask = bybit_quote.get("ask_price", 0)

        # Calculate order prices
        binance_buy_price = binance_bid + 0.01
        bybit_sell_price = bybit_ask - 0.01

        # Execute dual order
        result = await order_executor.execute_dual_order(
            binance_account=binance_account,
            bybit_account=bybit_account,
            binance_symbol="XAUUSDT",
            bybit_symbol="XAUUSD.s",
            binance_side="BUY",
            bybit_side="Sell",
            quantity=self.config.order_qty,
            binance_price=binance_buy_price,
            bybit_price=bybit_sell_price,
            order_type="LIMIT",
            max_retries=self.config.retry_times,
            db=db,
        )

        # Send notification
        if result["success"]:
            await self.send_notification(
                self.config.user_id,
                f"Forward arbitrage entry executed: Buy Binance @ {binance_buy_price}, Sell Bybit @ {bybit_sell_price}",
                "success",
            )
        else:
            await self.send_notification(
                self.config.user_id,
                f"Forward arbitrage entry failed: {result.get('error', 'Unknown error')}",
                "error",
            )

        return result

    async def execute_exit(
        self,
        binance_account: Account,
        bybit_account: Account,
        spread_data: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute forward arbitrage exit

        Sell Binance at ask - 0.01
        Buy Bybit at bid + 0.01
        """
        binance_quote = spread_data.get("binance_quote", {})
        bybit_quote = spread_data.get("bybit_quote", {})

        binance_ask = binance_quote.get("ask_price", 0)
        bybit_bid = bybit_quote.get("bid_price", 0)

        # Calculate order prices
        binance_sell_price = binance_ask - 0.01
        bybit_buy_price = bybit_bid + 0.01

        # Execute dual order
        result = await order_executor.execute_dual_order(
            binance_account=binance_account,
            bybit_account=bybit_account,
            binance_symbol="XAUUSDT",
            bybit_symbol="XAUUSD.s",
            binance_side="SELL",
            bybit_side="Buy",
            quantity=self.config.order_qty,
            binance_price=binance_sell_price,
            bybit_price=bybit_buy_price,
            order_type="LIMIT",
            max_retries=self.config.retry_times,
            db=db,
        )

        # Send notification
        if result["success"]:
            await self.send_notification(
                self.config.user_id,
                f"Forward arbitrage exit executed: Sell Binance @ {binance_sell_price}, Buy Bybit @ {bybit_buy_price}",
                "success",
            )
        else:
            await self.send_notification(
                self.config.user_id,
                f"Forward arbitrage exit failed: {result.get('error', 'Unknown error')}",
                "error",
            )

        return result
