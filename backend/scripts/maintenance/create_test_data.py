"""
Create test data for the Hustle XAU arbitrage system
Run this script to populate the database with initial test data
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models import (
    Base, User, Platform, Account, StrategyConfig,
    ArbitrageTask, OrderRecord, Position, MarketData,
    SpreadRecord, RiskAlert, AccountSnapshot
)

# Create sync engine
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def create_test_data():
    """Create test data in the database"""
    db = SessionLocal()

    try:
        print("Creating test data...")

        # 1. Create test user
        test_user = User(
            user_id=uuid.uuid4(),
            username="test_user",
            email="test@hustle.com",
            password_hash="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqNqYqNqYq",  # password: test123
            is_active=True,
            create_time=datetime.utcnow(),
            update_time=datetime.utcnow()
        )
        db.add(test_user)
        db.flush()
        print(f"✓ Created test user: {test_user.username}")

        # 2. Get or create platforms (they might already exist)
        binance_platform = db.query(Platform).filter(Platform.platform_id == 1).first()
        if not binance_platform:
            binance_platform = Platform(
                platform_id=1,
                platform_name="binance",
                api_base_url="https://fapi.binance.com",
                ws_base_url="wss://fstream.binance.com",
                account_api_type="binance_futures",
                market_api_type="binance_futures"
            )
            db.add(binance_platform)

        bybit_platform = db.query(Platform).filter(Platform.platform_id == 2).first()
        if not bybit_platform:
            bybit_platform = Platform(
                platform_id=2,
                platform_name="bybit",
                api_base_url="https://api.bybit.com",
                ws_base_url="wss://stream.bybit.com",
                account_api_type="bybit_v5",
                market_api_type="bybit_mt5"
            )
            db.add(bybit_platform)

        db.flush()
        print("✓ Platforms ready: Binance, Bybit")

        # 3. Create test accounts
        binance_account = Account(
            account_id=uuid.uuid4(),
            user_id=test_user.user_id,
            platform_id=1,
            account_name="Binance Test Account",
            api_key=settings.BINANCE_API_KEY,
            api_secret=settings.BINANCE_API_SECRET,
            is_active=True,
            is_default=True,
            create_time=datetime.utcnow(),
            update_time=datetime.utcnow()
        )

        bybit_account = Account(
            account_id=uuid.uuid4(),
            user_id=test_user.user_id,
            platform_id=2,
            account_name="Bybit Test Account",
            api_key=settings.BYBIT_API_KEY,
            api_secret=settings.BYBIT_API_SECRET,
            mt5_id="3971962",
            mt5_server="Bybit-Live-2",
            mt5_primary_pwd="Aq987456!",
            is_mt5_account=True,
            is_active=True,
            is_default=False,
            create_time=datetime.utcnow(),
            update_time=datetime.utcnow()
        )

        db.add(binance_account)
        db.add(bybit_account)
        db.flush()
        print("✓ Created test accounts: Binance, Bybit")

        # Commit all changes
        db.commit()
        print("\n✅ Test data created successfully!")
        print(f"\nTest User Credentials:")
        print(f"  Username: test_user")
        print(f"  Password: test123")
        print(f"  User ID: {test_user.user_id}")
        print(f"\nAccounts:")
        print(f"  Binance Account ID: {binance_account.account_id}")
        print(f"  Bybit Account ID: {bybit_account.account_id}")

    except Exception as e:
        print(f"\n❌ Error creating test data: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Hustle XAU Arbitrage System - Test Data Creator")
    print("=" * 60)
    print()

    create_test_data()

    print()
    print("=" * 60)
    print("You can now login with the test user credentials")
    print("=" * 60)
