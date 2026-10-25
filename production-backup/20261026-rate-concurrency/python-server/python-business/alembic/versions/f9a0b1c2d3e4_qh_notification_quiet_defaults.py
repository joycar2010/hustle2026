"""Preserve the intentionally silent QH system templates."""

from alembic import op


revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # d7 only converts legacy audible tone keys.  These seeded templates were
    # explicitly silent in the original catalog and must remain silent after a
    # deployment that already ran d7/e8.
    op.execute(
        """
        UPDATE notification_templates
        SET sound_key = 'none'
        WHERE template_name IN ('系统通知', '资金费结算')
        """
    )


def downgrade() -> None:
    pass
