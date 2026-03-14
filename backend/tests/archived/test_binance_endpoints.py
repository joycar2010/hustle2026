"""Test Binance positions and daily P&L endpoints"""
import asyncio
import psycopg2
from app.services.binance_client import BinanceFuturesClient
from datetime import datetime


async def test_binance_endpoints():
    # Get credentials from database
    conn = psycopg2.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='postgres',
        database='postgres'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT api_key, api_secret FROM accounts WHERE platform_id = 1 LIMIT 1")
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        print("No Binance account found in database")
        return

    api_key, api_secret = result
    print(f"Testing Binance API with key: {api_key[:20]}...")

    client = BinanceFuturesClient(api_key, api_secret)

    try:
        # Test 1: Account info (we know this works)
        print("\n1. Testing account info...")
        account = await client.get_account()
        print(f"   OK - Total Wallet Balance: {account.get('totalWalletBalance')}")

        # Test 2: Position risk
        print("\n2. Testing position risk...")
        positions = await client.get_position_risk()
        print(f"   OK - Found {len(positions)} positions")

        # Test 3: Income (for daily P&L)
        print("\n3. Testing income endpoint...")
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(today_start.timestamp() * 1000)
        income_data = await client.get_income(
            income_type="REALIZED_PNL",
            start_time=start_time,
            limit=1000
        )
        print(f"   OK - Found {len(income_data)} income records")

    except Exception as e:
        print(f"   ERROR: {str(e)}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_binance_endpoints())
