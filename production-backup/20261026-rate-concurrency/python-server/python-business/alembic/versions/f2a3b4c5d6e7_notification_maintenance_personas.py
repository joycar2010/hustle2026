"""Add notification-centre maintenance state and voice personas.

Revision ID: f2a3b4c5d6e7
Revises: f1b2c3d4e5f6

This revision is additive and deliberately tolerant of schemas created by an
older notification rollout.  In particular, production may already contain a
``notification_maintenance`` table without ``created_at`` (and with shorter
varchar limits).  The online path adds only missing columns and widens string
columns when the database can do so safely; it never drops or narrows legacy
data.
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "f1b2c3d4e5f6"
branch_labels = None
depends_on = None


# A downgrade may run in a fresh process, after the upgrade process has exited.
# Keep this marker only as a best-effort hint: when it is absent we retain
# pre-existing tables instead of risking deletion of an older installation's
# data.  Fresh same-process tests still get a complete reversible migration.
_CREATED_BY_THIS_MIGRATION: set[str] = set()


def _maintenance_columns(*, nullable: bool) -> tuple[sa.Column, ...]:
    return (
        sa.Column("enabled", sa.Boolean(), nullable=nullable, server_default=sa.text("false")),
        sa.Column("stop_strategy", sa.Boolean(), nullable=nullable, server_default=sa.text("true")),
        sa.Column("block_trading", sa.Boolean(), nullable=nullable, server_default=sa.text("true")),
        sa.Column("block_login", sa.Boolean(), nullable=nullable, server_default=sa.text("false")),
        sa.Column("title", sa.String(length=120), nullable=nullable, server_default=sa.text("'系统维护中'")),
        sa.Column("content", sa.Text(), nullable=nullable, server_default=sa.text("''")),
        sa.Column("until_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )


def _persona_columns(*, nullable: bool) -> tuple[sa.Column, ...]:
    return (
        sa.Column("name", sa.String(length=60), nullable=nullable, server_default=sa.text("''")),
        sa.Column(
            "voice", sa.String(length=80), nullable=nullable,
            server_default=sa.text("'zh-CN-XiaoxiaoNeural'"),
        ),
        sa.Column("style", sa.String(length=120), nullable=nullable, server_default=sa.text("''")),
        sa.Column("rate_pct", sa.Integer(), nullable=nullable, server_default=sa.text("0")),
        sa.Column("pitch_pct", sa.Integer(), nullable=nullable, server_default=sa.text("0")),
        sa.Column("sample", sa.String(length=300), nullable=nullable, server_default=sa.text("''")),
        sa.Column("is_enabled", sa.Boolean(), nullable=nullable, server_default=sa.text("true")),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )


def _create_maintenance_table() -> None:
    op.create_table(
        "notification_maintenance",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_maintenance_columns(nullable=False),
    )
    _CREATED_BY_THIS_MIGRATION.add("notification_maintenance")


def _create_persona_table() -> None:
    op.create_table(
        "notification_sound_personas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skey", sa.String(length=40), nullable=False),
        *_persona_columns(nullable=False),
        sa.UniqueConstraint("skey", name="uq_notification_sound_personas_skey"),
    )
    _CREATED_BY_THIS_MIGRATION.add("notification_sound_personas")


def _columns(bind, table_name: str) -> dict[str, dict]:
    """Return inspector column metadata, or an empty map for absent tables."""
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return {}
    return {item["name"]: item for item in inspector.get_columns(table_name)}


def _add_missing_columns(bind, table_name: str, columns: tuple[sa.Column, ...]) -> None:
    """Add only columns absent from a legacy table.

    A fresh inspector is intentionally not reused after each ALTER because
    SQLAlchemy caches inspector results.  Updating the local map keeps this
    helper idempotent even when two legacy columns are missing.
    """
    existing = _columns(bind, table_name)
    if not existing:
        return
    for column in columns:
        if column.name in existing:
            continue
        # SQLite rejects ``ALTER TABLE ... ADD COLUMN`` when the default is a
        # non-constant expression such as CURRENT_TIMESTAMP.  Add the column
        # without that default there, then backfill existing rows below.  Other
        # production dialects keep the server default for future inserts.
        add_column = column
        if (
            getattr(getattr(bind, "dialect", None), "name", "") == "sqlite"
            and isinstance(column.type, sa.DateTime)
            and column.server_default is not None
        ):
            add_column = sa.Column(column.name, column.type, nullable=True)
        op.add_column(table_name, add_column)
        if isinstance(column.type, sa.DateTime) and column.server_default is not None:
            # Use a controlled identifier set (all names come from this
            # migration) rather than interpolating user input into SQL.
            op.execute(
                sa.text(
                    f'UPDATE "{table_name}" SET "{column.name}" = CURRENT_TIMESTAMP '
                    f'WHERE "{column.name}" IS NULL'
                )
            )
        existing[column.name] = {"name": column.name, "type": column.type, "nullable": column.nullable}


def _maybe_widen_strings(bind, table_name: str, target_lengths: dict[str, int]) -> None:
    """Widen too-short varchar columns without ever narrowing or rewriting data.

    PostgreSQL/MySQL support an in-place type widening through Alembic.  SQLite
    cannot alter a column type without rebuilding the whole table, so it is
    intentionally left unchanged; API input is bounded to the model's limits
    and legacy SQLite installations remain usable.  TEXT/unbounded columns are
    already wider and are left alone.
    """
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect not in {"postgresql", "mysql", "mariadb"}:
        return
    existing = _columns(bind, table_name)
    if not existing:
        return
    for name, target in target_lengths.items():
        info = existing.get(name)
        if not info:
            continue
        current_type = info.get("type")
        current_len = getattr(current_type, "length", None)
        if current_len is None or current_len >= target:
            continue
        # Only widen character types.  A dialect may report a numeric/text
        # type with a synthetic ``length`` attribute; checking the class name
        # avoids an invalid ALTER on such columns.
        type_name = str(getattr(current_type, "__visit_name__", "")).lower()
        if type_name not in {"string", "varchar", "char"}:
            continue
        op.alter_column(
            table_name,
            name,
            existing_type=current_type,
            type_=sa.String(length=target),
            existing_nullable=info.get("nullable"),
            existing_server_default=info.get("default"),
        )


def _ensure_legacy_shape(bind) -> None:
    """Upgrade already-created notification tables without duplicate CREATEs."""
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notification_maintenance" in tables:
        # Existing rows are populated, so newly-added columns stay nullable.
        _add_missing_columns(bind, "notification_maintenance", _maintenance_columns(nullable=True))
        _maybe_widen_strings(
            bind,
            "notification_maintenance",
            {"title": 120, "updated_by": 100},
        )

    if "notification_sound_personas" in tables:
        # ``skey`` is the only required identity column.  A very old staging
        # table may have omitted it; add a nullable column and let the seed
        # rows establish the canonical values without deleting old rows.
        _add_missing_columns(
            bind,
            "notification_sound_personas",
            (sa.Column("skey", sa.String(length=40), nullable=True),)
            + _persona_columns(nullable=True),
        )
        _maybe_widen_strings(
            bind,
            "notification_sound_personas",
            {"skey": 40, "name": 60, "voice": 80, "style": 120, "sample": 300, "updated_by": 100},
        )


def _add_template_persona_column(bind) -> None:
    existing = _columns(bind, "notification_templates")
    if existing and "sound_persona_key" not in existing:
        op.add_column(
            "notification_templates",
            sa.Column("sound_persona_key", sa.String(length=40), nullable=True),
        )
    _maybe_widen_strings(bind, "notification_templates", {"sound_persona_key": 40})


def upgrade() -> None:
    # A test runner or an operator may invoke upgrade more than once in the
    # same interpreter.  Provenance must describe this invocation only; stale
    # markers from an earlier run must never make a legacy table droppable.
    _CREATED_BY_THIS_MIGRATION.clear()
    if context.is_offline_mode():
        # Offline SQL is generated for a fresh linear schema; inspection is
        # unavailable on Alembic's MockConnection.
        _create_maintenance_table()
        _create_persona_table()
        op.add_column(
            "notification_templates",
            sa.Column("sound_persona_key", sa.String(length=40), nullable=True),
        )
    else:
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        tables = set(inspector.get_table_names())
        if "notification_maintenance" not in tables:
            _create_maintenance_table()
        if "notification_sound_personas" not in tables:
            _create_persona_table()
        # Re-inspect after CREATEs.  This call is harmless for fresh tables and
        # repairs partially-created legacy tables without duplicate CREATEs.
        _ensure_legacy_shape(bind)
        _add_template_persona_column(bind)

    # Seed the singleton and the two recommended Chinese female personas.  The
    # INSERT ... SELECT form is portable across PostgreSQL and SQLite and is
    # idempotent on a partially migrated database.
    op.execute(
        sa.text(
            "INSERT INTO notification_maintenance "
            "(id, enabled, stop_strategy, block_trading, block_login, title, content, created_at, updated_at) "
            "SELECT 1, false, true, true, false, '系统维护中', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM notification_maintenance WHERE id = 1)"
        )
    )
    for skey, name, voice, style, rate, pitch, sample in (
        (
            "sweet", "甜妹", "zh-CN-XiaoyiNeural",
            "甜美、亲和、适合交易成功与普通通知", 4, 8,
            "亲，交易信号已更新，请及时查看。",
        ),
        (
            "yujie", "御姐", "zh-CN-XiaoxiaoNeural",
            "沉稳、清晰、适合风险与维护告警", -2, -4,
            "请注意，系统检测到一项需要处理的风险告警。",
        ),
    ):
        op.execute(
            sa.text(
                "INSERT INTO notification_sound_personas "
                "(skey, name, voice, style, rate_pct, pitch_pct, sample) "
                "SELECT :skey, :name, :voice, :style, :rate, :pitch, :sample "
                "WHERE NOT EXISTS (SELECT 1 FROM notification_sound_personas WHERE skey = :skey)"
            ).bindparams(
                skey=skey, name=name, voice=voice, style=style,
                rate=rate, pitch=pitch, sample=sample,
            )
        )

    op.execute(
        sa.text(
            "UPDATE notification_templates SET sound_persona_key = "
            "CASE WHEN lower(category) = 'risk' THEN 'yujie' "
            "WHEN lower(category) IN ('trade', 'marketing') THEN 'sweet' "
            "ELSE 'yujie' END "
            "WHERE sound_persona_key IS NULL"
        )
    )


def _table_exists(bind, table_name: str) -> bool:
    return table_name in set(sa.inspect(bind).get_table_names())


def downgrade() -> None:
    """Revert objects created by this revision without deleting legacy tables.

    Alembic may execute downgrade in a different process from upgrade, so the
    in-memory creation marker is absent in real rollback scenarios.  In that
    case all pre-existing tables are retained and only the f2-owned template
    column is removed.  This is intentionally conservative for production.
    """
    if context.is_offline_mode():
        # Offline SQL has no live schema to tell whether either table was
        # created by this revision or by an older staging rollout.  Emitting
        # unconditional DROP statements would therefore be destructive when
        # an operator reviews/applies a rollback script against a mixed
        # installation.  Without inspection we cannot prove that even the
        # template column belongs to this revision, so emit no destructive SQL.
        return

    bind = op.get_bind()
    if _table_exists(bind, "notification_templates"):
        cols = _columns(bind, "notification_templates")
        if "sound_persona_key" in cols:
            op.drop_column("notification_templates", "sound_persona_key")
    # Never drop a table unless this process created it during upgrade.  A
    # pre-existing table may contain user-maintained notifications/personas.
    for table_name in ("notification_sound_personas", "notification_maintenance"):
        if table_name in _CREATED_BY_THIS_MIGRATION and _table_exists(bind, table_name):
            op.drop_table(table_name)
