#!/usr/bin/env python3
"""Check if MT5 provides historical swap data through other APIs"""

import asyncio
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from app.core.config import settings

async def check_mt5_swap_sources():
    print("Checking MT5 swap data sources...")
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

    # Check account_info
    print("\n=== 1. Account Info ===")
    account_info = mt5.account_info()
    if account_info:
        print(f"Account info fields:")
        for attr in dir(account_info):
            if not attr.startswith('_'):
                value = getattr(account_info, attr, None)
                if value is not None and not callable(value):
                    print(f"  {attr}: {value}")

    # Check if there's a deal entry type for swap
    print("\n=== 2. Deal Entry Types ===")
    print("Checking MT5 deal entry constants:")
    deal_entry_attrs = [attr for attr in dir(mt5) if 'DEAL_ENTRY' in attr or 'DEAL_TYPE' in attr]
    for attr in deal_entry_attrs:
        print(f"  {attr}: {getattr(mt5, attr)}")

    # Check recent deals for all fields
    print("\n=== 3. Deal Object Fields ===")
    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=7)
    deals = mt5.history_deals_get(start_dt, end_dt)

    if deals and len(deals) > 0:
        deal = deals[0]
        print(f"Sample deal fields:")
        for attr in dir(deal):
            if not attr.startswith('_'):
                value = getattr(deal, attr, None)
                if value is not None and not callable(value):
                    print(f"  {attr}: {value}")

    # Check if there are special deal types for swap
    print("\n=== 4. Analyzing Deal Types ===")
    if deals:
        deal_types = {}
        for deal in deals:
            deal_type = deal.type if hasattr(deal, 'type') else 'unknown'
            deal_entry = deal.entry if hasattr(deal, 'entry') else 'unknown'
            key = f"type={deal_type}, entry={deal_entry}"

            if key not in deal_types:
                deal_types[key] = {'count': 0, 'has_swap': 0, 'total_swap': 0.0}

            deal_types[key]['count'] += 1

            if hasattr(deal, 'swap') and deal.swap != 0:
                deal_types[key]['has_swap'] += 1
                deal_types[key]['total_swap'] += deal.swap

        print("Deal type distribution:")
        for key, stats in deal_types.items():
            print(f"  {key}: {stats['count']} deals, {stats['has_swap']} with swap, total swap: {stats['total_swap']:.2f}")

    mt5.shutdown()

if __name__ == "__main__":
    asyncio.run(check_mt5_swap_sources())
