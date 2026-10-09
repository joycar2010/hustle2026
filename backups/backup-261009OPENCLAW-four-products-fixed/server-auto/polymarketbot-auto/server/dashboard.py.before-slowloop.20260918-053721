"""FastAPI dashboard backend.

Polls the local SQLite (trades.db), the CLOB book of the live market, the
deposit wallet's positions, and on-chain pUSD balance. Serves /api/state for
the UI to poll, and /api/events for incremental new-row pulls.

Run:  .venv/bin/uvicorn server.dashboard:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import asyncio
import hmac
import json
import math
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import dotenv_values, load_dotenv

from bot.book import fetch_book
from bot.btc_signal import BtcSignal, fetch_btc_signal, fetch_eth_signal
from bot.config import load as load_cfg
from bot.markets import LiveMarket, fetch_live_market
from bot.resolver import resolve_pending
from bot.store import realized_pnl_summary_today
from bot.sports_main import SportsPaperService
from bot.weather_data import CITY_CONFIG, configured_city_keys, fetch_ensemble_forecast
from bot.weather_markets import fetch_weather_markets
from bot.weather_strategy import build_signal

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("TRADES_DB_PATH", str(ROOT / "trades.db"))).expanduser()

cfg = load_cfg()

# Live controls are deliberately protected by a separate operator token.  The
# dashboard is reachable through the public HTTPS hostname, so exposing a
# start/stop route without authentication would allow anybody to place real
# orders.  The token is read from .env for every request so rotating it does
# not require a dashboard restart.
_live_control_lock = threading.Lock()


def _is_polyauto_instance() -> bool:
    """Return deployment identity without relying on a copied main .env."""
    value = os.environ.get("POLYAUTO_INSTANCE", "").strip().lower()
    if value in ("1", "true", "yes", "on", "auto"):
        return True
    return str(getattr(cfg, "instance_name", "main")).strip().lower() == "polyauto"


LIVE_SERVICE_IDS = ("BTC", "ETH", "WEATHER", "SPORTS")


def _control_env_values() -> dict[str, str]:
    values = dotenv_values(ROOT / ".env")
    return {str(k): str(v or "") for k, v in values.items()}


def _service_status_snapshot() -> dict[str, Any]:
    """Expose independent, truthful live gates for each polyauto service."""
    env = _control_env_values()
    auto = _is_polyauto_instance()
    assets = _live_process_status_base()
    try:
        process_mode = (ROOT / "bot.mode").read_text(encoding="utf-8").strip().lower()
    except OSError:
        process_mode = "paper"
    btc_enabled = env.get("BTC_LIVE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    eth_enabled = env.get("ETH_TRADING_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    weather_enabled = env.get("WEATHER_LIVE_TRADING_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    # Sports intentionally has no live implementation.  Do not add a config
    # escape hatch here; the paper service rejects live mode at its boundary.
    policy = {
        "BTC": {"live_enabled": btc_enabled, "can_enable_live": True, "mode": process_mode if assets["BTC"] and process_mode in ("live", "paper") else "paper", "running": assets["BTC"]},
        # polyauto explicitly opts into BTC and ETH live independently.  The
        # weather and sports services remain paper-only below.
        "ETH": {"live_enabled": eth_enabled, "can_enable_live": True, "mode": process_mode if assets["ETH"] and process_mode in ("live", "paper") else "paper", "running": assets["ETH"]},
        "WEATHER": {"live_enabled": False, "can_enable_live": False, "mode": "paper", "running": bool(getattr(cfg, "weather_enabled", False))},
        "SPORTS": {"live_enabled": False, "can_enable_live": False, "mode": "paper", "running": bool(getattr(cfg, "sports_enabled", False))},
    }
    if auto:
        # Weather and sports remain paper-only in the isolated instance.
        for service in ("WEATHER", "SPORTS"):
            policy[service]["live_enabled"] = False
            policy[service]["mode"] = "paper"
    return policy


def _live_process_status_base() -> dict[str, bool]:
    return {
        "BTC": _pid_alive(ROOT / "bot_btc.pid") or _pid_alive(ROOT / "bot.pid"),
        "ETH": _pid_alive(ROOT / "bot_eth.pid"),
    }


def _operator_token() -> str:
    values = dotenv_values(ROOT / ".env")
    return str(values.get("DASHBOARD_CONTROL_TOKEN") or "").strip()


def _require_operator(request: Request) -> None:
    expected = _operator_token()
    supplied = request.headers.get("X-Operator-Token", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="未配置 DASHBOARD_CONTROL_TOKEN，实盘控制已禁用",
        )
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="实盘控制令牌无效")


def _deposit_wallet_address() -> str:
    """Return the configured Polymarket collateral wallet.

    Older .env files only had FUNDER_ADDRESS.  Keep that as a compatibility
    fallback while honoring an explicitly migrated DEPOSIT_WALLET_ADDRESS.
    """
    return (
        str(getattr(cfg, "deposit_wallet_address", "") or "").strip()
        or str(getattr(cfg, "funder_address", "") or "").strip()
    )

# LLM settings are intentionally kept separate from the trading strategy.  The
# dashboard exposes provider/model metadata and accepts a new secret, but GET
# never returns the secret itself.  This mirrors the Mix systemLLM relay
# settings while keeping this small service provider-agnostic.
LLM_ENV_KEYS = (
    "LLM_ENABLED", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL",
    "LLM_API_KEY", "LLM_TIMEOUT_SEC", "LLM_MAX_TOKENS", "LLM_TEMPERATURE",
    "LLM_SYSTEM_PROMPT", "LLM_ADVISOR_ENABLED",
    "LLM_PRIMARY_ENABLED", "LLM_PRIMARY_PROVIDER", "LLM_PRIMARY_BASE_URL", "LLM_PRIMARY_MODEL",
    "LLM_PRIMARY_API_KEY", "LLM_PRIMARY_TIMEOUT_SEC", "LLM_PRIMARY_MAX_TOKENS", "LLM_PRIMARY_TEMPERATURE", "LLM_PRIMARY_SYSTEM_PROMPT",
    "LLM_SECONDARY_ENABLED", "LLM_SECONDARY_PROVIDER", "LLM_SECONDARY_BASE_URL", "LLM_SECONDARY_MODEL",
    "LLM_SECONDARY_API_KEY", "LLM_SECONDARY_TIMEOUT_SEC", "LLM_SECONDARY_MAX_TOKENS", "LLM_SECONDARY_TEMPERATURE", "LLM_SECONDARY_SYSTEM_PROMPT",
)
LLM_SECRET_MASK = "••••••••"

# Last connection/probe results are memory-only and never include provider
# responses or API keys. They are exposed as health metadata for the UI.
_llm_runtime: dict[str, Any] = {
    "last_test_ts": None,
    "last_test_ok": None,
    "last_test_error": None,
    "last_probe_ts": None,
    "last_probe_count": 0,
}

# Lightweight process-local token telemetry.  Providers return usage metadata
# on chat completions; keeping a bounded aggregate here lets the dashboard
# display live consumption without persisting prompts or model responses.
_llm_usage_lock = threading.Lock()
_llm_usage: dict[str, dict[str, Any]] = {}

def _wallet_status() -> dict[str, Any]:
    deposit = _deposit_wallet_address()
    return {
        "bound": bool(deposit),
        "status": "已绑定" if deposit else "未绑定",
        "address": deposit or None,
        "balance_available": _state.get("balance_pusd") is not None,
        "value_available": _state.get("value_usd") is not None,
    }


def _record_llm_usage(model: str, usage: Any = None, *, ok: bool = True, error: str | None = None) -> None:
    name = (model or "unknown").strip() or "unknown"
    raw = usage if isinstance(usage, dict) else {}
    def number(*keys: str) -> int:
        for key in keys:
            value = raw.get(key)
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0
    prompt = number("prompt_tokens", "input_tokens")
    completion = number("completion_tokens", "output_tokens")
    total = number("total_tokens") or prompt + completion
    now = time.time()
    with _llm_usage_lock:
        item = _llm_usage.setdefault(name, {
            "model": name, "requests": 0, "errors": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "last_tokens": 0, "last_ts": None, "last_error": None,
        })
        item["requests"] += 1
        item["prompt_tokens"] += prompt
        item["completion_tokens"] += completion
        item["total_tokens"] += total
        item["last_tokens"] = total
        item["last_ts"] = now
        item["last_error"] = None if ok else (error or "request failed")
        if not ok:
            item["errors"] += 1


def _llm_usage_snapshot() -> dict[str, Any]:
    with _llm_usage_lock:
        return {"models": [dict(value) for value in _llm_usage.values()], "ts": time.time()}


class LlmSettingsPayload(BaseModel):
    enabled: bool = False
    advisor_enabled: bool = False
    provider: str = Field(default="openai-compatible", max_length=64)
    base_url: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=256)
    # None/empty means retain the existing key.  The mask is also treated as
    # retain, so a browser can round-trip GET -> PUT without replacing it.
    api_key: Optional[str] = Field(default=None, max_length=2048)
    # The provider probe/test endpoints use the same bounded timeout. Keeping
    # one limit avoids a UI value that saves successfully but is rejected when
    # the user clicks either action.
    timeout_sec: float = Field(default=15.0, ge=1.0, le=60.0)
    max_tokens: int = Field(default=512, ge=1, le=32768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    system_prompt: str = Field(default="", max_length=12000)
    primary: Optional[dict[str, Any]] = None
    secondary: Optional[dict[str, Any]] = None


class LlmProbePayload(BaseModel):
    """Transient credentials used only for GET /models probing."""

    base_url: str = Field(..., max_length=512)
    api_key: Optional[str] = Field(default=None, max_length=2048)
    timeout_sec: float = Field(default=15.0, ge=1.0, le=60.0)
    slot: str = Field(default="primary", pattern="^(primary|secondary)$")


class LlmTestPayload(BaseModel):
    """Transient connection test; it never changes trading behaviour."""

    base_url: Optional[str] = Field(default=None, max_length=512)
    model: Optional[str] = Field(default=None, max_length=256)
    api_key: Optional[str] = Field(default=None, max_length=2048)
    prompt: str = Field(
        default="请仅回复：连接成功。不要执行任何交易或调用外部工具。",
        max_length=2000,
    )
    timeout_sec: float = Field(default=20.0, ge=1.0, le=60.0)
    slot: str = Field(default="primary", pattern="^(primary|secondary)$")


def _read_llm_env() -> dict[str, str]:
    values = dotenv_values(ROOT / ".env")
    # dotenv_values returns Optional values; normalize for JSON responses.
    return {k: str(values.get(k) or "") for k in LLM_ENV_KEYS}


def _llm_settings_response() -> dict[str, Any]:
    values = _read_llm_env()
    key = values.get("LLM_API_KEY", "")
    def profile(slot: str, fallback: bool = False) -> dict[str, Any]:
        p = "LLM_" + slot.upper() + "_"
        def val(name: str, default: str = "") -> str:
            raw = values.get(p + name, "")
            if fallback and not raw:
                raw = values.get("LLM_" + name, "")
            return raw or default
        secret = val("API_KEY")
        return {"enabled": val("ENABLED", "0").lower() in ("1", "true", "yes", "on"), "provider": val("PROVIDER", "openai-compatible"), "base_url": val("BASE_URL"), "model": val("MODEL"), "api_key": LLM_SECRET_MASK if secret else "", "api_key_configured": bool(secret), "timeout_sec": float(val("TIMEOUT_SEC", "30")), "max_tokens": int(float(val("MAX_TOKENS", "512"))), "temperature": float(val("TEMPERATURE", "0.2")), "system_prompt": val("SYSTEM_PROMPT")}
    legacy = {
        "enabled": values.get("LLM_ENABLED", "0").lower() in ("1", "true", "yes", "on"),
        "advisor_enabled": values.get("LLM_ADVISOR_ENABLED", "0").lower() in ("1", "true", "yes", "on"),
        "provider": values.get("LLM_PROVIDER") or "openai-compatible",
        "base_url": values.get("LLM_BASE_URL", ""),
        "model": values.get("LLM_MODEL", ""),
        "api_key": LLM_SECRET_MASK if key else "",
        "api_key_configured": bool(key),
        "timeout_sec": float(values.get("LLM_TIMEOUT_SEC") or 15),
        "max_tokens": int(float(values.get("LLM_MAX_TOKENS") or 512)),
        "temperature": float(values.get("LLM_TEMPERATURE") or 0.2),
        "system_prompt": values.get("LLM_SYSTEM_PROMPT", ""),
        "requires_restart": True,
        "health": {
            "last_test_ts": _llm_runtime["last_test_ts"],
            "last_test_ok": _llm_runtime["last_test_ok"],
            "last_test_error": _llm_runtime["last_test_error"],
            "last_probe_ts": _llm_runtime["last_probe_ts"],
            "last_probe_count": _llm_runtime["last_probe_count"],
            "usage": _llm_usage_snapshot(),
        },
    }
    legacy["primary"] = profile("PRIMARY", True)
    legacy["secondary"] = profile("SECONDARY", False)
    return legacy


def _quote_env(value: str) -> str:
    # dotenv-compatible double quoted value; escape backslash/quote/newlines.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _write_llm_env(payload: LlmSettingsPayload) -> None:
    if payload.base_url:
        parsed = urlparse(payload.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=400, detail="base_url 必须是 http(s) URL")
    env_path = ROOT / ".env"
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = original.splitlines()
    primary = payload.primary or {}
    secondary = payload.secondary or {}
    def pick(obj: dict[str, Any], name: str, fallback: Any) -> Any:
        value = obj.get(name)
        return fallback if value is None else value
    updates = {
        "LLM_ENABLED": "1" if payload.enabled else "0",
        "LLM_ADVISOR_ENABLED": "1" if payload.advisor_enabled else "0",
        "LLM_PROVIDER": payload.provider.strip() or "openai-compatible",
        "LLM_BASE_URL": payload.base_url.strip(),
        "LLM_MODEL": payload.model.strip(),
        "LLM_TIMEOUT_SEC": str(payload.timeout_sec),
        "LLM_MAX_TOKENS": str(payload.max_tokens),
        "LLM_TEMPERATURE": str(payload.temperature),
        "LLM_SYSTEM_PROMPT": payload.system_prompt,
    }
    if payload.api_key is not None and payload.api_key.strip() and payload.api_key.strip() != LLM_SECRET_MASK:
        updates["LLM_API_KEY"] = payload.api_key.strip()
    for slot, obj, fallback in (("PRIMARY", primary, payload), ("SECONDARY", secondary, None)):
        prefix = "LLM_" + slot + "_"
        updates[prefix + "ENABLED"] = "1" if bool(pick(obj, "enabled", getattr(fallback, "enabled", False))) else "0"
        updates[prefix + "PROVIDER"] = str(pick(obj, "provider", getattr(fallback, "provider", "openai-compatible")) or "openai-compatible")
        updates[prefix + "BASE_URL"] = str(pick(obj, "base_url", getattr(fallback, "base_url", "")) or "")
        updates[prefix + "MODEL"] = str(pick(obj, "model", getattr(fallback, "model", "")) or "")
        updates[prefix + "TIMEOUT_SEC"] = str(pick(obj, "timeout_sec", getattr(fallback, "timeout_sec", 30)) or 30)
        updates[prefix + "MAX_TOKENS"] = str(pick(obj, "max_tokens", getattr(fallback, "max_tokens", 512)) or 512)
        updates[prefix + "TEMPERATURE"] = str(pick(obj, "temperature", getattr(fallback, "temperature", 0.2)) or 0.2)
        updates[prefix + "SYSTEM_PROMPT"] = str(pick(obj, "system_prompt", getattr(fallback, "system_prompt", "")) or "")
        key_value = pick(obj, "api_key", None)
        if isinstance(key_value, str) and key_value.strip() and key_value.strip() != LLM_SECRET_MASK:
            updates[prefix + "API_KEY"] = key_value.strip()
    seen: set[str] = set()
    out: list[str] = []
    key_re = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
    for line in lines:
        match = key_re.match(line)
        key = match.group(1) if match else ""
        if key in updates:
            out.append(f"{key}={_quote_env(updates[key])}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={_quote_env(value)}")
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    tmp.replace(env_path)
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass


# In-memory rolling state, refreshed by background tasks.
_state: dict[str, Any] = {
    "ts": 0.0,
    "market": None,           # LiveMarket as dict
    "eth_market": None,
    "book_up": None,
    "book_down": None,
    "eth_book_up": None,
    "eth_book_down": None,
    "btc_signal": None,
    "eth_signal": None,
    # Short rolling spot-price history used by the dashboard's background
    # volatility charts.  Keeping this in the dashboard process avoids adding
    # another database write on every market-data tick.
    "btc_price_history": [],
    "eth_price_history": [],
    "balance_pusd": None,     # on-chain pUSD in deposit wallet
    "positions": [],          # data-api positions for deposit wallet
    "value_usd": None,        # data-api value endpoint
    "bot_running": False,
    "bot_assets": {"BTC": False, "ETH": False},
    "errors": {},             # last error per poller for debugging
    # Informational feeds displayed in the dashboard.  Weather is read-only
    # forecast data; sports is backed by the isolated paper service and never
    # submits CLOB orders.
    "weather": [],
    "sports": [],
    "sports_meta": {},
    "agent_status": {},
}

OPENCLAW_AGENT_IDS = ("desk", "search", "whale", "shill", "risk", "sniper", "exit", "rug")


def _openclaw_scope_defaults() -> tuple[dict[str, str], dict[str, Any]]:
    """Build market-data and execution scopes independently."""
    env = _control_env_values()
    try:
        process_mode = (ROOT / "bot.mode").read_text(encoding="utf-8").strip().lower()
    except OSError:
        process_mode = "paper"
    data_scope = {"BTC": "live" if process_mode in ("live", "paper") else "paper",
                  "ETH": "live" if process_mode in ("live", "paper") else "paper",
                  "WEATHER": "paper", "SPORTS": "paper"}
    btc_live = env.get("BTC_LIVE_ENABLED", "false").lower() in ("1", "true", "yes", "on") and process_mode == "live"
    eth_live = env.get("ETH_TRADING_ENABLED", "false").lower() in ("1", "true", "yes", "on") and process_mode == "live"
    execution = {role: ("btc_l2_live" if role == "sniper" and btc_live else
                        "btc_close_only_live" if role == "exit" and btc_live else
                        "btc_emergency_live" if role == "rug" and btc_live else
                        "risk_gate" if role == "risk" else "read_only")
                 for role in OPENCLAW_AGENT_IDS}
    if eth_live and not btc_live:
        execution.update({"sniper": "eth_l2_live", "exit": "eth_close_only_live", "rug": "eth_emergency_live"})
    return data_scope, execution

def _agent_status_snapshot() -> dict[str, Any]:
    """Expose truthful worker health for the UI; no OpenClaw worker is implied."""
    heartbeat_path = ROOT / "openclaw-heartbeat.json"
    try:
        if heartbeat_path.exists() and time.time() - heartbeat_path.stat().st_mtime < 20:
            payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                instance = str(payload.get("instance", "")).strip().lower()
                pid = int(payload.get("pid", 0) or 0)
                expected = "polyauto" if _is_polyauto_instance() else "main"
                pid_alive = False
                if pid > 0:
                    try:
                        os.kill(pid, 0)
                        pid_alive = True
                    except (OSError, ProcessLookupError, ValueError):
                        pid_alive = False
                roles = payload.get("roles")
                if instance == expected and pid_alive and isinstance(roles, dict) and all(role in roles for role in OPENCLAW_AGENT_IDS):
                    default_scope, default_execution = _openclaw_scope_defaults()
                    payload_models = payload.get("model_calls") or payload.get("models") or {}
                    normalized: dict[str, Any] = {}
                    for role in OPENCLAW_AGENT_IDS:
                        item = dict(roles.get(role) or {})
                        item.setdefault("data_scope", dict(default_scope))
                        if isinstance(item.get("data_scope"), str):
                            item["data_scope"] = dict(default_scope)
                        item.setdefault("execution_scope", default_execution.get(role, "read_only"))
                        item.setdefault("model_calls", payload_models if isinstance(payload_models, dict) else {})
                        normalized[role] = item
                    return normalized
    except (OSError, ValueError, TypeError):
        pass
    running = bool(_state.get("bot_running"))
    paper_mode = _state.get("bot_mode") != "live"
    default_scope, default_execution = _openclaw_scope_defaults()
    result: dict[str, Any] = {}
    for agent in OPENCLAW_AGENT_IDS:
        # The local Paper publisher represents all eight roles.  A role with
        # an empty queue is healthy and waiting, so expose it as running;
        # Paper mode itself remains the permission boundary for execution.
        status = "running" if running else "offline"
        result[agent] = {"status": status, "heartbeat_ts": time.time() if running else None, "queue_depth": 0, "market": "BTC/ETH", "mode": "paper" if paper_mode else "live", "detail": "Paper service; no OpenClaw signing permission" if paper_mode else "driven by strategy service"}
        result[agent].update({"data_scope": dict(default_scope), "execution_scope": default_execution.get(agent, "read_only"), "model_calls": {"primary": "waiting", "secondary": "waiting"}})
    return result

def _openclaw_bridge_snapshot() -> dict[str, Any]:
    """Expose the read-only OpenClaw event bridge and its execution owner."""
    heartbeat_path = ROOT / "openclaw-heartbeat.json"
    try:
        if heartbeat_path.exists() and time.time() - heartbeat_path.stat().st_mtime < 20:
            payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            bridge = payload.get("bridge")
            if isinstance(bridge, dict):
                return bridge
    except (OSError, ValueError, TypeError):
        pass
    return {"connected": False, "read_only": True, "strategy_owner": "deterministic-worker", "execution_owner": "l2-gateway"}

# Keep one service instance so paper decisions/exposure accumulate across
# dashboard polling cycles.  It has no live client and is deliberately not
# shared with the BTC/ETH workers.
_sports_service = SportsPaperService(cfg)

_PRICE_HISTORY_LIMIT = 180


def _record_price_history(asset: str, market_slug: str, signal: BtcSignal) -> None:
    """Append a sampled spot price for the dashboard chart.

    A new market window starts a fresh trace so the chart never joins prices
    from unrelated five-minute markets.  Values are intentionally kept small
    and serialisable; the UI normalises them to fit its compact SVG viewBox.
    """
    key = "eth_price_history" if asset == "ETH" else "btc_price_history"
    history = _state.setdefault(key, [])
    if history and history[-1].get("market_slug") != market_slug:
        history.clear()
    try:
        point = {
            "ts": float(signal.ts),
            "price": float(signal.current_price),
            "delta_usd": float(signal.delta_usd),
            "market_slug": market_slug,
        }
    except (TypeError, ValueError):
        return
    # Pollers can briefly return the same timestamp after a provider cache
    # hit.  Replace that sample instead of creating a visually noisy duplicate.
    if history and abs(float(history[-1].get("ts", 0)) - point["ts"]) < 0.01:
        history[-1] = point
    else:
        history.append(point)
    if len(history) > _PRICE_HISTORY_LIMIT:
        del history[:-_PRICE_HISTORY_LIMIT]


def _market_dict(m: LiveMarket) -> dict[str, Any]:
    return {
        "condition_id": m.condition_id,
        "market_slug": m.market_slug,
        "up_token": m.up_token,
        "down_token": m.down_token,
        "start_ts": m.start_ts,
        "end_ts": m.end_ts,
        "tick_size": m.tick_size,
        "neg_risk": m.neg_risk,
        "resolution_source": m.resolution_source,
    }


def _synthetic_market_dict(asset: str) -> dict[str, Any]:
    now = time.time()
    start_ts = math.floor(now / 300.0) * 300.0
    end_ts = start_ts + 300.0
    prefix = "eth-updown-5m" if asset == "ETH" else "btc-updown-5m"
    return {
        "condition_id": "",
        "market_slug": f"{prefix}-{int(start_ts)}",
        "up_token": "",
        "down_token": "",
        "start_ts": start_ts,
        "end_ts": end_ts,
        "tick_size": 0.01,
        "neg_risk": False,
        "resolution_source": "",
        "synthetic": True,
    }


def _signal_dict(sig: BtcSignal) -> dict[str, Any]:
    return {
        "ts": sig.ts,
        "symbol": sig.symbol,
        "source": sig.source,
        "source_ts": sig.source_ts,
        "age_sec": sig.age_sec,
        "feed_id": sig.feed_id,
        "price_to_beat": sig.price_to_beat,
        "current_price": sig.current_price,
        "delta_usd": sig.delta_usd,
        "signal_side": sig.signal_side,
        "threshold_usd": sig.threshold_usd,
        "up_min_delta_usd": sig.up_min_delta_usd,
        "up_max_delta_usd": sig.up_max_delta_usd,
        "down_min_delta_usd": sig.down_min_delta_usd,
        "down_max_delta_usd": sig.down_max_delta_usd,
    }


def _fallback_signal_from_decisions(asset: str) -> Optional[dict[str, Any]]:
    if not DB_PATH.exists():
        return None
    prefix = asset.lower()
    symbol = cfg.eth_price_symbol if asset == "ETH" else cfg.btc_price_symbol
    pattern = re.compile(
        rf"{prefix}_delta=([+-]?\d+(?:\.\d+)?) "
        r"price=(\d+(?:\.\d+)?) beat=(\d+(?:\.\d+)?) "
        r"signal=(UP|DOWN|FLAT)"
    )
    with db() as c:
        rows = c.execute(
            "SELECT ts, reason FROM decisions "
            "WHERE asset=? AND reason LIKE ? "
            "ORDER BY id DESC LIMIT 50",
            (asset, f"%{prefix}_delta=%"),
        ).fetchall()
    for row in rows:
        match = pattern.search(row["reason"] or "")
        if not match:
            continue
        delta, price, beat, side = match.groups()
        if asset == "ETH":
            threshold = cfg.eth_delta_threshold_usd
            up_min = cfg.eth_up_min_delta_usd
            up_max = cfg.eth_up_max_delta_usd
            down_min = cfg.eth_down_min_delta_usd
            down_max = cfg.eth_down_max_delta_usd
        else:
            threshold = cfg.btc_delta_threshold_usd
            up_min = cfg.btc_up_min_delta_usd
            up_max = cfg.btc_up_max_delta_usd
            down_min = cfg.btc_down_min_delta_usd
            down_max = cfg.btc_down_max_delta_usd
        return {
            "ts": row["ts"],
            "symbol": symbol,
            "source": "decision-log-stale",
            "price_to_beat": float(beat),
            "current_price": float(price),
            "delta_usd": float(delta),
            "signal_side": side,
            "threshold_usd": threshold,
            "up_min_delta_usd": up_min,
            "up_max_delta_usd": up_max,
            "down_min_delta_usd": down_min,
            "down_max_delta_usd": down_max,
            "stale": True,
        }
    return None


# ---------------------------------------------------------------------------
# SQLite reads


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _row(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


def local_day_start_ts(now: Optional[float] = None) -> float:
    local_now = datetime.fromtimestamp(now if now is not None else time.time())
    return datetime.combine(local_now.date(), dt_time.min).timestamp()


def recent_decisions(limit: int = 50, since_id: int = 0) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with db() as c:
        rows = c.execute(
            "SELECT id, ts, asset, market_slug, side, t_remaining, ask_price, ask_size, "
            "action, reason, dry_run FROM decisions WHERE id > ? "
            "ORDER BY id DESC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        return [_row(r) for r in rows]


def recent_orders(limit: int = 50, since_id: int = 0) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with db() as c:
        rows = c.execute(
            "SELECT o.id, o.ts, o.market_slug, o.condition_id, o.token_id, "
            "o.asset, o.side, o.size, o.price, o.order_id, o.status, o.filled_size, "
            "o.error, o.entry_rule, o.dry_run, r.winning_token, r.resolved_ts, "
            "x.exit_status, x.exit_ts, x.exit_size "
            "FROM orders o LEFT JOIN resolutions r ON r.condition_id = o.condition_id "
            "LEFT JOIN ("
            "  SELECT condition_id, token_id, dry_run, MAX(status) AS exit_status, "
            "  MAX(ts) AS exit_ts, SUM(size) AS exit_size "
            "  FROM orders "
            "  WHERE status IN ('exit_filled','exit_matched','exit_partial','exit_dry_run') "
            "  GROUP BY condition_id, token_id, dry_run"
            ") x ON x.condition_id=o.condition_id "
            "AND x.token_id=o.token_id AND x.dry_run=o.dry_run "
            "WHERE o.id > ? ORDER BY o.id DESC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            item = _row(r)
            is_exit = str(item["side"] or "").startswith("SELL_") or str(item["status"] or "").startswith("exit_")
            # FOK/FAK rejection is expected when the rapidly changing book no
            # longer has enough matching liquidity.  It remains an open
            # position and is retried on the next fresh quote, so don't present
            # it as a wallet/API failure in the dashboard.
            exit_unmatched = (
                is_exit
                and item["status"] in ("exit_error", "exit_pre_submit_error")
                and _is_exit_unmatched_error(item.get("error"))
            )
            if exit_unmatched:
                item["status"] = "exit_unmatched"
            exit_effective = item["status"] in ("exit_filled", "exit_matched", "exit_partial", "exit_dry_run")
            effective = (
                item["side"] in ("UP", "DOWN") and item["status"] in ("filled", "matched")
                or (item["dry_run"] == 1 and item["status"] == "dry_run")
            )
            if is_exit:
                if item["status"] == "exit_partial":
                    item["result"] = "PARTIAL_EXIT"
                elif exit_unmatched:
                    item["result"] = "EXIT_UNMATCHED"
                else:
                    item["result"] = (
                        "EXITED"
                        if exit_effective
                        else (
                            "EXIT_UNCERTAIN"
                            if item["status"] == "exit_timeout_pending_reconcile"
                            else "EXIT_FAILED"
                        )
                    )
            elif item["exit_status"] is not None:
                item["result"] = (
                    "PARTIAL_EXIT"
                    if item["exit_size"] is not None
                    and float(item["exit_size"]) < float(item["size"]) - 0.02
                    else "EXITED"
                )
            elif item["status"] == "timeout_pending_reconcile":
                item["result"] = "UNCERTAIN"
            elif not effective:
                item["result"] = (
                    "FAILED"
                    if item["status"] in ("error", "pre_submit_error")
                    else "NONE"
                )
            elif item["winning_token"] is None:
                item["result"] = "PENDING"
            elif item["token_id"] == item["winning_token"]:
                item["result"] = "HIT"
            else:
                item["result"] = "MISS"
            item["settled"] = (
                item["winning_token"] is not None
                or item["exit_status"] is not None
                or exit_effective
            )
            out.append(item)
        return out


def _is_exit_unmatched_error(error: object) -> bool:
    """True for an exchange liquidity miss that is safe to retry.

    Polymarket returns HTTP 400 for both FOK "not fully filled" and FAK "no
    orders found".  These are normal market outcomes, unlike malformed orders,
    rejected signatures, insufficient balance, or network failures.
    """
    text = str(error or "").lower()
    return (
        "couldn't be fully filled" in text
        or "couldn't be fully fill" in text
        or "no orders found to match" in text
        or "fok orders are fully filled or killed" in text
        or "fak orders are partially filled or killed" in text
    )


def realized_pnl_today() -> dict:
    """Read the same canonical PnL summary used by the bot risk gate.

    Resolution lookups run in the background; the API must remain a local,
    bounded-latency read even when Gamma is slow or unavailable.
    """
    return realized_pnl_summary_today(False)


_resolved_cache: dict[str, Optional[str]] = {}


def _resolved_winning_token(market_slug: str) -> Optional[str]:
    """Return the winning token_id for a resolved market, or None if unresolved.

    Gamma's `condition_ids` filter hides closed markets — query by slug instead.
    Cached in-process; markets resolve immutably so cache hits are safe.
    """
    if not market_slug:
        return None
    if market_slug in _resolved_cache:
        return _resolved_cache[market_slug]
    try:
        r = requests.get(
            f"{cfg.gamma_host}/markets",
            params={"slug": market_slug, "closed": "true"},
            timeout=3,
        )
        if r.status_code != 200:
            return None
        markets = r.json()
        if not markets:
            return None
        m = markets[0] if isinstance(markets, list) else markets
        if not m.get("closed"):
            return None
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            import json as _json
            prices = _json.loads(prices)
        if not prices or len(prices) != 2:
            return None
        token_ids = m.get("clobTokenIds")
        if isinstance(token_ids, str):
            import json as _json
            token_ids = _json.loads(token_ids)
        if not token_ids or len(token_ids) != 2:
            return None
        winner_idx = 0 if float(prices[0]) > float(prices[1]) else 1
        winner = str(token_ids[winner_idx])
        _resolved_cache[market_slug] = winner
        return winner
    except Exception:
        return None


def _record_resolution(condition_id: str, winning_token: str) -> None:
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO resolutions (condition_id, winning_token, resolved_ts) "
            "VALUES (?,?,?)",
            (condition_id, winning_token, time.time()),
        )


# ---------------------------------------------------------------------------
# Background pollers


async def poll_market_loop():
    while True:
        try:
            m = await asyncio.to_thread(
                fetch_live_market,
                cfg.gamma_host,
                cfg.series_slug,
            )
            if m:
                _state["market"] = _market_dict(m)
            elif (
                _state.get("market") is None
                or _state["market"].get("synthetic")
                or time.time() > _state["market"]["end_ts"] + cfg.market_stale_grace_sec
            ):
                _state["market"] = _synthetic_market_dict("BTC")
            _state["errors"].pop("market", None)
        except Exception as e:
            _state["market"] = _synthetic_market_dict("BTC")
            _state["errors"]["market"] = str(e)
        await asyncio.sleep(2.0)


async def poll_eth_market_loop():
    while True:
        if not cfg.eth_market_enabled:
            _state["eth_market"] = None
            await asyncio.sleep(2.0)
            continue
        try:
            m = await asyncio.to_thread(
                fetch_live_market,
                cfg.gamma_host,
                cfg.eth_series_slug,
            )
            if m:
                _state["eth_market"] = _market_dict(m)
            elif (
                _state.get("eth_market") is None
                or _state["eth_market"].get("synthetic")
                or time.time() > _state["eth_market"]["end_ts"] + cfg.market_stale_grace_sec
            ):
                _state["eth_market"] = _synthetic_market_dict("ETH")
            _state["errors"].pop("eth_market", None)
        except Exception as e:
            _state["eth_market"] = _synthetic_market_dict("ETH")
            _state["errors"]["eth_market"] = str(e)
        await asyncio.sleep(2.0)


async def poll_book_loop():
    while True:
        m = _state.get("market")
        if not m:
            await asyncio.sleep(0.5)
            continue
        if not m.get("up_token") or not m.get("down_token"):
            _state["book_up"] = None
            _state["book_down"] = None
            await asyncio.sleep(0.5)
            continue
        try:
            bu, bd = await asyncio.gather(
                asyncio.to_thread(fetch_book, cfg.clob_host, m["up_token"]),
                asyncio.to_thread(fetch_book, cfg.clob_host, m["down_token"]),
            )
            _state["book_up"] = {
                "best_bid": bu.best_bid,
                "bid_size": bu.bid_size,
                "best_ask": bu.best_ask,
                "ask_size": bu.ask_size,
            }
            _state["book_down"] = {
                "best_bid": bd.best_bid,
                "bid_size": bd.bid_size,
                "best_ask": bd.best_ask,
                "ask_size": bd.ask_size,
            }
            _state["errors"].pop("book", None)
        except Exception as e:
            _state["errors"]["book"] = str(e)
        await asyncio.sleep(0.25)


async def poll_eth_book_loop():
    while True:
        m = _state.get("eth_market")
        if not m:
            _state["eth_book_up"] = None
            _state["eth_book_down"] = None
            await asyncio.sleep(0.5)
            continue
        if not m.get("up_token") or not m.get("down_token"):
            _state["eth_book_up"] = None
            _state["eth_book_down"] = None
            await asyncio.sleep(0.5)
            continue
        try:
            bu, bd = await asyncio.gather(
                asyncio.to_thread(fetch_book, cfg.clob_host, m["up_token"]),
                asyncio.to_thread(fetch_book, cfg.clob_host, m["down_token"]),
            )
            _state["eth_book_up"] = {
                "best_bid": bu.best_bid,
                "bid_size": bu.bid_size,
                "best_ask": bu.best_ask,
                "ask_size": bu.ask_size,
            }
            _state["eth_book_down"] = {
                "best_bid": bd.best_bid,
                "bid_size": bd.bid_size,
                "best_ask": bd.best_ask,
                "ask_size": bd.ask_size,
            }
            _state["errors"].pop("eth_book", None)
        except Exception as e:
            _state["errors"]["eth_book"] = str(e)
        await asyncio.sleep(0.25)


async def poll_btc_signal_loop():
    while True:
        m = _state.get("market")
        # BTC signal is also a dashboard display feed. The entry filter can be
        # disabled without hiding the live BTC price and delta from the UI.
        if not m:
            _state["btc_signal"] = None
            await asyncio.sleep(1.0)
            continue
        try:
            market = LiveMarket(
                condition_id=m["condition_id"],
                market_slug=m["market_slug"],
                up_token=m["up_token"],
                down_token=m["down_token"],
                start_ts=m["start_ts"],
                end_ts=m["end_ts"],
                tick_size=m["tick_size"],
                neg_risk=m["neg_risk"],
                resolution_source=m.get("resolution_source", ""),
            )
            sig = await asyncio.to_thread(fetch_btc_signal, cfg, market)
            _state["btc_signal"] = _signal_dict(sig)
            _record_price_history("BTC", m["market_slug"], sig)
            _state["errors"].pop("btc_signal", None)
        except Exception as e:
            _state["btc_signal"] = None
            _state["errors"]["btc_signal"] = str(e)
        await asyncio.sleep(1.0)


async def poll_eth_signal_loop():
    while True:
        m = _state.get("eth_market")
        if not m or not cfg.eth_market_enabled:
            _state["eth_signal"] = None
            await asyncio.sleep(1.0)
            continue
        try:
            market = LiveMarket(
                condition_id=m["condition_id"],
                market_slug=m["market_slug"],
                up_token=m["up_token"],
                down_token=m["down_token"],
                start_ts=m["start_ts"],
                end_ts=m["end_ts"],
                tick_size=m["tick_size"],
                neg_risk=m["neg_risk"],
                resolution_source=m.get("resolution_source", ""),
            )
            sig = await asyncio.to_thread(fetch_eth_signal, cfg, market)
            _state["eth_signal"] = _signal_dict(sig)
            _record_price_history("ETH", m["market_slug"], sig)
            _state["errors"].pop("eth_signal", None)
        except Exception as e:
            _state["eth_signal"] = None
            _state["errors"]["eth_signal"] = str(e)
        await asyncio.sleep(1.0)


async def poll_positions_loop():
    deposit_wallet = _deposit_wallet_address()
    while True:
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", deposit_wallet):
            _state["positions"] = []
            _state["value_usd"] = None
            _state["errors"].pop("positions", None)
            _state["errors"].pop("value", None)
            await asyncio.sleep(10.0)
            continue
        try:
            r = await asyncio.to_thread(
                requests.get,
                "https://data-api.polymarket.com/positions",
                params={"user": deposit_wallet},
                timeout=3,
            )
            r.raise_for_status()
            _state["positions"] = r.json()
            _state["errors"].pop("positions", None)
        except Exception as e:
            _state["positions"] = []
            _state["errors"]["positions"] = str(e)

        try:
            r = await asyncio.to_thread(
                requests.get,
                "https://data-api.polymarket.com/value",
                params={"user": deposit_wallet},
                timeout=3,
            )
            r.raise_for_status()
            data = r.json()
            # The legacy endpoint returns [{value: ...}], while the current
            # v2 endpoint returns {data: {value: ...}}. Accept both shapes.
            if isinstance(data, list) and data:
                value = data[0].get("value") if isinstance(data[0], dict) else None
            elif isinstance(data, dict) and isinstance(data.get("data"), dict):
                value = data["data"].get("value")
            else:
                value = None
            if value is None:
                raise ValueError("value API response missing value")
            parsed_value = float(value)
            if not math.isfinite(parsed_value) or parsed_value < 0:
                raise ValueError("value API returned invalid value")
            _state["value_usd"] = parsed_value
            _state["errors"].pop("value", None)
        except Exception as e:
            _state["value_usd"] = None
            _state["errors"]["value"] = str(e)

        await asyncio.sleep(2.0)


async def poll_balance_loop():
    """Read the Polymarket pUSD balance of the configured deposit wallet."""
    PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
    SELECTOR = "0x70a08231"
    deposit_wallet = _deposit_wallet_address()
    while True:
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", deposit_wallet):
            _state["balance_pusd"] = None
            _state["errors"].pop("balance", None)
            await asyncio.sleep(10.0)
            continue
        try:
            data = SELECTOR + deposit_wallet.lower().replace("0x", "").rjust(64, "0")
            r = await asyncio.to_thread(
                requests.post,
                cfg.polygon_rpc,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_call",
                    "params": [{"to": PUSD, "data": data}, "latest"],
                },
                timeout=5,
            )
            r.raise_for_status()
            payload = r.json()
            if payload.get("error"):
                raise RuntimeError(f"RPC error: {payload['error']}")
            raw = payload.get("result")
            if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", raw):
                raise ValueError("RPC balance response missing 32-byte result")
            balance = int(raw, 16) / 1e6
            if not math.isfinite(balance) or balance < 0:
                raise ValueError("RPC balance returned invalid value")
            _state["balance_pusd"] = balance
            _state["errors"].pop("balance", None)
        except Exception as e:
            _state["balance_pusd"] = None
            _state["errors"]["balance"] = str(e)
        await asyncio.sleep(5.0)


def _weather_feed_snapshot() -> list[dict[str, Any]]:
    """Build a small read-only weather feed for the dashboard.

    Forecasts are fetched through the same parser/model used by the weather
    paper worker.  This function intentionally stops at presentation data and
    never calls a CLOB order method.
    """
    if not bool(getattr(cfg, "weather_enabled", False)):
        return []
    markets = fetch_weather_markets(cfg)
    rows: list[dict[str, Any]] = []
    seen_cities: set[str] = set()
    for market in markets[:12]:
        try:
            forecast = fetch_ensemble_forecast(cfg, market.city_key, market.target_date)
            signal = build_signal(cfg, market, forecast)
            mean_f = forecast.low_mean if market.metric == "low" else forecast.high_mean
            probability = (
                signal.model_yes_probability
                if signal.side == "UP"
                else signal.model_no_probability
            )
            city = str(CITY_CONFIG.get(market.city_key, {}).get("name") or market.city_key)
            seen_cities.add(market.city_key)
            rows.append(
                {
                    "city": city,
                    "condition": f"{market.metric} {market.threshold_f:.0f}°F · {signal.side}",
                    "temperature_c": round((mean_f - 32.0) * 5.0 / 9.0, 1),
                    "probability": round(float(probability), 6),
                    "source": "Open-Meteo ensemble",
                    "updated_ts": time.time(),
                    "market_slug": market.slug,
                    "target_date": market.target_date.isoformat(),
                    "edge": round(float(signal.edge), 6),
                }
            )
        except Exception as exc:
            log_msg = f"{market.slug or market.market_key}: {exc}"
            # A single malformed/temporarily unavailable city must not hide
            # all other weather rows.
            _state["errors"]["weather_item"] = str(log_msg)[:300]

    # Weather markets can be absent between event batches.  Keep the card a
    # useful real-time feed by showing today's ensemble forecast for configured
    # cities even when there is no tradable market to attach it to.
    today = datetime.now(timezone.utc).date()
    try:
        city_keys = configured_city_keys(cfg)
    except Exception:
        city_keys = [key.strip().lower() for key in str(getattr(cfg, "weather_cities", "")).split(",") if key.strip()]
    for city_key in city_keys:
        if city_key in seen_cities or len(rows) >= 8:
            continue
        try:
            forecast = fetch_ensemble_forecast(cfg, city_key, today)
            mean_f = forecast.high_mean
            city = str(CITY_CONFIG.get(city_key, {}).get("name") or city_key)
            rows.append(
                {
                    "city": city,
                    "condition": "今日最高（ensemble）",
                    "temperature_c": round((mean_f - 32.0) * 5.0 / 9.0, 1),
                    "probability": None,
                    "source": "Open-Meteo ensemble",
                    "updated_ts": time.time(),
                    "market_slug": None,
                    "target_date": today.isoformat(),
                }
            )
        except Exception as exc:
            _state["errors"]["weather_item"] = str(exc)[:300]
    return rows[:8]


async def poll_weather_loop():
    """Refresh the read-only weather feed without touching live trading."""
    while True:
        try:
            _state["weather"] = await asyncio.to_thread(_weather_feed_snapshot)
            _state["errors"].pop("weather", None)
        except Exception as exc:
            _state["weather"] = []
            _state["errors"]["weather"] = str(exc)
        interval = max(30.0, min(float(getattr(cfg, "weather_scan_interval_sec", 300.0)), 120.0))
        await asyncio.sleep(interval)


def _sports_feed_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert the sports paper service snapshot into compact UI rows."""
    rows: list[dict[str, Any]] = []
    for market in (snapshot.get("markets") or [])[:8]:
        outcomes = market.get("outcomes") or []
        prices = market.get("prices") or []
        try:
            probability = float(prices[0]) / max(sum(float(p) for p in prices[:2]), 1e-9)
        except (IndexError, TypeError, ValueError):
            probability = None
        rows.append(
            {
                "league": market.get("league") or market.get("sport") or "体育",
                "event": market.get("event_name") or market.get("question") or market.get("slug"),
                "status": "PAPER · 监控",
                "start_ts": market.get("event_start_ts"),
                "home_team": outcomes[0] if len(outcomes) > 0 else None,
                "away_team": outcomes[1] if len(outcomes) > 1 else None,
                "probability_home": probability,
                "source": "Gamma + market-implied",
                "market_slug": market.get("slug"),
                "neg_risk": bool(market.get("neg_risk")),
            }
        )
    return rows


