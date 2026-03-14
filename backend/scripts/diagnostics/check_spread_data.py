import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check_spread_data():
    """Check spread records in database"""
    engine = create_async_engine(
        'postgresql+asyncpg://postgres:postgres@localhost/postgres'
    )

    try:
        async with engine.begin() as conn:
            # Check if table exists
            result = await conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'spread_records'
                )
            """))
            table_exists = result.scalar()
            print(f"Table 'spread_records' exists: {table_exists}")

            if table_exists:
                # Check record count
                result = await conn.execute(text("""
                    SELECT COUNT(*) FROM spread_records
                """))
                count = result.scalar()
                print(f"Total records: {count}")

                if count > 0:
                    # Show latest record
                    result = await conn.execute(text("""
                        SELECT
                            timestamp,
                            symbol,
                            binance_bid,
                            binance_ask,
                            bybit_bid,
                            bybit_ask,
                            forward_spread,
                            reverse_spread
                        FROM spread_records
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """))
                    row = result.fetchone()
                    if row:
                        print(f"\nLatest record:")
                        print(f"  Timestamp: {row[0]}")
                        print(f"  Symbol: {row[1]}")
                        print(f"  Binance bid/ask: {row[2]}/{row[3]}")
                        print(f"  Bybit bid/ask: {row[4]}/{row[5]}")
                        print(f"  Forward spread: {row[6]}")
                        print(f"  Reverse spread: {row[7]}")

                    # Check recent 2 hours
                    result = await conn.execute(text("""
                        SELECT COUNT(*)
                        FROM spread_records
                        WHERE timestamp >= NOW() - INTERVAL '2 hours'
                    """))
                    recent_count = result.scalar()
                    print(f"\nRecords in last 2 hours: {recent_count}")
                else:
                    print("\n[WARNING] No records found in spread_records table")
                    print("The table exists but is empty.")
            else:
                print("\n[ERROR] Table 'spread_records' does not exist")
                print("You may need to run migrations to create the table.")

    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_spread_data())
