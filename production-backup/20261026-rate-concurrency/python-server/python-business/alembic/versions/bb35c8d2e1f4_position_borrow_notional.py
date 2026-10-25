"""Persist the confirmed borrow notional used by cumulative caps.

Revision ID: bb35c8d2e1f4
Revises: aa24b8c1d9e0
"""

from alembic import op


revision = "bb35c8d2e1f4"
down_revision = "aa24b8c1d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS "
        "borrow_usdt_amount NUMERIC(15,4)"
    )
    op.execute(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS "
        "borrowed_at TIMESTAMP WITH TIME ZONE"
    )
    # Existing OPEN rows already carry their executed spot notional.  It is a
    # conservative historical baseline for the new cap field; pre-hedge legacy
    # rows remain NULL and continue to use authoritative Binance debt value.
    op.execute(
        "UPDATE positions SET borrow_usdt_amount = open_usdt_amount "
        "WHERE borrow_usdt_amount IS NULL AND open_usdt_amount IS NOT NULL"
    )
    op.execute(
        "UPDATE positions SET borrowed_at = COALESCE(opened_at, created_at) "
        "WHERE borrowed_at IS NULL AND borrow_qty IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS borrowed_at")
    op.execute(
        "ALTER TABLE positions DROP COLUMN IF EXISTS borrow_usdt_amount"
    )
