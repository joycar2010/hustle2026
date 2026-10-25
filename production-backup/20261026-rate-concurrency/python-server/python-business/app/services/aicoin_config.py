"""Resolve the AiCoin credential pair used by every API consumer.

Historically the admin dashboard read only environment variables while the
market routers read the first database row.  That made the dashboard report
``not configured`` even though the market page had working credentials (and
made stale/disabled rows win over the current one).  Keep the lookup in one
place and tolerate the short period during which an older database has not
yet received the optional ``is_active``/timestamp columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, select

from app.config import settings
from app.db.models import AiCoinConfig


@dataclass(frozen=True)
class AiCoinCredentials:
    api_key: str
    api_secret: str
    source: str | None
    active_row: bool
    db_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


class AiCoinConfigStorageError(RuntimeError):
    """The configuration table cannot be read in the current schema.

    AiCoin market consumers deliberately catch this error and fall back to
    environment credentials.  Control-plane callers (the admin read/write
    endpoints) should instead expose an actionable migration error rather than
    silently reporting an empty configuration.
    """


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


_MASKED_SECRET_VALUES = frozenset({
    "****",
    "********",
    "[redacted]",
    "<redacted>",
})


def is_aicoin_masked(value: Any) -> bool:
    """Return whether a UI/storage value is a credential mask placeholder.

    Admin forms commonly submit the displayed ``****`` value back when only
    the other field changed.  Keep the comparison centralized and whitespace
    tolerant so a padded mask can never overwrite a real credential.
    """
    return _clean(value).lower() in _MASKED_SECRET_VALUES


def clean_aicoin_secret(value: Any) -> str:
    """Normalize a stored Secret and discard UI mask placeholders."""
    secret = _clean(value)
    return "" if secret.lower() in _MASKED_SECRET_VALUES else secret


def clean_aicoin_key(value: Any) -> str:
    """Normalize a stored Key and discard an accidental UI mask value."""
    key = _clean(value)
    return "" if key.lower() in _MASKED_SECRET_VALUES else key


def redact_aicoin_error(value: Any, *, limit: int = 180) -> str:
    """Bound and redact credential-bearing details from control-plane errors."""
    import re

    detail = " ".join(str(value or "").split())
    # AiCoin/client errors can echo signed query strings or request headers.
    # Keep an actionable class/message while never returning key/secret/token
    # material to the browser or persisting it in an EngineState-like field.
    detail = re.sub(
        r"(?i)(api[_-]?(?:key|secret)|access[_-]?token|signature|token)\s*[:=]\s*[^\s,&]+",
        r"\1=<redacted>",
        detail,
    )
    detail = re.sub(
        r"(?i)([?&](?:api[_-]?(?:key|secret)|access[_-]?token|signature|token)=)[^&\s]+",
        r"\1<redacted>",
        detail,
    )
    if len(detail) > limit:
        detail = detail[: max(0, limit - 3)] + "..."
    return detail


def _is_active(value: Any) -> bool:
    # A NULL value in a legacy row means "not yet migrated", so preserve the
    # old behavior and treat it as active.  Explicit false values remain off.
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no"}
    return bool(value)


def read_aicoin_config_rows(db) -> tuple[list[dict[str, Any]], frozenset[str]]:
    """Read AiCoin rows without selecting columns absent from an old schema.

    Some deployments created ``aicoin_config`` before ``is_active``,
    ``created_at`` and ``updated_at`` were added to the ORM model.  A normal
    ORM query emits ``SELECT`` for every mapped column and consequently fails
    on those deployments.  Inspect the live table and issue a Core query for
    only the columns that are actually present.  The returned column set is
    also used by the admin writer to avoid emitting updates for absent fields.

    ``AiCoinConfigStorageError`` is intentionally distinct from an empty table
    so callers can decide whether to fail closed or use environment fallback.
    """
    try:
        bind = db.get_bind()
        inspector = inspect(bind)
        names = frozenset(
            column["name"]
            for column in inspector.get_columns(AiCoinConfig.__tablename__)
        )
        required = {"id", "api_key", "api_secret"}
        if not required.issubset(names):
            missing = ", ".join(sorted(required - names)) or "table"
            raise AiCoinConfigStorageError(
                f"aicoin_config is missing required columns: {missing}"
            )

        table = AiCoinConfig.__table__
        columns = [table.c.id, table.c.api_key, table.c.api_secret]
        if "is_active" in names:
            columns.append(table.c.is_active)
        if "updated_at" in names:
            columns.append(table.c.updated_at)

        rows = [dict(row._mapping) for row in db.execute(select(*columns)).all()]
        # ``updated_at`` can be NULL for a legacy row.  ID is a deterministic
        # tie-breaker and is always present.
        def sort_key(row: dict[str, Any]) -> tuple[int, str, int]:
            value = row.get("updated_at")
            if value is None:
                stamp = ""
                present = 0
            elif hasattr(value, "isoformat"):
                stamp = value.isoformat()
                present = 1
            else:
                stamp = str(value)
                present = 1
            return present, stamp, int(row.get("id") or 0)

        rows.sort(key=sort_key, reverse=True)
        return rows, names
    except AiCoinConfigStorageError:
        raise
    except Exception as exc:  # noqa: BLE001 - caller decides fallback policy
        raise AiCoinConfigStorageError(str(exc)[:200]) from exc


def _database_candidates(db) -> tuple[list[dict[str, Any]], str | None]:
    """Compatibility wrapper used by the runtime resolver."""
    try:
        rows, _ = read_aicoin_config_rows(db)
        return rows, None
    except Exception as exc:  # noqa: BLE001 - retain environment fallback
        return [], str(exc)[:200]


def choose_active_aicoin_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose the newest complete active pair, then an active partial row."""
    partial: dict[str, Any] | None = None
    for row in rows:
        if not _is_active(row.get("is_active")):
            continue
        key = clean_aicoin_key(row.get("api_key"))
        secret = clean_aicoin_secret(row.get("api_secret"))
        if key and secret:
            return row
        if partial is None and (key or secret):
            partial = row
    return partial


