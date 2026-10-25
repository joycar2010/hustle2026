"""Add encrypted, optional Telegram configuration for delisting monitoring.

Revision ID: ef79a1b2c3d4
Revises: ee68f0a1b2c3
"""

from alembic import context, op
import sqlalchemy as sa


revision = "ef79a1b2c3d4"
down_revision = "ee68f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``--sql`` uses Alembic's MockConnection, which intentionally has no
    # inspection API.  A linear migration is safe to render deterministically
    # here because the preceding revisions establish ``pending_blacklist``
    # and this revision is applied exactly once on a fresh schema.  Online
    # upgrades retain the idempotent inspection path below for rolling
    # deployments that may already contain one of these objects.
    if context.is_offline_mode():
        op.add_column(
            "pending_blacklist",
            sa.Column("source_event_id", sa.String(length=255), nullable=True),
        )
        op.create_table(
            "delisting_monitor_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("interval_sec", sa.Integer(), nullable=False, server_default=sa.text("30")),
            sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("telegram_api_id", sa.String(length=128), nullable=True),
            sa.Column("telegram_api_hash", sa.String(length=256), nullable=True),
            sa.Column("telegram_session", sa.String(length=4096), nullable=True),
            sa.Column("telegram_chat", sa.String(length=255), nullable=True),
            sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.execute(
            sa.text(
                "INSERT INTO delisting_monitor_config "
                "(id, enabled, interval_sec, telegram_enabled) "
                "VALUES (1, true, 30, false)"
            )
        )
        return

    # Existing installations already have pending_blacklist; retain the
    # source message identifier so repeated 30-second scans are auditable.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pending_blacklist" in inspector.get_table_names() and "source_event_id" not in {
        column["name"] for column in inspector.get_columns("pending_blacklist")
    }:
        op.add_column("pending_blacklist", sa.Column("source_event_id", sa.String(length=255), nullable=True))

    if "delisting_monitor_config" not in inspector.get_table_names():
        op.create_table(
            "delisting_monitor_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("interval_sec", sa.Integer(), nullable=False, server_default=sa.text("30")),
            sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("telegram_api_id", sa.String(length=128), nullable=True),
            sa.Column("telegram_api_hash", sa.String(length=256), nullable=True),
            sa.Column("telegram_session", sa.String(length=4096), nullable=True),
            sa.Column("telegram_chat", sa.String(length=255), nullable=True),
            sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
    # A singleton row keeps the source configuration global and avoids
    # ambiguous precedence between multiple admin records.
    op.execute(
        sa.text(
            "INSERT INTO delisting_monitor_config (id, enabled, interval_sec, telegram_enabled) "
            "SELECT 1, true, 30, false WHERE NOT EXISTS "
            "(SELECT 1 FROM delisting_monitor_config WHERE id = 1)"
        )
    )


def downgrade() -> None:
    op.drop_table("delisting_monitor_config")
    if context.is_offline_mode():
        op.drop_column("pending_blacklist", "source_event_id")
        return
    bind = op.get_bind()
    if "pending_blacklist" in sa.inspect(bind).get_table_names() and "source_event_id" in {
        column["name"] for column in sa.inspect(bind).get_columns("pending_blacklist")
    }:
        op.drop_column("pending_blacklist", "source_event_id")
