"""
Initialize database with comprehensive schema for Hustle2026
This script creates all necessary tables for the XAU arbitrage system
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.config import settings
from app.core.database import Base
from app.models.user import User
from app.models.platform import Platform
from app.models.account import Account
from app.models.strategy import Strategy
from app.models.risk_alert import RiskAlert
from app.models.arbitrage import ArbitrageTask
from app.models.order import Order
from app.models.market_data import MarketData, SpreadRecord
from app.models.position import Position


def init_database():
    """Initialize database with all tables"""
    print("Connecting to database...")
    engine = create_engine(settings.DATABASE_URL)

    print("Dropping all existing tables...")
    Base.metadata.drop_all(bind=engine)

    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)

    # Create additional tables not in models
    with engine.connect() as conn:
        # Trades table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(user_id),
                account_id UUID NOT NULL REFERENCES accounts(account_id),
                position_id UUID REFERENCES positions(position_id),
                symbol VARCHAR(20) NOT NULL,
                platform VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                trade_type VARCHAR(20) NOT NULL,
                price FLOAT NOT NULL,
                quantity FLOAT NOT NULL,
                fee FLOAT DEFAULT 0.0,
                realized_pnl FLOAT DEFAULT 0.0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trades_user_time ON trades(user_id, timestamp)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trades_account_time ON trades(account_id, timestamp)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trades_position ON trades(position_id)"))

        # Account snapshots table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS account_snapshots (
                snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id UUID NOT NULL REFERENCES accounts(account_id),
                total_assets FLOAT NOT NULL,
                available_assets FLOAT NOT NULL,
                net_assets FLOAT NOT NULL,
                total_position FLOAT DEFAULT 0.0,
                frozen_assets FLOAT DEFAULT 0.0,
                margin_balance FLOAT DEFAULT 0.0,
                margin_used FLOAT DEFAULT 0.0,
                margin_available FLOAT DEFAULT 0.0,
                unrealized_pnl FLOAT DEFAULT 0.0,
                daily_pnl FLOAT DEFAULT 0.0,
                risk_ratio FLOAT DEFAULT 0.0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_account_snapshots_account_time ON account_snapshots(account_id, timestamp)"))

        # Strategy performance table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS strategy_performance (
                performance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                strategy_id INTEGER NOT NULL REFERENCES strategies(id),
                today_trades INTEGER DEFAULT 0,
                today_profit FLOAT DEFAULT 0.0,
                total_trades INTEGER DEFAULT 0,
                total_profit FLOAT DEFAULT 0.0,
                win_rate FLOAT DEFAULT 0.0,
                max_drawdown FLOAT DEFAULT 0.0,
                date DATE NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_strategy_performance_strategy_date ON strategy_performance(strategy_id, date)"))

        # System alerts table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_alerts (
                alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(user_id),
                alert_type VARCHAR(50) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                title VARCHAR(200) NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_system_alerts_user_time ON system_alerts(user_id, timestamp)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_system_alerts_user_read ON system_alerts(user_id, is_read)"))

        # Add API credentials columns to accounts table
        conn.execute(text("""
            ALTER TABLE accounts
            ADD COLUMN IF NOT EXISTS api_key VARCHAR(500),
            ADD COLUMN IF NOT EXISTS api_secret VARCHAR(500),
            ADD COLUMN IF NOT EXISTS mt5_id VARCHAR(50),
            ADD COLUMN IF NOT EXISTS mt5_server VARCHAR(100),
            ADD COLUMN IF NOT EXISTS mt5_password VARCHAR(500),
            ADD COLUMN IF NOT EXISTS last_sync_time TIMESTAMP
        """))

        conn.commit()

    print("Database initialized successfully!")
    print("\nCreated tables:")
    print("- users")
    print("- platforms")
    print("- accounts")
    print("- strategies")
    print("- risk_alerts")
    print("- arbitrage_opportunities")
    print("- orders")
    print("- market_data")
    print("- spread_records")
    print("- positions")
    print("- trades")
    print("- account_snapshots")
    print("- strategy_performance")
    print("- system_alerts")


if __name__ == "__main__":
    init_database()
