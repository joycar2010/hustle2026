"""Add time-leading indexes for bounded early-borrow retention deletes."""

from alembic import op


revision = "z1a2b3c4d5e6"
down_revision = "z0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY avoids blocking the read-only analytics collector.  Alembic
    # must leave its transaction for this PostgreSQL DDL operation.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_early_borrow_ticks_captured_at "
            "ON early_borrow_ticks (captured_at, id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_early_borrow_features_captured_at "
            "ON early_borrow_features (captured_at, id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_early_borrow_ticks_captured_at")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_early_borrow_features_captured_at")
