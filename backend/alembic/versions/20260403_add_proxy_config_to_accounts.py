"""Add proxy_config column to accounts table

Revision ID: 20260403_0001
Revises: 20260402
Create Date: 2026-04-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '20260403_0001'
down_revision = '20260402_bridge_port'
branch_labels = None
depends_on = None


def upgrade():
    # Add proxy_config column to accounts table
    op.add_column('accounts',
        sa.Column('proxy_config', JSONB, nullable=True,
                  comment='代理配置: {proxy_type, host, port, username, password, region}')
    )


def downgrade():
    # Remove proxy_config column from accounts table
    op.drop_column('accounts', 'proxy_config')
