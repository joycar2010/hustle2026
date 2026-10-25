import json
import time

import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/engine", tags=["engine"])


class CommandRequest(BaseModel):
    action: str  # "pause", "resume", "stop"
    target: str = "global"


class CommandResponse(BaseModel):
    message: str
    action: str
    target: str


@router.post("/command", response_model=CommandResponse)
async def send_command(cmd: CommandRequest):
    if cmd.action not in ("pause", "resume", "stop"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown action: {cmd.action}")

    r = aioredis.from_url(settings.redis_url)
    msg = json.dumps({"action": cmd.action, "target": cmd.target, "ts": int(time.time() * 1000)})
    await r.publish("engine:commands", msg)
    await r.aclose()

    return CommandResponse(
        message=f"Command '{cmd.action}' sent to {cmd.target}",
        action=cmd.action,
        target=cmd.target,
    )
