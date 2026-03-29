"""add opening and closing trigger check intervals

Revision ID: 20260316_0002
Revises: 20260316_0001
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260316_0002'
down_revision = '20260316_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns for opening and closing trigger check intervals
    op.add_column('strategy_configs', sa.Column('opening_trigger_check_interval', sa.Float(), nullable=True))
    op.add_column('strategy_configs', sa.Column('closing_trigger_check_interval', sa.Float(), nullable=True))

    # Migrate existing data: use trigger_check_interval if exists, otherwise default to 0.5 (500ms)
    op.execute("""
        UPDATE strategy_configs
        SET opening_trigger_check_interval = COALESCE(trigger_check_interval, 0.5),
            closing_trigger_check_interval = COALESCE(trigger_check_interval, 0.5)
        WHERE opening_trigger_check_interval IS NULL OR closing_trigger_check_interval IS NULL
    """)

    # Make columns non-nullable after migration
    op.alter_column('strategy_configs', 'opening_trigger_check_interval', nullable=False)
    op.alter_column('strategy_configs', 'closing_trigger_check_interval', nullable=False)


def downgrade():
    # Remove the new columns
    op.drop_column('strategy_configs', 'closing_trigger_check_interval')
    op.drop_column('strategy_configs', 'opening_trigger_check_interval')
