"""Add the per-user early-borrow dashboard push opt-in."""

from alembic import op


revision = "c6d7e8f9a0b1"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE global_rules "
        "ADD COLUMN IF NOT EXISTS early_borrow_auto_push_enabled "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE global_rules "
        "DROP COLUMN IF EXISTS early_borrow_auto_push_enabled"
    )
