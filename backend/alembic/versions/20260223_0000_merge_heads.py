"""Merge migration heads

Revision ID: 20260223_0000
Revises: 20260219_0000, 20260219_1700
Create Date: 2026-02-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260223_0000'
down_revision = ('20260219_0000', '20260219_1700')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
