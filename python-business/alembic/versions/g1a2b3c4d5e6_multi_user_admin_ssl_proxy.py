"""Multi-user isolation, admin system, SSL certificates, proxy pool

Revision ID: g1a2b3c4d5e6
Revises: f8b3c5d72e64
Create Date: 2026-05-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g1a2b3c4d5e6'
down_revision: Union[str, None] = 'f8b3c5d72e64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create users table (replaces admin_users)
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(200), nullable=False),
        sa.Column('email', sa.String(100), nullable=True),
        sa.Column('display_name', sa.String(50), nullable=True),
        sa.Column('role', sa.Enum('SUPER_ADMIN', 'ADMIN', 'USER', name='userrole'), nullable=False, server_default='USER'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('max_sub_accounts', sa.Integer(), server_default='5'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('login_ip', sa.String(50), nullable=True),
    )
    op.create_index('ix_users_username', 'users', ['username'])

    # Migrate existing admin_users data to users table
    op.execute("""
        INSERT INTO users (id, username, password_hash, is_active, role, created_at, last_login_at)
        SELECT id, username, password_hash, is_active, 'SUPER_ADMIN', created_at, last_login_at
        FROM admin_users
    """)

    # Get first user id for default assignment
    # We'll use a subquery approach in the ALTER statements

    # 2. Add user_id to all business tables
    for table in [
        'sub_accounts', 'master_account', 'global_rules', 'symbol_rules',
        'account_symbol_rules', 'blacklist', 'feishu_config', 'fund_rules',
        'positions', 'trade_logs', 'engine_state',
    ]:
        op.add_column(table, sa.Column('user_id', sa.Integer(), nullable=True))
        op.create_index(f'ix_{table}_user_id', table, ['user_id'])
        op.create_foreign_key(f'fk_{table}_user_id', table, 'users', ['user_id'], ['id'])

    # Set existing data to first admin user
    op.execute("""
        UPDATE sub_accounts SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE master_account SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE global_rules SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE symbol_rules SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE account_symbol_rules SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE blacklist SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE feishu_config SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE fund_rules SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE positions SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE trade_logs SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)
    op.execute("""
        UPDATE engine_state SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL
    """)

    # Add user_id to audit_logs
    op.add_column('audit_logs', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])

    # Remove unique constraints that conflict with multi-user
    # symbol_rules: symbol had a unique index, now needs (user_id, symbol) unique
    op.drop_index('ix_symbol_rules_symbol', 'symbol_rules')
    op.create_unique_constraint('uq_symbol_rules_user_symbol', 'symbol_rules', ['user_id', 'symbol'])

    # blacklist: symbol was unique, now needs (user_id, symbol) unique
    op.drop_constraint('blacklist_symbol_key', 'blacklist', type_='unique')
    op.create_unique_constraint('uq_blacklist_user_symbol', 'blacklist', ['user_id', 'symbol'])

    # engine_state: scope was unique, now needs (user_id, scope) unique
    op.drop_constraint('engine_state_scope_key', 'engine_state', type_='unique')
    op.create_unique_constraint('uq_engine_state_user_scope', 'engine_state', ['user_id', 'scope'])

    # 3. Create SSL certificates tables
    op.create_table(
        'ssl_certificates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cert_name', sa.String(100), nullable=False),
        sa.Column('domain_name', sa.String(200), nullable=False),
        sa.Column('cert_type', sa.String(20), nullable=False, server_default='upload'),
        sa.Column('cert_content', sa.Text(), nullable=False),
        sa.Column('key_content', sa.Text(), nullable=False),
        sa.Column('issuer', sa.String(200), nullable=True),
        sa.Column('subject', sa.String(200), nullable=True),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_deployed', sa.Boolean(), server_default='false'),
        sa.Column('deploy_path', sa.String(300), nullable=True),
        sa.Column('auto_renew', sa.Boolean(), server_default='false'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ssl_certificates_domain', 'ssl_certificates', ['domain_name'])

    op.create_table(
        'ssl_certificate_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('certificate_id', sa.Integer(), sa.ForeignKey('ssl_certificates.id'), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ssl_cert_logs_cert_id', 'ssl_certificate_logs', ['certificate_id'])

    # 4. Create proxy tables
    op.create_table(
        'proxy_pool',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('host', sa.String(100), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(100), nullable=True),
        sa.Column('password', sa.String(200), nullable=True),
        sa.Column('protocol', sa.String(20), nullable=False, server_default='http'),
        sa.Column('provider', sa.String(30), nullable=False, server_default='custom'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('health_score', sa.Integer(), server_default='100'),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('region', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'account_proxy_bindings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sub_account_id', sa.Integer(), sa.ForeignKey('sub_accounts.id'), nullable=False),
        sa.Column('proxy_id', sa.Integer(), sa.ForeignKey('proxy_pool.id'), nullable=False),
        sa.Column('platform', sa.String(30), nullable=False, server_default='binance'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('sub_account_id', 'platform', name='uq_account_proxy_platform'),
    )

    op.create_table(
        'proxy_health_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('proxy_id', sa.Integer(), sa.ForeignKey('proxy_pool.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_proxy_health_logs_proxy_id', 'proxy_health_logs', ['proxy_id'])

    op.create_table(
        'ipipgo_orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_no', sa.String(100), unique=True, nullable=False),
        sa.Column('product_name', sa.String(100), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('protocol', sa.String(20), nullable=True),
        sa.Column('region', sa.String(100), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('days_left', sa.Integer(), nullable=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('ipipgo_orders')
    op.drop_index('ix_proxy_health_logs_proxy_id', 'proxy_health_logs')
    op.drop_table('proxy_health_logs')
    op.drop_table('account_proxy_bindings')
    op.drop_table('proxy_pool')

    op.drop_index('ix_ssl_cert_logs_cert_id', 'ssl_certificate_logs')
    op.drop_table('ssl_certificate_logs')
    op.drop_index('ix_ssl_certificates_domain', 'ssl_certificates')
    op.drop_table('ssl_certificates')

    # Restore unique constraints
    op.drop_constraint('uq_engine_state_user_scope', 'engine_state', type_='unique')
    op.create_unique_constraint('engine_state_scope_key', 'engine_state', ['scope'])
    op.drop_constraint('uq_blacklist_user_symbol', 'blacklist', type_='unique')
    op.create_unique_constraint('blacklist_symbol_key', 'blacklist', ['symbol'])
    op.drop_constraint('uq_symbol_rules_user_symbol', 'symbol_rules', type_='unique')
    op.create_index('ix_symbol_rules_symbol', 'symbol_rules', ['symbol'], unique=True)

    op.drop_index('ix_audit_logs_user_id', 'audit_logs')
    op.drop_column('audit_logs', 'user_id')

    for table in [
        'engine_state', 'trade_logs', 'positions', 'fund_rules',
        'feishu_config', 'blacklist', 'account_symbol_rules', 'symbol_rules',
        'global_rules', 'master_account', 'sub_accounts',
    ]:
        op.drop_constraint(f'fk_{table}_user_id', table, type_='foreignkey')
        op.drop_index(f'ix_{table}_user_id', table)
        op.drop_column(table, 'user_id')

    op.drop_index('ix_users_username', 'users')
    op.drop_table('users')
    op.execute("DROP TYPE IF EXISTS userrole")
