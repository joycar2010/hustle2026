"""add trigger_check_interval to strategy_configs

Revision ID: 20260316_0001
Revises: 20260315_0001
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260316_0001'
down_revision = '20260315_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Add trigger_check_interval column with default 0.5 (500ms)
    op.add_column('strategy_configs', sa.Column('trigger_check_interval', sa.Float(), nullable=False, server_default='0.5'))

    # Update existing records to use 500ms (0.5 seconds) instead of old 50ms (0.05 seconds)
    op.execute("UPDATE strategy_configs SET trigger_check_interval = 0.5 WHERE trigger_check_interval < 0.1")


def downgrade():
    # Remove trigger_check_interval column
    op.drop_column('strategy_configs', 'trigger_check_interval')
