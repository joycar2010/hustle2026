"""Product-scoped Paper control and independently stored live settings."""
import fcntl
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

ROOT = Path("/home/ec2-user/polymarketbot-test")
STATE = ROOT / "state/products"


@dataclass(frozen=True)
class Product:
    key: str
    asset: str
    label: str
    series: str
    window: int
    unit: str
    ledger: Path

    @property
    def meta(self):
        return {"product_key": self.key, "asset": self.asset, "product": self.key.upper(),
                "label": self.label, "series_slug": self.series, "market_window": self.window,
                "mode": "late_edge", "paper_or_live": "paper"}

    @property
    def directory(self):
        return STATE / self.key


PRODUCTS = {p.key: p for p in (
    Product("btc5m", "BTC", "BTC 5M", "btc-up-or-down-5m", 300,
            "polymarket-test-btc-paper.service", ROOT / "state/paper-native-a/data/paper.db"),
    Product("btc15m", "BTC15M", "BTC 15M", "btc-up-or-down-15m", 900,
            "polytest-btc15m-paper.service", STATE / "btc15m/data/paper_btc15m.db"),
    Product("sol5m", "SOL", "SOL 5M", "sol-up-or-down-5m", 300, "polytest-sol5m-paper.service",
            ROOT / "releases/polytest-sol5m-20261121T140426Z/data/paper_sol5m.db"),
)}


def find(key):
    key = key.strip().lower()
    key = {"btc": "btc5m", "sol": "sol5m"}.get(key, key)
    if key not in PRODUCTS:
        raise HTTPException(404, "未知产品")
    return PRODUCTS[key]


# Only explicitly supported, non-secret strategy settings can cross the API.
LABELS = {
    "entry_window_sec": "尾盘入场窗口（秒）", "min_t_remaining_sec": "最少剩余时间（秒）",
    "min_entry_price": "最低入场价", "max_entry_price": "最高入场价",
    "opening_gap_max_entry_price": "开盘缺口价格上限", "high_ask_threshold": "高价档门槛",
    "min_net_edge": "最低净优势", "min_net_edge_high": "高价档最低净优势",
    "taker_fee_rate": "Taker 费率系数", "confirm_checks": "确认次数",
    "confirm_checks_high": "高价档确认次数", "delta_filter_enabled": "价格变化过滤",
    "up_min_delta_usd": "上涨最小价差（美元）", "down_max_delta_usd": "下跌最大价差（美元）",
    "signal_require_consensus": "要求行情源一致", "signal_min_venues": "最少行情源数量",
    "lead_table_enabled": "使用领先幅度表", "lead_edge_margin": "上涨领先优势余量",
    "lead_edge_margin_down": "下跌领先优势余量", "lead_min_bp": "最低领先幅度（基点）",
    "up_lead_min_bp": "上涨领先幅度（基点）", "down_lead_min_bp": "下跌领先幅度（基点）",
    "opening_gap_enabled": "启用开盘缺口", "opening_gap_window_sec": "开盘缺口窗口（秒）",
    "opening_gap_min_bp": "最小开盘缺口（基点）", "order_shares": "单笔张数",
    "max_order_usd": "单笔金额上限（美元）", "size_scale_enabled": "按价格缩放张数",
    "size_scale_ref_ask": "缩放参考价", "daily_loss_limit_usd": "日亏损上限（美元）",
    "daily_profit_limit_usd": "日止盈（美元，0 表示关闭）", "max_open_positions": "最大持仓笔数",
    "late_edge_hard_ban_price": "禁止入场价格", "late_edge_edge_safety": "入场安全系数",
    "bucket_calibration_enabled": "启用价格桶校准", "bucket_lookback_sec": "校准回看时间（秒）",
    "bucket_min_samples": "校准最少样本数", "bucket_wr_buffer": "校准胜率余量",
    "paper_slippage_ticks": "模拟滑点（档）", "paper_slippage_pct": "模拟滑点比例",
    "stop_loss_fraction": "相对买入价止损幅度", "per_trade_risk_fraction": "单笔金额占产品本金比例",
}
FRACTIONS = set(("min_entry_price max_entry_price opening_gap_max_entry_price high_ask_threshold "
                 "min_net_edge min_net_edge_high taker_fee_rate lead_edge_margin lead_edge_margin_down "
                 "size_scale_ref_ask late_edge_hard_ban_price bucket_wr_buffer paper_slippage_pct "
                 "stop_loss_fraction per_trade_risk_fraction").split())
POSITIVE = set(("confirm_checks confirm_checks_high signal_min_venues max_open_positions bucket_min_samples "
                "order_shares max_order_usd entry_window_sec late_edge_edge_safety").split())


def read(path, required=False):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        if not required:
            return {}
        raise HTTPException(503, "产品基础配置尚未就绪")
    except (ValueError, OSError):
        raise HTTPException(503, "产品配置文件读取失败")
    if not isinstance(value, dict):
        raise HTTPException(503, "产品配置文件格式错误")
    return value


