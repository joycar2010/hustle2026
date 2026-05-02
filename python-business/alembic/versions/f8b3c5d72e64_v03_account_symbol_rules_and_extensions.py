"""v0.3: account_symbol_rules table + SubAccount/GlobalRules/Symbol extensions

Revision ID: f8b3c5d72e64
Revises: e7a2b4c91f53
Create Date: 2026-05-01 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8b3c5d72e64'
down_revision: Union[str, None] = 'e7a2b4c91f53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'account_symbol_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sub_account_id', sa.Integer(), sa.ForeignKey('sub_accounts.id'), nullable=False),
        sa.Column('symbol', sa.String(30), nullable=False, index=True),
        sa.Column('open_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('close_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('order_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('remove_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('close_funding_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('repay_funding_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('max_daily_interest_rate', sa.Numeric(10, 6), nullable=True),
        sa.Column('repay_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('max_borrow_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('sub_account_id', 'symbol', name='uq_account_symbol'),
    )

    op.add_column('sub_accounts', sa.Column('max_positions', sa.Integer(), nullable=True))
    op.add_column('sub_accounts', sa.Column('max_borrow_amount', sa.Numeric(15, 2), nullable=True))

    op.add_column('global_rules', sa.Column('max_positions', sa.Integer(), server_default='10'))
    op.add_column('global_rules', sa.Column('auto_start_on_boot', sa.Boolean(), server_default='false'))
    op.add_column('global_rules', sa.Column('futures_liquidation_threshold', sa.Numeric(5, 2), nullable=True))

    op.add_column('symbols', sa.Column('is_new_coin', sa.Boolean(), server_default='false'))
    op.add_column('symbols', sa.Column('is_delisting', sa.Boolean(), server_default='false'))
    op.add_column('symbols', sa.Column('allow_open', sa.Boolean(), server_default='true'))
    op.add_column('symbols', sa.Column('volume_24h', sa.Numeric(20, 2), nullable=True))
    op.add_column('symbols', sa.Column('volume_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('symbols', 'volume_updated_at')
    op.drop_column('symbols', 'volume_24h')
    op.drop_column('symbols', 'allow_open')
    op.drop_column('symbols', 'is_delisting')
    op.drop_column('symbols', 'is_new_coin')

    op.drop_column('global_rules', 'futures_liquidation_threshold')
    op.drop_column('global_rules', 'auto_start_on_boot')
    op.drop_column('global_rules', 'max_positions')

    op.drop_column('sub_accounts', 'max_borrow_amount')
    op.drop_column('sub_accounts', 'max_positions')

    op.drop_table('account_symbol_rules')
