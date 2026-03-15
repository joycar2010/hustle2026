"""Check Binance API rate limit status"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.binance_client import BinanceFuturesClient
from app.core.config import settings


async def check_binance_status():
    """Check Binance API connection and rate limit status"""
    client = BinanceFuturesClient(
        api_key=settings.BINANCE_API_KEY,
        api_secret=settings.BINANCE_API_SECRET
    )

    print("=" * 60)
    print("Binance API Status Check")
    print("=" * 60)

    # Test 1: Server time (lightweight request)
    print("\n1. Testing server time...")
    try:
        time_data = await client.get_server_time()
        print(f"   ✓ Server time: {time_data.get('serverTime')}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 2: Book ticker (market data)
    print("\n2. Testing book ticker (XAUUSDT)...")
    try:
        ticker_data = await client.get_book_ticker("XAUUSDT")
        print(f"   ✓ Bid: {ticker_data.get('bidPrice')}, Ask: {ticker_data.get('askPrice')}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 3: Account info (requires authentication)
    print("\n3. Testing account info...")
    try:
        account_data = await client.get_account()
        print(f"   ✓ Total wallet balance: {account_data.get('totalWalletBalance')} USDT")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    await client.close()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(check_binance_status())