async def poll_sports_loop():
    """Run the independent sports paper scanner; live mode is impossible."""
    while True:
        try:
            snapshot = await asyncio.to_thread(_sports_service.run_once)
            _state["sports"] = _sports_feed_snapshot(snapshot)
            _state["sports_meta"] = snapshot
            _state["errors"].pop("sports", None)
        except Exception as exc:
            _state["sports"] = []
            _state["sports_meta"] = {"enabled": bool(getattr(cfg, "sports_enabled", False)), "mode": "paper", "status": "error", "paper_only": True, "live_orders": False}
            _state["errors"]["sports"] = str(exc)
        # Gamma pagination can be slow; keep a bounded dashboard cadence.
        await asyncio.sleep(60.0)


async def poll_bot_running_loop():
    pid_path = ROOT / "bot.pid"
    btc_pid_path = ROOT / "bot_btc.pid"
    eth_pid_path = ROOT / "bot_eth.pid"
    mode_path = ROOT / "bot.mode"

    def pid_exists(pid: int) -> bool:
        import os
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)  # signal 0 = check existence
            return True
        except (ProcessLookupError, ValueError, PermissionError, OSError):
            return False

    while True:
        asset_running = {"BTC": False, "ETH": False}
        for asset, asset_pid_path in (
            ("BTC", btc_pid_path if btc_pid_path.exists() else pid_path),
            ("ETH", eth_pid_path),
        ):
            if not asset_pid_path.exists():
                continue
            try:
                pid = int(asset_pid_path.read_text().strip())
                asset_running[asset] = pid_exists(pid)
            except ValueError:
                asset_running[asset] = False
        running = any(asset_running.values())
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                running = running or pid_exists(pid)
            except ValueError:
                pass
        mode = "unknown"
        if mode_path.exists():
            try:
                mode = mode_path.read_text().strip() or "unknown"
            except Exception:
                pass
        if not running:
            mode = "stopped"
        _state["bot_running"] = running
        _state["bot_assets"] = asset_running
        _state["bot_mode"] = mode
        await asyncio.sleep(2.0)


