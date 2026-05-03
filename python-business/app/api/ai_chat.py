import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models_ai import AiConfig, AiConversation, AiMessage, AiFaq
from app.db.session import get_db, SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/chat", tags=["ai-chat"])

PROVIDER_URLS = {
    "claude": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    site: str = "coin"


def _get_config(db: Session, site: str) -> AiConfig | None:
    cfg = db.query(AiConfig).filter(AiConfig.site == site).first()
    if not cfg:
        cfg = db.query(AiConfig).filter(AiConfig.site == "default").first()
    return cfg


def _build_faq_context(db: Session) -> str:
    faqs = db.query(AiFaq).filter(AiFaq.is_active == True).order_by(AiFaq.sort_order).all()
    if not faqs:
        return ""
    lines = ["\n--- FAQ Knowledge Base ---"]
    for f in faqs:
        lines.append(f"Q: {f.question}\nA: {f.answer}")
    return "\n".join(lines)


def _get_or_create_conversation(db: Session, site: str, session_id: str, user_id: int | None) -> AiConversation:
    conv = db.query(AiConversation).filter(
        AiConversation.session_id == session_id,
        AiConversation.site == site,
    ).first()
    if not conv:
        conv = AiConversation(site=site, user_id=user_id, session_id=session_id)
        db.add(conv)
        db.flush()
    return conv


def _get_history_messages(db: Session, conversation_id: int, limit: int = 20) -> list[dict]:
    msgs = (
        db.query(AiMessage)
        .filter(AiMessage.conversation_id == conversation_id)
        .order_by(AiMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(msgs)]


async def _stream_claude(api_key: str, model: str, system_prompt: str,
                         messages: list[dict], max_tokens: int, temperature: float,
                         base_url: str | None = None):
    url = f"{base_url}/v1/messages" if base_url else PROVIDER_URLS["claude"]
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": messages,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                logger.error(f"Claude API error {resp.status_code}: {err.decode()}")
                yield f"data: {json.dumps({'error': 'AI service error'})}\n\n"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    evt = json.loads(payload)
                    if evt.get("type") == "content_block_delta":
                        text = evt.get("delta", {}).get("text", "")
                        if text:
                            yield f"data: {json.dumps({'content': text})}\n\n"
                    elif evt.get("type") == "message_delta":
                        usage = evt.get("usage", {})
                        if usage:
                            yield f"data: {json.dumps({'usage': usage})}\n\n"
                except json.JSONDecodeError:
                    pass


async def _stream_openai(api_key: str, model: str, system_prompt: str,
                         messages: list[dict], max_tokens: int, temperature: float,
                         base_url: str | None = None):
    url = f"{base_url}/v1/chat/completions" if base_url else PROVIDER_URLS["openai"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    oai_messages = [{"role": "system", "content": system_prompt}] + messages
    body = {
        "model": model,
        "messages": oai_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                logger.error(f"OpenAI API error {resp.status_code}: {err.decode()}")
                yield f"data: {json.dumps({'error': 'AI service error'})}\n\n"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield f"data: {json.dumps({'content': text})}\n\n"
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass


@router.post("")
async def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    session_id = req.session_id or str(uuid.uuid4())

    config = _get_config(db, req.site)
    if not config or not config.is_enabled:
        raise HTTPException(status_code=503, detail="AI service is not enabled")
    if not config.api_key:
        raise HTTPException(status_code=503, detail="AI service not configured")

    conv = _get_or_create_conversation(db, req.site, session_id, user_id)
    history = _get_history_messages(db, conv.id)

    user_msg = AiMessage(conversation_id=conv.id, role="user", content=req.message, token_count=len(req.message) // 4)
    db.add(user_msg)
    conv.message_count = (conv.message_count or 0) + 1
    if not conv.title and len(req.message) > 0:
        conv.title = req.message[:100]
    db.commit()

    messages = history + [{"role": "user", "content": req.message}]
    faq_ctx = _build_faq_context(db)
    system_prompt = (config.system_prompt or "") + faq_ctx

    conv_id = conv.id
    collected_text: list[str] = []
    total_output_tokens = 0

    async def generate():
        nonlocal total_output_tokens
        provider = config.provider or "claude"
        custom_base = config.base_url if config.base_url else None
        if provider == "claude":
            streamer = _stream_claude(config.api_key, config.model_name, system_prompt,
                                      messages, config.max_tokens, config.temperature, custom_base)
        else:
            streamer = _stream_openai(config.api_key, config.model_name, system_prompt,
                                      messages, config.max_tokens, config.temperature, custom_base)

        async for chunk in streamer:
            yield chunk
            try:
                data = json.loads(chunk.replace("data: ", "").strip())
                if "content" in data:
                    collected_text.append(data["content"])
                if "usage" in data:
                    total_output_tokens = data["usage"].get("output_tokens", 0)
            except (json.JSONDecodeError, ValueError):
                pass

        yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'conversation_id': conv_id})}\n\n"

        full_reply = "".join(collected_text)
        if full_reply:
            save_db = SessionLocal()
            try:
                assistant_msg = AiMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=full_reply,
                    token_count=total_output_tokens or len(full_reply) // 4,
                )
                save_db.add(assistant_msg)
                save_conv = save_db.query(AiConversation).filter(AiConversation.id == conv_id).first()
                if save_conv:
                    save_conv.message_count = (save_conv.message_count or 0) + 1
                    save_conv.token_used = (save_conv.token_used or 0) + total_output_tokens + (len(req.message) // 4)
                save_db.commit()
            finally:
                save_db.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/history")
def chat_history(request: Request, db: Session = Depends(get_db),
                 search: str | None = None, site: str | None = None):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return []
    q = db.query(AiConversation).filter(AiConversation.user_id == user_id)
    if site:
        q = q.filter(AiConversation.site == site)
    if search:
        q = q.filter(AiConversation.title.ilike(f"%{search}%"))
    convs = q.order_by(AiConversation.updated_at.desc()).limit(50).all()
    return [
        {
            "id": c.id,
            "site": c.site,
            "session_id": c.session_id,
            "title": c.title or "",
            "message_count": c.message_count,
            "created_at": str(c.created_at) if c.created_at else None,
            "updated_at": str(c.updated_at) if c.updated_at else None,
        }
        for c in convs
    ]


@router.get("/history/{conversation_id}")
def chat_messages(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    conv = db.query(AiConversation).filter(AiConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (
        db.query(AiMessage)
        .filter(AiMessage.conversation_id == conversation_id)
        .order_by(AiMessage.id)
        .all()
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "token_count": m.token_count,
            "created_at": str(m.created_at) if m.created_at else None,
        }
        for m in msgs
    ]


@router.delete("/history/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    conv = db.query(AiConversation).filter(AiConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id and conv.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your conversation")
    db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"message": "Conversation deleted"}
