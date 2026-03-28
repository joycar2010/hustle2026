"""Check Binance API Key Configuration"""
import asyncio
import sys
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.account import Account

async def check_binance_keys():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Account).where(Account.platform_id == 1)
        )
        accounts = result.scalars().all()

        print(f"\nFound {len(accounts)} Binance accounts:\n")
        for acc in accounts:
            print(f"Account ID: {acc.account_id}")
            print(f"User ID: {acc.user_id}")
            print(f"API Key Prefix: {acc.api_key[:10]}...")
            print(f"API Key Length: {len(acc.api_key)}")
            print(f"API Secret Length: {len(acc.api_secret)}")
            print(f"Is Active: {acc.is_active}")
            print(f"Full API Key: {acc.api_key}")
            print("-" * 60)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_binance_keys())