async def poll_resolution_loop():
    """Back-fill settlement outcomes without blocking dashboard requests."""
    while True:
        try:
            await asyncio.gather(
                asyncio.to_thread(resolve_pending, cfg, False),
                asyncio.to_thread(resolve_pending, cfg, True),
            )
            _state["errors"].pop("resolution", None)
        except Exception as e:
            _state["errors"]["resolution"] = str(e)
        await asyncio.sleep(30.0)


# ---------------------------------------------------------------------------
# FastAPI app

app = FastAPI(title="poly_hft dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_utf8_json(request: Request, call_next):
    """Make the dashboard API's UTF-8 contract explicit for older proxies."""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


@app.on_event("startup")
async def _startup():
    asyncio.create_task(poll_market_loop())
    asyncio.create_task(poll_eth_market_loop())
    asyncio.create_task(poll_book_loop())
    asyncio.create_task(poll_eth_book_loop())
    asyncio.create_task(poll_btc_signal_loop())
    asyncio.create_task(poll_eth_signal_loop())
    asyncio.create_task(poll_positions_loop())
    asyncio.create_task(poll_balance_loop())
    asyncio.create_task(poll_weather_loop())
    asyncio.create_task(poll_sports_loop())
    asyncio.create_task(poll_bot_running_loop())
    asyncio.create_task(poll_resolution_loop())


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


def _pid_alive(path: Path) -> bool:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _live_process_status() -> dict[str, Any]:
    mode_path = ROOT / "bot.mode"
    try:
        mode_value = mode_path.read_text(encoding="utf-8").strip().lower()
    except (FileNotFoundError, OSError):
        mode_value = ""
    assets = _live_process_status_base()
    running = any(assets.values())
    mode = mode_value if running and mode_value in ("live", "paper") else ("unknown" if running else "stopped")
    return {"running": running, "mode": mode, "assets": assets, "services": _service_status_snapshot()}


def _process_output(result: subprocess.CompletedProcess[str]) -> str:
    """Return a bounded, secret-free command diagnostic for the UI."""
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    for key in ("PRIVATE_KEY", "CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"):
        text = re.sub(rf"(?im)({key}\s*[=:]\s*)\S+", r"\1[已隐藏]", text)
    return text[-3000:]


class LiveTogglePayload(BaseModel):
    live_enabled: bool


def _write_control_flag(key: str, enabled: bool) -> None:
    """Update one non-secret live flag in this instance's .env atomically."""
    if key not in {"BTC_LIVE_ENABLED", "ETH_TRADING_ENABLED", "WEATHER_LIVE_TRADING_ENABLED"}:
        raise HTTPException(status_code=400, detail="不支持修改该服务的实盘开关")
    path = ROOT / ".env"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines()
    replacement = f'{key}={"true" if enabled else "false"}'
    found = False
    out: list[str] = []
    pattern = re.compile(rf"^{re.escape(key)}\s*=", re.IGNORECASE)
    for line in lines:
        if pattern.match(line):
            out.append(replacement)
            found = True
        else:
            out.append(line)
    if not found:
        out.append(replacement)
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _service_key(asset: str) -> str:
    normalized = asset.strip().upper()
    if normalized not in LIVE_SERVICE_IDS:
        raise HTTPException(status_code=404, detail="未知服务")
    return normalized


@app.put("/api/live/services/{asset}")
def live_service_toggle(asset: str, payload: LiveTogglePayload, request: Request):
    """Set an independent live gate; BTC and ETH are eligible in polyauto."""
    _require_operator(request)
    service = _service_key(asset)
    if _is_polyauto_instance() and service not in {"BTC", "ETH"} and payload.live_enabled:
        raise HTTPException(status_code=403, detail=f"polyauto {service} 实盘路径已锁定；仅允许 BTC/ETH")
    if service == "SPORTS" and payload.live_enabled:
        raise HTTPException(status_code=403, detail="体育服务仅支持 Paper，禁止实盘")
    if service == "WEATHER" and payload.live_enabled and _is_polyauto_instance():
        raise HTTPException(status_code=403, detail="天气服务仅支持 Paper，禁止实盘")
    key = {"BTC": "BTC_LIVE_ENABLED", "ETH": "ETH_TRADING_ENABLED", "WEATHER": "WEATHER_LIVE_TRADING_ENABLED"}.get(service)
    if key is None:
        if not payload.live_enabled:
            return {"ok": True, "service": service, "live_enabled": False, "services": _service_status_snapshot()}
        raise HTTPException(status_code=403, detail="该服务没有实盘执行器")
    _write_control_flag(key, payload.live_enabled)
    return {"ok": True, "service": service, "live_enabled": payload.live_enabled, "services": _service_status_snapshot(), "note": "重启对应 worker 后生效"}


@app.get("/api/live/status")
def live_status():
    """Return process state; starting/stopping still requires the operator token."""
    return {"ok": True, **_live_process_status(), "ts": time.time()}


@app.get("/api/live/services")
def live_services():
    """Return per-service live capability and current mode.

    polyauto exposes a BTC-only live capability; ETH, weather and sports are
    hard locked to paper irrespective of copied environment values.
    """
    return {"ok": True, "instance": "polyauto" if _is_polyauto_instance() else "main", "services": _service_status_snapshot(), "ts": time.time()}


@app.post("/api/live/services/{asset}/start")
def live_service_start(asset: str, request: Request):
    service = _service_key(asset)
    if _is_polyauto_instance() and service not in {"BTC", "ETH"}:
        raise HTTPException(status_code=403, detail="polyauto 仅允许 BTC/ETH 实盘")
    if service not in {"BTC", "ETH"}:
        raise HTTPException(status_code=403, detail="请使用现有主实例总开关管理该服务")
    return live_start(request)


@app.post("/api/live/services/{asset}/stop")
def live_service_stop(asset: str, request: Request):
    service = _service_key(asset)
    if service != "BTC":
        raise HTTPException(status_code=403, detail="该服务没有独立实盘执行器")
    return live_stop(request)


@app.post("/api/live/start")
def live_start(request: Request):
    """Run the repository's guarded live launcher after token validation."""
    _require_operator(request)
    with _live_control_lock:
        current = _live_process_status()
        if current["running"]:
            raise HTTPException(status_code=409, detail="机器人已经在运行，请勿重复开启实盘")
        if _is_polyauto_instance() and not _service_status_snapshot()["BTC"]["live_enabled"]:
            raise HTTPException(status_code=403, detail="polyauto BTC 实盘开关未启用；请先单独开启 BTC")
        launcher = "run_live_polyauto.sh" if _is_polyauto_instance() else "run_live.sh"
        try:
            result = subprocess.run(
                ["/usr/bin/env", "bash", str(ROOT / "scripts" / launcher)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="实盘预检或启动超时，请查看 logs/ 日志")
        diagnostic = _process_output(result)
        if result.returncode != 0:
            raise HTTPException(
                status_code=502,
                detail=("实盘未启动；预检/启动失败。" + (f" {diagnostic}" if diagnostic else ""))[:3500],
            )
        return {"ok": True, **_live_process_status(), "diagnostic": diagnostic, "ts": time.time()}


@app.post("/api/live/stop")
def live_stop(request: Request):
    """Stop workers only; this never submits a sell or otherwise liquidates."""
    _require_operator(request)
    with _live_control_lock:
        stopper = "stop_live_asset.sh" if _is_polyauto_instance() else "stop_live.sh"
        command = ["/usr/bin/env", "bash", str(ROOT / "scripts" / stopper)]
        if _is_polyauto_instance():
            command.append("ALL")
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="停止实盘超时，请检查进程")
        diagnostic = _process_output(result)
        if result.returncode != 0:
            raise HTTPException(status_code=502, detail=("停止实盘失败。" + (f" {diagnostic}" if diagnostic else ""))[:3500])
        return {
            "ok": True,
            **_live_process_status(),
            "diagnostic": diagnostic,
            "note": "已停止机器人循环；现有 Polymarket 持仓不会自动卖出。",
            "ts": time.time(),
        }


@app.get("/api/settings/llm")
def llm_settings_get():
    """Return non-secret model relay settings for the system settings page."""
    return _llm_settings_response()


@app.put("/api/settings/llm")
def llm_settings_put(payload: LlmSettingsPayload):
    """Persist model relay settings without ever echoing an API key.

    The trading workers load .env at process start, therefore callers should
    restart the dashboard/bot services after saving.  Saving this page alone
    never enables live trading.
    """
    _write_llm_env(payload)
    return {"ok": True, **_llm_settings_response(), "saved_at": time.time()}


@app.get("/api/llm/usage")
def llm_usage():
    """Return aggregate token usage for the configured model slots."""
    settings = _llm_settings_response()
    usage = _llm_usage_snapshot()
    configured = {
        "primary": settings.get("primary", {}).get("model", ""),
        "secondary": settings.get("secondary", {}).get("model", ""),
    }
    return {"ok": True, "configured": configured, **usage}


def _llm_url(value: str, suffix: str = "") -> str:
    """Validate and normalize an OpenAI-compatible endpoint URL."""
    base = (value or "").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Base URL 必须是 http(s) 地址")
    # Users commonly paste the host root or a complete endpoint. Normalize to
    # the OpenAI-compatible /v1 base used by Mix and avoid duplicate paths.
    path = parsed.path.rstrip("/")
    for tail in ("/chat/completions", "/models"):
        if path.endswith(tail):
            path = path[: -len(tail)]
            break
    if not path:
        path = "/v1"
    base = f"{parsed.scheme}://{parsed.netloc}{path}"
    return base + suffix


def _safe_error(exc: Exception, *sensitive_values: str) -> str:
    """Return a short error with saved and transient API-key text removed."""
    msg = str(exc).replace("\n", " ")[:300]
    saved = _read_llm_env()
    keys = [
        saved.get("LLM_API_KEY", ""),
        saved.get("LLM_PRIMARY_API_KEY", ""),
        saved.get("LLM_SECONDARY_API_KEY", ""),
        *sensitive_values,
    ]
    for key in keys:
        if key:
            msg = msg.replace(key, "[已隐藏]")
    return msg


def _raise_provider_error(response: requests.Response) -> None:
    """Raise an actionable, key-redacted error for non-2xx provider replies."""
    if response.ok:
        return
    detail = (response.text or "").replace("\n", " ").strip()[:300]
    if detail:
        raise RuntimeError(f"上游 HTTP {response.status_code}: {detail}")
    response.raise_for_status()


def _model_aliases(provider: str, model: str) -> list[str]:
    """Return safe compatibility aliases for providers with moving model IDs."""
    value = (model or "").strip()
    low = value.lower()
    aliases = [value] if value else []
    # Several OpenAI-compatible Grok gateways never expose the speculative
    # ``grok-4.6`` id.  Prefer currently published aliases while retaining the
    # user supplied id as the first attempt.
    if "grok" in low:
        # Gateways frequently expose a moving subset of xAI model ids.  The
        # user-facing ``grok-4.6`` label is not a stable API id, and some
        # distributors return a 503 ``no available channel`` instead of a
        # useful 404.  Probe the requested id first, then try conservative
        # published aliases before consulting /models.
        aliases = ["grok-4.5", value] if value else ["grok-4.5"]
        aliases.extend([
            "grok-4-1-fast-reasoning",
            "grok-4-1-fast-non-reasoning",
            "grok-4-0709",
            "grok-4",
            "grok-3-latest",
            "grok-3",
            "grok-3-mini",
        ])
    return list(dict.fromkeys(aliases))


def _available_model_ids(base: str, key: str, timeout: float) -> list[str]:
    try:
        response = requests.get(
            _llm_url(base, "/models"),
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=timeout,
        )
        _raise_provider_error(response)
        data = response.json()
        raw = data.get("data", []) if isinstance(data, dict) else []
        return [str(item.get("id")) for item in raw if isinstance(item, dict) and item.get("id")]
    except Exception:
        return []


@app.post("/api/settings/llm/probe")
def llm_settings_probe(payload: LlmProbePayload):
    """Probe an OpenAI-compatible /models endpoint without persisting secrets."""
    base = _llm_url(payload.base_url)
    supplied_key = (payload.api_key or "").strip()
    saved = _read_llm_env()
    slot_key = "LLM_SECONDARY_API_KEY" if payload.slot == "secondary" else "LLM_PRIMARY_API_KEY"
    key = supplied_key if supplied_key and supplied_key != LLM_SECRET_MASK else (saved.get(slot_key, "") or saved.get("LLM_API_KEY", ""))
    if not key:
        raise HTTPException(status_code=400, detail="请先填写 API Key，或先保存已配置的密钥")
    try:
        response = requests.get(
            _llm_url(base, "/models"),
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=payload.timeout_sec,
        )
        _raise_provider_error(response)
        data = response.json()
        raw = data.get("data", []) if isinstance(data, dict) else []
        models = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
                elif isinstance(item, str):
                    models.append(item)
        models = list(dict.fromkeys(models))[:500]
        _llm_runtime.update(last_probe_ts=time.time(), last_probe_count=len(models))
        return {"ok": True, "models": models, "effective_base_url": base}
    except Exception as exc:
        _llm_runtime.update(last_probe_ts=time.time(), last_probe_count=0)
        raise HTTPException(status_code=502, detail=f"模型列表获取失败：{_safe_error(exc, key)}")


@app.post("/api/settings/llm/test")
def llm_settings_test(payload: LlmTestPayload):
    """Send one read-only chat request to verify connectivity.

    This endpoint is intentionally disconnected from order code: it only
    performs a provider health check and never changes strategy or trading
    mode. A supplied key is transient; an empty/masked key uses the saved key.
    """
    saved = _read_llm_env()
    slot_prefix = "LLM_SECONDARY_" if payload.slot == "secondary" else "LLM_PRIMARY_"
    base = _llm_url(payload.base_url or saved.get(slot_prefix + "BASE_URL", "") or saved.get("LLM_BASE_URL", ""))
    model = (payload.model or saved.get(slot_prefix + "MODEL", "") or saved.get("LLM_MODEL", "")).strip()
    supplied_key = (payload.api_key or "").strip()
    slot_key = "LLM_SECONDARY_API_KEY" if payload.slot == "secondary" else "LLM_PRIMARY_API_KEY"
    key = supplied_key if supplied_key and supplied_key != LLM_SECRET_MASK else (saved.get(slot_key, "") or saved.get("LLM_API_KEY", ""))
    if not key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")
    if not model:
        raise HTTPException(status_code=400, detail="请先填写模型名称")
    aliases = _model_aliases(saved.get("LLM_PROVIDER", ""), model)
    if "grok" in model.lower():
        available_hint = _available_model_ids(base, key, payload.timeout_sec)
        aliases.extend(item for item in available_hint if "grok" in item.lower())
        aliases = list(dict.fromkeys(aliases))
    body = {
        "messages": [
            {"role": "system", "content": "You are a read-only connectivity tester. Do not trade or call tools."},
            {"role": "user", "content": payload.prompt},
        ],
        "temperature": 0,
        "max_tokens": 64,
    }
    started = time.monotonic()
    try:
        last_exc: Exception | None = None
        for candidate in aliases:
            body["model"] = candidate
            try:
                response = requests.post(
                    _llm_url(base, "/chat/completions"),
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=body,
                    timeout=payload.timeout_sec,
                )
                _raise_provider_error(response)
                data = response.json()
                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices:
                    raise ValueError("响应缺少 choices")
                _record_llm_usage(candidate, data.get("usage"), ok=True)
                elapsed_ms = round((time.monotonic() - started) * 1000)
                _llm_runtime.update(last_test_ts=time.time(), last_test_ok=True, last_test_error=None)
                return {"ok": True, "model": candidate, "requested_model": model, "latency_ms": elapsed_ms}
            except Exception as exc:
                last_exc = exc
                if "model_not_found" not in str(exc).lower() and "no available channel" not in str(exc).lower():
                    break
        available = _available_model_ids(base, key, payload.timeout_sec)
        # Some gateways expose a valid Grok id only through /models.  Retry
        # those ids automatically after an unavailable-model response.
        dynamic = [item for item in available if "grok" in item.lower()]
        for candidate in dynamic:
            if candidate in aliases:
                continue
            body["model"] = candidate
            try:
                response = requests.post(
                    _llm_url(base, "/chat/completions"),
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=body,
                    timeout=payload.timeout_sec,
                )
                _raise_provider_error(response)
                data = response.json()
                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices:
                    raise ValueError("响应缺少 choices")
                _record_llm_usage(candidate, data.get("usage"), ok=True)
                elapsed_ms = round((time.monotonic() - started) * 1000)
                _llm_runtime.update(last_test_ts=time.time(), last_test_ok=True, last_test_error=None)
                return {"ok": True, "model": candidate, "requested_model": model, "latency_ms": elapsed_ms}
            except Exception as exc:
                last_exc = exc
                if "model_not_found" not in str(exc).lower() and "no available channel" not in str(exc).lower():
                    break
        if available and last_exc is not None:
            raise RuntimeError(f"模型 {model} 不可用；当前接口可用模型：{', '.join(available[:20])}") from last_exc
        if last_exc is not None:
            text = str(last_exc)
            lowered = text.lower()
            if "model_not_found" in lowered or "no available channel" in lowered:
                raise RuntimeError(
                    f"模型 {model} 在当前上游没有可用通道。请点击‘拉取模型’并选择返回列表中的 Grok 模型；"
                    "grok-4.6 不是稳定的 API 模型 ID。"
                ) from last_exc
            raise last_exc
        raise RuntimeError("model test not executed")
    except HTTPException:
        raise
    except Exception as exc:
        message = _safe_error(exc, key)
        _record_llm_usage(model, None, ok=False, error=message)
        _llm_runtime.update(last_test_ts=time.time(), last_test_ok=False, last_test_error=message)
        raise HTTPException(status_code=502, detail=f"连接测试失败：{message}")


OPENCLAW_PERMISSION_POLICY: dict[str, dict[str, Any]] = {
    "desk": {"name": "台长调度", "capabilities": ["任务分发", "日报", "审批队列"], "trading": False},
    "search": {"name": "机会猎手", "capabilities": ["市场发现", "价差扫描", "事件扫描"], "trading": False},
    "whale": {"name": "聪明钱跟踪", "capabilities": ["大额成交", "盘口异动", "地址行为分析"], "trading": False},
    "shill": {"name": "舆情验证", "capabilities": ["新闻", "公告", "民调和社交信息验证"], "trading": False},
    "risk": {"name": "风控合规", "capabilities": ["敞口", "滑点", "亏损熔断", "拒绝订单"], "trading": False},
    "sniper": {"name": "订单执行", "capabilities": ["风控通过的 CLOB 下单", "撤单"], "trading": True, "credential_scope": "L2 下单/撤单/查询"},
    "exit": {"name": "仓位管理", "capabilities": ["止盈", "止损", "平仓建议"], "trading": False},
    "rug": {"name": "熔断兜底", "capabilities": ["紧急撤单", "紧急平仓"], "trading": True, "open_positions": False},
}


@app.get("/api/openclaw/policy")
def openclaw_policy():
    return {
        "ok": True,
        "instance": "polyauto" if _is_polyauto_instance() else "main",
        "private_key_access": False,
        "withdrawal": False,
        "transfer": False,
        "wallet_mutation": False,
        "all_orders_require_risk": True,
        "roles": OPENCLAW_PERMISSION_POLICY,
    }


class LlmConsensusPayload(BaseModel):
    primary: str = Field(default="", max_length=64)
    secondary: str = Field(default="", max_length=64)
    lead_id: Optional[str] = Field(default=None, max_length=256)


class LlmAdvisorPayload(BaseModel):
    """Read-only dual-model advisor request; it never creates an order."""
    prompt: str = Field(..., min_length=1, max_length=4000)
    lead_id: Optional[str] = Field(default=None, max_length=256)


def _llm_advisor_call(slot: str, prompt: str) -> dict[str, Any]:
    values = _read_llm_env()
    prefix = "LLM_SECONDARY_" if slot == "secondary" else "LLM_PRIMARY_"
    model = values.get(prefix + "MODEL", "") or values.get("LLM_MODEL", "")
    base = values.get(prefix + "BASE_URL", "") or values.get("LLM_BASE_URL", "")
    key = values.get(prefix + "API_KEY", "") or values.get("LLM_API_KEY", "")
    enabled = values.get(prefix + "ENABLED", "0").lower() in ("1", "true", "yes", "on")
    if not enabled or not model or not base or not key:
        return {"slot": slot, "enabled": False, "model": model, "text": None, "error": "模型未启用或配置不完整"}
    timeout = float(values.get(prefix + "TIMEOUT_SEC", "30") or 30)
    configured_tokens = int(float(values.get(prefix + "MAX_TOKENS", "512") or 512))
    # The Grok distributor may return an empty body for long reasoning
    # budgets. Keep the reviewer call short; it only needs a compact verdict.
    max_tokens = min(configured_tokens, 128) if "grok" in model.lower() else configured_tokens
    body = {"model": model, "messages": [{"role": "system", "content": "You are a read-only quantitative advisor. Return analysis only. Never call tools, trade, transfer funds, or alter wallet settings."}, {"role": "user", "content": prompt}], "temperature": float(values.get(prefix + "TEMPERATURE", "0.2") or 0.2), "max_tokens": max_tokens}
    last: Exception | None = None
    aliases = _model_aliases(values.get(prefix + "PROVIDER", ""), model)
    # The configured Grok label is a UI alias. Resolve the provider's actual
    # published Grok ids as well, otherwise a gateway may return an empty or
    # non-JSON response for the stale alias and the reviewer stays unused.
    if "grok" in model.lower():
        aliases.extend(item for item in _available_model_ids(base, key, timeout) if "grok" in item.lower())
        aliases = list(dict.fromkeys(aliases))
    for candidate in aliases:
        body["model"] = candidate
        try:
            response = requests.post(_llm_url(base, "/chat/completions"), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=body, timeout=timeout)
            _raise_provider_error(response)
            data = response.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            text = choices[0].get("message", {}).get("content", "") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else ""
            if not text:
                raise ValueError("响应缺少模型文本")
            _record_llm_usage(candidate, data.get("usage"), ok=True)
            return {"slot": slot, "enabled": True, "model": candidate, "text": str(text)[:8000], "error": None}
        except Exception as exc:
            last = exc
            if "grok" in model.lower():
                # Retry the provider with its stable published id and a tiny
                # plain-text request. Some distributor channels reject the
                # richer reasoning payload with an empty response even though
                # the same key/model is healthy for a compact review.
                try:
                    retry = requests.post(
                        _llm_url(base, "/chat/completions"),
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": "grok-4.5", "messages": [{"role": "user", "content": prompt[:800]}], "temperature": 0, "max_tokens": 32},
                        timeout=timeout,
                    )
                    _raise_provider_error(retry)
                    retry_data = retry.json()
                    retry_choices = retry_data.get("choices") if isinstance(retry_data, dict) else None
                    retry_text = retry_choices[0].get("message", {}).get("content", "") if isinstance(retry_choices, list) and retry_choices and isinstance(retry_choices[0], dict) else ""
                    if retry_text:
                        _record_llm_usage("grok-4.5", retry_data.get("usage"), ok=True)
                        return {"slot": slot, "enabled": True, "model": "grok-4.5", "text": str(retry_text)[:8000], "error": None}
                except Exception as retry_exc:
                    last = retry_exc
            # Try the remaining compatibility/dynamic ids for Grok. Some
            # distributors signal an unavailable model with an empty body,
            # which previously stopped the loop before the fallback ids.
            if "grok" not in model.lower() and "model_not_found" not in str(exc).lower() and "no available channel" not in str(exc).lower():
                break
    message = _safe_error(last or RuntimeError("模型调用失败"), key)
    _record_llm_usage(model, None, ok=False, error=message)
    return {"slot": slot, "enabled": True, "model": model, "text": None, "error": message}


@app.post("/api/llm/advisor")
def llm_advisor(payload: LlmAdvisorPayload):
    """Run the configured advisors for analysis only; deterministic risk still gates orders."""
    primary = _llm_advisor_call("primary", payload.prompt)
    secondary = _llm_advisor_call("secondary", payload.prompt)
    return {"ok": True, "lead_id": payload.lead_id, "primary": primary, "secondary": secondary, "decision": "HOLD", "trading_allowed": False, "requires_risk": True}


@app.post("/api/openclaw/consensus")
@app.post("/api/llm/consensus")
def llm_consensus(payload: LlmConsensusPayload):
    """Combine two model suggestions without calling tools or placing orders."""
    def normalize(value: str) -> str:
        return re.sub(r"[^A-Z]", "", value.upper())
    primary = normalize(payload.primary)
    secondary = normalize(payload.secondary)
    allowed = {"BUY", "SELL", "HOLD"}
    if primary in allowed and primary == secondary:
        decision, reason = primary, "主模型与复核模型一致"
    else:
        decision, reason = "HOLD", "模型意见不一致或无效，等待风控/人工确认"
    return {"ok": True, "decision": decision, "reason": reason, "lead_id": payload.lead_id, "trading_allowed": False, "requires_risk": True}


def _risk_state(pnl: dict) -> str:
    """Approximate the bot's risk-gate state for UI display."""
    balance = _state.get("balance_pusd")
    value = _state.get("value_usd") or 0.0
    equity = (balance if balance is not None else cfg.paper_equity_usd) + value
    if (
        _state.get("bot_mode") == "live"
        and cfg.max_daily_realized_profit_usd > 0
        and pnl["realized_usd"] >= cfg.max_daily_realized_profit_usd
    ):
        return "PROFIT_TAKE"
    if (
        cfg.max_daily_loss_fraction > 0
        and pnl["realized_usd"] <= -(equity * cfg.max_daily_loss_fraction)
    ):
        return "LOSS_CAP"
    # consecutive-loss kill detection
    with db() as c:
        rows = c.execute(
            "SELECT o.token_id, r.winning_token FROM orders o "
            "JOIN resolutions r ON r.condition_id=o.condition_id "
            "LEFT JOIN ("
            "  SELECT condition_id, token_id, dry_run, SUM(size) AS exit_size "
            "  FROM orders "
            "  WHERE status IN ('exit_filled','exit_matched','exit_partial') "
            "  GROUP BY condition_id, token_id, dry_run"
            ") x ON x.condition_id=o.condition_id AND x.token_id=o.token_id "
            "AND x.dry_run=o.dry_run "
            "WHERE o.status IN ('filled','matched') AND o.side IN ('UP','DOWN') AND o.dry_run=0 "
            "AND COALESCE(x.exit_size, 0) < (o.size - 0.02) "
            "ORDER BY r.resolved_ts DESC LIMIT 10"
        ).fetchall()
    streak = 0
    for token, winner in rows:
        if token == winner:
            break
        streak += 1
    if cfg.consecutive_loss_kill > 0 and streak >= cfg.consecutive_loss_kill:
        return f"LOSS_STREAK({streak})"
    return "OK"

def _risk_snapshot(pnl: dict) -> dict[str, Any]:
    positions = _filter_active_positions(_state.get("positions") or [])
    position_value = 0.0
    for item in positions:
        try:
            position_value += float(item.get("size") or 0) * float(item.get("curPrice") or 0)
        except (TypeError, ValueError):
            continue
    # Orders are read from SQLite rather than `_state`: the dashboard keeps
    # recent orders as a response-only query, so relying on `_state.orders`
    # silently reported zero open orders.
    open_order_notional = 0.0
    try:
        with db() as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(COALESCE(size, 0) * COALESCE(price, 0)), 0) FROM orders WHERE LOWER(COALESCE(status, '')) "
                "IN ('submitted','open','matched','partial','partially_filled','pending')"
            ).fetchone()
        open_orders = int(row[0] or 0) if row else 0
        open_order_notional = float(row[1] or 0.0) if row else 0.0
    except Exception:
        open_orders = 0
    balance = _state.get("balance_pusd")
    equity = (float(balance) if balance is not None else float(getattr(cfg, "paper_equity_usd", 0.0))) + position_value
    exposure_ratio = position_value / equity if equity > 0 else None
    risk_state = _risk_state(pnl)
    return {
        "state": risk_state,
        "position_count": len(positions),
        "position_value_usd": round(position_value, 4),
        "open_orders": open_orders,
        "open_order_notional_usd": round(open_order_notional, 4),
        "exposure_ratio": round(exposure_ratio, 6) if exposure_ratio is not None else None,
        "circuit_reason": None if risk_state == "OK" else risk_state,
        "daily_realized_usd": pnl.get("realized_usd"),
        "max_daily_loss_fraction": cfg.max_daily_loss_fraction,
        "max_open_positions": cfg.max_open_positions,
        "updated_at": time.time(),
    }


