"""Scope AI FAQ entries to a product site.

Revision ID: bb88cc99dd00
Revises: aa77bb88cc99
"""
from alembic import op
import sqlalchemy as sa

revision = "bb88cc99dd00"
down_revision = "aa77bb88cc99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_faq",
        sa.Column("site", sa.String(30), nullable=False, server_default="default"),
    )
    op.create_index("ix_ai_faq_site", "ai_faq", ["site"])

    # Preserve existing shared FAQs for both product surfaces.  Future edits
    # are site-scoped and no longer leak between coin and coinadmin.
    op.execute(
        """
        INSERT INTO ai_faq (site, question, answer, category, sort_order,
                            is_active, created_at, updated_at)
        SELECT 'coin', question, answer, category, sort_order,
               is_active, created_at, updated_at
        FROM ai_faq WHERE site = 'default'
        """
    )
    op.execute(
        """
        INSERT INTO ai_faq (site, question, answer, category, sort_order,
                            is_active, created_at, updated_at)
        SELECT 'coinadmin', question, answer, category, sort_order,
               is_active, created_at, updated_at
        FROM ai_faq WHERE site = 'default'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_ai_faq_site", table_name="ai_faq")
    op.drop_column("ai_faq", "site")
