"""Add role column to users table

Revision ID: 20260219_1700
Revises: fa63d0970dfa
Create Date: 2026-02-19 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260219_1700'
down_revision = 'fa63d0970dfa'
branch_labels = None
depends_on = None


def upgrade():
    # Add role column to users table
    op.add_column('users', sa.Column('role', sa.String(50), nullable=False, server_default='交易员'))


def downgrade():
    # Remove role column from users table
    op.drop_column('users', 'role')
