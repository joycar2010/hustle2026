"""order-quality params on global_rules: slippage_pct, follow_type, stabilize_sec, tier_ratios

Revision ID: o9a0b1c2d3e4
Revises: n8f9a0b1c2d3
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "o9a0b1c2d3e4"
down_revision = "n8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('global_rules', sa.Column('slippage_pct', sa.Numeric(10, 4), server_default='0.1'))
    op.add_column('global_rules', sa.Column('follow_type', sa.String(10), server_default='market'))
    op.add_column('global_rules', sa.Column('stabilize_sec', sa.Numeric(6, 2), server_default='0'))
    op.add_column('global_rules', sa.Column('tier_ratios', sa.String(120), server_default=''))


def downgrade() -> None:
    op.drop_column('global_rules', 'tier_ratios')
    op.drop_column('global_rules', 'stabilize_sec')
    op.drop_column('global_rules', 'follow_type')
    op.drop_column('global_rules', 'slippage_pct')
