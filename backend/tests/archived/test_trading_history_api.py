#!/usr/bin/env python3
"""Test the trading history API to verify MT5 swap extraction"""

import asyncio
import sys
sys.path.insert(0, '/c/app/hustle2026/backend')

from datetime import datetime, timedelta, timezone
from app.api.v1.trading import _get_mt5_trades_realtime, _format_mt5_trades, _calculate_stats
from app.core.config import settings

async def test_trading_history_api():
    print("Testing trading history API for MT5 swap...")
    print("=" * 50)

    # Create a mock account object
    class MockAccount:
        def __init__(self):
            self.platform_id = 2
            self.is_mt5_account = True
            self.mt5_id = int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0
            self.mt5_primary_pwd = settings.BYBIT_MT5_PASSWORD
            self.mt5_server = settings.BYBIT_MT5_SERVER

    account = MockAccount()

    # Get deals from last 30 days
    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=30)

    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    print(f"Fetching MT5 trades from {start_dt.date()} to {end_dt.date()}")

    # Get MT5 trades
    mt5_deals = await _get_mt5_trades_realtime(account, start_ms, end_ms)

    print(f"Found {len(mt5_deals)} MT5 deals")

    # Format trades
    formatted_trades = _format_mt5_trades(mt5_deals)

    print(f"Formatted {len(formatted_trades)} trades")

    # Check for trades with swap
    trades_with_swap = [t for t in formatted_trades if t.get('overnight_fee', 0) != 0]

    print(f"\n=== Trades with Swap: {len(trades_with_swap)} ===")

    if trades_with_swap:
        print("\nDetails:")
        for trade in trades_with_swap:
            print(f"  Ticket: {trade.get('id')}")
            print(f"  Time: {trade.get('timestamp')}")
            print(f"  Symbol: {trade.get('symbol')}")
            print(f"  Side: {trade.get('side')}")
            print(f"  Volume: {trade.get('quantity')}")
            print(f"  Price: {trade.get('price')}")
            print(f"  Overnight Fee: {trade.get('overnight_fee')} USD")
            print(f"  Profit: {trade.get('profit')} USD")
            print()

    # Calculate statistics
    stats = _calculate_stats([], formatted_trades, 0.0)

    print(f"=== Statistics ===")
    print(f"MT5 Volume: {stats['mt5Volume']:.2f}")
    print(f"MT5 Amount: {stats['mt5Amount']:.2f} USD")
    print(f"MT5 Overnight Fee: {stats['mt5OvernightFee']:.2f} USD")
    print(f"MT5 Fee: {stats['mt5Fee']:.2f} USD")
    print(f"MT5 Realized PnL: {stats['mt5RealizedPnL']:.2f} USD")

    if stats['mt5OvernightFee'] > 0:
        print(f"\n[OK] MT5 overnight fee successfully extracted: {stats['mt5OvernightFee']:.2f} USD")
    else:
        print(f"\n[INFO] No overnight fees in this period (all positions closed quickly)")

if __name__ == "__main__":
    asyncio.run(test_trading_history_api())
