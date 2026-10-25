"""Add read-only early-borrow analytics and per-user auto-push opt-in."""

from alembic import op


revision = "aa24b8c1d9e0"
# This worktree's migration graph ends at the hedge-convergence revision.
# The production deployment adds its existing notification chain before aa24.
down_revision = "aa77bb88cc99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The feature is deliberately isolated from positions/trade logs. These
    # tables store market observations and human-review suggestions only.
    op.execute(
        "ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS "
        "early_borrow_auto_push_enabled BOOLEAN NOT NULL DEFAULT FALSE"
    )
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
            open_spread_buffer_pct DOUBLE PRECISION NOT NULL DEFAULT 0.05,
            similarity_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.85,
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
            spot_bid NUMERIC(30,12), spot_ask NUMERIC(30,12),
            futures_bid NUMERIC(30,12), futures_ask NUMERIC(30,12),
            spread_long DOUBLE PRECISION, spread_short DOUBLE PRECISION,
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
            position_ratio DOUBLE PRECISION, account_ratio DOUBLE PRECISION,
            leverage_ratio DOUBLE PRECISION, open_interest DOUBLE PRECISION,
            oi_change_pct DOUBLE PRECISION, oi_change_5m_pct DOUBLE PRECISION,
            oi_change_15m_pct DOUBLE PRECISION, oi_change_30m_pct DOUBLE PRECISION,
            oi_change_1h_pct DOUBLE PRECISION, oi_change_3h_pct DOUBLE PRECISION,
            oi_change_6h_pct DOUBLE PRECISION,
            source VARCHAR(20) NOT NULL DEFAULT 'binance_public'
        )
        """
    )
    for column in (
        "oi_change_5m_pct", "oi_change_15m_pct", "oi_change_30m_pct",
        "oi_change_1h_pct", "oi_change_3h_pct", "oi_change_6h_pct",
    ):
        op.execute(f"ALTER TABLE early_borrow_features ADD COLUMN IF NOT EXISTS {column} DOUBLE PRECISION")
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
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_cases_status ON early_borrow_cases(status)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS early_borrow_candidates (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            detected_at TIMESTAMPTZ NOT NULL,
            current_spread DOUBLE PRECISION NOT NULL,
            similarity_score DOUBLE PRECISION NOT NULL,
            estimated_hit_rate DOUBLE PRECISION,
            matched_case_count INTEGER NOT NULL DEFAULT 0,
            evidence_case_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            case_id INTEGER REFERENCES early_borrow_cases(id) ON DELETE SET NULL,
            feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'suggested',
            notified_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
            note TEXT, created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    for column, definition in (
        ("estimated_hit_rate", "DOUBLE PRECISION"),
        ("matched_case_count", "INTEGER NOT NULL DEFAULT 0"),
        ("evidence_case_ids", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ):
        op.execute(f"ALTER TABLE early_borrow_candidates ADD COLUMN IF NOT EXISTS {column} {definition}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_candidates_symbol_time ON early_borrow_candidates(symbol, detected_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_early_borrow_candidates_status ON early_borrow_candidates(status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_early_borrow_candidates_status_expiry_time "
        "ON early_borrow_candidates(status, expires_at, detected_at)"
    )
    op.execute("INSERT INTO early_borrow_config (id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM early_borrow_config)")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS early_borrow_auto_push_enabled")
    op.execute("DROP TABLE IF EXISTS early_borrow_candidates")
    op.execute("DROP TABLE IF EXISTS early_borrow_cases")
    op.execute("DROP TABLE IF EXISTS early_borrow_features")
    op.execute("DROP TABLE IF EXISTS early_borrow_ticks")
    op.execute("DROP TABLE IF EXISTS early_borrow_config")
