"""Strengthen the active Position uniqueness predicate.

Production is already at ``f0a1b2c3d4e5``. This migration is intentionally
linear from that revision and only rebuilds the existing index; it does not
rewrite exchange-backed position rows.
"""

import sqlalchemy as sa
from alembic import context, op


revision = "f0a1b2c3d4f6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

_ACTIVE_SQL = (
    "upper(trim(coalesce(status, ''))) NOT IN "
    "('CLOSED', 'FAILED', 'CANCELLED', 'CANCELED')"
)


def _is_offline_mode() -> bool:
    """Avoid online duplicate probes when Alembic renders ``--sql``.

    The migration is also imported directly by unit tests, where Alembic's
    context proxy is not active.  In that case the normal online path is the
    correct fallback.
    """
    try:
        return bool(context.is_offline_mode())
    except (NameError, RuntimeError):
        return False


def upgrade() -> None:
    if _is_offline_mode():
        # Offline rendering has no result set to inspect for duplicates.  The
        # online deployment gate below still performs that safety check before
        # creating the same index.  Keep the SQL schema/dialect neutral so the
        # generated script is usable for PostgreSQL and SQLite.
        op.execute("DROP INDEX IF EXISTS uq_positions_active_account_symbol")
        op.execute(
            "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
            "ON positions (sub_account_id, canonical_symbol) WHERE "
            + _ACTIVE_SQL
        )
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        bind.execute(sa.text("DROP INDEX IF EXISTS uq_positions_active_account_symbol"))
        bind.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
                "ON positions (sub_account_id, canonical_symbol) WHERE "
                + _ACTIVE_SQL
            )
        )
        return

    duplicates = bind.execute(
        sa.text(
            "SELECT sub_account_id, canonical_symbol, "
            "array_agg(id ORDER BY id) AS ids "
            "FROM positions WHERE "
            + _ACTIVE_SQL
            + " GROUP BY sub_account_id, canonical_symbol HAVING count(*) > 1"
        )
    ).mappings().all()
    if duplicates:
        detail = "; ".join(
            f"account={row['sub_account_id']} symbol={row['canonical_symbol']} "
            f"ids={row['ids']}"
            for row in duplicates
        )
        raise RuntimeError(
            "active Position duplicates require exchange reconciliation before "
            f"index rebuild: {detail}"
        )

    op.execute("DROP INDEX IF EXISTS public.uq_positions_active_account_symbol")
    op.execute(
        "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
        "ON public.positions (sub_account_id, canonical_symbol) WHERE "
        + _ACTIVE_SQL
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_positions_active_account_symbol")
    op.execute(
        "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
        "ON public.positions (sub_account_id, canonical_symbol) WHERE "
        "upper(trim(coalesce(status, ''))) NOT IN ('CLOSED', 'FAILED')"
    )
