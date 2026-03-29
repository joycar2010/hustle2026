#!/usr/bin/env python3
"""Test MT5 historical positions to get swap on close"""

import asyncio
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from app.core.config import settings

async def test_mt5_positions_history():
    print("Testing MT5 historical positions for swap...")
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

    # Get current open positions
    print("\n=== Current Open Positions ===")
    positions = mt5.positions_get()
    if positions:
        print(f"Found {len(positions)} open positions")
        total_swap = 0.0
        for pos in positions:
            print(f"  Position {pos.ticket}: symbol={pos.symbol}, volume={pos.volume}, "
                  f"swap={pos.swap:.2f}, profit={pos.profit:.2f}")
            total_swap += pos.swap
        print(f"Total swap from open positions: {total_swap:.2f} USD")
    else:
        print("No open positions")

    # Try to get historical positions (if API supports it)
    print("\n=== Checking for Historical Positions API ===")

    # MT5 doesn't have a direct history_positions_get() function
    # We need to reconstruct positions from deals

    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=7)

    deals = mt5.history_deals_get(start_dt, end_dt)

    if not deals:
        print("No historical deals found")
        mt5.shutdown()
        return

    print(f"Found {len(deals)} historical deals")

    # Group deals by position ID to reconstruct positions
    positions_map = {}

    for deal in deals:
        if deal.symbol != "XAUUSD+":
            continue

        # Check if deal has position_id
        if hasattr(deal, 'position_id'):
            pos_id = deal.position_id

            if pos_id not in positions_map:
                positions_map[pos_id] = {
                    'deals': [],
                    'total_swap': 0.0,
                    'total_profit': 0.0,
                    'volume': 0.0
                }

            positions_map[pos_id]['deals'].append(deal)

            # Accumulate swap and profit
            if hasattr(deal, 'swap'):
                positions_map[pos_id]['total_swap'] += deal.swap
            if hasattr(deal, 'profit'):
                positions_map[pos_id]['total_profit'] += deal.profit

    print(f"\nReconstructed {len(positions_map)} positions from deals")

    if positions_map:
        print("\nPosition details:")
        print("-" * 80)
        total_historical_swap = 0.0

        for pos_id, pos_data in list(positions_map.items())[:10]:  # Show first 10
            print(f"  Position {pos_id}:")
            print(f"    Deals: {len(pos_data['deals'])}")
            print(f"    Total swap: {pos_data['total_swap']:.2f} USD")
            print(f"    Total profit: {pos_data['total_profit']:.2f} USD")
            total_historical_swap += pos_data['total_swap']

        print(f"\nTotal swap from historical positions: {total_historical_swap:.2f} USD")

    mt5.shutdown()

if __name__ == "__main__":
    asyncio.run(test_mt5_positions_history())
