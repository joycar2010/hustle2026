"""add opening_m_coin and closing_m_coin fields

Revision ID: 20260228_0001
Revises: 20260226_0002
Create Date: 2026-02-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260228_0001'
down_revision = '20260226_0002'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns
    op.add_column('strategy_configs', sa.Column('opening_m_coin', sa.Float(), nullable=True))
    op.add_column('strategy_configs', sa.Column('closing_m_coin', sa.Float(), nullable=True))

    # Set default values from existing m_coin
    op.execute('UPDATE strategy_configs SET opening_m_coin = m_coin WHERE opening_m_coin IS NULL')
    op.execute('UPDATE strategy_configs SET closing_m_coin = m_coin WHERE closing_m_coin IS NULL')

    # Make columns non-nullable
    op.alter_column('strategy_configs', 'opening_m_coin', nullable=False)
    op.alter_column('strategy_configs', 'closing_m_coin', nullable=False)


def downgrade():
    op.drop_column('strategy_configs', 'closing_m_coin')
    op.drop_column('strategy_configs', 'opening_m_coin')
