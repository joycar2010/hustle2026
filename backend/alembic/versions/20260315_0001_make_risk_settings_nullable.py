"""make risk settings fields nullable

Revision ID: 20260315_0001
Revises: 20260306_0001
Create Date: 2026-03-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260315_0001'
down_revision = '20260306_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Make all numeric fields in risk_settings nullable
    op.alter_column('risk_settings', 'binance_net_asset',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'bybit_mt5_net_asset',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'total_net_asset',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'binance_liquidation_price',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'bybit_mt5_liquidation_price',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'mt5_lag_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'reverse_open_price',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'reverse_open_sync_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'reverse_close_price',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'reverse_close_sync_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'forward_open_price',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'forward_open_sync_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'forward_close_price',
               existing_type=sa.Float(),
               nullable=True)
    op.alter_column('risk_settings', 'forward_close_sync_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'single_leg_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'spread_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'net_asset_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'mt5_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=True)
    op.alter_column('risk_settings', 'liquidation_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=True)


def downgrade():
    # Revert all fields back to NOT NULL with defaults
    op.alter_column('risk_settings', 'liquidation_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'mt5_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'net_asset_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'spread_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'single_leg_alert_repeat_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'forward_close_sync_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'forward_close_price',
               existing_type=sa.Float(),
               nullable=False,
               server_default='0.2')
    op.alter_column('risk_settings', 'forward_open_sync_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'forward_open_price',
               existing_type=sa.Float(),
               nullable=False,
               server_default='0.5')
    op.alter_column('risk_settings', 'reverse_close_sync_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'reverse_close_price',
               existing_type=sa.Float(),
               nullable=False,
               server_default='0.2')
    op.alter_column('risk_settings', 'reverse_open_sync_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='3')
    op.alter_column('risk_settings', 'reverse_open_price',
               existing_type=sa.Float(),
               nullable=False,
               server_default='0.5')
    op.alter_column('risk_settings', 'mt5_lag_count',
               existing_type=sa.Integer(),
               nullable=False,
               server_default='5')
    op.alter_column('risk_settings', 'bybit_mt5_liquidation_price',
               existing_type=sa.Float(),
               nullable=False,
               server_default='2000')
    op.alter_column('risk_settings', 'binance_liquidation_price',
               existing_type=sa.Float(),
               nullable=False,
               server_default='2000')
    op.alter_column('risk_settings', 'total_net_asset',
               existing_type=sa.Float(),
               nullable=False,
               server_default='20000')
    op.alter_column('risk_settings', 'bybit_mt5_net_asset',
               existing_type=sa.Float(),
               nullable=False,
               server_default='10000')
    op.alter_column('risk_settings', 'binance_net_asset',
               existing_type=sa.Float(),
               nullable=False,
               server_default='10000')
