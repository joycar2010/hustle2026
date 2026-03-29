"""add notifications table

Revision ID: 20260225_0001
Revises: 20260223_0002
Create Date: 2026-02-25 20:38:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '20260225_0001'
down_revision = '20260223_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column('notification_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),  # trade, alert, system, info
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create indexes
    op.create_index('idx_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('idx_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('idx_notifications_user_read', 'notifications', ['user_id', 'is_read'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_notifications_user_read', table_name='notifications')
    op.drop_index('idx_notifications_created_at', table_name='notifications')
    op.drop_index('idx_notifications_user_id', table_name='notifications')
    
    # Drop table
    op.drop_table('notifications')