def _filter_active_positions(positions: list[dict]) -> list[dict]:
    """Return positions that still require trading attention.

    The Data API keeps settled winning positions in the same collection and
    marks them ``redeemable`` (or ``mergeable``).  They are no longer open
    trading positions and must not keep the risk gate or dashboard showing a
    stale holding forever.
    """
    out: list[dict] = []
    for p in positions:
        cp = p.get("curPrice")
        sz = p.get("size")
        if cp is None or sz is None:
            continue
        try:
            if float(cp) <= 0.0 or float(sz) <= 0.0:
                continue
        except Exception:
            continue
        if bool(p.get("redeemable")) or bool(p.get("mergeable")):
            continue
        out.append(p)
    return out


def _filter_settled_positions(positions: list[dict]) -> list[dict]:
    """Keep resolved positions visible in a separate settlement section."""
    out: list[dict] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        if bool(position.get("redeemable")) or bool(position.get("mergeable")):
            out.append(position)
    return out


def _compact_sports_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Keep the 500ms dashboard poll small; detailed sports data is not needed by the card."""
    if not isinstance(meta, dict):
        return {}
    compact = {key: meta.get(key) for key in ("enabled", "mode", "status", "paper_only", "live_orders") if key in meta}
    markets = meta.get("markets")
    decisions = meta.get("decisions")
    orders = meta.get("orders")
    if isinstance(markets, list):
        compact["market_count"] = len(markets)
    if isinstance(decisions, list):
        compact["decision_count"] = len(decisions)
        compact["recent_decisions"] = decisions[-10:]
    if isinstance(orders, list):
        compact["order_count"] = len(orders)
        compact["recent_orders"] = orders[-10:]
    return compact


@app.get("/api/state")
def state():
    m = _state.get("market")
    eth_m = _state.get("eth_market")
    now = time.time()
    pnl = realized_pnl_today()
    use_decision_log_fallback = "rtds" not in cfg.price_signal_source.strip().lower()
    btc_signal = _state.get("btc_signal") or (
        _fallback_signal_from_decisions("BTC") if use_decision_log_fallback else None
    )
    eth_signal = _state.get("eth_signal") or (
        _fallback_signal_from_decisions("ETH") if use_decision_log_fallback else None
    )
    return {
        "now": now,
        "bot_running": _state["bot_running"],
        "bot_mode": _state.get("bot_mode", "stopped"),
        "bot_assets": _state.get("bot_assets", {"BTC": False, "ETH": False}),
        "instance": "polyauto" if _is_polyauto_instance() else "main",
        "service_modes": _service_status_snapshot(),
        "risk_state": _risk_state(pnl),
        "risk_snapshot": _risk_snapshot(pnl),
        "wallet": {
            "eoa": cfg.wallet_address,
            "deposit": _deposit_wallet_address(),
            "funder": cfg.funder_address,
            "balance_pusd": _state.get("balance_pusd"),
            "value_usd": _state.get("value_usd"),
            "binding": _wallet_status(),
        },
        "market": (
            None
            if not m
            else {
                **m,
                "t_remaining": m["end_ts"] - now,
            }
        ),
        "eth_market": (
            None
            if not eth_m
            else {
                **eth_m,
                "t_remaining": eth_m["end_ts"] - now,
            }
        ),
        "book_up": _state.get("book_up"),
        "book_down": _state.get("book_down"),
        "eth_book_up": _state.get("eth_book_up"),
        "eth_book_down": _state.get("eth_book_down"),
        "btc_signal": btc_signal,
        "eth_signal": eth_signal,
        "btc_price_history": list(_state.get("btc_price_history") or []),
        "eth_price_history": list(_state.get("eth_price_history") or []),
        "weather": list(_state.get("weather") or []),
        "sports": list(_state.get("sports") or []),
        # The compact `sports` list feeds the card; this metadata keeps the
        # full paper audit (markets, decisions and simulated orders) available
        # to operators without coupling it to the CLOB order tables.
        "sports_meta": _compact_sports_meta(_state.get("sports_meta") or {}),
        "agent_status": _agent_status_snapshot(),
        "openclaw_bridge": _openclaw_bridge_snapshot(),
        "llm": {
            "settings": {
                "primary_model": _llm_settings_response().get("primary", {}).get("model", ""),
                "secondary_model": _llm_settings_response().get("secondary", {}).get("model", ""),
            },
            "usage": _llm_usage_snapshot(),
        },
        "positions": _filter_active_positions(_state.get("positions") or []),
        "settled_positions": _filter_settled_positions(_state.get("positions") or []),
        "pnl": pnl,
        "config": {
            "min_entry_price": cfg.min_entry_price,
            "max_entry_price": cfg.max_entry_price,
            "up_min_entry_price": cfg.up_min_entry_price,
            "up_max_entry_price": cfg.up_max_entry_price,
            "min_net_edge": cfg.min_net_edge,
            "high_price_edge_threshold": cfg.high_price_edge_threshold,
            "high_price_min_net_edge": cfg.high_price_min_net_edge,
            "high_price_btc_delta_usd": cfg.high_price_btc_delta_usd,
            "btc_delta_filter_enabled": cfg.btc_delta_filter_enabled,
            "btc_delta_threshold_usd": cfg.btc_delta_threshold_usd,
            "btc_up_min_delta_usd": cfg.btc_up_min_delta_usd,
            "btc_up_max_delta_usd": cfg.btc_up_max_delta_usd,
            "btc_down_min_delta_usd": cfg.btc_down_min_delta_usd,
            "btc_down_max_delta_usd": cfg.btc_down_max_delta_usd,
            "btc_price_symbol": cfg.btc_price_symbol,
            "price_signal_source": cfg.price_signal_source,
            "rtds_ws_url": cfg.rtds_ws_url,
            "rtds_topic": cfg.rtds_topic,
            "rtds_max_age_sec": cfg.rtds_max_age_sec,
            "rtds_stale_max_age_sec": cfg.rtds_stale_max_age_sec,
            "chainlink_btc_twap_30s_feed_id": cfg.chainlink_btc_twap_30s_feed_id,
            "chainlink_eth_twap_30s_feed_id": cfg.chainlink_eth_twap_30s_feed_id,
            "price_source_guard_enabled": cfg.price_source_guard_enabled,
            "allow_binance_proxy_chainlink_entries": cfg.allow_binance_proxy_chainlink_entries,
            "eth_market_enabled": cfg.eth_market_enabled,
            "eth_trading_enabled": cfg.eth_trading_enabled,
            "instance_name": getattr(cfg, "instance_name", "main"),
            "btc_live_enabled": _service_status_snapshot()["BTC"]["live_enabled"],
            "eth_live_allowed": bool(getattr(cfg, "eth_live_allowed", True)),
            "weather_live_allowed": bool(getattr(cfg, "weather_live_allowed", True)),
            "sports_live_allowed": False,
            "eth_series_slug": cfg.eth_series_slug,
            "eth_price_symbol": cfg.eth_price_symbol,
            "eth_delta_filter_enabled": cfg.eth_delta_filter_enabled,
            "eth_delta_threshold_usd": cfg.eth_delta_threshold_usd,
            "eth_up_min_delta_usd": cfg.eth_up_min_delta_usd,
            "eth_up_max_delta_usd": cfg.eth_up_max_delta_usd,
            "eth_down_min_delta_usd": cfg.eth_down_min_delta_usd,
            "eth_down_max_delta_usd": cfg.eth_down_max_delta_usd,
            "eth_high_price_delta_usd": cfg.eth_high_price_delta_usd,
            "eth_early_strong_delta_up_min_delta_usd": cfg.eth_early_strong_delta_up_min_delta_usd,
            "eth_early_strong_delta_down_max_delta_usd": cfg.eth_early_strong_delta_down_max_delta_usd,
            "eth_strong_delta_up_min_delta_usd": cfg.eth_strong_delta_up_min_delta_usd,
            "eth_strong_delta_down_max_delta_usd": cfg.eth_strong_delta_down_max_delta_usd,
            "eth_late_edge_up_min_delta_usd": cfg.eth_late_edge_up_min_delta_usd,
            "eth_late_edge_down_max_delta_usd": cfg.eth_late_edge_down_max_delta_usd,
            "eth_late_edge_confirm_checks": cfg.eth_late_edge_confirm_checks,
            "eth_early_strong_delta_risk_fraction": cfg.eth_early_strong_delta_risk_fraction,
            "eth_strong_delta_risk_fraction": cfg.eth_strong_delta_risk_fraction,
            "eth_order_risk_fraction": cfg.eth_order_risk_fraction,
            "eth_late_edge_risk_fraction": cfg.eth_late_edge_risk_fraction,
            "seconds_before_close": cfg.seconds_before_close,
            "min_t_remaining_sec": cfg.min_t_remaining_sec,
            "mid_entry_enabled": cfg.mid_entry_enabled,
            "mid_entry_window_sec": cfg.mid_entry_window_sec,
            "mid_entry_min_t_remaining_sec": cfg.mid_entry_min_t_remaining_sec,
            "mid_entry_min_price": cfg.mid_entry_min_price,
            "mid_entry_max_price": cfg.mid_entry_max_price,
            "mid_entry_confirm_checks": cfg.mid_entry_confirm_checks,
            "mid_entry_risk_fraction": cfg.mid_entry_risk_fraction,
            "mid_btc_up_min_delta_usd": cfg.mid_btc_up_min_delta_usd,
            "mid_btc_down_max_delta_usd": cfg.mid_btc_down_max_delta_usd,
            "strong_delta_entry_enabled": cfg.strong_delta_entry_enabled,
            "strong_delta_entry_window_sec": cfg.strong_delta_entry_window_sec,
            "strong_delta_entry_min_t_remaining_sec": cfg.strong_delta_entry_min_t_remaining_sec,
            "strong_delta_entry_min_price": cfg.strong_delta_entry_min_price,
            "strong_delta_entry_max_price": cfg.strong_delta_entry_max_price,
            "strong_delta_entry_up_min_delta_usd": cfg.strong_delta_entry_up_min_delta_usd,
            "strong_delta_entry_down_max_delta_usd": cfg.strong_delta_entry_down_max_delta_usd,
            "strong_delta_entry_confirm_checks": cfg.strong_delta_entry_confirm_checks,
            "strong_delta_entry_risk_fraction": cfg.strong_delta_entry_risk_fraction,
            "early_strong_delta_entry_enabled": cfg.early_strong_delta_entry_enabled,
            "early_strong_delta_entry_window_sec": cfg.early_strong_delta_entry_window_sec,
            "early_strong_delta_entry_min_t_remaining_sec": cfg.early_strong_delta_entry_min_t_remaining_sec,
            "early_strong_delta_entry_min_price": cfg.early_strong_delta_entry_min_price,
            "early_strong_delta_entry_max_price": cfg.early_strong_delta_entry_max_price,
            "early_strong_delta_entry_up_min_delta_usd": cfg.early_strong_delta_entry_up_min_delta_usd,
            "early_strong_delta_entry_down_max_delta_usd": cfg.early_strong_delta_entry_down_max_delta_usd,
            "early_strong_delta_entry_confirm_checks": cfg.early_strong_delta_entry_confirm_checks,
            "early_strong_delta_entry_risk_fraction": cfg.early_strong_delta_entry_risk_fraction,
            "early_strong_delta_entry_hedge_enabled": cfg.early_strong_delta_entry_hedge_enabled,
            "early_strong_delta_entry_hedge_max_price": cfg.early_strong_delta_entry_hedge_max_price,
            "normal_scale_in_enabled": cfg.normal_scale_in_enabled,
            "late_edge_entry_enabled": cfg.late_edge_entry_enabled,
            "late_edge_entry_window_sec": cfg.late_edge_entry_window_sec,
            "late_edge_entry_min_t_remaining_sec": cfg.late_edge_entry_min_t_remaining_sec,
            "late_edge_entry_min_price": cfg.late_edge_entry_min_price,
            "late_edge_entry_max_price": cfg.late_edge_entry_max_price,
            "late_edge_entry_delta_filter_enabled": cfg.late_edge_entry_delta_filter_enabled,
            "late_edge_entry_up_min_delta_usd": cfg.late_edge_entry_up_min_delta_usd,
            "late_edge_entry_down_max_delta_usd": cfg.late_edge_entry_down_max_delta_usd,
            "late_edge_entry_confirm_checks": cfg.late_edge_entry_confirm_checks,
            "late_edge_entry_mid_confirm_checks": cfg.late_edge_entry_mid_confirm_checks,
            "late_edge_entry_late_confirm_checks": cfg.late_edge_entry_late_confirm_checks,
            "late_edge_entry_risk_fraction": cfg.late_edge_entry_risk_fraction,
            "eth_late_edge_delta_filter_enabled": cfg.eth_late_edge_delta_filter_enabled,
            "stable_delta_entry_enabled": cfg.stable_delta_entry_enabled,
            "stable_delta_entry_window_sec": cfg.stable_delta_entry_window_sec,
            "stable_delta_entry_min_t_remaining_sec": cfg.stable_delta_entry_min_t_remaining_sec,
            "stable_delta_entry_min_price": cfg.stable_delta_entry_min_price,
            "stable_delta_entry_max_price": cfg.stable_delta_entry_max_price,
            "stable_delta_entry_min_abs_delta_usd": cfg.stable_delta_entry_min_abs_delta_usd,
            "stable_delta_entry_max_abs_delta_usd": cfg.stable_delta_entry_max_abs_delta_usd,
            "stable_delta_entry_max_delta_move_usd": cfg.stable_delta_entry_max_delta_move_usd,
            "stable_delta_entry_confirm_checks": cfg.stable_delta_entry_confirm_checks,
            "stable_delta_entry_risk_fraction": cfg.stable_delta_entry_risk_fraction,
            "entry_momentum_filter_enabled": cfg.entry_momentum_filter_enabled,
            "entry_momentum_min_price": cfg.entry_momentum_min_price,
            "entry_momentum_max_price": cfg.entry_momentum_max_price,
            "entry_momentum_max_ask_move": cfg.entry_momentum_max_ask_move,
            "eth_stable_delta_min_abs_usd": cfg.eth_stable_delta_min_abs_usd,
            "eth_stable_delta_max_abs_usd": cfg.eth_stable_delta_max_abs_usd,
            "eth_stable_delta_max_move_usd": cfg.eth_stable_delta_max_move_usd,
            "eth_stable_delta_trade_enabled": cfg.eth_stable_delta_trade_enabled,
            "early_entry_enabled": cfg.early_entry_enabled,
            "early_entry_seconds_before_close": cfg.early_entry_seconds_before_close,
            "early_entry_min_price": cfg.early_entry_min_price,
            "early_entry_max_price": cfg.early_entry_max_price,
            "tail_entry_enabled": cfg.tail_entry_enabled,
            "tail_entry_window_sec": cfg.tail_entry_window_sec,
            "tail_entry_min_t_remaining_sec": cfg.tail_entry_min_t_remaining_sec,
            "tail_entry_min_price": cfg.tail_entry_min_price,
            "tail_entry_max_price": cfg.tail_entry_max_price,
            "tail_entry_confirm_checks": cfg.tail_entry_confirm_checks,
            "tail_entry_risk_fraction": cfg.tail_entry_risk_fraction,
            "strong_normal_reverse_enabled": cfg.strong_normal_reverse_enabled,
            "strong_normal_reverse_held_bid_threshold": cfg.strong_normal_reverse_held_bid_threshold,
            "strong_normal_reverse_min_price": cfg.strong_normal_reverse_min_price,
            "strong_normal_reverse_max_price": cfg.strong_normal_reverse_max_price,
            "strong_normal_reverse_confirm_checks": cfg.strong_normal_reverse_confirm_checks,
            "strong_normal_reverse_risk_fraction": cfg.strong_normal_reverse_risk_fraction,
            "scale_in_after_early_enabled": cfg.scale_in_after_early_enabled,
            "max_buys_per_market": cfg.max_buys_per_market,
            "one_side_per_market": cfg.one_side_per_market,
            "trend_overheat_filter_enabled": cfg.trend_overheat_filter_enabled,
            "trend_overheat_min_streak": cfg.trend_overheat_min_streak,
            "trend_overheat_price_floor": cfg.trend_overheat_price_floor,
            "order_risk_fraction": cfg.order_risk_fraction,
            "order_fixed_notional_usd": cfg.order_fixed_notional_usd,
            "order_balance_reserve_usd": cfg.order_balance_reserve_usd,
            "min_order_notional_usd": cfg.min_order_notional_usd,
            "target_min_orders_per_hour": cfg.target_min_orders_per_hour,
            "max_orders_per_hour": cfg.max_orders_per_hour,
            "max_open_positions": cfg.max_open_positions,
            "max_daily_loss_fraction": cfg.max_daily_loss_fraction,
            "max_daily_realized_profit_usd": cfg.max_daily_realized_profit_usd,
            "order_retry_cooldown_sec": cfg.order_retry_cooldown_sec,
            "max_buy_retries_per_market": cfg.max_buy_retries_per_market,
            "retry_min_t_remaining_sec": cfg.retry_min_t_remaining_sec,
            "max_retry_price_drift_ticks": cfg.max_retry_price_drift_ticks,
            "fok_price_buffer_ticks": cfg.fok_price_buffer_ticks,
            "market_stale_grace_sec": cfg.market_stale_grace_sec,
            "confirm_checks": cfg.confirm_checks,
            "stagnation_window_sec": cfg.stagnation_window_sec,
            "volatility_window_sec": cfg.volatility_window_sec,
            "max_top_move_ticks": cfg.max_top_move_ticks,
            "early_reversal_exit_enabled": cfg.early_reversal_exit_enabled,
            "early_reversal_exit_window_sec": cfg.early_reversal_exit_window_sec,
            "early_reversal_exit_min_t_remaining_sec": cfg.early_reversal_exit_min_t_remaining_sec,
            "early_reversal_held_bid_threshold": cfg.early_reversal_held_bid_threshold,
            "early_reversal_confirm_checks": cfg.early_reversal_confirm_checks,
            "early_reversal_exit_fraction": cfg.early_reversal_exit_fraction,
            "reversal_exit_enabled": cfg.reversal_exit_enabled,
            "reversal_partial_exit_enabled": cfg.reversal_partial_exit_enabled,
            "reversal_partial_exit_window_sec": cfg.reversal_partial_exit_window_sec,
            "reversal_partial_exit_min_t_remaining_sec": cfg.reversal_partial_exit_min_t_remaining_sec,
            "reversal_partial_held_bid_threshold": cfg.reversal_partial_held_bid_threshold,
            "reversal_partial_held_bid_drawdown": cfg.reversal_partial_held_bid_drawdown,
            "reversal_partial_confirm_checks": cfg.reversal_partial_confirm_checks,
            "reversal_partial_exit_fraction": cfg.reversal_partial_exit_fraction,
            "reversal_exit_window_sec": cfg.reversal_exit_window_sec,
            "reversal_normal_min_t_remaining_sec": cfg.reversal_normal_min_t_remaining_sec,
            "reversal_exit_min_t_remaining_sec": cfg.reversal_exit_min_t_remaining_sec,
            "reversal_opposite_bid_threshold": cfg.reversal_opposite_bid_threshold,
            "reversal_confirm_checks": cfg.reversal_confirm_checks,
            "reversal_held_bid_threshold": cfg.reversal_held_bid_threshold,
            "reversal_held_bid_drawdown": cfg.reversal_held_bid_drawdown,
            "reversal_exit_require_btc_reversal": cfg.reversal_exit_require_btc_reversal,
            "reversal_late_exit_enabled": cfg.reversal_late_exit_enabled,
            "reversal_late_window_sec": cfg.reversal_late_window_sec,
            "reversal_late_held_bid_threshold": cfg.reversal_late_held_bid_threshold,
            "reversal_late_confirm_checks": cfg.reversal_late_confirm_checks,
            "reversal_exit_order_fraction": cfg.reversal_exit_order_fraction,
            "sell_fok_slippage_ticks": cfg.sell_fok_slippage_ticks,
            "sell_exit_max_depth_ticks": cfg.sell_exit_max_depth_ticks,
            "sell_exit_max_depth_levels": cfg.sell_exit_max_depth_levels,
            "sell_exit_fak_fallback_enabled": cfg.sell_exit_fak_fallback_enabled,
            "sell_exit_reconcile_trades": cfg.sell_exit_reconcile_trades,
            "weather_enabled": cfg.weather_enabled,
            "weather_live_trading_enabled": cfg.weather_live_trading_enabled,
            "weather_cities": cfg.weather_cities,
            "weather_scan_interval_sec": cfg.weather_scan_interval_sec,
            "weather_min_edge": cfg.weather_min_edge,
            "weather_min_entry_price": cfg.weather_min_entry_price,
            "weather_max_entry_price": cfg.weather_max_entry_price,
            "sports_enabled": cfg.sports_enabled,
            "sports_market_scan_pages": cfg.sports_market_scan_pages,
            "sports_max_days_ahead": cfg.sports_max_days_ahead,
            "sports_min_edge": cfg.sports_min_edge,
            "sports_min_entry_price": cfg.sports_min_entry_price,
            "sports_max_entry_price": cfg.sports_max_entry_price,
            "sports_max_exposure_usd": cfg.sports_max_exposure_usd,
            "sports_order_size": cfg.sports_order_size,
            "sports_confirm_checks": cfg.sports_confirm_checks,
            "sports_live_trading_enabled": False,
        },
        "decisions": recent_decisions(limit=80),
        "orders": recent_orders(limit=30),
        "errors": _state.get("errors") or {},
    }


@app.get("/api/sports/summary")
def sports_summary():
    """Return the latest isolated sports paper audit snapshot.

    The endpoint is intentionally backed by the in-memory paper service and
    exposes its ``paper_only``/``live_orders`` invariants for external
    monitoring.  It never accepts order commands or CLOB credentials.
    """
    snapshot = dict(_state.get("sports_meta") or {})
    if not snapshot:
        snapshot = _sports_service.snapshot(status="starting")
    return snapshot


@app.get("/api/events")
def events(since_decision: int = Query(0), since_order: int = Query(0)):
    return {
        "decisions": recent_decisions(limit=200, since_id=since_decision),
        "orders": recent_orders(limit=50, since_id=since_order),
    }
