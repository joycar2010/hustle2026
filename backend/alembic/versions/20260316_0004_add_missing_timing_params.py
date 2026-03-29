"""add missing timing parameters

Revision ID: 20260316_0004
Revises: 20260316_0003
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260316_0004'
down_revision = '20260316_0003'
branch_labels = None
depends_on = None


def upgrade():
    # Add missing trigger count parameters
    op.add_column('strategy_timing_configs',
        sa.Column('opening_trigger_count', sa.Integer(), nullable=False, server_default='3')
    )
    op.add_column('strategy_timing_configs',
        sa.Column('closing_trigger_count', sa.Integer(), nullable=False, server_default='3')
    )

    # Add frontend interaction parameters
    op.add_column('strategy_timing_configs',
        sa.Column('status_polling_interval', sa.Float(), nullable=False, server_default='5.0')
    )
    op.add_column('strategy_timing_configs',
        sa.Column('debounce_delay', sa.Float(), nullable=False, server_default='0.5')
    )


def downgrade():
    op.drop_column('strategy_timing_configs', 'debounce_delay')
    op.drop_column('strategy_timing_configs', 'status_polling_interval')
    op.drop_column('strategy_timing_configs', 'closing_trigger_count')
    op.drop_column('strategy_timing_configs', 'opening_trigger_count')
