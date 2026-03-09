import asyncio
from sqlalchemy import create_engine, text

def check_accounts_structure():
    """Check accounts table structure"""
    engine = create_engine('postgresql://postgres:postgres@localhost/postgres')

    with engine.connect() as conn:
        # Get table columns
        result = conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'accounts'
            ORDER BY ordinal_position
        """))

        print("Accounts table columns:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")

        # Check account count
        result = conn.execute(text("SELECT COUNT(*) FROM accounts"))
        count = result.scalar()
        print(f"\nTotal accounts: {count}")

        if count > 0:
            # Show sample account
            result = conn.execute(text("SELECT * FROM accounts LIMIT 1"))
            row = result.fetchone()
            print(f"\nSample account columns: {result.keys()}")

if __name__ == "__main__":
    check_accounts_structure()
