"""add bridge_service_port to mt5_clients

Revision ID: 20260402_bridge_port
Revises: 20260402_bridge
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260402_bridge_port'
down_revision = '20260402_bridge'
branch_labels = None
depends_on = None


def upgrade():
    # 添加 bridge_service_port 字段
    op.add_column('mt5_clients',
        sa.Column('bridge_service_port', sa.Integer(), nullable=True, comment='Bridge服务端口')
    )


def downgrade():
    # 删除 bridge_service_port 字段
    op.drop_column('mt5_clients', 'bridge_service_port')
