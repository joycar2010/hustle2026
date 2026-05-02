"""add symbol_rules table and sub_account fund columns

Revision ID: 462bde8a8eff
Revises:
Create Date: 2026-05-01 05:31:47.972604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '462bde8a8eff'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'symbol_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('open_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('close_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('order_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('remove_spread', sa.Numeric(10, 4), nullable=True),
        sa.Column('close_funding_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('repay_funding_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('allow_remove', sa.Boolean(), server_default='true'),
        sa.Column('allow_repay', sa.Boolean(), server_default='true'),
        sa.Column('source', sa.String(10), server_default='custom'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_symbol_rules_symbol', 'symbol_rules', ['symbol'], unique=True)

    op.add_column('sub_accounts', sa.Column('order_amount', sa.Numeric(15, 2), nullable=True))
    op.add_column('sub_accounts', sa.Column('base_margin_amount', sa.Numeric(15, 2), nullable=True))
    op.add_column('sub_accounts', sa.Column('single_transfer_amount', sa.Numeric(15, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('sub_accounts', 'single_transfer_amount')
    op.drop_column('sub_accounts', 'base_margin_amount')
    op.drop_column('sub_accounts', 'order_amount')
    op.drop_index('ix_symbol_rules_symbol', 'symbol_rules')
    op.drop_table('symbol_rules')
