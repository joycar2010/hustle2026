"""
Create test account snapshots for MT5 accounts
This will populate the account_snapshots table with sample data
"""
import asyncio
from datetime import datetime
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.models.account_snapshot import AccountSnapshot
import uuid

async def create_test_snapshots():
    async with AsyncSessionLocal() as session:
        # Get all MT5 accounts
        result = await session.execute(
            select(Account).where(Account.is_mt5_account == True)
        )
        mt5_accounts = result.scalars().all()

        if not mt5_accounts:
            print("No MT5 accounts found")
            return

        print(f"Found {len(mt5_accounts)} MT5 accounts")

        for account in mt5_accounts:
            # Create a test snapshot with sample data
            snapshot = AccountSnapshot(
                snapshot_id=uuid.uuid4(),
                account_id=account.account_id,
                total_balance=10000.00,  # Sample balance
                available_balance=8500.00,
                margin_used=1500.00,
                unrealized_pnl=250.50,
                timestamp=datetime.utcnow()
            )

            session.add(snapshot)
            print(f"Created snapshot for account: {account.account_name}")

        await session.commit()
        print("\nTest snapshots created successfully!")

if __name__ == "__main__":
    asyncio.run(create_test_snapshots())
