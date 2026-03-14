import asyncio
from sqlalchemy import create_engine, text

def check_accounts():
    """Check if there are enabled accounts"""
    engine = create_engine('postgresql://postgres:postgres@localhost/postgres')

    with engine.connect() as conn:
        # Check Binance accounts
        result = conn.execute(text("""
            SELECT COUNT(*) FROM accounts
            WHERE platform_id = 1 AND is_active = true
        """))
        binance_count = result.scalar()
        print(f"Active Binance accounts: {binance_count}")

        # Check Bybit accounts
        result = conn.execute(text("""
            SELECT COUNT(*) FROM accounts
            WHERE platform_id = 2 AND is_active = true
        """))
        bybit_count = result.scalar()
        print(f"Active Bybit accounts: {bybit_count}")

        if binance_count == 0 and bybit_count == 0:
            print("\n[WARNING] No active accounts found!")
            print("The market data service may not be collecting data because there are no active accounts.")
        else:
            print("\n[OK] There are active accounts.")

if __name__ == "__main__":
    check_accounts()
