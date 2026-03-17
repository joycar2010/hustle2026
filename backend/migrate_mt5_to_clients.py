"""
Migration script to move MT5 configuration from accounts table to mt5_clients table.

This script:
1. Finds all accounts with MT5 configuration (mt5_id, mt5_server, mt5_primary_pwd)
2. Creates a default MT5 client for each account
3. Preserves all existing MT5 configuration data
"""

import asyncio
import sys
from sqlalchemy import select, and_
from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.models.mt5_client import MT5Client
from app.models.proxy import ProxyPool  # Import to resolve relationship


async def migrate_mt5_configs():
    """Migrate MT5 configurations from accounts to mt5_clients table"""

    async with AsyncSessionLocal() as db:
        try:
            # Find all MT5 accounts with configuration
            result = await db.execute(
                select(Account).where(
                    and_(
                        Account.is_mt5_account == True,
                        Account.mt5_id.isnot(None)
                    )
                )
            )
            mt5_accounts = result.scalars().all()

            if not mt5_accounts:
                print("No MT5 accounts found with configuration. Nothing to migrate.")
                return

            print(f"Found {len(mt5_accounts)} MT5 accounts to migrate")

            migrated_count = 0
            skipped_count = 0

            for account in mt5_accounts:
                # Check if a client already exists for this account
                existing_client = await db.execute(
                    select(MT5Client).where(
                        and_(
                            MT5Client.account_id == account.account_id,
                            MT5Client.mt5_login == account.mt5_id
                        )
                    )
                )

                if existing_client.scalar_one_or_none():
                    print(f"  [SKIP] Account {account.account_name} (ID: {account.account_id}) - client already exists")
                    skipped_count += 1
                    continue

                # Create default MT5 client
                mt5_client = MT5Client(
                    account_id=account.account_id,
                    client_name=f"{account.account_name} - Default Client",
                    mt5_login=account.mt5_id,
                    mt5_password=account.mt5_primary_pwd,  # Already encrypted
                    password_type='primary',
                    mt5_server=account.mt5_server,
                    mt5_path='C:\\Program Files\\MetaTrader 5\\terminal64.exe',  # Default path
                    mt5_data_path=None,
                    proxy_id=None,  # No proxy by default
                    priority=1,  # Highest priority
                    is_active=True,
                    connection_status='disconnected'
                )

                db.add(mt5_client)
                print(f"  [MIGRATED] Account {account.account_name} (ID: {account.account_id})")
                print(f"             MT5 Login: {account.mt5_id}, Server: {account.mt5_server}")
                migrated_count += 1

            # Commit all changes
            await db.commit()

            print(f"\nMigration completed successfully!")
            print(f"   Migrated: {migrated_count} accounts")
            print(f"   Skipped: {skipped_count} accounts (already migrated)")
            print(f"\nNote: Original MT5 configuration in accounts table is preserved for backward compatibility.")

        except Exception as e:
            await db.rollback()
            print(f"\nMigration failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    print("=" * 80)
    print("MT5 Configuration Migration Script")
    print("=" * 80)
    print("\nThis script will migrate MT5 configurations from accounts table to mt5_clients table.")
    print("The original data in accounts table will be preserved.\n")

    response = input("Do you want to proceed? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Migration cancelled.")
        sys.exit(0)

    print("\nStarting migration...\n")
    asyncio.run(migrate_mt5_configs())
