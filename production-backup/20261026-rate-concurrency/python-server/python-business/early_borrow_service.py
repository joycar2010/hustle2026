"""Binance-only, read-only early-borrow analytics.

The service consumes the existing Rust/WebSocket spread hash and public
Binance Futures statistics.  It never imports or calls a trading client.
When a user explicitly enables the GlobalRules auto-push switch, a matching
symbol is mirrored to that user's dashboard push list as control-plane state;
the mirror does not borrow, place, or cancel any order.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_right
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.db.models import GlobalRules, Symbol
from app.db.models_auth import User
from app.db.models_early_borrow import (
    EarlyBorrowCandidate,
    EarlyBorrowCase,
    EarlyBorrowConfig,
    EarlyBorrowFeature,
    EarlyBorrowTick,
)
from app.db.models_notify import NotificationLog
from app.db.session import SessionLocal
from app.services import binance_client
from app.services.pushed_symbols import (
    auto_global_rules_key,
    clear_auto_global_rule_account_markers_async,
    mutate_pushed_symbols_async,
)
from engine.freshness import configured_spread_max_age_ms

logger = logging.getLogger(__name__)

SPREADS_KEY = "spreads"
UNIVERSE_KEY = "early_borrow:universe"
STATUS_KEY = "early_borrow:status"
SPOT_WS_SOURCE = "binance_ws"
# Advisory matching must use the same local WS freshness contract as execution.
SPREAD_SNAPSHOT_MAX_AGE_MS = configured_spread_max_age_ms()
AUTO_PUSH_COMMAND_TTL_SEC = 120

try:
    # Exchange-info is only used to refresh the read-only universe.  A bounded
    # timeout keeps a Binance edge/network stall from delaying the first local
    # spread sample; the previous cached universe remains usable meanwhile.
    UNIVERSE_REFRESH_TIMEOUT_SEC = max(
        2.0,
        min(10.0, float(os.getenv("EARLY_BORROW_UNIVERSE_TIMEOUT_SEC", "5"))),
    )
except (TypeError, ValueError, OverflowError):
    UNIVERSE_REFRESH_TIMEOUT_SEC = 5.0

# The public Binance statistics endpoints are symbol-scoped. A five-minute
# pass over the eligible universe therefore makes three requests per symbol.
# Keep the fan-out bounded and operator-tunable so one slow symbol cannot
# serialize the whole pass or exhaust httpx/OS connection limits.
try:
    METRIC_CONCURRENCY = max(
        4,
        min(64, int(os.getenv("EARLY_BORROW_METRIC_CONCURRENCY", "24"))),
    )
except (TypeError, ValueError, OverflowError):
    METRIC_CONCURRENCY = 24

# Candidate matching opens a short-lived DB session per symbol. A small
# separate limit keeps the database pool available to dashboard requests while
# still avoiding the previous one-symbol-at-a-time evaluation loop.
try:
    CANDIDATE_EVAL_CONCURRENCY = max(
        1,
        min(8, int(os.getenv("EARLY_BORROW_CANDIDATE_CONCURRENCY", "4"))),
    )
except (TypeError, ValueError, OverflowError):
    CANDIDATE_EVAL_CONCURRENCY = 4

FAPI_BASE = "https://fapi.binance.com"
POSITION_RATIO_URL = f"{FAPI_BASE}/futures/data/topLongShortPositionRatio"
ACCOUNT_RATIO_URL = f"{FAPI_BASE}/futures/data/globalLongShortAccountRatio"
TOP_ACCOUNT_RATIO_URL = f"{FAPI_BASE}/futures/data/topLongShortAccountRatio"
OI_URL = f"{FAPI_BASE}/fapi/v1/openInterest"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc_datetime(value: datetime) -> datetime:
    """Normalize DB timestamps before doing window arithmetic.

    PostgreSQL returns timezone-aware values while SQLite (used by local
    tests/dev instances) commonly returns naive UTC values. Treating the
    latter as UTC keeps case matching deterministic across both backends.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _config_number(value: Any, default: float) -> float:
    """Return a finite config number, falling back for legacy bad rows."""
    parsed = _float(value)
    return float(default) if parsed is None else parsed


def _config_integer(value: Any, default: int) -> int:
    """Return an integer config value without propagating NULL/invalid data."""
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _spread_snapshot_fresh(
    item: dict[str, Any],
    *,
    now_ms: int | None = None,
    max_age_ms: int = SPREAD_SNAPSHOT_MAX_AGE_MS,
) -> bool:
    """Require both legs' local WS receive times to be recent.

    Binance event time (``ts``) is not a liveness signal. Snapshots without
    the Rust receive-time fields are legacy data and fail closed.
    """
    receive_times = (
        _float(item.get("spot_recv_ts_ms")),
        _float(item.get("fut_recv_ts_ms")),
    )
    current = int(time.time() * 1000) if now_ms is None else int(now_ms)
    limit = max(1, int(max_age_ms))
    return all(
        timestamp is not None
        and timestamp > 0
        and current - int(timestamp) >= -60_000
        and current - int(timestamp) <= limit
        for timestamp in receive_times
    )


