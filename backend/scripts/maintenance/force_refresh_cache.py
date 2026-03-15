#!/usr/bin/env python3
"""Force refresh account cache and verify funding_fee"""

import asyncio
from app.services.account_service import account_data_service
from app.core.config import settings

async def force_refresh():
    print("Force refreshing account cache...")
    print("=" * 50)

    # Clear existing cache
    account_data_service._cache.clear()
    print(f"Cache cleared. Size: {len(account_data_service._cache)}")

    # Get MT5 credentials from settings
    mt5_id = int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0
    mt5_password = settings.BYBIT_MT5_PASSWORD
    mt5_server = settings.BYBIT_MT5_SERVER

    print(f"\nMT5 Account: {mt5_id}")
    print(f"Server: {mt5_server}")

    # Force fetch fresh data
    print("\nFetching fresh balance data...")
    balance = await account_data_service.get_bybit_balance(
        api_key="",
        api_secret="",
        account_type="UNIFIED",
        mt5_id=mt5_id,
        mt5_password=mt5_password,
        mt5_server=mt5_server
    )

    print(f"\nBalance Data:")
    print(f"  Total Assets: {balance.total_assets} USD")
    print(f"  Net Assets: {balance.net_assets} USD")
    print(f"  Available Balance: {balance.available_balance} USD")
    print(f"  Funding Fee: {balance.funding_fee} USD")

    if balance.funding_fee == 0.0:
        print("\n[ERROR] Funding fee is still 0.0!")
    else:
        print(f"\n[OK] Funding fee is {balance.funding_fee} USD")

    print(f"\nCache size after fetch: {len(account_data_service._cache)}")

if __name__ == "__main__":
    asyncio.run(force_refresh())
