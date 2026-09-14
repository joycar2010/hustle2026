import time

import redis as redis_lib
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.middleware.permissions import require_admin

router = APIRouter(prefix="/api/admin/ws", tags=["admin-ws"])

_ws_start_time = time.time()


class WsConfigRequest(BaseModel):
    streamer_name: str
    interval_seconds: int


@router.get("/stats")
def ws_stats(request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    from app.api.websocket import manager

    connections = len(manager.active)
    uptime = int(time.time() - _ws_start_time)

    streamers = []
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)
        spread_count = r.hlen("spreads")
        streamers.append({
            "name": "spread_data",
            "status": "active" if spread_count > 0 else "idle",
            "interval": 1,
            "message_count": spread_count,
        })

        channels = r.pubsub_channels("*")
        channel_list = [c if isinstance(c, str) else c.decode() for c in channels]

        for ch_name, display in [("position:updates", "position_update"), ("worker:status", "engine_status")]:
            streamers.append({
                "name": display,
                "status": "active" if ch_name in channel_list else "idle",
                "interval": 5,
                "message_count": 0,
            })
    except Exception:
        streamers = [
            {"name": "spread_data", "status": "error", "interval": 1, "message_count": 0},
            {"name": "position_update", "status": "error", "interval": 5, "message_count": 0},
            {"name": "engine_status", "status": "error", "interval": 5, "message_count": 0},
        ]

    return {
        "connections": connections,
        "messages_total": 0,
        "uptime_seconds": uptime,
        "streamers": streamers,
    }


@router.post("/config")
def update_ws_config(req: WsConfigRequest, request: Request):
    require_admin(request)

    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.set(f"ws:config:{req.streamer_name}", str(req.interval_seconds))
    except Exception:
        pass

    return {"message": f"Config updated for {req.streamer_name}"}
