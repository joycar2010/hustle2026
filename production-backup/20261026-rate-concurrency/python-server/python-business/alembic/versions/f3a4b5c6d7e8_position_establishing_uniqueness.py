"""Narrow the active Position uniqueness predicate to establishing rows only.

编号②「叠加借币」多笔独立对冲 (Path C).  The previous index
(``f0a1b2c3d4f6``) enforced *at most one non-terminal row* per
``(sub_account_id, canonical_symbol)`` — i.e. a single active tranche per
slot — which blocked a user from borrowing an independent supplementary
tranche after raising a slot's cap.

This migration rebuilds ``uq_positions_active_account_symbol`` so it covers
only *establishing* rows (the opening pipeline PENDING_BORROW →
BORROW_SUBMITTING → BORROW_OUTCOME_UNKNOWN → BORROWED(_IDLE) → HEDGING →
SPOT_SOLD, plus any unknown/future status, which fails safe as establishing).
Result: **at most one establishing row per slot**, while OPEN, every
closing-side row (CLOSING_FUTURES/FUTURES_CLOSED/CLOSING_SPOT/SPOT_BOUGHT/
PENDING_REPAY/REPAYING) and every terminal row may coexist without limit.
Over-borrow is still prevented — the cumulative per-slot cap is enforced by
``execute_borrow`` against live Binance principal, and the single-establishing
invariant guarantees a second tranche's principal is committed before a third
one can begin.

The WHERE predicate below is the SQL twin of
``engine.trading.order_executor.NON_ESTABLISHING_STATUSES`` and MUST stay in
lockstep with it byte-for-byte.

It only rebuilds the index; it never rewrites exchange-backed position rows.
Because the prior index already guaranteed at most one non-terminal row per
slot (and establishing ⊂ non-terminal), current production data cannot contain
two establishing rows for a slot, so the duplicate-safety gate below is a
belt-and-braces check that passes cleanly on today's data.

Applied manually (the repo carries multiple Alembic heads, so ``upgrade head``
is ambiguous): ``alembic upgrade f3a4b5c6d7e8``.
"""

import sqlalchemy as sa
from alembic import context, op


revision = "f3a4b5c6d7e8"
down_revision = "z3c4d5e6f7a8"
branch_labels = None
depends_on = None

# Establishing rows = every status NOT in this non-establishing allow-set.
# Keep byte-for-byte identical to
# engine.trading.order_executor.NON_ESTABLISHING_STATUSES.
_ESTABLISHING_SQL = (
    "upper(trim(coalesce(status, ''))) NOT IN "
    "('OPEN', 'CLOSING_FUTURES', 'FUTURES_CLOSED', 'CLOSING_SPOT', "
    "'SPOT_BOUGHT', 'PENDING_REPAY', 'REPAYING', 'CLOSED', 'FAILED', "
    "'CANCELLED', 'CANCELED')"
)

# The predicate installed by the previous migration (f0a1b2c3d4f6); restored on
# downgrade so a rollback re-imposes the single-active-tranche invariant.
_PRIOR_ACTIVE_SQL = (
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
            + _ESTABLISHING_SQL
        )
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        bind.execute(sa.text("DROP INDEX IF EXISTS uq_positions_active_account_symbol"))
        bind.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
                "ON positions (sub_account_id, canonical_symbol) WHERE "
                + _ESTABLISHING_SQL
            )
        )
        return

    duplicates = bind.execute(
        sa.text(
            "SELECT sub_account_id, canonical_symbol, "
            "array_agg(id ORDER BY id) AS ids "
            "FROM positions WHERE "
            + _ESTABLISHING_SQL
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
            "establishing Position duplicates require exchange reconciliation "
            f"before index rebuild: {detail}"
        )

    op.execute("DROP INDEX IF EXISTS public.uq_positions_active_account_symbol")
    op.execute(
        "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
        "ON public.positions (sub_account_id, canonical_symbol) WHERE "
        + _ESTABLISHING_SQL
    )


def downgrade() -> None:
    # Restoring the wider predicate re-imposes the single-active-tranche
    # invariant.  A slot that legitimately holds multiple coexisting tranches
    # under Path C would violate it, so a downgrade must only be attempted once
    # every slot has been reconciled back to at most one non-terminal row.
    if _is_offline_mode():
        op.execute("DROP INDEX IF EXISTS uq_positions_active_account_symbol")
        op.execute(
            "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
            "ON positions (sub_account_id, canonical_symbol) WHERE "
            + _PRIOR_ACTIVE_SQL
        )
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        bind.execute(sa.text("DROP INDEX IF EXISTS uq_positions_active_account_symbol"))
        bind.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
                "ON positions (sub_account_id, canonical_symbol) WHERE "
                + _PRIOR_ACTIVE_SQL
            )
        )
        return

    op.execute("DROP INDEX IF EXISTS public.uq_positions_active_account_symbol")
    op.execute(
        "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
        "ON public.positions (sub_account_id, canonical_symbol) WHERE "
        + _PRIOR_ACTIVE_SQL
    )
