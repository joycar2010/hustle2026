"""add leverage to accounts

Revision ID: 20260226_0002
Revises: 20260226_0001
Create Date: 2026-02-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260226_0002'
down_revision = '20260226_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Add leverage column to accounts table
    op.add_column('accounts', sa.Column('leverage', sa.Integer(), nullable=True))

    # Set default leverage based on platform_id
    # Binance (platform_id=1): 20x, Bybit (platform_id=2): 100x
    op.execute("UPDATE accounts SET leverage = 20 WHERE platform_id = 1")
    op.execute("UPDATE accounts SET leverage = 100 WHERE platform_id = 2")


def downgrade():
    # Remove leverage column
    op.drop_column('accounts', 'leverage')
