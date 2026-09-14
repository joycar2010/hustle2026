"""optimization phase 1: max_order_count on sub_accounts

Revision ID: m7e8f9a0b1c2
Revises: l6d7e8f9a0b1
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = "m7e8f9a0b1c2"
down_revision = "l6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sub_accounts', sa.Column('max_order_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('sub_accounts', 'max_order_count')
