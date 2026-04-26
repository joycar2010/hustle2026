"""Patch codex_client.py to add LLM fallback/degradation logic.
- Retry with exponential backoff on timeout/5xx
- Fallback to cheaper model on persistent failure
- Circuit breaker pattern (5 failures in 5min → noop for 2min)
"""
import re

path = "/data/hustle2026/backend/app/services/agent/codex_client.py"
with open(path, "r") as f:
    c = f.read()

# 1. Add imports at top
old_imports = "import json\nimport os\nimport re\nimport time"
new_imports = """import json
import logging
import os
import re
import time
import asyncio
from collections import deque"""
c = c.replace(old_imports, new_imports, 1)

# 2. Add circuit breaker state after _MODEL_TTL
old_ttl = "_MODEL_TTL = 5.0"
new_ttl = """_MODEL_TTL = 5.0

# ── LLM degradation / circuit breaker ──
_FALLBACK_MODELS = ['deepseek-v3.2', 'deepseek-r1', 'gpt-4.1-mini']
_failure_log: deque = deque(maxlen=20)  # timestamps of recent failures
_CIRCUIT_WINDOW = 300   # 5 minutes
_CIRCUIT_THRESHOLD = 5  # failures to trip
_CIRCUIT_COOLDOWN = 120 # 2 minutes open
_circuit_open_until: float = 0.0
_logger = logging.getLogger(__name__)


def _is_circuit_open() -> bool:
    return time.time() < _circuit_open_until


def _record_failure():
    global _circuit_open_until
    now = time.time()
    _failure_log.append(now)
    recent = sum(1 for t in _failure_log if now - t < _CIRCUIT_WINDOW)
    if recent >= _CIRCUIT_THRESHOLD:
        _circuit_open_until = now + _CIRCUIT_COOLDOWN
        _logger.warning(
            '[codex_client] circuit breaker OPEN — %d failures in %ds, cooling down %ds',
            recent, _CIRCUIT_WINDOW, _CIRCUIT_COOLDOWN
        )


def _pick_fallback_model(primary: str) -> str:
    for fb in _FALLBACK_MODELS:
        if fb != primary:
            return fb
    return _FALLBACK_MODELS[0]"""
c = c.replace(old_ttl, new_ttl, 1)

# 3. Replace call_decider with retry+fallback version
old_func_sig = "async def call_decider(\n    system_prompt: str, user_prompt: str,\n    temperature: float = 0.1, db=None,\n) -> Tuple[Optional[Dict[str, Any]], Dict[str, int], int]:"

# Find the function and replace it entirely
func_start = c.find(old_func_sig)
assert func_start >= 0, "call_decider signature not found"

new_call_decider = '''async def call_decider(
    system_prompt: str, user_prompt: str,
    temperature: float = 0.1, db=None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, int], int]:
    # Circuit breaker check — return noop immediately if open
    if _is_circuit_open():
        _logger.warning('[codex_client] circuit breaker OPEN, returning noop fallback')
        noop = {"action": "noop", "leg": "both", "qty": 0.0,
                "reason": "LLM circuit breaker open — service degraded, waiting for recovery",
                "trigger": "circuit_breaker", "confidence": 0.0, "is_rebalance_補腿": False}
        return noop, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, 0

    client = get_client()
    if db is not None:
        model, stream_enabled = await get_runtime_model_and_stream(db)
    else:
        import logging as _logging
        model = os.getenv('OPENCLAW_LLM_MODEL', 'gpt-5.2')
        stream_enabled = True
        _logging.getLogger(__name__).warning(
            '[codex_client] call_decider invoked without db session; '
            'using env/default model=%s', model
        )

    # Retry with fallback: primary model → retry → fallback model → retry
    models_to_try = [model, model, _pick_fallback_model(model)]
    delays = [0, 2, 5]  # seconds before each attempt

    for attempt, (try_model, delay) in enumerate(zip(models_to_try, delays)):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            proposal, usage, latency_ms = await _do_llm_call(
                client, try_model, stream_enabled,
                system_prompt, user_prompt, temperature
            )
            if attempt > 0:
                _logger.info('[codex_client] succeeded on attempt %d with model %s', attempt + 1, try_model)
            return proposal, usage, latency_ms
        except Exception as e:
            _logger.warning('[codex_client] attempt %d/%d failed (model=%s): %s',
                           attempt + 1, len(models_to_try), try_model, str(e)[:200])
            _record_failure()
            if attempt == len(models_to_try) - 1:
                _logger.error('[codex_client] all %d attempts exhausted, returning noop', len(models_to_try))
                noop = {"action": "noop", "leg": "both", "qty": 0.0,
                        "reason": f"LLM degraded: {str(e)[:100]}",
                        "trigger": "llm_fallback", "confidence": 0.0, "is_rebalance_補腿": False}
                return noop, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, 0
    # unreachable
    return None, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, 0


async def _do_llm_call(
    client: AsyncOpenAI, model: str, stream_enabled: bool,
    system_prompt: str, user_prompt: str, temperature: float,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, int], int]:
    t0 = time.time()
    text = ''
    usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

    if stream_enabled:
        chunks = []
        last_usage = None
        stream = await client.chat.completions.create(
            model=model, temperature=temperature,
            messages=[{'role': 'system', 'content': system_prompt},
                      {'role': 'user', 'content': user_prompt}],
            stream=True,
            stream_options={'include_usage': True},
            timeout=60,
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
            timeout=60,
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
    return proposal, usage, latency_ms'''

# Replace from func_start to end of file
c = c[:func_start] + new_call_decider + '\n'

with open(path, "w") as f:
    f.write(c)
print("codex_client.py patched with LLM degradation logic")
