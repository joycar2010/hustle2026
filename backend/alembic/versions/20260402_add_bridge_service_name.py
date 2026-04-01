"""add bridge_service_name to mt5_clients

Revision ID: 20260402_bridge
Revises: 20260401_1555_aa9e0c575650
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260402_bridge'
down_revision = '20260401_1555_aa9e0c575650_add_system_service_flag_to_mt5_clients'
branch_labels = None
depends_on = None


def upgrade():
    # 添加 bridge_service_name 字段
    op.add_column('mt5_clients',
        sa.Column('bridge_service_name', sa.String(100), nullable=True, comment='Bridge服务名称（nssm服务）')
    )


def downgrade():
    # 删除 bridge_service_name 字段
    op.drop_column('mt5_clients', 'bridge_service_name')