def resolve_aicoin_credentials(db=None) -> AiCoinCredentials:
    """Return one coherent key/secret pair.

    A complete active database pair wins over environment values.  A partial
    database pair is returned as-is (and therefore remains visibly incomplete)
    instead of mixing a key from one source with a secret from another.  When
    no usable database row exists, the deployment environment is used.
    """
    owned_db = db is None
    db_error = None
    rows: list[dict[str, Any]] = []
    if owned_db:
        try:
            from app.db.session import SessionLocal

            db = SessionLocal()
        except Exception as exc:  # noqa: BLE001
            db = None
            db_error = str(exc)[:200]

    if db is not None:
        try:
            rows, db_error = _database_candidates(db)
        finally:
            if owned_db:
                try:
                    db.close()
                except Exception:
                    pass

    row = choose_active_aicoin_row(rows)
    if row is not None:
        key = clean_aicoin_key(row.get("api_key"))
        secret = clean_aicoin_secret(row.get("api_secret"))
        return AiCoinCredentials(
            key, secret, "database", True, db_error,
        )

    key = clean_aicoin_key(getattr(settings, "aicoin_api_key", ""))
    secret = clean_aicoin_secret(getattr(settings, "aicoin_api_secret", ""))
    return AiCoinCredentials(
        key,
        secret,
        "environment" if (key or secret) else None,
        False,
        db_error,
    )


__all__ = [
    "AiCoinConfigStorageError",
    "AiCoinCredentials",
    "clean_aicoin_key",
    "clean_aicoin_secret",
    "is_aicoin_masked",
    "redact_aicoin_error",
    "choose_active_aicoin_row",
    "read_aicoin_config_rows",
    "resolve_aicoin_credentials",
]
