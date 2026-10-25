"""Raise the default parallel borrow-account cap to five.

The cap is an admission limit for distinct sub-accounts borrowing one asset.
The active-position uniqueness constraint remains account scoped and is not
relaxed by this migration.
"""

from alembic import op


revision = "z5e6f7a8b9c0"
down_revision = "z4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE global_rules SET multi_max_accounts_per_symbol = 5 "
        "WHERE multi_max_accounts_per_symbol = 3 OR multi_max_accounts_per_symbol IS NULL"
    )
    op.execute(
        "ALTER TABLE global_rules ALTER COLUMN multi_max_accounts_per_symbol "
        "SET DEFAULT 5"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE global_rules ALTER COLUMN multi_max_accounts_per_symbol "
        "SET DEFAULT 3"
    )

