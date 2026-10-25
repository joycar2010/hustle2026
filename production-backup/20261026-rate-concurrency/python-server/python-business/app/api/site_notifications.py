"""Public, read-only notification state consumed by the user site.

Only currently active records are exposed.  Administrative writes remain in
``admin_notify`` and require an admin JWT.  This router intentionally has no
worker or exchange integration.
"""

import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.models_notify import NotificationMaintenance, SiteNotice, SoundPersona
from app.db.session import get_db
from app.api.admin_notify import _canonical_voice, _persona_payload


router = APIRouter(prefix="/api/site", tags=["site-notifications"])
logger = logging.getLogger(__name__)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _notice_payload(item: SiteNotice) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "content": item.content,
        "enabled": bool(item.enabled),
        "starts_at": _iso(item.starts_at),
        "ends_at": _iso(item.ends_at),
        "updated_at": _iso(item.updated_at),
    }


def _maintenance_payload(item: NotificationMaintenance | None) -> dict:
    if item is None:
        return {
            "enabled": False,
            "stop_strategy": True,
            "block_trading": True,
            "block_login": False,
            "title": "",
            "content": "",
            "until_at": None,
        }
    return {
        "enabled": bool(item.enabled),
        "stop_strategy": bool(item.stop_strategy),
        "block_trading": bool(item.block_trading),
        "block_login": bool(item.block_login),
        "title": item.title,
        "content": item.content,
        "until_at": _iso(item.until_at),
        "updated_at": _iso(item.updated_at),
    }


def _active_filter(now: dt.datetime):
    return (
        SiteNotice.enabled.is_(True),
        (SiteNotice.starts_at.is_(None) | (SiteNotice.starts_at <= now)),
        (SiteNotice.ends_at.is_(None) | (SiteNotice.ends_at >= now)),
    )


@router.get("/notices/active")
def active_notices(db: Session = Depends(get_db)):
    """Return active notice and maintenance banners without authentication."""
    now = dt.datetime.now(dt.timezone.utc)
    rows = (
        db.query(SiteNotice)
        .filter(*_active_filter(now))
        .order_by(SiteNotice.kind.desc(), SiteNotice.updated_at.desc(), SiteNotice.id.desc())
        .limit(20)
        .all()
    )
    return [_notice_payload(row) for row in rows]


@router.get("/maintenance")
def public_maintenance(db: Session = Depends(get_db)):
    """Return the singleton maintenance state for login/trading UI guards."""
    item = db.query(NotificationMaintenance).filter(NotificationMaintenance.id == 1).first()
    return _maintenance_payload(item)


@router.get("/tts")
async def public_persona_tts(
    key: str = Query(..., min_length=1, max_length=40),
    text: str = Query("", max_length=240),
    db: Session = Depends(get_db),
):
    """Public, bounded voice preview used by the authenticated user marquee.

    Only enabled, persisted personas can be requested; arbitrary Edge voices
    are never accepted.  Browser TTS remains the client-side fallback when
    this optional endpoint or the Edge service is unavailable.
    """
    persona = db.query(SoundPersona).filter(SoundPersona.skey == key, SoundPersona.enabled.is_(True)).first()
    if not persona or persona.engine != "edge":
        raise HTTPException(status_code=404, detail="Sound persona unavailable")
    try:
        import edge_tts
        localized = _persona_payload(persona)
        communicate = edge_tts.Communicate(
            (text or localized["sample_text"] or "这是一条语音播报测试。").strip()[:240],
            _canonical_voice(persona.skey, persona.style or "", persona.edge_voice or persona.voice),
            rate=persona.edge_rate or "+0%",
            pitch=persona.edge_pitch or "+0Hz",
        )
        # Buffer the bounded preview before sending headers.  Edge's websocket
        # handshake can fail (for example, a regional egress returns 403); a
        # streaming response would otherwise become an incomplete 200 body and
        # produce a noisy ASGI exception.  The client can then use browser TTS.
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        audio = b"".join(chunks)
        if not audio:
            raise RuntimeError("Edge TTS returned no audio")
        return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        logger.info("public Edge TTS unavailable for %s: %s", key, exc)
        raise HTTPException(status_code=503, detail="Edge TTS unavailable") from exc
