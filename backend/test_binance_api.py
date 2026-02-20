"""Test Binance API connection"""
import asyncio
import psycopg2
from app.services.binance_client import BinanceFuturesClient


async def test_binance_api():
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
        # Test public endpoint first
        print("\n1. Testing public endpoint (server time)...")
        server_time = await client.get_server_time()
        print(f"   OK Server time: {server_time}")

        # Test authenticated endpoint
        print("\n2. Testing authenticated endpoint (account info)...")
        account = await client.get_account()
        print(f"   OK Account data received")
        print(f"   Total Wallet Balance: {account.get('totalWalletBalance')}")
        print(f"   Available Balance: {account.get('availableBalance')}")

    except Exception as e:
        print(f"   ERROR: {str(e)}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_binance_api())
