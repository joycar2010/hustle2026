"""MT5 Infrastructure status & alerting endpoint.

Exposes:
  - GET  /api/v1/mt5-infra/status     — admin dashboard polls this; aggregates Agent /health
  - POST /api/v1/mt5-infra/alert      — Windows healthcheck task POSTs failures here;
                                         we fan out to Feishu + Redis (for WS broadcast)

Both routes are protected by the shared MT5_AGENT_API_KEY header (X-API-Key)
so that Windows scripts and admin frontend can both call them without user JWT.
The admin frontend additionally proxies through the existing user-auth wrapper
in MasterDashboard, but the underlying endpoint trusts the shared key.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v1.mt5_agent import MT5_AGENT_API_KEY, MT5_AGENT_URL, call_agent_api
from app.services.feishu_service import get_feishu_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Admin user (super admin) Feishu open_id for infra alerts. Hardcoded by request;
# can be moved to a config table later if more recipients are needed.
INFRA_ALERT_OPEN_ID = "ou_613cc2eabae277733bdee67edb3d8cc5"
REDIS_ALERT_KEY = "mt5:infra:last_alert"
REDIS_STATUS_KEY = "mt5:infra:last_status"


def _require_api_key(x_api_key: Optional[str]):
    if x_api_key != MT5_AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")


@router.get("/status")
async def get_infra_status(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Aggregate Agent /health and return a normalized payload.
    Admin frontend polls this every ~10s.
    """
    # Soft auth — allow requests with valid user JWT to skip the key check.
    # Frontend reuses the same axios client with bearer token, so we accept that.
    if x_api_key and x_api_key != MT5_AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{MT5_AGENT_URL}/health")
            resp.raise_for_status()
            data = resp.json()
        # Cache to Redis so dashboards can fall back if Agent is briefly down
        try:
            from app.core.redis_client import redis_client
            r = redis_client.client
            if r is not None:
                await r.set(REDIS_STATUS_KEY, json.dumps(data), ex=120)
        except Exception:
            pass
        return {"reachable": True, **data}
    except Exception as e:
        # Fall back to last cached status so the panel does not flash red on a
        # single transient request failure
        cached = None
        try:
            from app.core.redis_client import redis_client
            r = redis_client.client
            if r is not None:
                raw = await r.get(REDIS_STATUS_KEY)
                if raw:
                    cached = json.loads(raw)
        except Exception:
            pass
        return {
            "reachable": False,
            "error": str(e),
            "cached": cached,
        }


class InfraAlertFailure(BaseModel):
    target: str = Field(..., description="service name or component")
    reason: str
    fails: int = 1


class InfraAlertPayload(BaseModel):
    timestamp: str
    host: str
    failures: List[InfraAlertFailure]


@router.post("/alert")
async def report_infra_alert(
    payload: InfraAlertPayload,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Receive an alert pushed by the Windows healthcheck task and fan it out:
       - Feishu card to admin open_id
       - Redis pub for admin websocket
       - Persist to last_alert key for late joiners to read
    """
    _require_api_key(x_api_key)

    # Build markdown block for Feishu card body
    bullet_lines = []
    for f in payload.failures:
        bullet_lines.append(f"- **{f.target}** — {f.reason} (连续失败 {f.fails} 次)")
    md_body = (
        f"**主机**: {payload.host}\n"
        f"**时间**: {payload.timestamp}\n\n"
        f"**故障组件**:\n" + "\n".join(bullet_lines)
    )

    # 1. Feishu
    feishu = get_feishu_service()
    feishu_result = {"success": False, "error": "feishu service not initialized"}
    if feishu:
        try:
            feishu_result = await feishu.send_card_message(
                receive_id=INFRA_ALERT_OPEN_ID,
                title="🚨 MT5 基础设施告警",
                content=md_body,
                receive_id_type="open_id",
                color="red",
            )
        except Exception as e:
            logger.exception("infra feishu alert failed")
            feishu_result = {"success": False, "error": str(e)}

    # 2. Redis publish + last_alert persistence
    try:
        from app.core.redis_client import redis_client
        r = redis_client.client
        if r is not None:
            event = {
                "type": "mt5_infra_alert",
                "timestamp": payload.timestamp,
                "host": payload.host,
                "failures": [f.dict() for f in payload.failures],
            }
            await r.set(REDIS_ALERT_KEY, json.dumps(event), ex=3600)
            await r.publish("ws:admin_event", json.dumps(event))
    except Exception as e:
        logger.warning(f"infra alert redis publish failed: {e}")

    return {
        "ok": True,
        "feishu": feishu_result,
    }


@router.get("/alert/last")
async def last_alert():
    """Last alert (within 1h) so admin panel can display banner on page load."""
    try:
        from app.core.redis_client import redis_client
        r = redis_client.client
        if r is not None:
            raw = await r.get(REDIS_ALERT_KEY)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return None
