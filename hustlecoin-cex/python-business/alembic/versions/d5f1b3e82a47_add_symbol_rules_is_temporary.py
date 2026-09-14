"""add symbol_rules is_temporary column

Revision ID: d5f1b3e82a47
Revises: c4e9a2f71d03
Create Date: 2026-05-01 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f1b3e82a47'
down_revision: Union[str, None] = 'c4e9a2f71d03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('symbol_rules', sa.Column('is_temporary', sa.Boolean(), server_default='false'))


def downgrade() -> None:
    op.drop_column('symbol_rules', 'is_temporary')
