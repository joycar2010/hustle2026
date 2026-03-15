"""Add pending_orders table for order persistence

Revision ID: 20260306_0001
Revises: 20260228_add_opening_closing_m_coin
Create Date: 2026-03-06 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260306_0001'
down_revision = '20260228_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Create pending_orders table
    op.create_table(
        'pending_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('strategy_type', sa.String(20), nullable=False, comment='forward_opening, reverse_closing, etc.'),
        sa.Column('platform', sa.String(20), nullable=False, comment='binance, bybit'),
        sa.Column('order_id', sa.String(100), nullable=True, comment='Exchange order ID'),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False, comment='BUY, SELL'),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('price', sa.Numeric(20, 8), nullable=True),
        sa.Column('order_type', sa.String(20), nullable=False, comment='LIMIT, MARKET'),
        sa.Column('status', sa.String(20), nullable=False, comment='PENDING, FILLED, PARTIAL, CANCELLED, FAILED'),
        sa.Column('filled_quantity', sa.Numeric(20, 8), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('extra_data', postgresql.JSONB(), nullable=True, comment="Additional metadata"),
    )

    # Create indexes
    op.create_index('idx_pending_orders_user_status', 'pending_orders', ['user_id', 'status'])
    op.create_index('idx_pending_orders_created_at', 'pending_orders', ['created_at'])
    op.create_index('idx_pending_orders_expires_at', 'pending_orders', ['expires_at'])
    op.create_index('idx_pending_orders_order_id', 'pending_orders', ['order_id'])


def downgrade():
    op.drop_index('idx_pending_orders_order_id', table_name='pending_orders')
    op.drop_index('idx_pending_orders_expires_at', table_name='pending_orders')
    op.drop_index('idx_pending_orders_created_at', table_name='pending_orders')
    op.drop_index('idx_pending_orders_user_status', table_name='pending_orders')
    op.drop_table('pending_orders')