def _config_values() -> dict[str, Any]:
    """Load or create the single global configuration row."""
    db = SessionLocal()
    try:
        row = db.query(EarlyBorrowConfig).order_by(EarlyBorrowConfig.id).first()
        if row is None:
            row = EarlyBorrowConfig()
            db.add(row)
            db.commit()
            db.refresh(row)
        # Keep the collector's interpretation identical to the HTTP read
        # endpoint.  During a rolling migration an existing row can contain
        # NULL, NaN, or out-of-range values; letting those reach the loop can
        # silently disable sampling (``bool(None)``) or make its interval
        # effectively unbounded, which surfaces as a permanently loading tab.
        return {
            "enabled": bool(row.enabled if row.enabled is not None else True),
            "sample_interval_sec": max(1, min(60, _config_integer(row.sample_interval_sec, 2))),
            "metrics_interval_sec": max(60, min(3600, _config_integer(row.metrics_interval_sec, 300))),
            "lookback_hours": max(1, min(12, _config_integer(row.lookback_hours, 6))),
            "warning_spread_pct": _config_number(row.warning_spread_pct, 0.8),
            "candidate_spread_pct": _config_number(row.candidate_spread_pct, 0.45),
            "trigger_spread_pct": _config_number(row.trigger_spread_pct, 1.0),
            "open_spread_pct": _config_number(row.open_spread_pct, 0.5),
            "open_spread_buffer_pct": max(0.0, _config_number(row.open_spread_buffer_pct, 0.05)),
            "similarity_threshold": min(1.0, max(0.0, _config_number(row.similarity_threshold, 0.85))),
            "notification_cooldown_sec": max(60, min(86400, _config_integer(row.notification_cooldown_sec, 1800))),
            "retention_days": max(1, min(90, _config_integer(row.retention_days, 7))),
        }
    finally:
        db.close()


def _eligible_from_db() -> set[str]:
    db = SessionLocal()
    try:
        rows = db.query(Symbol.symbol).filter(
            Symbol.is_active.is_(True),
            Symbol.margin_tradable.is_(True),
            Symbol.futures_tradable.is_(True),
        ).all()
        return {str(row[0]).upper() for row in rows if row[0]}
    finally:
        db.close()


def _enabled_auto_push_users() -> list[int]:
    """Return only user-scoped rules that explicitly enable auto push.

    The early-borrow collector is global market analytics, while pushed lists
    are account state.  Keeping the lookup here (instead of deriving users
    from Redis keys) ensures a missing/disabled rule can never inherit another
    user's list.  ``user_id IS NULL`` is the system defaults row and is never
    eligible for this feature.
    """
    db = SessionLocal()
    try:
        rows = db.query(GlobalRules.user_id).join(
            User,
            User.id == GlobalRules.user_id,
        ).filter(
            GlobalRules.user_id.isnot(None),
            GlobalRules.early_borrow_auto_push_enabled.is_(True),
            User.is_active.is_(True),
        ).all()
        return sorted({int(row[0]) for row in rows if row[0] is not None})
    except Exception:
        logger.exception("Failed to load early-borrow auto-push users")
        return []
    finally:
        db.close()


