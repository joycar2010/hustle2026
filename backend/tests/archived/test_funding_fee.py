"""Simple test to check if funding_fee is in aggregated data"""
import asyncio
from app.services.account_service import account_data_service
from app.core.database import get_db
from app.models.account import Account
from sqlalchemy import select
from uuid import UUID

async def test():
    print("Testing funding_fee in aggregated data...")
    print("-" * 50)

    # Get database session
    db_gen = get_db()
    db = await anext(db_gen)

    try:
        # Get accounts
        result = await db.execute(
            select(Account).where(Account.user_id == UUID("0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24"))
        )
        accounts = result.scalars().all()
        active_accounts = [acc for acc in accounts if acc.is_active]

        print(f"Found {len(active_accounts)} active accounts\n")

        # Get aggregated data
        data = await account_data_service.get_aggregated_account_data(list(active_accounts))

        # Check each account
        for acc in data.get('accounts', []):
            print(f"Account: {acc['account_name']}")
            print(f"  Platform: {acc['platform_id']}, MT5: {acc['is_mt5_account']}")
            balance = acc.get('balance', {})
            print(f"  Total Assets: {balance.get('total_assets', 0)}")
            print(f"  Funding Fee: {balance.get('funding_fee', 'MISSING!')}")
            print()

    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(test())
