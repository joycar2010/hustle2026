"""Test script to verify MT5 swap calculation"""
import asyncio
from app.services.market_service import market_data_service

async def test_swap():
    print("Testing MT5 swap calculation...")
    print("-" * 50)

    # Get MT5 client
    mt5_client = market_data_service.mt5_client

    # Connect to MT5
    if not mt5_client.connected:
        print("MT5 not connected, attempting to connect...")
        mt5_client.connect()

    if not mt5_client.connected:
        print("[FAIL] Failed to connect to MT5")
        return

    print("[OK] MT5 connected")

    # Get account info
    account_info = mt5_client.get_account_info()

    if account_info is None:
        print("[FAIL] Failed to get account info")
        return

    print("\nAccount Info:")
    print(f"  Login: {account_info.get('login')}")
    print(f"  Balance: {account_info.get('balance')} USD")
    print(f"  Equity: {account_info.get('equity')} USD")
    print(f"  Profit: {account_info.get('profit')} USD")
    print(f"  Swap: {account_info.get('swap')} USD")

    print("\n" + "=" * 50)
    if account_info.get('swap', 0) == 0:
        print("[WARNING] Swap is 0 - This could mean:")
        print("   1. No open positions")
        print("   2. No historical deals with swap in last 30 days")
        print("   3. All swaps are actually 0")
    else:
        print(f"[OK] Swap calculated successfully: {account_info.get('swap')} USD")

if __name__ == "__main__":
    asyncio.run(test_swap())
