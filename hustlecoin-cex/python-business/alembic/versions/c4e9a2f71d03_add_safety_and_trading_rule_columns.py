"""add safety and trading rule columns

Revision ID: c4e9a2f71d03
Revises: a3c7e1f40b92
Create Date: 2026-05-01 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e9a2f71d03'
down_revision: Union[str, None] = 'a3c7e1f40b92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # global_rules: safety + trading rule columns
    op.add_column('global_rules', sa.Column('max_loss_per_position', sa.Numeric(15, 2), nullable=True))
    op.add_column('global_rules', sa.Column('circuit_breaker_spread_pct', sa.Numeric(10, 4), nullable=True))
    op.add_column('global_rules', sa.Column('circuit_breaker_pause_sec', sa.Integer(), server_default='300'))
    op.add_column('global_rules', sa.Column('max_daily_interest_rate', sa.Numeric(10, 6), nullable=True))
    op.add_column('global_rules', sa.Column('repay_spread', sa.Numeric(10, 4), nullable=True))

    # symbol_rules: per-symbol interest rate cap + repay spread
    op.add_column('symbol_rules', sa.Column('max_daily_interest_rate', sa.Numeric(10, 6), nullable=True))
    op.add_column('symbol_rules', sa.Column('repay_spread', sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    op.drop_column('symbol_rules', 'repay_spread')
    op.drop_column('symbol_rules', 'max_daily_interest_rate')
    op.drop_column('global_rules', 'repay_spread')
    op.drop_column('global_rules', 'max_daily_interest_rate')
    op.drop_column('global_rules', 'circuit_breaker_pause_sec')
    op.drop_column('global_rules', 'circuit_breaker_spread_pct')
    op.drop_column('global_rules', 'max_loss_per_position')
