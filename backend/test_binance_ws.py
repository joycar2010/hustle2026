"""Test Binance WebSocket Connection"""
import asyncio
import sys
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.services.binance_client import BinanceFuturesClient

async def test_binance_ws():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Account).where(Account.platform_id == 1)
        )
        account = result.scalars().first()

        if not account:
            print("No Binance account found")
            return

        print(f"Testing Binance account: {account.account_id}")
        print(f"API Key: {account.api_key[:10]}...")
        print(f"API Secret: {account.api_secret[:10]}...")

        client = BinanceFuturesClient(account.api_key, account.api_secret)
        try:
            listen_key = await client.create_futures_listen_key()
            print(f"\nSuccess! ListenKey created: {listen_key[:10]}...")
            print("WebSocket connection should work now")
        except Exception as e:
            print(f"\nError creating listenKey: {e}")
        finally:
            await client.close()

if __name__ == "__main__":
    asyncio.run(test_binance_ws())
