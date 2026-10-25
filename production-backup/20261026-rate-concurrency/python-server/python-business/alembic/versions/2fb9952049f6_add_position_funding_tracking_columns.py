"""add position funding tracking columns

Revision ID: 2fb9952049f6
Revises: 462bde8a8eff
Create Date: 2026-05-01 05:35:57.854693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fb9952049f6'
down_revision: Union[str, None] = '462bde8a8eff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('cumulative_funding_fee', sa.Numeric(15, 8), server_default='0'))
    op.add_column('positions', sa.Column('cumulative_interest', sa.Numeric(15, 8), server_default='0'))
    op.add_column('positions', sa.Column('funding_rate_ratio', sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    op.drop_column('positions', 'funding_rate_ratio')
    op.drop_column('positions', 'cumulative_interest')
    op.drop_column('positions', 'cumulative_funding_fee')
