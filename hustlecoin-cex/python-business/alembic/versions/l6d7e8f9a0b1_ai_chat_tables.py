"""ai chat tables and config site column

Revision ID: l6d7e8f9a0b1
Revises: k5c6d7e8f9a0
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "l6d7e8f9a0b1"
down_revision = "k5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_config", sa.Column("site", sa.String(30), nullable=False, server_default="default"))
    op.add_column("ai_config", sa.Column("rate_limit_per_min", sa.Integer(), nullable=True, server_default="10"))
    op.create_unique_constraint("uq_ai_config_site", "ai_config", ["site"])

    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(30), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default="0"),
        sa.Column("token_used", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
    op.drop_constraint("uq_ai_config_site", "ai_config", type_="unique")
    op.drop_column("ai_config", "rate_limit_per_min")
    op.drop_column("ai_config", "site")
