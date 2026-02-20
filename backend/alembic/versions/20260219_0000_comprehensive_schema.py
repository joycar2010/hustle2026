"""Comprehensive schema for Hustle2026 XAU arbitrage system

Revision ID: 20260219_0000
Revises:
Create Date: 2026-02-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '20260219_0000'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create market_data table if not exists
    op.create_table(
        'market_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('bid_price', sa.Float(), nullable=False),
        sa.Column('ask_price', sa.Float(), nullable=False),
        sa.Column('mid_price', sa.Float(), nullable=False),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_market_data_symbol_platform_time', 'market_data', ['symbol', 'platform', 'timestamp'])
    op.create_index('idx_market_data_timestamp', 'market_data', ['timestamp'])

    # Create spread_records table
    op.create_table(
        'spread_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('symbol', sa.String(20), nullable=False, server_default='XAUUSDT'),
        sa.Column('binance_bid', sa.Float(), nullable=False),
        sa.Column('binance_ask', sa.Float(), nullable=False),
        sa.Column('bybit_bid', sa.Float(), nullable=False),
        sa.Column('bybit_ask', sa.Float(), nullable=False),
        sa.Column('forward_spread', sa.Float(), nullable=False),
        sa.Column('reverse_spread', sa.Float(), nullable=False),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_spread_records_time', 'spread_records', ['timestamp'])
    op.create_index('idx_spread_records_symbol_time', 'spread_records', ['symbol', 'timestamp'])

    # Create positions table if not exists
    op.create_table(
        'positions',
        sa.Column('position_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.account_id'), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('current_price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('leverage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('unrealized_pnl', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('realized_pnl', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('margin_used', sa.Float(), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('open_time', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('close_time', sa.TIMESTAMP()),
        sa.Column('update_time', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_positions_user_open', 'positions', ['user_id', 'is_open'])
    op.create_index('idx_positions_account', 'positions', ['account_id'])

    # Create trades table for historical trades
    op.create_table(
        'trades',
        sa.Column('trade_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.account_id'), nullable=False),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('positions.position_id')),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),  # buy, sell
        sa.Column('trade_type', sa.String(20), nullable=False),  # open, close, manual
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('fee', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('realized_pnl', sa.Float(), server_default='0.0'),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_trades_user_time', 'trades', ['user_id', 'timestamp'])
    op.create_index('idx_trades_account_time', 'trades', ['account_id', 'timestamp'])
    op.create_index('idx_trades_position', 'trades', ['position_id'])

    # Create account_snapshots table for tracking account balance history
    op.create_table(
        'account_snapshots',
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.account_id'), nullable=False),
        sa.Column('total_assets', sa.Float(), nullable=False),
        sa.Column('available_assets', sa.Float(), nullable=False),
        sa.Column('net_assets', sa.Float(), nullable=False),
        sa.Column('total_position', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('frozen_assets', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('margin_balance', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('margin_used', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('margin_available', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('unrealized_pnl', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('daily_pnl', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('risk_ratio', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_account_snapshots_account_time', 'account_snapshots', ['account_id', 'timestamp'])

    # Create strategy_performance table for tracking strategy performance
    op.create_table(
        'strategy_performance',
        sa.Column('performance_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('strategy_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('strategies.strategy_id'), nullable=False),
        sa.Column('today_trades', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('today_profit', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_trades', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_profit', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('win_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('max_drawdown', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_strategy_performance_strategy_date', 'strategy_performance', ['strategy_id', 'date'])

    # Create system_alerts table for system notifications
    op.create_table(
        'system_alerts',
        sa.Column('alert_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('alert_type', sa.String(50), nullable=False),  # risk, spread, system, trade
        sa.Column('severity', sa.String(20), nullable=False),  # info, warning, error, critical
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_system_alerts_user_time', 'system_alerts', ['user_id', 'timestamp'])
    op.create_index('idx_system_alerts_user_read', 'system_alerts', ['user_id', 'is_read'])

    # Add API credentials columns to accounts table if not exists
    try:
        op.add_column('accounts', sa.Column('api_key', sa.String(500)))
        op.add_column('accounts', sa.Column('api_secret', sa.String(500)))
        op.add_column('accounts', sa.Column('mt5_id', sa.String(50)))
        op.add_column('accounts', sa.Column('mt5_server', sa.String(100)))
        op.add_column('accounts', sa.Column('mt5_password', sa.String(500)))
        op.add_column('accounts', sa.Column('last_sync_time', sa.TIMESTAMP()))
    except:
        pass  # Columns may already exist


def downgrade():
    # Drop tables in reverse order
    op.drop_table('system_alerts')
    op.drop_table('strategy_performance')
    op.drop_table('account_snapshots')
    op.drop_table('trades')
    op.drop_table('positions')
    op.drop_table('spread_records')
    op.drop_table('market_data')

    # Remove added columns from accounts
    try:
        op.drop_column('accounts', 'last_sync_time')
        op.drop_column('accounts', 'mt5_password')
        op.drop_column('accounts', 'mt5_server')
        op.drop_column('accounts', 'mt5_id')
        op.drop_column('accounts', 'api_secret')
        op.drop_column('accounts', 'api_key')
    except:
        pass
