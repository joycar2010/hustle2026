#!/usr/bin/env python3
"""Test MT5 historical trades swap fee extraction"""

import asyncio
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from app.core.config import settings

async def test_mt5_deals_swap():
    print("Testing MT5 historical deals swap extraction...")
    print("=" * 50)

    # Connect to MT5
    mt5_id = int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0
    mt5_password = settings.BYBIT_MT5_PASSWORD
    mt5_server = settings.BYBIT_MT5_SERVER

    print(f"Connecting to MT5: {mt5_id} @ {mt5_server}")

    if not mt5.initialize():
        print(f"[ERROR] MT5 initialize failed: {mt5.last_error()}")
        return

    if not mt5.login(mt5_id, mt5_password, mt5_server):
        print(f"[ERROR] MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return

    print("[OK] MT5 connected successfully")

    # Get deals from last 7 days
    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=7)

    print(f"\nFetching deals from {start_dt} to {end_dt}")

    deals = mt5.history_deals_get(start_dt, end_dt)

    if not deals:
        print("[WARNING] No deals found")
        mt5.shutdown()
        return

    print(f"[OK] Found {len(deals)} total deals")

    # Filter XAUUSD.s deals
    xau_deals = [d for d in deals if d.symbol == "XAUUSD.s"]
    print(f"[OK] Found {len(xau_deals)} XAUUSD.s deals")

    # Analyze swap fees
    total_swap = 0.0
    deals_with_swap = 0

    print("\nRecent deals with swap:")
    print("-" * 80)
    print(f"{'Time':<20} {'Ticket':<12} {'Type':<6} {'Volume':<8} {'Price':<10} {'Swap':<10} {'Profit':<10}")
    print("-" * 80)

    for deal in xau_deals[:20]:  # Show first 20 deals
        deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
        deal_type = "BUY" if deal.type == 0 else "SELL" if deal.type == 1 else "OTHER"

        swap = float(deal.swap) if hasattr(deal, 'swap') else 0.0
        profit = float(deal.profit) if hasattr(deal, 'profit') else 0.0

        if swap != 0:
            deals_with_swap += 1
            total_swap += swap

        print(f"{deal_time.strftime('%Y-%m-%d %H:%M:%S'):<20} {deal.ticket:<12} {deal_type:<6} "
              f"{deal.volume:<8.2f} {deal.price:<10.2f} {swap:<10.2f} {profit:<10.2f}")

    print("-" * 80)
    print(f"\nSummary:")
    print(f"  Total deals: {len(xau_deals)}")
    print(f"  Deals with swap: {deals_with_swap}")
    print(f"  Total swap: {total_swap:.2f} USD")

    if deals_with_swap == 0:
        print("\n[WARNING] No deals with swap found!")
        print("This might mean:")
        print("  1. No positions were held overnight during this period")
        print("  2. Swap is only settled when positions are closed")
    else:
        print(f"\n[OK] Successfully extracted swap from {deals_with_swap} deals")

    mt5.shutdown()

if __name__ == "__main__":
    asyncio.run(test_mt5_deals_swap())
