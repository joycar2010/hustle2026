"""Add proxy management tables

Revision ID: 20260316_0007
Revises: 20260316_0006
Create Date: 2026-03-16 18:37:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '20260316_0007'
down_revision = '20260316_0006'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 创建代理池表
    op.create_table(
        'proxy_pool',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('proxy_type', sa.String(20), nullable=False, comment='代理类型: http, https, socks5'),
        sa.Column('host', sa.String(255), nullable=False, comment='代理主机地址'),
        sa.Column('port', sa.Integer(), nullable=False, comment='代理端口'),
        sa.Column('username', sa.String(255), nullable=True, comment='代理用户名'),
        sa.Column('password', sa.String(255), nullable=True, comment='代理密码'),
        sa.Column('provider', sa.String(50), nullable=False, default='qingguo', comment='代理提供商: qingguo, custom'),
        sa.Column('region', sa.String(50), nullable=True, comment='代理地区'),
        sa.Column('ip_address', sa.String(50), nullable=True, comment='代理IP地址'),
        sa.Column('expire_time', sa.TIMESTAMP(), nullable=True, comment='过期时间'),
        sa.Column('status', sa.String(20), nullable=False, default='active', comment='状态: active, inactive, expired, failed'),
        sa.Column('health_score', sa.Integer(), nullable=False, default=100, comment='健康分数 0-100'),
        sa.Column('last_check_time', sa.TIMESTAMP(), nullable=True, comment='最后检查时间'),
        sa.Column('total_requests', sa.Integer(), nullable=False, default=0, comment='总请求次数'),
        sa.Column('failed_requests', sa.Integer(), nullable=False, default=0, comment='失败请求次数'),
        sa.Column('avg_latency_ms', sa.Float(), nullable=True, comment='平均延迟(毫秒)'),
        sa.Column('extra_metadata', JSONB, nullable=True, comment='额外元数据'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True, comment='创建人'),
    )

    # 创建索引
    op.create_index('idx_proxy_pool_status', 'proxy_pool', ['status'])
    op.create_index('idx_proxy_pool_provider', 'proxy_pool', ['provider'])
    op.create_index('idx_proxy_pool_health', 'proxy_pool', ['health_score'])
    op.create_index('idx_proxy_pool_expire', 'proxy_pool', ['expire_time'])

    # 2. 创建账户代理绑定表
    op.create_table(
        'account_proxy_bindings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False, comment='账户ID'),
        sa.Column('proxy_id', sa.Integer(), nullable=False, comment='代理ID'),
        sa.Column('platform_id', sa.Integer(), nullable=False, comment='平台ID: 1=Binance, 2=Bybit'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True, comment='是否启用'),
        sa.Column('priority', sa.Integer(), nullable=False, default=0, comment='优先级，数字越大优先级越高'),
        sa.Column('bind_time', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False, comment='绑定时间'),
        sa.Column('unbind_time', sa.TIMESTAMP(), nullable=True, comment='解绑时间'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.account_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['proxy_id'], ['proxy_pool.id'], ondelete='CASCADE'),
    )

    # 创建唯一索引：一个账户在同一平台只能绑定一个活跃代理
    op.create_index('idx_account_proxy_unique', 'account_proxy_bindings',
                    ['account_id', 'platform_id', 'is_active'], unique=True,
                    postgresql_where=sa.text('is_active = true'))
    op.create_index('idx_account_proxy_account', 'account_proxy_bindings', ['account_id'])
    op.create_index('idx_account_proxy_proxy', 'account_proxy_bindings', ['proxy_id'])

    # 3. 创建代理健康检查日志表
    op.create_table(
        'proxy_health_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('proxy_id', sa.Integer(), nullable=False, comment='代理ID'),
        sa.Column('check_time', sa.TIMESTAMP(), nullable=False, comment='检查时间'),
        sa.Column('is_success', sa.Boolean(), nullable=False, comment='是否成功'),
        sa.Column('latency_ms', sa.Float(), nullable=True, comment='延迟(毫秒)'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('check_type', sa.String(50), nullable=False, default='auto', comment='检查类型: auto, manual'),
        sa.Column('target_url', sa.String(255), nullable=True, comment='测试目标URL'),
        sa.Column('response_code', sa.Integer(), nullable=True, comment='响应状态码'),
        sa.ForeignKeyConstraint(['proxy_id'], ['proxy_pool.id'], ondelete='CASCADE'),
    )

    # 创建索引
    op.create_index('idx_proxy_health_proxy', 'proxy_health_logs', ['proxy_id'])
    op.create_index('idx_proxy_health_time', 'proxy_health_logs', ['check_time'])
    op.create_index('idx_proxy_health_success', 'proxy_health_logs', ['is_success'])

    # 4. 创建代理使用统计表
    op.create_table(
        'proxy_usage_stats',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('proxy_id', sa.Integer(), nullable=False, comment='代理ID'),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False, comment='账户ID'),
        sa.Column('platform_id', sa.Integer(), nullable=False, comment='平台ID'),
        sa.Column('date', sa.Date(), nullable=False, comment='统计日期'),
        sa.Column('total_requests', sa.Integer(), nullable=False, default=0, comment='总请求数'),
        sa.Column('success_requests', sa.Integer(), nullable=False, default=0, comment='成功请求数'),
        sa.Column('failed_requests', sa.Integer(), nullable=False, default=0, comment='失败请求数'),
        sa.Column('avg_latency_ms', sa.Float(), nullable=True, comment='平均延迟'),
        sa.Column('total_data_mb', sa.Float(), nullable=False, default=0, comment='总流量(MB)'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['proxy_id'], ['proxy_pool.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.account_id'], ondelete='CASCADE'),
    )

    # 创建唯一索引：每个代理+账户+日期只有一条记录
    op.create_unique_constraint('uq_proxy_usage_stats', 'proxy_usage_stats',
                                ['proxy_id', 'account_id', 'date'])
    op.create_index('idx_proxy_usage_date', 'proxy_usage_stats', ['date'])
    op.create_index('idx_proxy_usage_proxy', 'proxy_usage_stats', ['proxy_id'])


def downgrade():
    op.drop_table('proxy_usage_stats')
    op.drop_table('proxy_health_logs')
    op.drop_table('account_proxy_bindings')
    op.drop_table('proxy_pool')
