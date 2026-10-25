"""Scope AI FAQ knowledge entries by site.

Existing rows remain in the legacy ``default`` bucket and are copied to both
first-class sites so an upgrade does not remove the current knowledge base.
"""

from alembic import op
import sqlalchemy as sa


revision = "z2b3c4d5e6f7"
# Merge the two existing heads (the main f2 chain and the early-borrow z1
# chain) while applying this schema change once.
down_revision = ("f2a3b4c5d6e7", "z1a2b3c4d5e6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("ai_faq")}
    if "site" not in columns:
        op.add_column(
            "ai_faq",
            sa.Column("site", sa.String(length=30), nullable=False, server_default="default"),
        )
        op.create_index("ix_ai_faq_site", "ai_faq", ["site"])

    # Idempotent copy: each source default row gets one row per site.  The
    # PostgreSQL and SQLite forms below both avoid duplicate copies on retry.
    for site in ("coin", "coinadmin"):
        op.execute(sa.text(
            "INSERT INTO ai_faq (site, question, answer, category, sort_order, is_active) "
            "SELECT :site, question, answer, category, sort_order, is_active "
            "FROM ai_faq src WHERE src.site = 'default' "
            "AND NOT EXISTS (SELECT 1 FROM ai_faq dst WHERE dst.site = :site "
            "AND dst.question = src.question AND dst.answer = src.answer)"
        ).bindparams(site=site))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("ai_faq")}
    if "site" in columns:
        op.drop_index("ix_ai_faq_site", table_name="ai_faq")
        op.drop_column("ai_faq", "site")
