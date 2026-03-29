"""Add ladder config columns to strategy_configs

Revision ID: 20260226_0001
Revises: 20260225_0002
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260226_0001'
down_revision = ('20260225_0002', '20260225_0000')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add mCoin (max lots per batch)
    op.add_column('strategy_configs', sa.Column('m_coin', sa.Float(), nullable=False, server_default='5'))
    # Add ladder configs as JSONB array
    op.add_column('strategy_configs', sa.Column('ladders', postgresql.JSONB(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('strategy_configs', 'ladders')
    op.drop_column('strategy_configs', 'm_coin')