def _persist_ticks(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    db = SessionLocal()
    try:
        db.bulk_insert_mappings(EarlyBorrowTick, rows)
        db.commit()
    finally:
        db.close()


def _persist_features(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    db = SessionLocal()
    try:
        db.bulk_insert_mappings(EarlyBorrowFeature, rows)
        db.commit()
    finally:
        db.close()


OI_WINDOWS: tuple[tuple[int, str], ...] = (
    (5, "oi_change_5m_pct"),
    (15, "oi_change_15m_pct"),
    (30, "oi_change_30m_pct"),
    (60, "oi_change_1h_pct"),
    (180, "oi_change_3h_pct"),
    (360, "oi_change_6h_pct"),
)


def _enrich_oi_changes(rows: list[dict[str, Any]], now: datetime) -> None:
    """Attach fixed-window OI deltas using persisted five-minute samples.

    The collector is restarted independently of the trading worker.  Reading
    the previous six hours from the case database means a restart does not
    silently turn the first post-restart sample into a fake 5m change.
    """
    if not rows:
        return
    symbols = {str(row.get("symbol") or "").upper() for row in rows}
    symbols.discard("")
    if not symbols:
        return

    def epoch(value: datetime) -> float:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    db = SessionLocal()
    try:
        cutoff = now - timedelta(hours=6, minutes=5)
        history: dict[str, list[tuple[float, float]]] = {}
        query = db.query(
            EarlyBorrowFeature.symbol,
            EarlyBorrowFeature.captured_at,
            EarlyBorrowFeature.open_interest,
        ).filter(
            EarlyBorrowFeature.symbol.in_(symbols),
            EarlyBorrowFeature.captured_at >= cutoff,
            EarlyBorrowFeature.captured_at < now,
            EarlyBorrowFeature.open_interest.isnot(None),
        ).order_by(EarlyBorrowFeature.symbol, EarlyBorrowFeature.captured_at)
        for symbol, captured_at, open_interest in query.all():
            value = _float(open_interest)
            if value is not None and value > 0:
                history.setdefault(str(symbol).upper(), []).append((epoch(captured_at), value))

        now_epoch = epoch(now)
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            current = _float(row.get("open_interest"))
            if not symbol or current is None or current <= 0:
                continue
            prior = history.get(symbol, [])
            times = [item[0] for item in prior]
            for minutes, field in OI_WINDOWS:
                target = now_epoch - minutes * 60
                index = bisect_right(times, target) - 1
                baseline = prior[index][1] if index >= 0 else None
                row[field] = ((current - baseline) / baseline * 100) if baseline else None
            row["oi_change_pct"] = row.get("oi_change_5m_pct")
    finally:
        db.close()


def _trajectory(ticks: list[Any], features: list[Any], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Compress six hours of raw observations into twelve 30-minute buckets."""
    start = _utc_datetime(start)
    end = _utc_datetime(end)
    duration = max(1.0, (end - start).total_seconds())
    buckets: list[dict[str, list[float]]] = [
        {
            "spread": [], "position": [], "account": [], "leverage": [],
            "oi_change_5m": [], "oi_change_15m": [], "oi_change_30m": [],
            "oi_change_1h": [], "oi_change_3h": [], "oi_change_6h": [], "oi": [],
        }
        for _ in range(12)
    ]

    def index(ts: datetime) -> int:
        ts = _utc_datetime(ts)
        value = int(((ts - start).total_seconds() / duration) * 12)
        return max(0, min(11, value))

    for row in ticks:
        bucket = buckets[index(row.captured_at)]
        if row.spread_short is not None:
            bucket["spread"].append(float(row.spread_short))
    for row in features:
        bucket = buckets[index(row.captured_at)]
        for key, value in (
            ("position", row.position_ratio),
            ("account", row.account_ratio),
            ("leverage", row.leverage_ratio),
            ("oi_change_5m", getattr(row, "oi_change_5m_pct", None) or row.oi_change_pct),
            ("oi_change_15m", getattr(row, "oi_change_15m_pct", None)),
            ("oi_change_30m", getattr(row, "oi_change_30m_pct", None)),
            ("oi_change_1h", getattr(row, "oi_change_1h_pct", None)),
            ("oi_change_3h", getattr(row, "oi_change_3h_pct", None)),
            ("oi_change_6h", getattr(row, "oi_change_6h_pct", None)),
            ("oi", row.open_interest),
        ):
            if value is not None and math.isfinite(float(value)):
                bucket[key].append(float(value))

    result: list[dict[str, Any]] = []
    for bucket in buckets:
        item: dict[str, Any] = {}
        for key, values in bucket.items():
            item[key] = sum(values) / len(values) if values else None
        result.append(item)
    return result


def _similarity(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> float:
    """Compare trajectories after per-feature min/max normalization."""
    if not left or not right:
        return 0.0
    keys = (
        "spread", "position", "account", "leverage", "oi_change_5m",
        "oi_change_15m", "oi_change_30m", "oi_change_1h", "oi_change_3h",
        "oi_change_6h", "oi",
    )
    distances: list[float] = []
    for key in keys:
        a = [x.get(key) for x in left]
        b = [x.get(key) for x in right]
        values = [float(v) for v in a + b if v is not None and math.isfinite(float(v))]
        if len(values) < 2:
            continue
        low, high = min(values), max(values)
        scale = high - low or 1.0
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        if not pairs:
            continue
        distances.extend(abs((float(x) - low) / scale - (float(y) - low) / scale) for x, y in pairs)
    if not distances:
        return 0.0
    return max(0.0, min(1.0, 1.0 - sum(distances) / len(distances)))


def _metric_row_valid(row: Any) -> bool:
    """Require all requested public metrics before using a feature row."""
    ratios = (
        _float(getattr(row, "position_ratio", None)),
        _float(getattr(row, "account_ratio", None)),
        _float(getattr(row, "leverage_ratio", None)),
    )
    oi = _float(getattr(row, "open_interest", None))
    return all(value is not None and value > 0 for value in ratios) and oi is not None and oi > 0


def _history_ready(
    rows: list[Any],
    start: datetime,
    end: datetime,
    lookback_hours: int,
    metrics_interval_sec: int = 300,
) -> bool:
    """Ensure a candidate/case really has the configured lookback history."""
    valid = [row for row in rows if _metric_row_valid(row)]
    if len(valid) < 3:
        return False
    first = min(_utc_datetime(row.captured_at) for row in valid)
    last = max(_utc_datetime(row.captured_at) for row in valid)
    start = _utc_datetime(start)
    end = _utc_datetime(end)
    required = max(0.0, lookback_hours * 3600 - max(60, metrics_interval_sec) * 2)
    return (last - first).total_seconds() >= required and first <= start + timedelta(
        seconds=max(60, metrics_interval_sec) * 2
    ) and last >= end - timedelta(seconds=max(60, metrics_interval_sec) * 2)


def _build_case_sync(
    symbol: str,
    trigger_at: datetime,
    trigger_spread: float,
    lookback_hours: int,
    metrics_interval_sec: int = 300,
) -> int | None:
    db = SessionLocal()
    try:
        window_start = trigger_at - timedelta(hours=lookback_hours)
        existing = db.query(EarlyBorrowCase).filter(
            EarlyBorrowCase.symbol == symbol,
            EarlyBorrowCase.trigger_at >= trigger_at - timedelta(minutes=10),
        ).first()
        if existing:
            return existing.id
        ticks = db.query(EarlyBorrowTick).filter(
            EarlyBorrowTick.symbol == symbol,
            EarlyBorrowTick.captured_at >= window_start,
            # The case represents the trajectory *before* the jump. Excluding
            # the trigger instant prevents a concurrently captured metric/tick
            # from leaking post-trigger information into future matches.
            EarlyBorrowTick.captured_at < trigger_at,
        ).order_by(EarlyBorrowTick.captured_at).all()
        features = db.query(EarlyBorrowFeature).filter(
            EarlyBorrowFeature.symbol == symbol,
            EarlyBorrowFeature.captured_at >= window_start,
            EarlyBorrowFeature.captured_at < trigger_at,
        ).order_by(EarlyBorrowFeature.captured_at).all()
        trajectory = _trajectory(ticks, features, window_start, trigger_at)
        # Keep jumps observed during warm-up for audit, but only expose cases
        # with enough raw spread ticks and five-minute feature rows to support
        # a meaningful six-hour trajectory match.
        case_status = (
            "ready"
            if len(ticks) >= 6 and _history_ready(
                features, window_start, trigger_at, lookback_hours, metrics_interval_sec
            )
            else "warming"
        )
        row = EarlyBorrowCase(
            symbol=symbol,
            trigger_at=trigger_at,
            trigger_spread=trigger_spread,
            window_start=window_start,
            window_end=trigger_at,
            sample_count=len(ticks) + len(features),
            status=case_status,
            feature_summary={
                "version": 1,
                "lookback_hours": lookback_hours,
                "trajectory": trajectory,
                "tick_count": len(ticks),
                "feature_count": len(features),
            },
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception:
        db.rollback()
        logger.exception("Failed to build early-borrow case for %s", symbol)
        return None
    finally:
        db.close()


def _evaluate_symbol_sync(symbol: str, spread: float, cfg: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    # Keep the MIX rule semantics: the effective candidate line includes the
    # configured anti-latency buffer. This path remains read-only.
    effective_candidate = cfg["candidate_spread_pct"] + cfg.get("open_spread_buffer_pct", 0.05)
    if spread < effective_candidate or spread >= cfg["trigger_spread_pct"]:
        return None
    db = SessionLocal()
    try:
        since = now - timedelta(hours=cfg["lookback_hours"])
        recent = db.query(EarlyBorrowCandidate).filter(
            EarlyBorrowCandidate.symbol == symbol,
            EarlyBorrowCandidate.detected_at >= now - timedelta(seconds=cfg["notification_cooldown_sec"]),
        ).first()
        if recent:
            return None
        ticks = db.query(EarlyBorrowTick).filter(
            EarlyBorrowTick.symbol == symbol,
            EarlyBorrowTick.captured_at >= since,
            EarlyBorrowTick.captured_at <= now,
        ).order_by(EarlyBorrowTick.captured_at).all()
        features = db.query(EarlyBorrowFeature).filter(
            EarlyBorrowFeature.symbol == symbol,
            EarlyBorrowFeature.captured_at >= since,
            EarlyBorrowFeature.captured_at <= now,
        ).order_by(EarlyBorrowFeature.captured_at).all()
        # Do not manufacture a recommendation until the complete lookback and
        # all requested metrics are present.
        if len(ticks) < 6 or not _history_ready(
            features, since, now, cfg["lookback_hours"], cfg["metrics_interval_sec"]
        ):
            return None
        trajectory = _trajectory(ticks, features, since, now)
        cases = db.query(EarlyBorrowCase).filter(EarlyBorrowCase.status == "ready").order_by(
            EarlyBorrowCase.trigger_at.desc()
        ).limit(500).all()
        matches: list[tuple[float, EarlyBorrowCase]] = []
        for case in cases:
            summary = case.feature_summary or {}
            score = _similarity(trajectory, summary.get("trajectory") or [])
            if score >= cfg["similarity_threshold"]:
                matches.append((score, case))
        matches.sort(key=lambda item: (item[0], item[1].trigger_at), reverse=True)
        best_score, best_case = matches[0] if matches else (0.0, None)
        if best_case is None or best_score < cfg["similarity_threshold"]:
            return None
        evidence_case_ids = [case.id for _, case in matches[:5]]
        row = EarlyBorrowCandidate(
            symbol=symbol,
            detected_at=now,
            current_spread=spread,
            similarity_score=best_score,
            # A jump-case library is evidence, not a backtest.  Do not present
            # the count of positive cases as a fabricated hit rate.
            estimated_hit_rate=None,
            matched_case_count=len(matches),
            evidence_case_ids=evidence_case_ids,
            case_id=best_case.id,
            feature_snapshot={
                "trajectory": trajectory,
                "case_symbol": best_case.symbol,
                "matched_case_ids": evidence_case_ids,
            },
            status="suggested",
            notified_at=now,
            expires_at=now + timedelta(seconds=cfg["notification_cooldown_sec"]),
            note="仅为历史跳点案例匹配建议，不自动借币、不自动开仓；命中率待积累",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {
            "id": row.id,
            "symbol": symbol,
            "spread": spread,
            "score": best_score,
            "case_id": best_case.id,
            "case_symbol": best_case.symbol,
            "matched_case_count": len(matches),
            "evidence_case_ids": evidence_case_ids,
            "notification_cooldown_sec": cfg["notification_cooldown_sec"],
        }
    except Exception:
        db.rollback()
        logger.exception("Failed to evaluate early-borrow candidate for %s", symbol)
        return None
    finally:
        db.close()


def _write_notification_log(candidate: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        db.add(NotificationLog(
            template_name="提前借币建议",
            channel="marquee",
            status="sent",
            content=(
                f"{candidate['symbol']} 当前点差 {candidate['spread']:.3f}%、案例相似度 "
                f"{candidate['score']:.1%}；仅建议，不自动借币/不开仓"
            ),
        ))
        db.commit()
    finally:
        db.close()


class EarlyBorrowService:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._metrics_task: asyncio.Task | None = None
        self._universe: set[str] = set()
        self._last_refresh = 0.0
        self._last_metrics = 0.0
        self._last_purge = 0.0
        self._last_spread: dict[str, float] = {}
        self._previous_oi: dict[str, float] = {}
        self._last_error: str | None = None
        self._metrics_error: str | None = None
        self._last_tick_at: datetime | None = None
        self._last_feature_at: datetime | None = None
        self._enabled = False

    async def start(self) -> None:
        if self._running:
            return
        # The collector is a read-only auxiliary loop.  Bound Redis connect and
        # command waits so a degraded cache cannot hold the loop (and its
        # status heartbeat) in ``loading`` forever.  The client reconnects on
        # the next cycle after a transient failure.
        self._redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        self._last_error = None
        self._metrics_error = None
        self._running = True
        self._task = asyncio.create_task(self._run(), name="early-borrow-service")
        logger.info("EarlyBorrowService started (read-only)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
            self._metrics_task = None
        if self._redis:
            try:
                await self._redis.set(STATUS_KEY, json.dumps({"running": False}))
            except Exception:
                # Shutdown must remain best-effort when Redis is already down.
                logger.debug("Unable to publish early-borrow stop status", exc_info=True)
            try:
                await self._redis.aclose()
            except Exception:
                logger.debug("Unable to close early-borrow Redis client", exc_info=True)
            self._redis = None

    @property
    def status(self) -> dict[str, Any]:
        if not self._running:
            state = "STOPPED"
        elif not self._enabled:
            state = "DISABLED"
        elif self._last_error or self._metrics_error:
            state = "ERROR"
        elif not self._universe:
            state = "WAITING_FOR_UNIVERSE"
        elif self._last_tick_at is None:
            state = "WARMING_UP"
        else:
            state = "RUNNING"
        return {
            "running": self._running,
            "enabled": self._enabled,
            "state": state,
            "universe_size": len(self._universe),
            "last_tick_at": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "last_feature_at": self._last_feature_at.isoformat() if self._last_feature_at else None,
            "last_error": self._last_error or self._metrics_error,
            "read_only": True,
        }

    async def _run(self) -> None:
        while self._running:
            started = time.monotonic()
            sample_interval = 2.0
            try:
                cfg = await asyncio.to_thread(_config_values)
                self._enabled = bool(cfg["enabled"])
                sample_interval = float(cfg["sample_interval_sec"])
                if cfg["enabled"]:
                    now_mono = time.monotonic()
                    if now_mono - self._last_refresh >= 600 or not self._universe:
                        await self._refresh_universe()
                    await self._sample_spreads(cfg)
                    # Metrics are intentionally off the two-second sampling
                    # path. A full Binance pass can take seconds even with
                    # bounded concurrency; awaiting it here used to pause
                    # spread ticks and Redis status heartbeats for the whole
                    # duration. Keep at most one pass in flight and publish
                    # errors from its own task.
                    if (
                        now_mono - self._last_metrics >= cfg["metrics_interval_sec"]
                        and (self._metrics_task is None or self._metrics_task.done())
                    ):
                        self._last_metrics = now_mono
                        self._metrics_task = asyncio.create_task(
                            self._metrics_cycle(cfg),
                            name="early-borrow-metrics",
                        )
                    if now_mono - self._last_purge >= 3600:
                        await asyncio.to_thread(self._purge, cfg["retention_days"])
                        self._last_purge = now_mono
                    # A completed metrics task is consumed here so exceptions
                    # cannot become unhandled-task warnings. The task itself
                    # records a useful error until the next successful cycle.
                    if self._metrics_task is not None and self._metrics_task.done():
                        self._metrics_task = None
                    self._last_error = None
                else:
                    await asyncio.sleep(5)
                if self._redis:
                    await self._redis.set(STATUS_KEY, json.dumps(self.status), ex=120)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)[:300]
                logger.exception("EarlyBorrowService cycle failed")
            delay = max(0.2, sample_interval - (time.monotonic() - started))
            await asyncio.sleep(delay)

    async def _metrics_cycle(self, cfg: dict[str, Any]) -> None:
        """Run one slow analytics pass without blocking spread sampling."""
        try:
            await self._collect_metrics(cfg)
            await self._evaluate_candidates(cfg)
            # Only a successful complete pass clears an earlier metrics error.
            self._metrics_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._metrics_error = str(exc)[:300]
            logger.exception("EarlyBorrowService metrics cycle failed")

    async def _refresh_universe(self) -> None:
        # Reuse the last successful exchange-info intersection immediately.
        # This is especially important after an API restart: status and any
        # readers observing the service no longer remain in
        # WAITING_FOR_UNIVERSE while the authoritative refresh is in flight.
        cached = False
        if self._redis:
            try:
                raw = await self._redis.get(UNIVERSE_KEY)
                parsed = json.loads(raw) if raw else []
                if isinstance(parsed, list):
                    cached_universe = {
                        str(symbol).strip().upper()
                        for symbol in parsed
                        if isinstance(symbol, str) and str(symbol).strip()
                    }
                    if cached_universe:
                        self._universe = cached_universe
                        cached = True
            except Exception:
                logger.debug("Unable to read cached early-borrow universe", exc_info=True)
        try:
            spot, futures = await asyncio.wait_for(
                asyncio.gather(
                    binance_client.fetch_spot_exchange_info(),
                    binance_client.fetch_futures_exchange_info(),
                ),
                timeout=UNIVERSE_REFRESH_TIMEOUT_SEC,
            )
            futures_set = {str(item["symbol"]).upper() for item in futures}
            refreshed_universe = {
                str(item["symbol"]).upper()
                for item in spot
                if item.get("is_margin") and str(item["symbol"]).upper() in futures_set
            }
            # Do not replace a known-good cached set with an empty response
            # from a transient/partial exchange-info payload.
            if refreshed_universe:
                self._universe = refreshed_universe
                if self._redis:
                    try:
                        await self._redis.set(UNIVERSE_KEY, json.dumps(sorted(self._universe)), ex=900)
                    except Exception:
                        # A cache write failure must not discard the fresh
                        # exchange-info result or trigger the DB fallback.
                        logger.debug("Unable to persist early-borrow universe cache", exc_info=True)
            self._last_refresh = time.monotonic()
            logger.info("Early-borrow eligible Binance universe: %d", len(self._universe))
        except Exception as exc:
            if not cached:
                fallback = await asyncio.to_thread(_eligible_from_db)
                if fallback:
                    self._universe = fallback
            self._last_refresh = time.monotonic()
            logger.warning(
                "Early-borrow universe refresh failed%s: %s",
                " (using cached universe)" if cached else "",
                exc,
            )

    async def _sample_spreads(self, cfg: dict[str, Any]) -> None:
        if not self._redis or not self._universe:
            return
        raw_items = await self._redis.hgetall(SPREADS_KEY)
        now = _utcnow()
        tick_rows: list[dict[str, Any]] = []
        triggers: list[tuple[str, float]] = []
        warnings: list[tuple[str, float]] = []
        for symbol, raw in raw_items.items():
            symbol = symbol.upper()
            if symbol not in self._universe:
                continue
            try:
                item = json.loads(raw)
                spread = _float(item.get("spread_short"))
                if spread is None:
                    continue
                if not _spread_snapshot_fresh(item, now_ms=int(now.timestamp() * 1000)):
                    continue
                previous = self._last_spread.get(symbol)
                self._last_spread[symbol] = spread
                if (
                    previous is not None
                    and previous < cfg["warning_spread_pct"] <= spread
                    and spread < cfg["trigger_spread_pct"]
                ):
                    warnings.append((symbol, spread))
                # If the process restarted while a symbol was already above
                # the jump line, use persisted pre-restart ticks to build the
                # case instead of silently losing the event.
                if ((previous is not None and previous < cfg["trigger_spread_pct"] <= spread)
                        or (previous is None and spread >= cfg["trigger_spread_pct"])):
                    triggers.append((symbol, spread))
                tick_rows.append({
                    "symbol": symbol,
                    "captured_at": now,
                    "spot_bid": _float(item.get("spot_bid")),
                    "spot_ask": _float(item.get("spot_ask")),
                    "futures_bid": _float(item.get("fut_bid")),
                    "futures_ask": _float(item.get("fut_ask")),
                    "spread_long": _float(item.get("spread_long")),
                    "spread_short": spread,
                    "source": SPOT_WS_SOURCE,
                })
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        await asyncio.to_thread(_persist_ticks, tick_rows)
        if tick_rows:
            self._last_tick_at = now
        for symbol, spread in triggers:
            await asyncio.to_thread(
                _build_case_sync,
                symbol,
                now,
                spread,
                cfg["lookback_hours"],
                cfg["metrics_interval_sec"],
            )
        for symbol, spread in warnings:
            await self._publish_warning(symbol, spread, cfg["notification_cooldown_sec"])

    async def _publish_warning(self, symbol: str, spread: float, cooldown: int) -> None:
        """Publish a de-duplicated warning without creating a borrow action.

        Keep the short-lived Redis key as a small read model as well as a
        cooldown lock.  The dashboard warning feed can then show the same
        event as the WS marquee, even when the event was emitted before the
        monitor modal was opened.  This key is advisory state only; it never
        enters the worker's pushed-symbol or order paths.
        """
        if not self._redis:
            return
        key = f"early_borrow:warning:{symbol}"
        ttl = max(60, int(cooldown or 0))
        now = _utcnow()
        expires_at = now + timedelta(seconds=ttl)
        payload = {
            "type": "spread_warning",
            "title": f"点差预警 · {symbol}",
            "content": (
                f"{symbol} 当前点差 {spread:.3f}% 已达到预警线；仅发送提醒，"
                "不代表借币，不自动借币或开仓。"
            ),
            "priority": 3,
            "color": "#f59e0b",
            "blink": False,
            "sound": "alert",
            "symbol": symbol,
            "spread": spread,
            "detected_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "read_only": True,
        }
        try:
            if not await self._redis.set(key, json.dumps(payload, ensure_ascii=False), nx=True, ex=ttl):
                return
        except Exception:
            return
        await self._redis.publish("notification:broadcast", json.dumps(payload, ensure_ascii=False))

    async def _get_metric(self, client: httpx.AsyncClient, symbol: str) -> dict[str, float | None]:
        async def get_ratio(url: str) -> float | None:
            try:
                response = await client.get(url, params={"symbol": symbol, "period": "5m", "limit": 1})
                if response.status_code != 200:
                    return None
                payload = response.json()
                item = payload[-1] if isinstance(payload, list) and payload else payload
                return _float(item.get("longShortRatio")) if isinstance(item, dict) else None
            except Exception:
                return None

        async def get_oi() -> float | None:
            try:
                response = await client.get(OI_URL, params={"symbol": symbol})
                if response.status_code != 200:
                    return None
                return _float(response.json().get("openInterest"))
            except Exception:
                return None

        position, account, oi = await asyncio.gather(
            get_ratio(POSITION_RATIO_URL),
            get_ratio(ACCOUNT_RATIO_URL),
            get_oi(),
        )
        # Leverage is derived from the requested position/account ratios; no
        # private endpoint or extra top-account request is needed.
        leverage = position / account if position is not None and account and account > 0 else None
        previous = self._previous_oi.get(symbol)
        oi_change = ((oi - previous) / previous * 100) if oi is not None and previous and previous > 0 else None
        if oi is not None:
            self._previous_oi[symbol] = oi
        return {
            "position_ratio": position,
            "account_ratio": account,
            "leverage_ratio": leverage,
            "open_interest": oi,
            "oi_change_pct": oi_change,
        }

    async def _collect_metrics(self, cfg: dict[str, Any]) -> None:
        if not self._universe:
            return
        now = _utcnow()
        rows: list[dict[str, Any]] = []
        semaphore = asyncio.Semaphore(METRIC_CONCURRENCY)
        # Each symbol task issues three requests concurrently. Keep the client
        # pool just above that bound while retaining keep-alive connections for
        # the next five-minute pass.
        limits = httpx.Limits(
            max_connections=max(12, METRIC_CONCURRENCY * 3),
            max_keepalive_connections=METRIC_CONCURRENCY,
        )
        async with httpx.AsyncClient(timeout=12, limits=limits) as client:
            async def one(symbol: str) -> None:
                async with semaphore:
                    metric = await self._get_metric(client, symbol)
                    rows.append({"symbol": symbol, "captured_at": now, "source": "binance_public", **metric})
            await asyncio.gather(*(one(symbol) for symbol in sorted(self._universe)))
        await asyncio.to_thread(_enrich_oi_changes, rows, now)
        await asyncio.to_thread(_persist_features, rows)
        if rows:
            self._last_feature_at = now

    async def _evaluate_candidates(self, cfg: dict[str, Any]) -> None:
        if not self._redis or not self._universe:
            return
        raw_items = await self._redis.hgetall(SPREADS_KEY)
        now = _utcnow()
        eligible: list[tuple[str, float]] = []
        for symbol, raw in raw_items.items():
            symbol = symbol.upper()
            if symbol not in self._universe:
                continue
            try:
                item = json.loads(raw)
                if not _spread_snapshot_fresh(item, now_ms=int(now.timestamp() * 1000)):
                    continue
                spread = _float(item.get("spread_short"))
            except Exception:
                spread = None
            if spread is None:
                continue
            # Avoid scheduling a DB worker for the common case where the live
            # spread is below the advisory line or already at the jump line.
            # `_evaluate_symbol_sync` repeats this guard as a defensive check
            # for direct callers.
            effective_candidate = cfg["candidate_spread_pct"] + cfg.get("open_spread_buffer_pct", 0.05)
            if spread < effective_candidate or spread >= cfg["trigger_spread_pct"]:
                continue
            eligible.append((symbol, spread))

        if not eligible:
            return

        semaphore = asyncio.Semaphore(CANDIDATE_EVAL_CONCURRENCY)

        async def evaluate(symbol: str, spread: float):
            async with semaphore:
                return await asyncio.to_thread(_evaluate_symbol_sync, symbol, spread, cfg, now)

        # Matching is read-heavy and independent per symbol. Bounded parallel
        # evaluation removes the previous serial delay without exhausting the
        # SQLAlchemy pool or reordering notification side effects.
        results = await asyncio.gather(
            *(evaluate(symbol, spread) for symbol, spread in eligible),
            return_exceptions=True,
        )
        for candidate in results:
            if isinstance(candidate, Exception):
                logger.warning("Early-borrow candidate evaluation failed: %s", candidate)
                continue
            if candidate:
                await self._publish_candidate(candidate)

    async def _auto_push_candidate(self, candidate: dict[str, Any], cooldown_sec: int) -> list[int]:
        """Mirror a suggestion into explicitly opted-in users' push lists.

        ``pushed_symbols`` is a JSON array for compatibility with the Worker
        and dashboard APIs.  A per-user Redis NX key provides a restart-safe
        cooldown in addition to list membership de-duplication.  This method
        only writes Redis control-plane state and publishes a user-scoped
        update; it deliberately has no exchange/trading-client dependency.
        """
        if not self._redis:
            return []
        symbol = str(candidate.get("symbol") or "").strip().upper()
        if not symbol:
            return []
        try:
            users = await asyncio.to_thread(_enabled_auto_push_users)
        except Exception:
            logger.exception("Failed to resolve early-borrow auto-push users")
            return []
        if not users:
            return []

        ttl = max(60, int(cooldown_sec or 0))
        now_ts = time.time()
        pushed_users: list[int] = []
        for user_id in users:
            ps_key = f"engine:{user_id}:pushed_symbols"
            cooldown_key = f"early_borrow:auto_push:{user_id}:{symbol}"
            command_key = f"engine:{user_id}:push_commands"
            try:
                raw = await self._redis.get(ps_key)
                try:
                    parsed = json.loads(raw) if raw else []
                    current = {
                        str(item).strip().upper()
                        for item in parsed
                        if isinstance(item, str) and str(item).strip()
                    }
                except (TypeError, ValueError, json.JSONDecodeError):
                    current = set()
                if symbol in current:
                    continue

                # Claim before the read/modify/write sequence so two service
                # loops cannot enqueue the same user/symbol concurrently.
                if not await self._redis.set(cooldown_key, str(now_ts), nx=True, ex=ttl):
                    continue

                # Re-read after claiming the cooldown.  A manual push may have
                # arrived between the first read and the claim.
                raw = await self._redis.get(ps_key)
                try:
                    parsed = json.loads(raw) if raw else []
                    current = {
                        str(item).strip().upper()
                        for item in parsed
                        if isinstance(item, str) and str(item).strip()
                    }
                except (TypeError, ValueError, json.JSONDecodeError):
                    current = set()
                if symbol in current:
                    continue

                current, changed = await mutate_pushed_symbols_async(
                    self._redis,
                    ps_key,
                    add={symbol},
                    add_guard_key=f"engine:{user_id}:removed_cooldown:{symbol}",
                )
                if not changed:
                    continue
                # Early-borrow is an automatic source.  Keep its first
                # execution on the tenant's global rule snapshot until a
                # user explicitly saves a single-symbol/account override.
                try:
                    await self._redis.hsetnx(
                        auto_global_rules_key(user_id), symbol, "1"
                    )
                    await clear_auto_global_rule_account_markers_async(
                        self._redis, user_id, symbol
                    )
                except Exception:
                    logger.warning(
                        "Unable to persist automatic rule source for %s", symbol,
                        exc_info=True,
                    )
                await self._redis.rpush(
                    command_key,
                    json.dumps({"action": "push", "symbol": symbol, "source": "early_borrow"}),
                )
                await self._redis.expire(command_key, AUTO_PUSH_COMMAND_TTL_SEC)
                await self._redis.publish(
                    "pushed:updates",
                    json.dumps({
                        "user_id": user_id,
                        # mutate_pushed_symbols_async returns the ordered
                        # queue; publish it unchanged so the newest push
                        # remains at the top of the dashboard.
                        "pushed_symbols": current,
                        "source": "early_borrow",
                        "symbol": symbol,
                    }),
                )
                pushed_users.append(user_id)
            except Exception:
                logger.exception(
                    "Failed to auto-push early-borrow candidate %s for user %s",
                    symbol,
                    user_id,
                )
        return pushed_users

    async def _publish_candidate(self, candidate: dict[str, Any]) -> None:
        if not self._redis:
            return
        # Resolve the users once so both Redis list updates and notifications
        # use the same opt-in boundary. No user opted in means no personal
        # auto-push event is emitted.
        pushed_users = await self._auto_push_candidate(
            candidate,
            int(candidate.get("notification_cooldown_sec") or 1800),
        )
        content = (
            f"{candidate['symbol']} 提前借币建议：当前开仓点差 {candidate['spread']:.3f}%，"
            f"历史案例 {candidate['case_symbol']} 相似度 {candidate['score']:.1%}。"
            "仅为案例匹配提醒，不自动借币、不自动开仓。"
        )
        payload = {
            "type": "early_borrow",
            "title": f"提前借币建议 · {candidate['symbol']}",
            "content": content,
            "priority": 2,
            "color": "#f59e0b",
            "blink": False,
            "sound": "early_borrow",
            "symbol": candidate["symbol"],
            "candidate_id": candidate["id"],
            "read_only": True,
        }
        for user_id in pushed_users:
            user_payload = {**payload, "user_id": user_id}
            await self._redis.publish("notification:broadcast", json.dumps(user_payload, ensure_ascii=False))
        await asyncio.to_thread(_write_notification_log, candidate)

    @staticmethod
    def _purge(retention_days: int) -> None:
        cutoff = _utcnow() - timedelta(days=retention_days)
        db = SessionLocal()
        try:
            for model in (EarlyBorrowTick, EarlyBorrowFeature, EarlyBorrowCase, EarlyBorrowCandidate):
                column = model.captured_at if model in (EarlyBorrowTick, EarlyBorrowFeature) else (
                    model.trigger_at if model is EarlyBorrowCase else model.detected_at
                )
                db.query(model).filter(column < cutoff).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


early_borrow_service = EarlyBorrowService()