def unit_status(product):
    result = subprocess.run(["systemctl", "show", "-p", "ActiveState", "-p", "MainPID", product.unit],
                            capture_output=True, text=True, timeout=4, check=False)
    props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return props.get("ActiveState") == "active", int(props.get("MainPID") or 0)


_ERROR_CACHE: dict[str, tuple[float, int]] = {}
_HEALTH_CACHE: dict[str, tuple[float, dict]] = {}


def _heartbeat_mode(product: Product) -> str:
    if product.key == "btc5m":
        return "late_edge"
    if product.key == "btc15m":
        return "late_edge_btc15m_le"
    return f"late_edge_{product.key}"


def _worker_error_count(product: Product, now: float) -> int:
    """Read recent worker errors without running journalctl on every state frame."""
    cached = _ERROR_CACHE.get(product.unit)
    if cached and now - cached[0] < 10.0:
        return cached[1]
    count = 0
    try:
        result = subprocess.run(
            ["journalctl", "-u", product.unit, "--since", "24 hours ago",
             "--no-pager", "-o", "cat"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            count = sum(1 for line in result.stdout.splitlines()
                        if "tick failed" in line.lower())
    except (OSError, subprocess.SubprocessError):
        count = 0
    _ERROR_CACHE[product.unit] = (now, count)
    return count


def _ledger_health(product: Product, now: float) -> tuple[Optional[float], Optional[str]]:
    if not product.ledger.exists():
        return None, None
    try:
        with sqlite3.connect(f"file:{product.ledger}?mode=ro", uri=True, timeout=1.5) as conn:
            row = conn.execute(
                "SELECT ts FROM events WHERE kind='decision' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            latest_risk = conn.execute(
                "SELECT ts, payload FROM events WHERE kind='risk_block' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except (OSError, sqlite3.Error):
        return None, None
    decision_ts = float(row[0]) if row and row[0] is not None else None
    reason = None
    if latest_risk and latest_risk[0] is not None and (
        decision_ts is None or float(latest_risk[0]) >= decision_ts
    ):
        try:
            payload = json.loads(latest_risk[1] or "{}")
            candidate = str(payload.get("reason") or "").strip()
            if candidate:
                reason = candidate
        except (TypeError, ValueError):
            reason = "risk_block"
    return decision_ts, reason


def health(product):
    """Return product-level worker and market-data health for the dashboard."""
    now = time.time()
    cached = _HEALTH_CACHE.get(product.key)
    if cached and now - cached[0] < 0.75:
        return {**cached[1], "checked_at": now}
    active, pid = unit_status(product)
    decision_ts, circuit_reason = _ledger_health(product, now)
    heartbeat = {}
    heartbeat_file = product.ledger.parent / f"heartbeat_{_heartbeat_mode(product)}.json"
    try:
        heartbeat = json.loads(heartbeat_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        heartbeat = {}
    heartbeat_ts = heartbeat.get("ts")
    heartbeat_ts = float(heartbeat_ts) if isinstance(heartbeat_ts, (int, float)) else None
    decision_age = max(now - decision_ts, 0.0) if decision_ts is not None else None
    heartbeat_age = max(now - heartbeat_ts, 0.0) if heartbeat_ts is not None else None
    fresh = bool(active and decision_age is not None and decision_age <= 120.0
                 and heartbeat_age is not None and heartbeat_age <= 120.0)
    freshness = "fresh" if fresh else ("stale" if active else "unknown")
    if not active:
        circuit_reason = "worker_inactive"
    elif not fresh and not circuit_reason:
        circuit_reason = "market_data_stale" if heartbeat_age is not None else "heartbeat_missing"
    result = {
        "worker_active": active,
        "worker_state": "RUNNING" if active else "STOPPED",
        "worker_pid": pid,
        "last_decision_ts": decision_ts,
        "last_decision_age_sec": decision_age,
        "last_successful_tick_ts": heartbeat_ts,
        "market_data_age_sec": heartbeat_age,
        "tick_error_count": _worker_error_count(product, now),
        "freshness": freshness,
        "allow_entries": bool(active and fresh and not circuit_reason),
        "circuit_reason": circuit_reason,
        "heartbeat_market_slug": heartbeat.get("market_slug"),
        "heartbeat_detail": heartbeat.get("detail"),
        "checked_at": now,
        "source": "systemd + isolated ledger + paper heartbeat",
    }
    _HEALTH_CACHE[product.key] = (now, result)
    return result


def snapshot(product):
    active, pid = unit_status(product)
    raw = read(product.directory / "effective.json")
    verified = (active and pid > 0 and raw.get("pid") == pid and raw.get("product_key") == product.key
                and Path(raw.get("ledger") or "/").resolve() == product.ledger.resolve())
    allowed = LABELS.keys() | {"paper_bankroll_usd"}
    effective = {k: v for k, v in raw.get("config", {}).items() if k in allowed} if verified else {}
    return {**product.meta, "paper_enabled": active, "worker_pid": pid, "live_enabled": False,
            "configuration_verified": verified, "effective": effective, "health": health(product)}


def field_spec(p, key, default):
    if type(default) is bool:
        return {"key": key, "label": LABELS[key], "type": "boolean"}
    lo = 1 if key in POSITIVE and type(default) is int else 0
    hi = 1 if key in FRACTIONS else None
    if key in {"entry_window_sec", "min_t_remaining_sec", "opening_gap_window_sec"}:
        hi = p.window
    if key == "down_max_delta_usd":
        lo, hi = None, 0
    return {"key": key, "label": LABELS[key], "type": "number", "min": lo, "max": hi,
            "step": 1 if type(default) is int else "any"}


def config(p):
    base = read(p.directory / "base.json", required=True)
    fields = [field_spec(p, k, base[k]) for k in LABELS if k in base and type(base[k]) in (float, int, bool)]
    keys = {f["key"] for f in fields}
    lanes = {lane: {k: v for k, v in {**base, **read(p.directory / f"{lane}.json")}.items() if k in keys}
             for lane in ("paper", "live")}
    revision = hashlib.sha256(json.dumps(lanes, sort_keys=True).encode()).hexdigest()
    return {**snapshot(p), **lanes, "fields": fields, "revision": revision}


def atomic_write(path, data):
    f = tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False)
    try:
        with f:
            json.dump(data, f, sort_keys=True, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(f.name, path)
    finally:
        Path(f.name).unlink(missing_ok=True)


@contextmanager
def locked(p):
    if not p.directory.is_dir():
        raise HTTPException(503, "产品目录尚未就绪")
    with (p.directory / ".control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def operate(p, action):
    try:
        result = subprocess.run(["sudo", "-n", "systemctl", *action, p.unit], capture_output=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503, "控制 Paper 服务超时")
    if result.returncode:
        raise HTTPException(503, "无法控制对应产品的 Paper 服务")


def verify(p, expected, old_pid=0):
    for _ in range(48):
        state = snapshot(p)
        if (state["configuration_verified"] and state["worker_pid"] != old_pid
                and all(state["effective"].get(k) == v for k, v in expected.items())):
            return state
        time.sleep(0.25)
    raise HTTPException(503, "Worker 尚未确认加载配置")


def toggle(p, enabled):
    with locked(p):
        expect = config(p)["paper"]
        operate(p, ["enable" if enabled else "disable", "--now"])
        if enabled:
            verify(p, expect)
        elif unit_status(p)[0]:
            raise HTTPException(503, "Worker 未停止")
        return config(p)


def save(p, body):
    if not isinstance(body, dict) or body.get("lane") not in ("live", "paper") or not isinstance(body.get("values"), dict):
        raise HTTPException(422, "必须提供配置模式及参数")
    lane, values = body["lane"], body["values"]
    with locked(p):
        current = config(p)
        if body.get("revision") != current["revision"]:
            raise HTTPException(409, "配置已更新，请重新读取")
        fields = {f["key"]: f for f in current["fields"]}
        for key, value in values.items():
            spec = fields.get(key)
            if not spec:
                raise HTTPException(422, f"未知参数 {key}")
            if spec["type"] == "boolean":
                ok = type(value) is bool
            else:
                ok = (type(value) in (int, float) and math.isfinite(value)
                      and (spec["step"] != 1 or int(value) == value)
                      and (spec["min"] is None or value >= spec["min"])
                      and (spec["max"] is None or value <= spec["max"])
                      and (key not in POSITIVE or value > 0))
            if not ok:
                raise HTTPException(422, f"参数超出范围 {key}")
        candidate = {**current[lane], **values}
        if (not 0 < candidate["min_entry_price"] <= candidate["max_entry_price"] < 1 or
                not 0 < candidate["min_t_remaining_sec"] < candidate["entry_window_sec"]):
            raise HTTPException(422, "入场价格或时间区间无效")
        if candidate == current[lane]:
            return current
        file = p.directory / f"{lane}.json"
        original = read(file)
        normalized = {k: int(v) if fields[k].get("step") == 1 else v for k, v in values.items()}
        base = read(p.directory / "base.json", required=True)
        updated = {**original, **normalized}
        atomic_write(file, {k: v for k, v in updated.items() if v != base.get(k)})
        if lane == "paper" and current["paper_enabled"]:
            try:
                operate(p, ["restart"])
                verify(p, candidate, current["worker_pid"])
            except Exception:
                atomic_write(file, original)
                operate(p, ["restart"])
                verify(p, current["paper"])
                raise
        return config(p)
