"""Add fee field to order_records

Revision ID: 20260223_0001
Revises: 20260223_0000
Create Date: 2026-02-23 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260223_0001'
down_revision = '20260223_0000'
branch_labels = None
depends_on = None


def upgrade():
    # Add fee column to order_records table
    op.add_column('order_records', sa.Column('fee', sa.Float(), nullable=False, server_default='0.0'))


def downgrade():
    # Remove fee column from order_records table
    op.drop_column('order_records', 'fee')
