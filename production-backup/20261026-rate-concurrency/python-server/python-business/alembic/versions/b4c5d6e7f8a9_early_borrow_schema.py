"""Complete the read-only early-borrow analytics schema."""

from alembic import op


revision = "b4c5d6e7f8a9"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE early_borrow_config "
        "ADD COLUMN IF NOT EXISTS open_spread_buffer_pct DOUBLE PRECISION NOT NULL DEFAULT 0.05"
    )
    op.execute(
        "ALTER TABLE early_borrow_config "
        "ALTER COLUMN similarity_threshold SET DEFAULT 0.85"
    )
    # 0.72 was the provisional seed in the first migration. Upgrade only that
    # untouched seed row; any other operator-selected threshold is preserved.
    op.execute(
        "UPDATE early_borrow_config SET similarity_threshold = 0.85 "
        "WHERE id = 1 AND similarity_threshold = 0.72"
    )
    for column in (
        "oi_change_5m_pct",
        "oi_change_15m_pct",
        "oi_change_30m_pct",
        "oi_change_1h_pct",
        "oi_change_3h_pct",
        "oi_change_6h_pct",
    ):
        op.execute(
            f"ALTER TABLE early_borrow_features "
            f"ADD COLUMN IF NOT EXISTS {column} DOUBLE PRECISION"
        )
    op.execute(
        "ALTER TABLE early_borrow_candidates "
        "ADD COLUMN IF NOT EXISTS estimated_hit_rate DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE early_borrow_candidates "
        "ADD COLUMN IF NOT EXISTS matched_case_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE early_borrow_candidates "
        "ADD COLUMN IF NOT EXISTS evidence_case_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE early_borrow_candidates DROP COLUMN IF EXISTS evidence_case_ids")
    op.execute("ALTER TABLE early_borrow_candidates DROP COLUMN IF EXISTS matched_case_count")
    op.execute("ALTER TABLE early_borrow_candidates DROP COLUMN IF EXISTS estimated_hit_rate")
    for column in (
        "oi_change_6h_pct",
        "oi_change_3h_pct",
        "oi_change_1h_pct",
        "oi_change_30m_pct",
        "oi_change_15m_pct",
        "oi_change_5m_pct",
    ):
        op.execute(f"ALTER TABLE early_borrow_features DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE early_borrow_config DROP COLUMN IF EXISTS open_spread_buffer_pct")
