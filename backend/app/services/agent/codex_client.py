"""OpenCLAW LLM client — OpenAI-compatible Chat Completions with hot-reloadable model
selection and streaming.

Reads selected model from agent_active_config['llm_settings']['model'] (5s LRU cache);
falls back to env OPENCLAW_LLM_MODEL.

When streaming=True (default), we still return a single accumulated content string —
streaming is purely a UX/relay-stability feature (avoids long single-shot responses
being killed by relay timeouts), not a token-by-token UI.
"""
import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple
from openai import AsyncOpenAI

_client: Optional[AsyncOpenAI] = None
_model_cache: Tuple[str, bool, float] = ('', False, 0.0)  # (model, streaming, ts)
_MODEL_TTL = 5.0


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        base_url = os.getenv('OPENCLAW_LLM_BASE_URL', '').rstrip('/')
        api_key = os.getenv('OPENCLAW_LLM_API_KEY', '')
        if not base_url or not api_key:
            raise RuntimeError('OPENCLAW_LLM_BASE_URL and OPENCLAW_LLM_API_KEY must be set')
        _client = AsyncOpenAI(base_url=base_url + '/v1', api_key=api_key, timeout=120)
    return _client


async def get_runtime_model_and_stream(db) -> Tuple[str, bool]:
    """Read model + streaming from agent_active_config (cached 5s)."""
    global _model_cache
    cached_model, cached_stream, ts = _model_cache
    if time.time() - ts < _MODEL_TTL and cached_model:
        return cached_model, cached_stream
    try:
        from app.services.agent import config_loader
        cfg = await config_loader.load_config(db)
        ls = cfg.get('llm_settings', {}) or {}
        model = ls.get('model') or os.getenv('OPENCLAW_LLM_MODEL', 'gpt-5')
        stream = bool(ls.get('streaming', True))
        _model_cache = (model, stream, time.time())
        return model, stream
    except Exception:
        return os.getenv('OPENCLAW_LLM_MODEL', 'gpt-5'), True


def invalidate_model_cache():
    global _model_cache
    _model_cache = ('', False, 0.0)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def call_decider(
    system_prompt: str, user_prompt: str,
    temperature: float = 0.1, db=None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, int], int]:
    client = get_client()
    if db is not None:
        model, stream_enabled = await get_runtime_model_and_stream(db)
    else:
        model = os.getenv('OPENCLAW_LLM_MODEL', 'gpt-5')
        stream_enabled = True

    t0 = time.time()
    text = ''
    usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

    if stream_enabled:
        chunks = []
        last_usage = None
        # stream_options.include_usage gets us the final usage block
        stream = await client.chat.completions.create(
            model=model, temperature=temperature,
            messages=[{'role': 'system', 'content': system_prompt},
                      {'role': 'user', 'content': user_prompt}],
            stream=True,
            stream_options={'include_usage': True},
        )
        async for ev in stream:
            if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
                chunks.append(ev.choices[0].delta.content)
            if getattr(ev, 'usage', None):
                last_usage = ev.usage
        text = ''.join(chunks)
        if last_usage:
            usage = {
                'prompt_tokens': getattr(last_usage, 'prompt_tokens', 0) or 0,
                'completion_tokens': getattr(last_usage, 'completion_tokens', 0) or 0,
                'total_tokens': getattr(last_usage, 'total_tokens', 0) or 0,
            }
    else:
        resp = await client.chat.completions.create(
            model=model, temperature=temperature,
            messages=[{'role': 'system', 'content': system_prompt},
                      {'role': 'user', 'content': user_prompt}],
        )
        text = resp.choices[0].message.content if resp.choices else ''
        if resp.usage:
            usage = {
                'prompt_tokens': resp.usage.prompt_tokens or 0,
                'completion_tokens': resp.usage.completion_tokens or 0,
                'total_tokens': resp.usage.total_tokens or 0,
            }

    latency_ms = int((time.time() - t0) * 1000)
    proposal = _extract_json(text or '')
    return proposal, usage, latency_ms
