"""Separate one borrow request from one opening tranche.

Revision ID: cc46d7e8f9a0
Revises: bb35c8d2e1f4
"""

from alembic import op


revision = "cc46d7e8f9a0"
down_revision = "bb35c8d2e1f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS "
        "open_order_amount NUMERIC(15,2)"
    )
    op.execute(
        "ALTER TABLE symbol_rules ADD COLUMN IF NOT EXISTS "
        "open_order_amount NUMERIC(15,2)"
    )
    op.execute(
        "ALTER TABLE account_symbol_rules ADD COLUMN IF NOT EXISTS "
        "open_order_amount NUMERIC(15,2)"
    )
    op.execute(
        "ALTER TABLE rule_presets ADD COLUMN IF NOT EXISTS "
        "open_order_amount NUMERIC(15,2)"
    )

    # Before this split, order_amount was also the opening-tranche amount at
    # every rule layer. Preserve those explicit values while allowing future
    # edits to configure borrow and hedge sizes independently.
    op.execute(
        "UPDATE global_rules SET open_order_amount = order_amount "
        "WHERE open_order_amount IS NULL AND order_amount IS NOT NULL"
    )
    op.execute(
        "UPDATE symbol_rules SET open_order_amount = order_amount "
        "WHERE open_order_amount IS NULL AND order_amount IS NOT NULL"
    )
    op.execute(
        "UPDATE account_symbol_rules SET open_order_amount = order_amount "
        "WHERE open_order_amount IS NULL AND order_amount IS NOT NULL"
    )
    op.execute(
        "UPDATE rule_presets SET open_order_amount = order_amount "
        "WHERE open_order_amount IS NULL AND order_amount IS NOT NULL"
    )
    # SubAccount already had separate fields. Older rows can have only the
    # borrow-request field populated; fill only the missing opening value and
    # never overwrite an explicit account opening amount.
    op.execute(
        "UPDATE sub_accounts SET order_amount = single_order_amount "
        "WHERE order_amount IS NULL AND single_order_amount IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE rule_presets DROP COLUMN IF EXISTS open_order_amount")
    op.execute(
        "ALTER TABLE account_symbol_rules DROP COLUMN IF EXISTS open_order_amount"
    )
    op.execute("ALTER TABLE symbol_rules DROP COLUMN IF EXISTS open_order_amount")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS open_order_amount")
