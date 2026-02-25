"""add system_logs table

Revision ID: 20260225_0002
Revises: 20260225_0001
Create Date: 2026-02-25 20:44:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '20260225_0002'
down_revision = '20260225_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create system_logs table
    op.create_table(
        'system_logs',
        sa.Column('log_id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('level', sa.String(20), nullable=False),  # info, warning, error, critical
        sa.Column('category', sa.String(50), nullable=False),  # api, trade, system, auth
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),  # JSON string for additional details
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create indexes
    op.create_index('idx_system_logs_user_id', 'system_logs', ['user_id'])
    op.create_index('idx_system_logs_timestamp', 'system_logs', ['timestamp'])
    op.create_index('idx_system_logs_level_time', 'system_logs', ['level', 'timestamp'])
    op.create_index('idx_system_logs_category_time', 'system_logs', ['category', 'timestamp'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_system_logs_category_time', table_name='system_logs')
    op.drop_index('idx_system_logs_level_time', table_name='system_logs')
    op.drop_index('idx_system_logs_timestamp', table_name='system_logs')
    op.drop_index('idx_system_logs_user_id', table_name='system_logs')
    
    # Drop table
    op.drop_table('system_logs')
