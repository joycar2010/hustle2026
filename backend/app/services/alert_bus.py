"""Unified Alert Bus.

A single fan-in / fan-out point for ALL alerts in the system. Producers
(risk_alert_service, spread_alert_service, balance_monitor, leg_monitor,
agent feishu_broadcast, ...) call AlertBus.emit(...) — never call sinks
(Feishu, WebSocket, DB) directly.

Responsibilities
----------------
1. Atomic deduplication via Redis SETNX EX on the
   ``alert:dedup:{user_id}:{pair_code}:{template_key}`` key. Survives
   process restarts; works across multiple workers.

2. Fan-out to all enabled sinks for the (user, severity) tuple:
     - Feishu card  (when user.feishu_open_id and template.enable_feishu)
     - WebSocket    (front-end popup + sound)
     - DB persist   (agent_alerts table — durable history)

3. Per-user / per-template channel toggles via
   user_notification_settings.feishu_enabled / enable_risk_notifications.

4. Best-effort: a sink failure NEVER aborts the others; each is wrapped
   in its own try/except and logged.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.redis_client import redis_client
from app.websocket.manager import manager as ws_manager

logger = logging.getLogger(__name__)


# ── Severity ─────────────────────────────────────────────────────────────────
class Severity:
    INFO = "info"
    WARN = "warn"
    DANGER = "danger"
    CRITICAL = "critical"


_VALID_SEVERITY = {Severity.INFO, Severity.WARN, Severity.DANGER, Severity.CRITICAL}


# ── Public event ─────────────────────────────────────────────────────────────
@dataclass
class AlertEvent:
    """A single alert emitted to the bus.

    user_id     — owner of the alert. Empty string means system-wide; the bus
                  will fan out to all admin/operator users with feishu_open_id.
    pair_code   — hedging pair scope (XAU, XAG, ...). "" for non-pair-scoped
                  alerts (account balance, MT5 lag, etc).
    template_key— matches notification_templates.template_key when present;
                  for ad-hoc alerts (no DB template) used only for the dedup key.
    title       — short headline shown on popup / Feishu card.
    message     — full body.
    severity    — info / warn / danger / critical
    cooldown_s  — minimum gap between identical emits (per dedup key).
                  0 disables dedup.
    payload     — extra context, persisted to agent_alerts.payload.
    """

    user_id: str
    template_key: str
    title: str
    message: str
    pair_code: str = ""
    severity: str = Severity.WARN
    cooldown_s: int = 60
    payload: Dict[str, Any] = field(default_factory=dict)
    ack_required: bool = False

    def dedup_key(self) -> str:
        return f"alert:dedup:{self.user_id or '_global'}:{self.pair_code or '_'}:{self.template_key}"

    def ws_event_type(self) -> str:
        # Front-end already routes on "risk_alert" — reuse it for compat.
        return "risk_alert"


# ── Bus ──────────────────────────────────────────────────────────────────────
class AlertBus:
    """Singleton-style; instantiate via the module-level ``alert_bus``."""

    async def emit(self, event: AlertEvent) -> bool:
        """Emit one alert. Returns True if it cleared dedup and was fanned out,
        False if it was suppressed by the cooldown."""
        if event.severity not in _VALID_SEVERITY:
            logger.warning(f"[AlertBus] invalid severity={event.severity}, coercing to warn")
            event.severity = Severity.WARN

        if not await self._claim_dedup(event):
            logger.debug(f"[AlertBus] suppressed (cooldown): {event.dedup_key()}")
            return False

        # Fan out — each sink is independent. Failures do not propagate.
        sent_feishu = False
        try:
            sent_feishu = await self._sink_feishu(event)
        except Exception as e:
            logger.warning(f"[AlertBus] sink_feishu error: {e}")

        try:
            await self._sink_websocket(event)
        except Exception as e:
            logger.warning(f"[AlertBus] sink_websocket error: {e}")

        try:
            await self._sink_db(event, feishu_sent=sent_feishu)
        except Exception as e:
            logger.warning(f"[AlertBus] sink_db error: {e}")

        return True

    # ── Public helpers for services that keep their own fan-out
    # (templates, email, custom WS payload) but still use our cross-process
    # Redis dedup and the shared agent_alerts ledger.
    async def try_dedup(self, dedup_key: str, cooldown_s: int) -> bool:
        """Attempt to claim a dedup slot. Returns True if the caller may
        proceed with the alert, False if it should be suppressed."""
        if cooldown_s <= 0:
            return True
        event = AlertEvent(
            user_id="", template_key=dedup_key,
            title="", message="",
            cooldown_s=cooldown_s,
        )
        event.dedup_key = lambda _k=dedup_key: _k  # type: ignore[assignment]
        return await self._claim_dedup(event)

    async def persist(
        self,
        *,
        user_id: str = "",
        pair_code: str = "",
        template_key: str,
        severity: str = Severity.WARN,
        title: str = "",
        message: str = "",
        payload: Optional[Dict[str, Any]] = None,
        ack_required: bool = False,
        feishu_sent: bool = False,
    ) -> None:
        """Persist an already-delivered alert into agent_alerts."""
        event = AlertEvent(
            user_id=user_id, pair_code=pair_code,
            template_key=template_key, severity=severity,
            title=title, message=message,
            payload=payload or {}, ack_required=ack_required,
            cooldown_s=0,
        )
        try:
            await self._sink_db(event, feishu_sent=feishu_sent)
        except Exception as e:
            logger.warning(f"[AlertBus] persist error: {e}")

    # ── Dedup ────────────────────────────────────────────────────────────────
    async def _claim_dedup(self, event: AlertEvent) -> bool:
        if event.cooldown_s <= 0:
            return True
        rc = redis_client.client
        if rc is None:
            # Redis down — fall back to a process-local cache so a Redis blip
            # doesn't unleash an alert storm.
            return _local_dedup_claim(event.dedup_key(), event.cooldown_s)
        try:
            ok = await rc.set(event.dedup_key(), "1", ex=event.cooldown_s, nx=True)
            return bool(ok)
        except Exception as e:
            logger.warning(f"[AlertBus] redis dedup error: {e}")
            return _local_dedup_claim(event.dedup_key(), event.cooldown_s)

    # ── Sinks ────────────────────────────────────────────────────────────────
    async def _sink_feishu(self, event: AlertEvent) -> bool:
        """Send Feishu card to the owning user (or fan out to admins for
        system-wide events with no user_id)."""
        from app.services.feishu_service import get_feishu_service

        feishu = get_feishu_service()
        if feishu is None:
            return False

        recipients = await self._resolve_feishu_recipients(event.user_id, event.template_key)
        if not recipients:
            return False

        title = f"[{event.severity.upper()}] {event.title}"
        sent_any = False
        for r in recipients:
            try:
                color = {
                    Severity.INFO: "blue",
                    Severity.WARN: "orange",
                    Severity.DANGER: "red",
                    Severity.CRITICAL: "red",
                }.get(event.severity, "blue")
                res = await feishu.send_card_message(
                    receive_id=r["receive_id"],
                    title=title,
                    content=event.message,
                    receive_id_type=r["receive_id_type"],
                    color=color,
                )
                if res.get("success"):
                    sent_any = True
            except Exception as e:
                logger.debug(f"[AlertBus] feishu send to {r['receive_id']} failed: {e}")
        return sent_any

    async def _sink_websocket(self, event: AlertEvent) -> None:
        msg = {
            "type": event.ws_event_type(),
            "data": {
                "template_key": event.template_key,
                "pair_code": event.pair_code,
                "severity": event.severity,
                "title": event.title,
                "message": event.message,
                "payload": event.payload,
                "ack_required": event.ack_required,
                "ts": int(time.time() * 1000),
            },
        }
        if event.user_id:
            await ws_manager.send_to_user(msg, event.user_id)
            # Stream hub: per-user alerts channel (Python WS /api/v1/ws subscribers)
            try:
                from app.websocket.stream_hub import stream_hub
                await stream_hub.publish(f"alerts.{event.user_id}", msg["data"])
            except Exception:
                pass
            # Also publish via Redis → Go Hub for the Go WS connection (frontend-go)
            try:
                rc = redis_client.client
                if rc is not None:
                    payload = {"user_id": event.user_id, **msg}
                    await rc.publish("ws:user_event", json.dumps(payload))
            except Exception:
                pass
        else:
            # System-wide: broadcast
            await ws_manager.broadcast(msg)
            try:
                from app.websocket.stream_hub import stream_hub
                await stream_hub.publish("alerts.global", msg["data"])
            except Exception:
                pass
            try:
                rc = redis_client.client
                if rc is not None:
                    await rc.publish("ws:broadcast", json.dumps(msg))
            except Exception:
                pass

    async def _sink_db(self, event: AlertEvent, feishu_sent: bool) -> None:
        """Persist to agent_alerts. Schema constraints: level in
        (info, warn, danger, critical). user_id column does not exist; we
        carry it inside payload for now to avoid a migration."""
        async with AsyncSessionLocal() as db:
            payload = dict(event.payload)
            payload.setdefault("user_id", event.user_id)
            payload.setdefault("pair_code", event.pair_code)
            payload.setdefault("template_key", event.template_key)
            await db.execute(
                _text(
                    "INSERT INTO agent_alerts (level, category, message, payload, "
                    "feishu_sent, ack_required) "
                    "VALUES (:level, :category, :message, CAST(:payload AS JSONB), "
                    ":feishu_sent, :ack_required)"
                ),
                {
                    "level": event.severity,
                    "category": event.template_key or "ad_hoc",
                    "message": event.message,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "feishu_sent": feishu_sent,
                    "ack_required": event.ack_required,
                },
            )
            await db.commit()

    # ── Recipients ───────────────────────────────────────────────────────────
    async def _resolve_feishu_recipients(self, user_id: str, template_key: str = "") -> list:
        """Return a list of {receive_id, receive_id_type, user_id} dicts.

        - If user_id is given: only that user (if they have a Feishu binding
          AND have not disabled feishu in their notification settings).
        - If empty: fan out to admin/operator users with a Feishu binding.
        """
        recipients: list = []
        seen_ids: set = set()
        async with AsyncSessionLocal() as db:
            if user_id:
                # 1. Trader self (primary recipient)
                row = (
                    await db.execute(
                        _text(
                            "SELECT u.feishu_open_id, u.feishu_mobile, u.email, "
                            "  COALESCE(s.feishu_enabled, true) AS feishu_enabled "
                            "FROM users u "
                            "LEFT JOIN user_notification_settings s "
                            "  ON s.user_id = u.user_id "
                            "WHERE u.user_id = CAST(:uid AS UUID)"
                        ),
                        {"uid": user_id},
                    )
                ).first()
                if row and row[3]:
                    if row[0] and row[0] not in seen_ids:
                        recipients.append({"receive_id": row[0], "receive_id_type": "open_id"})
                        seen_ids.add(row[0])
                    elif row[1] and row[1] not in seen_ids:
                        recipients.append({"receive_id": row[1], "receive_id_type": "mobile"})
                        seen_ids.add(row[1])
                    elif row[2] and row[2] not in seen_ids:
                        recipients.append({"receive_id": row[2], "receive_id_type": "email"})
                        seen_ids.add(row[2])
                # 2. Fan-out to subscribers of this trader for the matching template
                try:
                    rows = (
                        await db.execute(
                            _text(
                                "SELECT DISTINCT su.feishu_open_id "
                                "FROM notification_subscriptions ns "
                                "JOIN users su ON su.user_id = ns.subscriber_user_id "
                                "JOIN notification_templates nt ON nt.template_id = ns.template_id "
                                "LEFT JOIN user_notification_settings uns ON uns.user_id = su.user_id "
                                "WHERE ns.trader_user_id = CAST(:uid AS UUID) "
                                "  AND ns.is_enabled = true "
                                "  AND nt.template_key = :tk "
                                "  AND su.feishu_open_id IS NOT NULL AND su.feishu_open_id <> '' "
                                "  AND su.user_id <> CAST(:uid AS UUID) "
                                "  AND COALESCE(uns.feishu_enabled, true) = true"
                            ),
                            {"uid": user_id, "tk": template_key or ""},
                        )
                    ).fetchall()
                    for r in rows:
                        if r[0] and r[0] not in seen_ids:
                            recipients.append({"receive_id": r[0], "receive_id_type": "open_id"})
                            seen_ids.add(r[0])
                except Exception as _sub_err:
                    logger.debug(f"[alert_bus] subscribers fan-out failed: {_sub_err}")
                return recipients

            # System-wide fan-out (no target user_id): deliver to admin /
            # operator / security-admin roles with a Feishu binding. The
            # `users.openclaw_enabled` column is the per-user auto.hustle2026.xyz
            # login flag and MUST NOT be used as a recipient filter here.
            rows = (
                await db.execute(
                    _text(
                        "SELECT u.feishu_open_id FROM users u "
                        "WHERE u.feishu_open_id IS NOT NULL AND u.feishu_open_id <> '' "
                        "AND u.is_active = true "
                        "AND (u.role IN ('超级管理员','系统管理员','安全管理员') "
                        "     OR COALESCE(u.role,'user') IN ('admin','operator','security_admin'))"
                    )
                )
            ).fetchall()
            for r in rows:
                recipients.append({"receive_id": r[0], "receive_id_type": "open_id"})
            return recipients


# ── Local-fallback dedup (Redis down) ────────────────────────────────────────
_local_dedup: Dict[str, float] = {}


def _local_dedup_claim(key: str, ttl_s: int) -> bool:
    now = time.monotonic()
    expires = _local_dedup.get(key, 0.0)
    if now < expires:
        return False
    _local_dedup[key] = now + ttl_s
    # Opportunistic cleanup
    if len(_local_dedup) > 2048:
        for k in [k for k, v in _local_dedup.items() if v < now]:
            _local_dedup.pop(k, None)
    return True


# Module singleton
alert_bus = AlertBus()
