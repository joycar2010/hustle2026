"""Add MT5 clients table for multi-client support

Revision ID: 20260316_0008
Revises: 20260316_0007
Create Date: 2026-03-16 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260316_0008'
down_revision = '20260316_0007'
branch_labels = None
depends_on = None


def upgrade():
    # 创建MT5客户端表
    op.create_table(
        'mt5_clients',
        sa.Column('client_id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('account_id', UUID(as_uuid=True), sa.ForeignKey('accounts.account_id', ondelete='CASCADE'), nullable=False, comment='关联的MT5账户'),
        sa.Column('client_name', sa.String(100), nullable=False, comment='客户端名称'),

        # MT5安装配置
        sa.Column('mt5_path', sa.String(500), nullable=False, comment='MT5可执行文件路径'),
        sa.Column('mt5_data_path', sa.String(500), nullable=True, comment='MT5数据目录路径'),

        # 登录凭证
        sa.Column('mt5_login', sa.String(100), nullable=False, comment='MT5账号'),
        sa.Column('mt5_password', sa.String(256), nullable=False, comment='MT5密码（加密）'),
        sa.Column('mt5_server', sa.String(100), nullable=False, comment='MT5服务器地址'),
        sa.Column('password_type', sa.String(20), nullable=False, default='primary', comment='密码类型: primary/readonly'),

        # 代理配置
        sa.Column('proxy_id', sa.Integer(), sa.ForeignKey('proxy_pool.id', ondelete='SET NULL'), nullable=True, comment='绑定的代理'),

        # 连接状态
        sa.Column('connection_status', sa.String(20), nullable=False, default='disconnected', comment='连接状态: connected/disconnected/error'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True, comment='是否启用'),
        sa.Column('priority', sa.Integer(), nullable=False, default=0, comment='优先级（数字越小优先级越高）'),

        # 连接统计
        sa.Column('last_connected_at', sa.TIMESTAMP(), nullable=True, comment='最后连接时间'),
        sa.Column('last_disconnected_at', sa.TIMESTAMP(), nullable=True, comment='最后断开时间'),
        sa.Column('total_connections', sa.Integer(), nullable=False, default=0, comment='总连接次数'),
        sa.Column('failed_connections', sa.Integer(), nullable=False, default=0, comment='失败连接次数'),
        sa.Column('avg_latency_ms', sa.Float(), nullable=True, comment='平均延迟（毫秒）'),

        # 元数据
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True, comment='创建人'),
    )

    # 创建索引
    op.create_index('idx_mt5_clients_account_id', 'mt5_clients', ['account_id'])
    op.create_index('idx_mt5_clients_status', 'mt5_clients', ['connection_status'])
    op.create_index('idx_mt5_clients_active', 'mt5_clients', ['is_active'])
    op.create_index('idx_mt5_clients_proxy_id', 'mt5_clients', ['proxy_id'])

    # 创建唯一约束（同一账户下的客户端名称不能重复）
    op.create_unique_constraint('uq_mt5_clients_account_name', 'mt5_clients', ['account_id', 'client_name'])


def downgrade():
    op.drop_table('mt5_clients')
