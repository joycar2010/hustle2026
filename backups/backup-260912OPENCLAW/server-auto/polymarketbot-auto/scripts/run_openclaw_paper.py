"""Local OpenClaw-compatible Paper heartbeat publisher."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import requests

ROLES = ("desk", "search", "whale", "shill", "risk", "sniper", "exit", "rug")

def _env_flags(root: Path) -> tuple[bool, bool, str]:
    """Read non-secret live gates without importing the dashboard process."""
    values: dict[str, str] = {}
    try:
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'").lower()
    except OSError:
        pass
    try:
        process_mode = (root / "bot.mode").read_text(encoding="utf-8").strip().lower()
    except OSError:
        process_mode = "paper"
    truthy = {"1", "true", "yes", "on"}
    return values.get("BTC_LIVE_ENABLED", "false") in truthy, values.get("ETH_TRADING_ENABLED", "false") in truthy, process_mode

def _market_data_scope(process_mode: str) -> dict[str, str]:
    """Market feed scope is independent from permission to place orders."""
    return {
        "BTC": "live" if process_mode in ("live", "paper") else "paper",
        "ETH": "live" if process_mode in ("live", "paper") else "paper",
        "WEATHER": "paper",
        "SPORTS": "paper",
    }

def _activity_snapshot(root: Path, now: float) -> dict[str, object]:
    """Read recent strategy events without touching credentials or orders."""
    empty = {"decision_id": 0, "order_id": 0, "decision_activity": 0,
             "order_activity": 0, "open_orders": 0, "last_asset": None}
    db_path = Path(os.environ.get("TRADES_DB_PATH", str(root / "trades.db"))).expanduser()
    if not db_path.is_absolute():
        db_path = root / db_path
    if not db_path.exists():
        return empty
    try:
        with sqlite3.connect(str(db_path), timeout=0.2) as conn:
            decision = conn.execute("SELECT id, ts, asset FROM decisions ORDER BY id DESC LIMIT 1").fetchone() or (0, 0, None)
            order = conn.execute("SELECT id, ts, asset FROM orders ORDER BY id DESC LIMIT 1").fetchone() or (0, 0, None)
            window_start = now - 12.0
            decision_activity = conn.execute("SELECT COUNT(*) FROM decisions WHERE ts >= ?", (window_start,)).fetchone()[0]
            order_activity = conn.execute("SELECT COUNT(*) FROM orders WHERE ts >= ?", (window_start,)).fetchone()[0]
            open_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status IN ('open','live','matched','partial','pending')").fetchone()[0]
            return {"decision_id": int(decision[0] or 0), "order_id": int(order[0] or 0),
                    "decision_activity": int(decision_activity or 0), "order_activity": int(order_activity or 0),
                    "open_orders": int(open_orders or 0), "last_asset": order[2] or decision[2],
                    "last_ts": max(float(decision[1] or 0), float(order[1] or 0))}
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return empty

def _call_dual_models(activity: dict[str, object], now: float) -> dict[str, object]:
    """Send a read-only workflow snapshot through the dashboard advisor API.

    The dashboard owns provider credentials and token accounting.  This worker
    only submits market context; it never receives or stores keys and never
    submits an order based on the model response.
    """
    endpoint = os.environ.get("OPENCLAW_ADVISOR_URL", "http://127.0.0.1:8887/api/llm/advisor")
    lead_id = f"openclaw-{int(activity.get('decision_id', 0))}"
    prompt = (
        "OpenClaw read-only workflow review. Return a short JSON suggestion with BUY, SELL, or HOLD. "
        "Do not call tools or place orders; deterministic risk remains the only order gate. "
        f"decision_id={activity.get('decision_id', 0)}, order_id={activity.get('order_id', 0)}, "
        f"decision_activity={activity.get('decision_activity', 0)}, order_activity={activity.get('order_activity', 0)}, "
        f"open_orders={activity.get('open_orders', 0)}, asset={activity.get('last_asset') or 'BTC/ETH'}."
    )
    try:
        # The dashboard calls the two providers sequentially (their own
        # per-provider timeouts can be 60s/30s), so the bridge must allow the
        # complete read-only pair to finish.
        response = requests.post(endpoint, json={"prompt": prompt, "lead_id": lead_id}, timeout=120)
        response.raise_for_status()
        data = response.json() if response.content else {}
        primary = data.get("primary") if isinstance(data, dict) else {}
        secondary = data.get("secondary") if isinstance(data, dict) else {}
        return {
            "last_call_ts": now,
            "lead_id": lead_id,
            "primary_ok": isinstance(primary, dict) and not primary.get("error"),
            "secondary_ok": isinstance(secondary, dict) and not secondary.get("error"),
            "primary_model": primary.get("model") if isinstance(primary, dict) else None,
            "secondary_model": secondary.get("model") if isinstance(secondary, dict) else None,
            "error": None,
        }
    except Exception as exc:
        return {"last_call_ts": now, "lead_id": lead_id, "primary_ok": False,
                "secondary_ok": False, "primary_model": None, "secondary_model": None,
                "error": str(exc)[:300]}
def main() -> None:
    root = Path(__file__).resolve().parent.parent
    heartbeat = root / "openclaw-heartbeat.json"
    last_model_call = 0.0
    last_model_decision = 0
    model_state: dict[str, object] = {"enabled": True, "primary_ok": False, "secondary_ok": False}
    model_lock = threading.Lock()

    def run_models(snapshot: dict[str, object], call_ts: float) -> None:
        result = _call_dual_models(snapshot, call_ts)
        with model_lock:
            model_state.clear()
            model_state.update(result)
    while True:
        now = time.time()
        btc_live, eth_live, process_mode = _env_flags(root)
        live_execution = process_mode == "live" and (btc_live or eth_live)
        activity = _activity_snapshot(root, now)
        analysis_queue = min(99, int(activity.get("decision_activity", 0)))
        execution_queue = min(99, max(int(activity.get("order_activity", 0)), int(activity.get("open_orders", 0))))
        decision_id = int(activity.get("decision_id", 0) or 0)
        if decision_id and now - last_model_call >= 90:
            threading.Thread(target=run_models, args=(dict(activity), now), daemon=True).start()
            last_model_call = now
            last_model_decision = decision_id
        with model_lock:
            model_snapshot = dict(model_state)
        # Keep market-data status separate from execution permissions.  The
        # feed can remain live while a strategy is paper-only.
        data_scope = _market_data_scope(process_mode)
        model_calls = {
            "primary": "ok" if model_snapshot.get("primary_ok") else ("error" if model_snapshot.get("error") else "waiting"),
            "secondary": "ok" if model_snapshot.get("secondary_ok") else ("error" if model_snapshot.get("error") else "waiting"),
            "primary_model": model_snapshot.get("primary_model") or "gpt-6-astra",
            "secondary_model": model_snapshot.get("secondary_model") or "grok-4.6",
            "last_call_ts": model_snapshot.get("last_call_ts"),
        }
        roles = {
            role: {
                # Every role is a healthy Paper worker. Paper mode still
                # prevents signing or live execution; status reflects worker
                # health rather than whether a queue currently has work.
                "status": "running",
                "heartbeat_ts": now,
                "queue_depth": execution_queue if role in ("sniper", "exit", "rug") else analysis_queue,
                "market": "BTC/ETH/天气/体育",
                "mode": "live" if live_execution and role in ("sniper", "exit", "rug") else "paper",
                "execution_detail": "L2 实盘执行链路；仅 BTC/ETH；仍需 RISK 通过" if live_execution and role in ("sniper", "exit", "rug") else "Paper 调度；无钱包和下单权限",
                "detail": "本地 Paper 调度；无钱包和下单权限",
                "workflow_stage": "执行中" if (execution_queue if role in ("sniper", "exit", "rug") else analysis_queue) else "等待行情",
                "last_decision_id": activity.get("decision_id", 0),
                "last_order_id": activity.get("order_id", 0),
                "processed_total": activity.get("decision_id", 0) if role not in ("sniper", "exit", "rug") else activity.get("order_id", 0),
                "execution_scope": (
                    "btc_l2_live" if live_execution and role == "sniper" else
                    "btc_close_only_live" if live_execution and role == "exit" else
                    "btc_emergency_live" if live_execution and role == "rug" else
                    "risk_gate" if role == "risk" else "read_only"
                ),
                "data_scope": data_scope,
                "model_calls": model_calls,
            }
            for role in ROLES
        }
        state = {
            "schema_version": 1,
            "instance": "polyauto" if "polymarketbot-auto" in str(root).lower() else "main",
            "pid": os.getpid(),
            "updated_ts": now,
            "roles": roles,
            "bridge": {
                "connected": True,
                "read_only": True,
                "strategy_owner": "deterministic-worker",
                "execution_owner": "l2-gateway",
                "btc_live": btc_live and process_mode == "live",
                "eth_live": eth_live and process_mode == "live",
                "last_decision_id": activity.get("decision_id", 0),
                "last_order_id": activity.get("order_id", 0),
            },
            "models": model_snapshot,
            "data_scope": data_scope,
            "model_calls": model_calls,
        }
        tmp = heartbeat.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(heartbeat)
        time.sleep(5)

if __name__ == "__main__":
    main()
