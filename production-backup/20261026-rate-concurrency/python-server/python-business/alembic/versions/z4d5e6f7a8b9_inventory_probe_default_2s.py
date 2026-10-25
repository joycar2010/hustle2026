"""Lower the account-wide inventory probe default to two requests per second.

The Binance ``available-inventory`` endpoint returns all assets for one
account, so the configured rate is an account-wide request budget. Existing
legacy rows carrying the old 3.8 default are migrated; explicit sub-account
overrides remain untouched.
"""

from alembic import op


revision = "z4d5e6f7a8b9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE global_rules SET inventory_probe_rate_per_sec = 2.0 "
        "WHERE inventory_probe_rate_per_sec = 3.8"
    )
    op.execute(
        "ALTER TABLE global_rules ALTER COLUMN inventory_probe_rate_per_sec "
        "SET DEFAULT 2.0"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE global_rules ALTER COLUMN inventory_probe_rate_per_sec "
        "SET DEFAULT 3.8"
    )

