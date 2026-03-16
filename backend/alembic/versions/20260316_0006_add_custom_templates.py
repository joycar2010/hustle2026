"""add custom templates

Revision ID: 20260316_0006
Revises: 20260316_0005
Create Date: 2026-03-16 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260316_0006'
down_revision = '20260316_0005'
branch_labels = None
depends_on = None


def upgrade():
    # 创建自定义模板表
    op.create_table(
        'timing_config_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('strategy_type', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('config_data', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ondelete='SET NULL')
    )

    # 创建索引
    op.create_index('idx_timing_config_templates_strategy_type', 'timing_config_templates', ['strategy_type'])
    op.create_index('idx_timing_config_templates_created_at', 'timing_config_templates', ['created_at'])


def downgrade():
    # 删除索引
    op.drop_index('idx_timing_config_templates_created_at')
    op.drop_index('idx_timing_config_templates_strategy_type')

    # 删除表
    op.drop_table('timing_config_templates')
