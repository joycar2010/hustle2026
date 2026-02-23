"""Add source field to order_records

Revision ID: 20260223_0002
Revises: 20260223_0001
Create Date: 2026-02-23 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260223_0002'
down_revision = '20260223_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Add source column to order_records table
    op.add_column('order_records', sa.Column('source', sa.String(20), nullable=False, server_default='manual'))


def downgrade():
    # Remove source column from order_records table
    op.drop_column('order_records', 'source')
