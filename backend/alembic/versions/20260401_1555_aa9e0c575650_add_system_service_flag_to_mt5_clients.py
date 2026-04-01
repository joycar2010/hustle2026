"""add system service flag to mt5_clients

Revision ID: aa9e0c575650
Revises: 20260316_0008
Create Date: 2026-04-01 15:55:04.109533+00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa9e0c575650'
down_revision = '20260316_0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('mt5_clients',
        sa.Column('is_system_service', sa.Boolean(),
                  nullable=False, server_default='false'))
    op.create_index('idx_mt5_clients_system_service',
                    'mt5_clients', ['is_system_service'])


def downgrade() -> None:
    op.drop_index('idx_mt5_clients_system_service', table_name='mt5_clients')
    op.drop_column('mt5_clients', 'is_system_service')
