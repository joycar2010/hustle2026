"""add strategy timing configs table

Revision ID: 20260316_0003
Revises: 20260316_0002
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260316_0003'
down_revision = '20260316_0002'
branch_labels = None
depends_on = None


def upgrade():
    # Create strategy_timing_configs table
    op.create_table(
        'strategy_timing_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('config_level', sa.String(length=20), nullable=False),
        sa.Column('strategy_type', sa.String(length=50), nullable=True),
        sa.Column('strategy_instance_id', sa.Integer(), nullable=True),

        # Trigger control group
        sa.Column('trigger_check_interval', sa.Float(), nullable=False, server_default='0.5'),

        # Order execution group
        sa.Column('binance_timeout', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('bybit_timeout', sa.Float(), nullable=False, server_default='0.1'),
        sa.Column('order_check_interval', sa.Float(), nullable=False, server_default='0.2'),
        sa.Column('spread_check_interval', sa.Float(), nullable=False, server_default='2.0'),
        sa.Column('mt5_deal_sync_wait', sa.Float(), nullable=False, server_default='3.0'),

        # Flow control group
        sa.Column('api_spam_prevention_delay', sa.Float(), nullable=False, server_default='3.0'),
        sa.Column('delayed_single_leg_check_delay', sa.Float(), nullable=False, server_default='10.0'),
        sa.Column('delayed_single_leg_second_check_delay', sa.Float(), nullable=False, server_default='1.0'),

        # Retry configuration group
        sa.Column('api_retry_times', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('api_retry_delay', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('max_binance_limit_retries', sa.Integer(), nullable=False, server_default='25'),

        # Wait delay group
        sa.Column('open_wait_after_cancel_no_trade', sa.Float(), nullable=False, server_default='3.0'),
        sa.Column('open_wait_after_cancel_part', sa.Float(), nullable=False, server_default='2.0'),
        sa.Column('close_wait_after_cancel_no_trade', sa.Float(), nullable=False, server_default='3.0'),
        sa.Column('close_wait_after_cancel_part', sa.Float(), nullable=False, server_default='2.0'),

        # Metadata
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', sa.Integer(), nullable=True),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('config_level', 'strategy_type', 'strategy_instance_id', name='uq_timing_config_level')
    )

    # Insert global default configuration
    op.execute("""
        INSERT INTO strategy_timing_configs (
            config_level, strategy_type, strategy_instance_id,
            trigger_check_interval, binance_timeout, bybit_timeout,
            order_check_interval, spread_check_interval, mt5_deal_sync_wait,
            api_spam_prevention_delay, delayed_single_leg_check_delay, delayed_single_leg_second_check_delay,
            api_retry_times, api_retry_delay, max_binance_limit_retries,
            open_wait_after_cancel_no_trade, open_wait_after_cancel_part,
            close_wait_after_cancel_no_trade, close_wait_after_cancel_part
        ) VALUES (
            'global', NULL, NULL,
            0.5, 5.0, 0.1,
            0.2, 2.0, 3.0,
            3.0, 10.0, 1.0,
            3, 0.5, 25,
            3.0, 2.0,
            3.0, 2.0
        )
    """)

    # Insert strategy type default configurations
    strategy_types = ['reverse_opening', 'reverse_closing', 'forward_opening', 'forward_closing']
    for strategy_type in strategy_types:
        op.execute(f"""
            INSERT INTO strategy_timing_configs (
                config_level, strategy_type, strategy_instance_id,
                trigger_check_interval, binance_timeout, bybit_timeout,
                order_check_interval, spread_check_interval, mt5_deal_sync_wait,
                api_spam_prevention_delay, delayed_single_leg_check_delay, delayed_single_leg_second_check_delay,
                api_retry_times, api_retry_delay, max_binance_limit_retries,
                open_wait_after_cancel_no_trade, open_wait_after_cancel_part,
                close_wait_after_cancel_no_trade, close_wait_after_cancel_part
            ) VALUES (
                'strategy_type', '{strategy_type}', NULL,
                0.5, 5.0, 0.1,
                0.2, 2.0, 3.0,
                3.0, 10.0, 1.0,
                3, 0.5, 25,
                3.0, 2.0,
                3.0, 2.0
            )
        """)


def downgrade():
    op.drop_table('strategy_timing_configs')
