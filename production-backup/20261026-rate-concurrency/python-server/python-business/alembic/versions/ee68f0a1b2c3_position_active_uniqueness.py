"""Enforce one non-terminal Position per account and canonical symbol.

Revision ID: ee68f0a1b2c3
Revises: dd57e9f0a1b2

The migration intentionally does not guess how to merge two rows that may
represent separate exchange-side debt/hedge legs.  It canonicalizes legacy
symbols, then aborts before creating the unique index when an active duplicate
exists.  The transaction is rolled back and the duplicate IDs are reported so
an operator can reconcile the exchange state explicitly.  Terminal history is
never rewritten.  The active predicate is deliberately case/whitespace/
NULL-safe, so legacy state spellings cannot bypass the invariant.
"""

import re

import sqlalchemy as sa
from alembic import op


revision = "ee68f0a1b2c3"
down_revision = "dd57e9f0a1b2"
branch_labels = None
depends_on = None


# Keep the terminal-state definition in one place.  ``NOT IN`` by itself is
# not safe here: SQL comparisons are case-sensitive and ``NULL NOT IN (...)``
# evaluates to UNKNOWN, which would exclude the row from a partial index.
# Treat every value other than the two explicit terminal states as active,
# including a legacy NULL/blank value.
_ACTIVE_STATUS_SQL = (
    "upper(trim(coalesce(status, ''))) NOT IN ('CLOSED', 'FAILED')"
)


def _sqlite_guard_triggers(bind) -> None:
    """Enforce the PostgreSQL ``canonical_symbol NOT NULL`` contract on SQLite.

    SQLite cannot alter an existing column to ``NOT NULL`` without rebuilding
    the whole table (which is unsafe for this financial ledger and its foreign
    keys).  A pair of aborting triggers gives the rolling/test database the
    same write-time guarantee while leaving the reflected table untouched.
    """
    bind.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_positions_canonical_symbol_required_insert
            BEFORE INSERT ON positions
            FOR EACH ROW
            WHEN NEW.canonical_symbol IS NULL
              OR trim(NEW.canonical_symbol) = ''
            BEGIN
                SELECT RAISE(ABORT, 'positions.canonical_symbol must not be null');
            END
            """
        )
    )
    bind.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_positions_canonical_symbol_required_update
            BEFORE UPDATE OF canonical_symbol ON positions
            FOR EACH ROW
            WHEN NEW.canonical_symbol IS NULL
              OR trim(NEW.canonical_symbol) = ''
            BEGIN
                SELECT RAISE(ABORT, 'positions.canonical_symbol must not be null');
            END
            """
        )
    )


