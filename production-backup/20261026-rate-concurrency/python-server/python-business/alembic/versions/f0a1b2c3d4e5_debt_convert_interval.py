"""Set the residual-debt conversion default to thirty minutes.

The old application default was six hours (21600 seconds).  Rows carrying
that old hard-coded value are migrated to the new default; an operator can
still choose another cadence afterward through the fund-rules API.  The
conversion worker remains fail-closed for every non-terminal Position, so a
shorter maintenance interval cannot touch an active or unresolved lifecycle.
"""

from alembic import context, op
import sqlalchemy as sa


revision = "f0a1b2c3d4e5"
down_revision = "ef79a1b2c3d4"
branch_labels = None
depends_on = None


_NEW_DEFAULT = 1800
_LEGACY_DEFAULT = 21600


def _is_offline_mode() -> bool:
    """Read Alembic's offline flag without requiring an active proxy.

    Migration unit tests invoke ``upgrade`` with an ``Operations`` object
    directly, outside Alembic's ``EnvironmentContext``.  In that case the
    context proxy raises ``NameError``; treating it as online preserves the
    normal inspected/batch-alter path while ``--sql`` still gets the explicit
    offline DDL below.
    """
    try:
        return bool(context.is_offline_mode())
    except (NameError, RuntimeError):
        return False


def _normalize_existing_rows(bind) -> None:
    """Move NULL/legacy-default rows without touching other overrides."""
    bind.execute(
        sa.text(
            "UPDATE fund_rules "
            "SET debt_convert_interval_sec = :new_default "
            "WHERE debt_convert_interval_sec IS NULL "
            "   OR debt_convert_interval_sec = :legacy_default"
        ),
        {"new_default": _NEW_DEFAULT, "legacy_default": _LEGACY_DEFAULT},
    )


def _normalize_existing_rows_offline() -> None:
    """Render literal values for ``alembic upgrade --sql``.

    Bound parameters are intentionally not used here: Alembic's offline
    renderer has no live bind and would otherwise emit ``NULL`` literals,
    producing a script that silently fails to normalize legacy rows.
    """
    op.execute(
        "UPDATE fund_rules "
        f"SET debt_convert_interval_sec = {_NEW_DEFAULT} "
        "WHERE debt_convert_interval_sec IS NULL "
        f"OR debt_convert_interval_sec = {_LEGACY_DEFAULT}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _is_offline_mode():
        # MockConnection has no inspection API.  At this linear revision the
        # table and column are guaranteed by the preceding schema migrations,
        # so render the deterministic update/default statements directly.
        _normalize_existing_rows_offline()
        op.execute(
            "ALTER TABLE fund_rules ALTER COLUMN debt_convert_interval_sec "
            f"SET DEFAULT {_NEW_DEFAULT}"
        )
        return
    if "fund_rules" not in sa.inspect(bind).get_table_names():
        return

    _normalize_existing_rows(bind)

    if bind.dialect.name == "sqlite":
        # SQLite has no ALTER COLUMN syntax; Alembic's batch implementation
        # rebuilds the table while preserving existing columns/constraints.
        with op.batch_alter_table("fund_rules") as batch:
            batch.alter_column(
                "debt_convert_interval_sec",
                existing_type=sa.Integer(),
                existing_nullable=True,
                server_default=sa.text(str(_NEW_DEFAULT)),
            )
        return

    op.execute(
        "ALTER TABLE fund_rules ALTER COLUMN debt_convert_interval_sec "
        f"SET DEFAULT {_NEW_DEFAULT}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _is_offline_mode():
        op.execute(
            "ALTER TABLE fund_rules ALTER COLUMN debt_convert_interval_sec "
            f"SET DEFAULT {_LEGACY_DEFAULT}"
        )
        return
    if "fund_rules" not in sa.inspect(bind).get_table_names():
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("fund_rules") as batch:
            batch.alter_column(
                "debt_convert_interval_sec",
                existing_type=sa.Integer(),
                existing_nullable=True,
                server_default=sa.text(str(_LEGACY_DEFAULT)),
            )
        return

    op.execute(
        "ALTER TABLE fund_rules ALTER COLUMN debt_convert_interval_sec "
        f"SET DEFAULT {_LEGACY_DEFAULT}"
    )
