"""add sub_account owl fields (risk_threshold, min_balance, single_order_amount)

Revision ID: e7a2b4c91f53
Revises: d5f1b3e82a47
Create Date: 2026-05-01 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a2b4c91f53'
down_revision: Union[str, None] = 'd5f1b3e82a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sub_accounts', sa.Column('risk_threshold', sa.Numeric(5, 2), nullable=True))
    op.add_column('sub_accounts', sa.Column('min_balance', sa.Numeric(10, 2), nullable=True))
    op.add_column('sub_accounts', sa.Column('single_order_amount', sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('sub_accounts', 'single_order_amount')
    op.drop_column('sub_accounts', 'min_balance')
    op.drop_column('sub_accounts', 'risk_threshold')
