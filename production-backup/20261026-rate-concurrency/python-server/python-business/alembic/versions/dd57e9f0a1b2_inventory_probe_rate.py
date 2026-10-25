"""Separate inventory probe cadence from borrow submission pacing.

Revision ID: dd57e9f0a1b2
Revises: cc46d7e8f9a0
"""

from alembic import op


revision = "dd57e9f0a1b2"
down_revision = "cc46d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS "
        "inventory_probe_rate_per_sec NUMERIC(6,2)"
    )
    op.execute(
        "UPDATE global_rules SET inventory_probe_rate_per_sec = 3.8 "
        "WHERE inventory_probe_rate_per_sec IS NULL"
    )
    op.execute(
        "ALTER TABLE global_rules ALTER COLUMN "
        "inventory_probe_rate_per_sec SET DEFAULT 3.8"
    )
    op.execute(
        "ALTER TABLE global_rules ALTER COLUMN "
        "inventory_probe_rate_per_sec SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE sub_accounts ADD COLUMN IF NOT EXISTS "
        "inventory_probe_rate_per_sec NUMERIC(6,2)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sub_accounts DROP COLUMN IF EXISTS "
        "inventory_probe_rate_per_sec"
    )
    op.execute(
        "ALTER TABLE global_rules DROP COLUMN IF EXISTS "
        "inventory_probe_rate_per_sec"
    )
