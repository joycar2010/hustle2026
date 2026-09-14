"""phase 2: rule_presets table + is_risky on symbols

Revision ID: n8f9a0b1c2d3
Revises: m7e8f9a0b1c2
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = "n8f9a0b1c2d3"
down_revision = "m7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('symbols', sa.Column('is_risky', sa.Boolean(), server_default='false'))

    op.create_table(
        'rule_presets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('open_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('close_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('order_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('remove_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('close_funding_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('repay_funding_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('repay_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('max_daily_interest_rate', sa.Numeric(10, 6), nullable=True),
        sa.Column('max_borrow_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('rule_presets')
    op.drop_column('symbols', 'is_risky')
