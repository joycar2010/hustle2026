"""Test script to verify Bybit API connection and data retrieval"""
import asyncio
import sys
from app.services.bybit_client import BybitV5Client
from app.core.config import settings

async def test_bybit_api():
    """Test Bybit API with credentials from database"""
    # You need to provide actual API keys here
    # For now, using empty keys to test the structure
    api_key = input("Enter Bybit API Key: ").strip()
    api_secret = input("Enter Bybit API Secret: ").strip()

    if not api_key or not api_secret:
        print("Error: API key and secret are required")
        return

    client = BybitV5Client(api_key, api_secret)

    try:
        print("\n=== Testing Bybit API Connection ===\n")

        # Test 1: Get server time (public endpoint, no auth required)
        print("1. Testing server time (public endpoint)...")
        try:
            server_time = await client.get_server_time()
            print(f"✓ Server time: {server_time}")
        except Exception as e:
            print(f"✗ Server time failed: {e}")

        # Test 2: Get wallet balance with UNIFIED account type
        print("\n2. Testing wallet balance (UNIFIED account)...")
        try:
            wallet_data = await client.get_wallet_balance("UNIFIED")
            print(f"✓ Wallet data: {wallet_data}")

            account_list = wallet_data.get("list", [])
            if account_list:
                account = account_list[0]
                print(f"\nAccount details:")
                print(f"  - Total Equity: {account.get('totalEquity', 0)}")
                print(f"  - Total Wallet Balance: {account.get('totalWalletBalance', 0)}")
                print(f"  - Total Available Balance: {account.get('totalAvailableBalance', 0)}")
                print(f"  - Total Margin Balance: {account.get('totalMarginBalance', 0)}")

                coins = account.get("coin", [])
                if coins:
                    print(f"\nCoin details:")
                    for coin in coins:
                        print(f"  - {coin.get('coin')}: {coin.get('walletBalance', 0)}")
            else:
                print("  No accounts found in response")
        except Exception as e:
            print(f"✗ Wallet balance (UNIFIED) failed: {e}")

        # Test 3: Try CONTRACT account type
        print("\n3. Testing wallet balance (CONTRACT account)...")
        try:
            wallet_data = await client.get_wallet_balance("CONTRACT")
            print(f"✓ Wallet data: {wallet_data}")
        except Exception as e:
            print(f"✗ Wallet balance (CONTRACT) failed: {e}")

        # Test 4: Try SPOT account type
        print("\n4. Testing wallet balance (SPOT account)...")
        try:
            wallet_data = await client.get_wallet_balance("SPOT")
            print(f"✓ Wallet data: {wallet_data}")
        except Exception as e:
            print(f"✗ Wallet balance (SPOT) failed: {e}")

        # Test 5: Get account info
        print("\n5. Testing account info...")
        try:
            account_info = await client.get_account_info()
            print(f"✓ Account info: {account_info}")
        except Exception as e:
            print(f"✗ Account info failed: {e}")

        # Test 6: Get positions
        print("\n6. Testing positions (linear)...")
        try:
            positions = await client.get_positions("linear")
            print(f"✓ Positions: {positions}")
        except Exception as e:
            print(f"✗ Positions failed: {e}")

    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_bybit_api())
