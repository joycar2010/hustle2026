"""Separate inventory polling rate from borrow-submit pacing."""
from alembic import op
import sqlalchemy as sa

revision = "aa99bb00cc11"
down_revision = "y9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_probe_rate_per_sec" not in {c["name"] for c in inspector.get_columns("global_rules")}:
        op.add_column(
            "global_rules",
            sa.Column("inventory_probe_rate_per_sec", sa.Numeric(6, 2), nullable=False, server_default="3.8"),
        )
    if "inventory_probe_rate_per_sec" not in {c["name"] for c in inspector.get_columns("sub_accounts")}:
        op.add_column(
            "sub_accounts",
            sa.Column("inventory_probe_rate_per_sec", sa.Numeric(6, 2), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_probe_rate_per_sec" in {c["name"] for c in inspector.get_columns("sub_accounts")}:
        op.drop_column("sub_accounts", "inventory_probe_rate_per_sec")
    if "inventory_probe_rate_per_sec" in {c["name"] for c in inspector.get_columns("global_rules")}:
        op.drop_column("global_rules", "inventory_probe_rate_per_sec")
