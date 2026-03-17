#!/usr/bin/env python3
"""Find deals with swap and analyze them"""

import asyncio
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from app.core.config import settings

async def find_deals_with_swap():
    print("Finding deals with swap...")
    print("=" * 50)

    # Connect to MT5
    mt5_id = int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0
    mt5_password = settings.BYBIT_MT5_PASSWORD
    mt5_server = settings.BYBIT_MT5_SERVER

    if not mt5.initialize():
        print(f"[ERROR] MT5 initialize failed")
        return

    if not mt5.login(mt5_id, mt5_password, mt5_server):
        print(f"[ERROR] MT5 login failed")
        mt5.shutdown()
        return

    print("[OK] MT5 connected")

    # Get deals from last 30 days to find more swap examples
    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=30)

    print(f"\nFetching deals from {start_dt.date()} to {end_dt.date()}")

    deals = mt5.history_deals_get(start_dt, end_dt)

    if not deals:
        print("No deals found")
        mt5.shutdown()
        return

    print(f"Found {len(deals)} total deals")

    # Filter deals with swap
    deals_with_swap = [d for d in deals if hasattr(d, 'swap') and d.swap != 0]

    print(f"\n=== Deals with Swap: {len(deals_with_swap)} ===")

    if deals_with_swap:
        print("\nDetailed information:")
        print("-" * 100)
        print(f"{'Time':<20} {'Ticket':<12} {'Type':<6} {'Entry':<6} {'Symbol':<12} {'Volume':<8} {'Price':<10} {'Swap':<10} {'Profit':<10}")
        print("-" * 100)

        total_swap = 0.0

        for deal in deals_with_swap:
            deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
            deal_type_str = "BUY" if deal.type == 0 else "SELL" if deal.type == 1 else f"TYPE{deal.type}"
            entry_str = "IN" if deal.entry == 0 else "OUT" if deal.entry == 1 else f"E{deal.entry}"

            print(f"{deal_time.strftime('%Y-%m-%d %H:%M:%S'):<20} {deal.ticket:<12} {deal_type_str:<6} {entry_str:<6} "
                  f"{deal.symbol:<12} {deal.volume:<8.2f} {deal.price:<10.2f} {deal.swap:<10.2f} {deal.profit:<10.2f}")

            total_swap += deal.swap

        print("-" * 100)
        print(f"Total swap from {len(deals_with_swap)} deals: {total_swap:.2f} USD")

        # Analyze pattern
        print("\n=== Pattern Analysis ===")
        print(f"All deals with swap have:")
        entry_types = set(d.entry for d in deals_with_swap)
        deal_types = set(d.type for d in deals_with_swap)
        print(f"  Entry types: {entry_types}")
        print(f"  Deal types: {deal_types}")

    else:
        print("\n[WARNING] No deals with swap found in the last 30 days")
        print("This suggests that:")
        print("  1. Swap is only recorded in specific deal types")
        print("  2. Or swap is accumulated elsewhere and not in individual deals")

    # Also check all XAUUSD+ deals
    xau_deals = [d for d in deals if d.symbol == "XAUUSD+"]
    xau_with_swap = [d for d in xau_deals if hasattr(d, 'swap') and d.swap != 0]

    print(f"\n=== XAUUSD+ Specific ===")
    print(f"Total XAUUSD+ deals: {len(xau_deals)}")
    print(f"XAUUSD+ deals with swap: {len(xau_with_swap)}")

    if xau_with_swap:
        total_xau_swap = sum(d.swap for d in xau_with_swap)
        print(f"Total XAUUSD+ swap: {total_xau_swap:.2f} USD")

    mt5.shutdown()

if __name__ == "__main__":
    asyncio.run(find_deals_with_swap())
