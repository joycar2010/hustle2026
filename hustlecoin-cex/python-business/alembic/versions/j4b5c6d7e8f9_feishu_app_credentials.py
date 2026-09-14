"""feishu config: add app_id, app_secret columns

Revision ID: j4b5c6d7e8f9
Revises: i3a4b5c6d7e8
"""
from alembic import op
import sqlalchemy as sa

revision = "j4b5c6d7e8f9"
down_revision = "i3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feishu_config", sa.Column("app_id", sa.String(100), server_default=""))
    op.add_column("feishu_config", sa.Column("app_secret", sa.String(200), server_default=""))


def downgrade() -> None:
    op.drop_column("feishu_config", "app_secret")
    op.drop_column("feishu_config", "app_id")
