"""HTTP read APIs for the early-borrow suggestion feed."""

import json
import math
from datetime import datetime, timedelta, timezone
from itertools import islice

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only

from app.db.models_early_borrow import (
    EarlyBorrowCandidate,
    EarlyBorrowCase,
    EarlyBorrowConfig,
    EarlyBorrowFeature,
    EarlyBorrowTick,
)
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id, require_admin
from app.services.early_borrow_service import early_borrow_service

router = APIRouter(prefix="/api/early-borrow", tags=["early-borrow"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _config_payload(row: EarlyBorrowConfig) -> dict:
    # A rolling deployment can briefly expose a row created by an older
    # migration with nullable/default-less fields.  Keep the read endpoint
    # total and use the same defaults as the background collector instead of
    # failing the whole monitor request on ``float(None)``.
    def number(name: str, default: float) -> float:
        value = getattr(row, name, None)
        try:
            parsed = float(default if value is None else value)
            return parsed if math.isfinite(parsed) else float(default)
        except (TypeError, ValueError, OverflowError):
            return float(default)

    def integer(name: str, default: int) -> int:
        value = getattr(row, name, None)
        try:
            return int(default if value is None else value)
        except (TypeError, ValueError, OverflowError):
            return int(default)

    warning_spread = number("warning_spread_pct", 0.8)
    candidate_spread = number("candidate_spread_pct", 0.45)
    trigger_spread = number("trigger_spread_pct", 1.0)
    open_spread = number("open_spread_pct", 0.5)
    open_buffer = max(0.0, number("open_spread_buffer_pct", 0.05))
    return {
        "enabled": bool(row.enabled if row.enabled is not None else True),
        "sample_interval_sec": max(1, min(60, integer("sample_interval_sec", 2))),
        "metrics_interval_sec": max(60, min(3600, integer("metrics_interval_sec", 300))),
        "lookback_hours": max(1, min(12, integer("lookback_hours", 6))),
        "warning_spread_pct": warning_spread,
        "candidate_spread_pct": candidate_spread,
        "trigger_spread_pct": trigger_spread,
        "open_spread_pct": open_spread,
        "open_spread_buffer_pct": open_buffer,
        "effective_candidate_spread_pct": candidate_spread + open_buffer,
        "similarity_threshold": min(1.0, max(0.0, number("similarity_threshold", 0.85))),
        "notification_cooldown_sec": max(60, min(86400, integer("notification_cooldown_sec", 1800))),
        "retention_days": max(1, min(90, integer("retention_days", 7))),
        "read_only": True,
    }


def _ensure_config(db: Session) -> EarlyBorrowConfig:
    row = db.query(EarlyBorrowConfig).order_by(EarlyBorrowConfig.id).first()
    if row is None:
        row = EarlyBorrowConfig()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _candidate_expired(row: EarlyBorrowCandidate, now: datetime) -> bool:
    """Return the effective expiry without mutating a read-only GET path."""
    expires_at = row.expires_at
    if not expires_at:
        return False
    # SQLite test/dev sessions may return naive datetimes while PostgreSQL
    # returns aware values.  Treat the former as UTC, matching ``_now``.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _candidate_query_for_status(query, status: str, now: datetime):
    """Apply status semantics without an UPDATE/COMMIT on every dashboard read."""
    if status == "recent":
        # Include active suggestions and their expired counterparts.  Rows
        # explicitly dismissed remain hidden, as before.
        return query.filter(EarlyBorrowCandidate.status.in_(("suggested", "expired")))
    if status == "suggested":
        return query.filter(
            EarlyBorrowCandidate.status == "suggested",
            or_(
                EarlyBorrowCandidate.expires_at.is_(None),
                EarlyBorrowCandidate.expires_at > now,
            ),
        )
    if status == "expired":
        return query.filter(or_(
            EarlyBorrowCandidate.status == "expired",
            and_(
                EarlyBorrowCandidate.status == "suggested",
                EarlyBorrowCandidate.expires_at.isnot(None),
                EarlyBorrowCandidate.expires_at <= now,
            ),
        ))
    if status != "all":
        return query.filter(EarlyBorrowCandidate.status == status)
    return query


def _high_volume_counts(db: Session) -> tuple[int, int, bool]:
    """Return cheap Tick/Feature counts and whether they are estimates.

    PostgreSQL's table statistics are sufficient for this operational status
    view and avoid sequential scans over the continuously growing collector
    tables. SQLite and other development databases retain exact counts.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return (
            db.query(func.count(EarlyBorrowTick.id)).scalar() or 0,
            db.query(func.count(EarlyBorrowFeature.id)).scalar() or 0,
            False,
        )

    try:
        rows = db.execute(
            text(
                """
                SELECT c.relname,
                       GREATEST(COALESCE(s.n_live_tup, c.reltuples, 0), 0)::bigint AS row_count
                  FROM pg_class AS c
             LEFT JOIN pg_stat_user_tables AS s ON s.relid = c.oid
                 WHERE c.oid IN (to_regclass(:tick_table), to_regclass(:feature_table))
                """
            ),
            {
                "tick_table": EarlyBorrowTick.__tablename__,
                "feature_table": EarlyBorrowFeature.__tablename__,
            },
        ).all()
        counts = {str(row[0]): int(row[1] or 0) for row in rows}
        return (
            counts.get(EarlyBorrowTick.__tablename__, 0),
            counts.get(EarlyBorrowFeature.__tablename__, 0),
            True,
        )
    except SQLAlchemyError:
        # Never fall back to an expensive exact count on the production path.
        # A transient catalog failure should degrade an informational counter,
        # not make the whole monitor tab time out.
        db.rollback()
        return 0, 0, True


def _warning_items(limit: int = 100) -> list[dict]:
    """Read the short-lived warning feed shared with the WS marquee.

    Warnings are intentionally not ``EarlyBorrowCandidate`` rows: they are a
    threshold notification only and must never satisfy or suppress a case
    match.  The service stores their payload in the existing de-duplication
    keys, so this read path needs no trading tables or user/account state.
    Older keys contain ``"1"``; those remain readable as symbol-only records
    until their cooldown expires.
    """
    redis = None
    try:
        import redis as redis_lib
        from app.config import settings

        redis = redis_lib.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        rows: list[dict] = []
        now = _now()
        # SCAN is deliberately bounded, but reading each key with individual
        # TTL/GET round trips made this endpoint scale as 2*N network RTTs
        # (and could consume the five-second browser deadline when many
        # symbols crossed the warning line).  Keep the bounded key list, then
        # fetch both values in one non-transactional pipeline round trip.
        keys = list(islice(
            redis.scan_iter(match="early_borrow:warning:*", count=max(50, limit)),
            max(1, limit),
        ))
        payloads: list[tuple[int, object]] = []
        pipeline_factory = getattr(redis, "pipeline", None)
        if keys and callable(pipeline_factory):
            pipe = pipeline_factory(transaction=False)
            for key in keys:
                pipe.ttl(key)
                pipe.get(key)
            values = pipe.execute()
            # A healthy redis-py pipeline returns exactly two values per key.
            # Treat a malformed response as an outage instead of silently
            # pairing values with the wrong symbols.
            if len(values) != len(keys) * 2:
                raise RuntimeError("invalid early-borrow warning pipeline response")
            payloads = [
                (int(values[index] or 0), values[index + 1])
                for index in range(0, len(values), 2)
            ]
        else:
            # Compatibility for minimal Redis test doubles and older clients
            # without Pipeline.  Production redis-py always takes the branch
            # above, so this path is intentionally simple and bounded.
            payloads = [(int(redis.ttl(key) or 0), redis.get(key)) for key in keys]

        for key, (ttl, raw) in zip(keys, payloads):
            symbol = key.rsplit(":", 1)[-1].upper()
            payload: dict = {}
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        payload = parsed
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            if payload.get("symbol"):
                symbol = str(payload["symbol"]).upper()
            # A legacy lock has no event timestamp.  Estimate it from its
            # remaining TTL so it still appears in the monitor immediately.
            detected_at = payload.get("detected_at")
            if not detected_at:
                detected_at = (now - timedelta(seconds=max(0, 1800 - max(ttl, 0)))).isoformat()
            expires_at = payload.get("expires_at") or (
                now + timedelta(seconds=max(0, ttl))
            ).isoformat()
            spread = payload.get("spread")
            try:
                spread = float(spread) if spread is not None else None
            except (TypeError, ValueError):
                spread = None
            rows.append({
                "id": f"warning:{symbol}",
                "symbol": symbol,
                "detected_at": detected_at,
                "current_spread": spread,
                "status": "warning",
                "expires_at": expires_at,
                "note": "点差预警仅发送提醒，不自动借币、不自动开仓",
                "read_only": True,
            })
        rows.sort(key=lambda item: str(item.get("detected_at") or ""), reverse=True)
        return rows[: max(1, limit)]
    except Exception:
        # A Redis outage must not hide the candidate table or leave the tab
        # spinning.  The WS path will still deliver a live warning on retry.
        return []
    finally:
        # Pipeline/SCAN failures can happen before the normal return.  Always
        # release this short-lived client so repeated tab opens do not leak a
        # socket or exhaust the Redis pool.
        if redis is not None:
            try:
                redis.close()
            except Exception:
                pass


@router.get("/candidates")
def list_candidates(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    status: str = Query("recent", pattern="^(suggested|dismissed|expired|recent|all)$"),
    compact: bool = Query(False),
):
    """Return the independent dashboard suggestion list.

    This endpoint deliberately does not call the existing push-symbol API.
    A client can therefore inspect or dismiss a suggestion without adding a
    live trading symbol to any Worker account.
    """
    get_current_user_id(request)
    now = _now()
    query = db.query(EarlyBorrowCandidate)
    query = _candidate_query_for_status(query, status, now)
    if compact:
        query = query.options(load_only(
            EarlyBorrowCandidate.id,
            EarlyBorrowCandidate.symbol,
            EarlyBorrowCandidate.detected_at,
            EarlyBorrowCandidate.current_spread,
            EarlyBorrowCandidate.similarity_score,
            EarlyBorrowCandidate.estimated_hit_rate,
            EarlyBorrowCandidate.matched_case_count,
            EarlyBorrowCandidate.case_id,
            EarlyBorrowCandidate.status,
            EarlyBorrowCandidate.notified_at,
            EarlyBorrowCandidate.expires_at,
            EarlyBorrowCandidate.note,
        ))
    rows = query.order_by(EarlyBorrowCandidate.detected_at.desc()).limit(limit).all()

    items = []
    for row in rows:
        item = {
            "id": row.id,
            "symbol": row.symbol,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "current_spread": row.current_spread,
            "similarity_score": row.similarity_score,
            "estimated_hit_rate": row.estimated_hit_rate,
            "matched_case_count": row.matched_case_count or 0,
            "case_id": row.case_id,
            "status": "expired" if row.status == "suggested" and _candidate_expired(row, now) else row.status,
            "notified_at": row.notified_at.isoformat() if row.notified_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "note": row.note or "仅建议，不自动借币/不开仓",
        }
        if not compact:
            item["evidence_case_ids"] = row.evidence_case_ids or []
            item["feature_snapshot"] = row.feature_snapshot or {}
        items.append(item)

    return {
        "items": items,
        "warnings": _warning_items(limit),
        "compact": compact,
        "read_only": True,
    }


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(candidate_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = db.query(EarlyBorrowCandidate).filter(EarlyBorrowCandidate.id == candidate_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="提前借币建议不存在")
    row.status = "dismissed"
    db.commit()
    return {"ok": True, "id": row.id, "status": row.status}


@router.get("/cases")
def list_cases(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    compact: bool = Query(False),
):
    get_current_user_id(request)
    query = db.query(EarlyBorrowCase)
    if compact:
        query = query.options(load_only(
            EarlyBorrowCase.id,
            EarlyBorrowCase.symbol,
            EarlyBorrowCase.trigger_at,
            EarlyBorrowCase.trigger_spread,
            EarlyBorrowCase.window_start,
            EarlyBorrowCase.window_end,
            EarlyBorrowCase.sample_count,
            EarlyBorrowCase.status,
        ))
    rows = query.order_by(EarlyBorrowCase.trigger_at.desc()).limit(limit).all()

    items = []
    for row in rows:
        item = {
            "id": row.id,
            "symbol": row.symbol,
            "trigger_at": row.trigger_at.isoformat() if row.trigger_at else None,
            "trigger_spread": row.trigger_spread,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "sample_count": row.sample_count,
            "status": row.status,
        }
        if not compact:
            item["feature_summary"] = row.feature_summary or {}
        items.append(item)

    return {
        "items": items,
        "compact": compact,
        "read_only": True,
    }


@router.get("/status")
def get_status(request: Request, db: Session = Depends(get_db)):
    get_current_user_id(request)
    cfg = _ensure_config(db)
    candidate_count = db.query(EarlyBorrowCandidate).filter(
        EarlyBorrowCandidate.status == "suggested",
        (
            EarlyBorrowCandidate.expires_at.is_(None)
            | (EarlyBorrowCandidate.expires_at > _now())
        ),
    ).count()
    case_count = db.query(EarlyBorrowCase).count()
    ready_case_count = db.query(EarlyBorrowCase).filter(EarlyBorrowCase.status == "ready").count()
    tick_count, feature_count, counts_estimated = _high_volume_counts(db)
    service_status = dict(early_borrow_service.status)
    if bool(cfg.enabled) and not service_status.get("running"):
        service_status["state"] = "SERVICE_OFFLINE"
    return {
        **service_status,
        "enabled": bool(cfg.enabled),
        "config": _config_payload(cfg),
        "latest_tick_at": service_status.get("last_tick_at"),
        "latest_feature_at": service_status.get("last_feature_at"),
        "suggested_count": candidate_count,
        "case_count": case_count,
        "ready_case_count": ready_case_count,
        "tick_count": tick_count,
        "feature_count": feature_count,
        "counts_estimated": counts_estimated,
        "read_only": True,
    }


@router.get("/config")
def get_config(request: Request, db: Session = Depends(get_db)):
    get_current_user_id(request)
    return _config_payload(_ensure_config(db))


class EarlyBorrowConfigUpdate(BaseModel):
    enabled: bool | None = None
    sample_interval_sec: int | None = Field(default=None, ge=1, le=60)
    metrics_interval_sec: int | None = Field(default=None, ge=60, le=3600)
    lookback_hours: int | None = Field(default=None, ge=1, le=12)
    warning_spread_pct: float | None = Field(default=None, ge=0, le=20)
    candidate_spread_pct: float | None = Field(default=None, ge=0, le=20)
    trigger_spread_pct: float | None = Field(default=None, ge=0, le=20)
    open_spread_pct: float | None = Field(default=None, ge=0, le=20)
    open_spread_buffer_pct: float | None = Field(default=None, ge=0, le=10)
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    notification_cooldown_sec: int | None = Field(default=None, ge=60, le=86400)
    retention_days: int | None = Field(default=None, ge=1, le=90)


@router.put("/config")
def update_config(req: EarlyBorrowConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = _ensure_config(db)
    for field in req.model_fields:
        value = getattr(req, field)
        if value is not None:
            setattr(row, field, value)
    # Validate the normalized values as well as the submitted fields.  This
    # keeps a legacy NULL row from turning a harmless partial update into a
    # TypeError/500 response.
    normalized = _config_payload(row)
    if normalized["candidate_spread_pct"] > normalized["trigger_spread_pct"]:
        raise HTTPException(status_code=400, detail="候选点差不能高于跳点案例阈值")
    if normalized["open_spread_pct"] > normalized["trigger_spread_pct"]:
        raise HTTPException(status_code=400, detail="真正开仓线不能高于跳点案例阈值")
    if normalized["effective_candidate_spread_pct"] > normalized["open_spread_pct"]:
        raise HTTPException(status_code=400, detail="借币候选线叠加缓冲后不能高于真正开仓线")
    if normalized["warning_spread_pct"] < normalized["effective_candidate_spread_pct"]:
        raise HTTPException(status_code=400, detail="点差预警线不能低于借币候选线")
    db.commit()
    db.refresh(row)
    return _config_payload(row)
