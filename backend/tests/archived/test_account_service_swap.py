"""Test account service swap calculation"""
import asyncio
import logging
from app.services.account_service import AccountDataService

# Enable logging to see debug output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def test_account_swap():
    print("Testing account service swap calculation...")
    print("-" * 50)

    account_service = AccountDataService()

    # Test with MT5 account credentials from settings
    from app.core.config import settings

    mt5_id = int(settings.BYBIT_MT5_ID) if settings.BYBIT_MT5_ID else 0
    mt5_password = settings.BYBIT_MT5_PASSWORD
    mt5_server = settings.BYBIT_MT5_SERVER

    print(f"Testing with MT5 account: {mt5_id}")
    print(f"Server: {mt5_server}")
    print()

    try:
        # Get Bybit balance (which uses MT5 for MT5 accounts)
        balance = await account_service.get_bybit_balance(
            api_key="",  # Not needed for MT5 accounts
            api_secret="",
            mt5_id=mt5_id,
            mt5_password=mt5_password,
            mt5_server=mt5_server
        )

        print("Account Balance Retrieved:")
        print(f"  Total Assets: {balance.total_assets} USD")
        print(f"  Net Assets: {balance.net_assets} USD")
        print(f"  Available Balance: {balance.available_balance} USD")
        print(f"  Funding Fee (MT5 Swap): {balance.funding_fee} USD")
        print()

        if balance.funding_fee == 0:
            print("[WARNING] Funding fee is 0!")
            print("This means the swap calculation returned 0.")
        else:
            print(f"[OK] Funding fee calculated: {balance.funding_fee} USD")

    except Exception as e:
        print(f"[ERROR] Failed to get account balance: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_account_swap())