def _sqlite_upgrade(bind) -> None:
    """Apply the same fail-closed migration to local/test SQLite databases.

    Production uses PostgreSQL (and the SQL below keeps its transactional
    ``DO`` duplicate report), but SQLite is used by the engine's migration and
    repository tests.  Avoid PostgreSQL-only casts/regex there while keeping
    the actual partial unique index semantics identical.
    """
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("positions")}
    if "canonical_symbol" not in columns:
        op.add_column("positions", sa.Column("canonical_symbol", sa.String(30), nullable=True))

    rows = bind.execute(sa.text("SELECT id, symbol, status FROM positions")).mappings().all()
    normalized: list[tuple[int, str, str, str, bool]] = []
    for row in rows:
        raw = str(row.get("symbol") or "").strip().upper()
        cleaned = re.sub(r"[-_\s]", "", raw)
        if re.fullmatch(r"[A-Z0-9]{1,26}USDT", cleaned):
            canonical = cleaned
        elif re.fullmatch(r"[A-Z0-9]{1,26}", cleaned):
            canonical = f"{cleaned}USDT"
        else:
            canonical = f"LEGACY-{int(row['id'])}"
        base = canonical[:-4] if not canonical.startswith("LEGACY-") else str(row.get("symbol") or "")
        active = str(row.get("status") or "").strip().upper() not in {"CLOSED", "FAILED"}
        # Keep malformed/legacy terminal or active symbols untouched in the
        # human-facing columns; their row-specific canonical key only exists
        # to make the migration deterministic and collision-free.
        rewrite = active and not canonical.startswith("LEGACY-")
        normalized.append((int(row["id"]), canonical, canonical, base, rewrite))

    for row_id, canonical, symbol, base, rewrite in normalized:
        bind.execute(
            sa.text(
                "UPDATE positions SET canonical_symbol=:canonical, "
                "symbol=CASE WHEN :rewrite THEN :symbol ELSE symbol END, "
                "base_asset=CASE WHEN :rewrite THEN :base ELSE base_asset END "
                "WHERE id=:id"
            ),
            {
                "canonical": canonical,
                "symbol": symbol,
                "base": base,
                "rewrite": rewrite,
                "id": row_id,
            },
        )

    duplicates = bind.execute(
        sa.text(
            "SELECT sub_account_id, canonical_symbol, "
            "group_concat(id, ',') AS ids "
            f"FROM positions WHERE {_ACTIVE_STATUS_SQL} "
            "GROUP BY sub_account_id, canonical_symbol HAVING count(*) > 1"
        )
    ).mappings().all()
    if duplicates:
        details = "; ".join(
            f"account={row['sub_account_id']} symbol={row['canonical_symbol']} ids={row['ids']}"
            for row in duplicates
        )
        raise RuntimeError(
            "active Position duplicates require exchange reconciliation before migration: "
            + details
        )

    # SQLite has no ``ALTER COLUMN ... SET NOT NULL``.  Keep the model
    # nullable during rolling upgrades, but reject raw NULL/blank writes with
    # triggers so a direct SQL writer cannot bypass the unique key.  Drop and
    # recreate the index to upgrade installations that may have run an older
    # version of this migration with a case-sensitive predicate.
    _sqlite_guard_triggers(bind)
    bind.execute(
        sa.text("DROP INDEX IF EXISTS uq_positions_active_account_symbol")
    )
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_positions_active_account_symbol "
            "ON positions (sub_account_id, canonical_symbol) "
            f"WHERE {_ACTIVE_STATUS_SQL}"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        _sqlite_upgrade(bind)
        return

    op.execute(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS "
        "canonical_symbol VARCHAR(30)"
    )

    # Collapse legacy spellings (BTC, btc-usdt, BTC_USDT) to the pair key used
    # by all new Position writes.  Blank/invalid legacy symbols receive a
    # row-specific quarantine key; execution never creates such a row, but it
    # must not make unrelated history collide during index creation.  Rebuild
    # the value for every row (rather than only NULL values) so a partially
    # applied/manual backfill cannot leave a non-canonical key behind.
    op.execute(
        """
        UPDATE positions AS p
        SET canonical_symbol = CASE
            WHEN normalized.cleaned ~ '^[A-Z0-9]{1,26}USDT$'
                THEN normalized.cleaned
            WHEN normalized.cleaned ~ '^[A-Z0-9]{1,26}$'
                THEN normalized.cleaned || 'USDT'
            ELSE 'LEGACY-' || p.id::text
        END
        FROM (
            SELECT id,
                   upper(regexp_replace(coalesce(trim(symbol), ''), '[-_[:space:]]', '', 'g')) AS cleaned
            FROM positions
        ) AS normalized
        WHERE p.id = normalized.id
        """
    )
    op.execute(
        """
        UPDATE positions AS p
        SET symbol = canonical_symbol,
            base_asset = regexp_replace(canonical_symbol, 'USDT$', '')
        WHERE p.canonical_symbol IS NOT NULL
          AND p.canonical_symbol NOT LIKE 'LEGACY-%'
          AND upper(trim(coalesce(p.status, ''))) NOT IN ('CLOSED', 'FAILED')
        """
    )

    # A duplicate active row may carry an independent Binance borrow, spot
    # sale, or futures hedge.  Silently picking a survivor would create a
    # financial record that is not backed by exchange state.  Fail closed with
    # the conflicting IDs; the transaction keeps the original rows untouched.
    op.execute(
        """
        DO $$
        DECLARE conflict_text text;
        BEGIN
            SELECT string_agg(
                       format('account=%s symbol=%s ids=%s', sub_account_id,
                              canonical_symbol, ids), '; '
                       ORDER BY sub_account_id, canonical_symbol
                   )
              INTO conflict_text
              FROM (
                  SELECT sub_account_id, canonical_symbol,
                         string_agg(id::text, ',' ORDER BY id) AS ids
                    FROM positions
                   WHERE upper(trim(coalesce(status, ''))) NOT IN ('CLOSED', 'FAILED')
                   GROUP BY sub_account_id, canonical_symbol
                  HAVING count(*) > 1
              ) AS duplicates;
            IF conflict_text IS NOT NULL THEN
                RAISE EXCEPTION
                    'active Position duplicates require exchange reconciliation before migration: %',
                    conflict_text;
            END IF;
        END $$;
        """
    )

    op.execute(
        "ALTER TABLE positions ALTER COLUMN canonical_symbol SET NOT NULL"
    )
    # Rebuild rather than rely on IF NOT EXISTS: this migration may be rerun
    # against a database where an earlier rolling image created the weaker,
    # case-sensitive predicate under the same index name.
    op.execute("DROP INDEX IF EXISTS uq_positions_active_account_symbol")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_positions_active_account_symbol
            ON positions (sub_account_id, canonical_symbol)
            WHERE upper(trim(coalesce(status, ''))) NOT IN ('CLOSED', 'FAILED')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_positions_active_account_symbol")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS canonical_symbol")
    elif "canonical_symbol" in {
        column["name"] for column in sa.inspect(bind).get_columns("positions")
    }:
        op.execute(
            "DROP TRIGGER IF EXISTS trg_positions_canonical_symbol_required_update"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_positions_canonical_symbol_required_insert"
        )
        op.drop_column("positions", "canonical_symbol")
