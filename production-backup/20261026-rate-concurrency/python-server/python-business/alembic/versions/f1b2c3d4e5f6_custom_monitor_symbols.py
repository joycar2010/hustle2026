"""Add tenant-scoped asymmetric spot/futures monitor mappings.

Revision ID: f1b2c3d4e5f6
Revises: f0a1b2c3d4f6
"""

import sqlalchemy as sa
from alembic import op


revision = "f1b2c3d4e5f6"
down_revision = "f0a1b2c3d4f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_monitor_symbols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("spot_symbol", sa.String(length=30), nullable=False),
        sa.Column("futures_symbol", sa.String(length=30), nullable=False),
        sa.Column("display_symbol", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_removed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=True, server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=True, server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "spot_symbol", "futures_symbol",
            name="uq_custom_monitor_user_spot_futures",
        ),
    )
    op.create_index(
        "ix_custom_monitor_symbols_user_id",
        "custom_monitor_symbols",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_custom_monitor_user_active",
        "custom_monitor_symbols",
        ["user_id", "is_active", "is_removed"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_custom_monitor_user_active", table_name="custom_monitor_symbols")
    op.drop_index("ix_custom_monitor_symbols_user_id", table_name="custom_monitor_symbols")
    op.drop_table("custom_monitor_symbols")
