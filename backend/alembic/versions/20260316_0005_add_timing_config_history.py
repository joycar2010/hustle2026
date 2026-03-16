"""add timing config history

Revision ID: 20260316_0005
Revises: 20260316_0004
Create Date: 2026-03-16 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260316_0005'
down_revision = '20260316_0004'
branch_labels = None
depends_on = None


def upgrade():
    # 创建配置历史表
    op.create_table(
        'timing_config_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('config_level', sa.String(20), nullable=False),
        sa.Column('strategy_type', sa.String(50), nullable=True),
        sa.Column('strategy_instance_id', sa.Integer(), nullable=True),

        # 配置数据（JSON格式存储所有参数）
        sa.Column('config_data', postgresql.JSONB(), nullable=False),
        sa.Column('template', sa.String(50), nullable=True),

        # 元数据
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('change_reason', sa.Text(), nullable=True),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['config_id'], ['strategy_timing_configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ondelete='SET NULL')
    )

    # 创建索引
    op.create_index('idx_timing_config_history_config_id', 'timing_config_history', ['config_id'])
    op.create_index('idx_timing_config_history_strategy_type', 'timing_config_history', ['strategy_type'])
    op.create_index('idx_timing_config_history_created_at', 'timing_config_history', ['created_at'])

    # 添加template字段到strategy_timing_configs表
    op.add_column('strategy_timing_configs', sa.Column('template', sa.String(50), nullable=True))

    # 添加is_locked字段到strategy_timing_configs表（用于配置锁定）
    op.add_column('strategy_timing_configs', sa.Column('is_locked', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('strategy_timing_configs', sa.Column('locked_by', UUID(as_uuid=True), nullable=True))
    op.add_column('strategy_timing_configs', sa.Column('locked_at', sa.DateTime(), nullable=True))

    # 添加外键
    op.create_foreign_key('fk_timing_configs_locked_by', 'strategy_timing_configs', 'users', ['locked_by'], ['user_id'], ondelete='SET NULL')


def downgrade():
    # 删除外键
    op.drop_constraint('fk_timing_configs_locked_by', 'strategy_timing_configs', type_='foreignkey')

    # 删除字段
    op.drop_column('strategy_timing_configs', 'locked_at')
    op.drop_column('strategy_timing_configs', 'locked_by')
    op.drop_column('strategy_timing_configs', 'is_locked')
    op.drop_column('strategy_timing_configs', 'template')

    # 删除索引
    op.drop_index('idx_timing_config_history_created_at')
    op.drop_index('idx_timing_config_history_strategy_type')
    op.drop_index('idx_timing_config_history_config_id')

    # 删除表
    op.drop_table('timing_config_history')
