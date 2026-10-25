"""add read-only early-borrow analytics tables

Revision ID: a1b2c3d4e5f7
Revises: ab88cc99dd00
"""

from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "ab88cc99dd00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS early_borrow_config (
            id SERIAL PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            sample_interval_sec INTEGER NOT NULL DEFAULT 2,
            metrics_interval_sec INTEGER NOT NULL DEFAULT 300,
            lookback_hours INTEGER NOT NULL DEFAULT 6,
            warning_spread_pct DOUBLE PRECISION NOT NULL DEFAULT 0.8,
            candidate_spread_pct DOUBLE PRECISION NOT NULL DEFAULT 0.45,
            trigger_spread_pct DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            open_spread_pct DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            similarity_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.72,
            notification_cooldown_sec INTEGER NOT NULL DEFAULT 1800,
            retention_days INTEGER NOT NULL DEFAULT 7,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS early_borrow_ticks (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            spot_bid NUMERIC(30,12),
            spot_ask NUMERIC(30,12),
            futures_bid NUMERIC(30,12),
            futures_ask NUMERIC(30,12),
            spread_long DOUBLE PRECISION,
            spread_short DOUBLE PRECISION,
            source VARCHAR(20) NOT NULL DEFAULT 'binance_ws'
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_ticks_symbol_time ON early_borrow_ticks(symbol, captured_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS early_borrow_features (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            position_ratio DOUBLE PRECISION,
            account_ratio DOUBLE PRECISION,
            leverage_ratio DOUBLE PRECISION,
            open_interest DOUBLE PRECISION,
            oi_change_pct DOUBLE PRECISION,
            source VARCHAR(20) NOT NULL DEFAULT 'binance_public'
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_features_symbol_time ON early_borrow_features(symbol, captured_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS early_borrow_cases (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            trigger_at TIMESTAMPTZ NOT NULL,
            trigger_spread DOUBLE PRECISION NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 0,
            feature_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'ready',
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_cases_symbol_trigger ON early_borrow_cases(symbol, trigger_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS early_borrow_candidates (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            detected_at TIMESTAMPTZ NOT NULL,
            current_spread DOUBLE PRECISION NOT NULL,
            similarity_score DOUBLE PRECISION NOT NULL,
            case_id INTEGER REFERENCES early_borrow_cases(id) ON DELETE SET NULL,
            feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'suggested',
            notified_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            note TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_candidates_symbol_time ON early_borrow_candidates(symbol, detected_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_candidates_status ON early_borrow_candidates(status)")
    op.execute("INSERT INTO early_borrow_config (id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM early_borrow_config)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS early_borrow_candidates")
    op.execute("DROP TABLE IF EXISTS early_borrow_cases")
    op.execute("DROP TABLE IF EXISTS early_borrow_features")
    op.execute("DROP TABLE IF EXISTS early_borrow_ticks")
    op.execute("DROP TABLE IF EXISTS early_borrow_config")
