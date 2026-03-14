import asyncio
from sqlalchemy import create_engine, text

def check_risk_settings_structure():
    """Check risk_settings table structure"""
    engine = create_engine('postgresql://postgres:postgres@localhost/postgres')

    with engine.connect() as conn:
        # Get table columns
        result = conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'risk_settings'
            ORDER BY ordinal_position
        """))

        print("Risk Settings table columns:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")

        # Check settings count
        result = conn.execute(text("SELECT COUNT(*) FROM risk_settings"))
        count = result.scalar()
        print(f"\nTotal risk settings: {count}")

        if count > 0:
            # Show sample settings
            result = conn.execute(text("SELECT * FROM risk_settings LIMIT 1"))
            row = result.fetchone()
            print(f"\nSample settings columns: {result.keys()}")

if __name__ == "__main__":
    check_risk_settings_structure()
