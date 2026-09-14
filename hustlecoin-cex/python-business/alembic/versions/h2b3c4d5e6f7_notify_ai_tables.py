"""Add notification_templates, notification_logs, ai_faq, ai_config tables

Revision ID: h2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-05-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h2b3c4d5e6f7'
down_revision: Union[str, None] = 'g1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notification_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('template_name', sa.String(100), nullable=False),
        sa.Column('category', sa.String(30), nullable=False, server_default='system'),
        sa.Column('title_template', sa.String(200), nullable=False, server_default=''),
        sa.Column('content_template', sa.Text(), nullable=False, server_default=''),
        sa.Column('enable_feishu', sa.Boolean(), server_default='true'),
        sa.Column('enable_email', sa.Boolean(), server_default='false'),
        sa.Column('priority', sa.Integer(), server_default='2'),
        sa.Column('cooldown_seconds', sa.Integer(), server_default='60'),
        sa.Column('is_enabled', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'notification_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('template_name', sa.String(100), nullable=True),
        sa.Column('channel', sa.String(30), nullable=False, server_default='feishu'),
        sa.Column('recipient', sa.String(200), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='sent'),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_notification_logs_created', 'notification_logs', ['created_at'])

    op.create_table(
        'ai_faq',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False, server_default='general'),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'ai_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider', sa.String(30), nullable=False, server_default='claude'),
        sa.Column('api_key', sa.String(300), nullable=True),
        sa.Column('model_name', sa.String(100), nullable=False, server_default='claude-sonnet-4-6'),
        sa.Column('temperature', sa.Float(), server_default='0.7'),
        sa.Column('max_tokens', sa.Integer(), server_default='2000'),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='false'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed default notification templates
    op.execute("""
        INSERT INTO notification_templates (template_name, category, title_template, content_template, enable_feishu, priority)
        VALUES
        ('开仓通知', 'trade', '开仓成功', '币对: {symbol}, 价差: {spread}%, 金额: {amount} USDT', true, 2),
        ('平仓通知', 'trade', '平仓完成', '币对: {symbol}, PnL: {pnl} USDT', true, 2),
        ('风控告警', 'risk', '风控预警', '风控等级: {level}, 详情: {detail}', true, 1),
        ('系统通知', 'system', '系统消息', '{message}', true, 3)
    """)


def downgrade() -> None:
    op.drop_table('ai_config')
    op.drop_table('ai_faq')
    op.drop_index('ix_notification_logs_created', 'notification_logs')
    op.drop_table('notification_logs')
    op.drop_table('notification_templates')
