#!/usr/bin/env python3
"""Small read-only dashboard for the isolated PolyDex P2/P3 test lane."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

P1 = Path(os.getenv("P1_STATE_DIR", "/var/lib/poly-dex-test/p1")) / "state.json"
P2P3 = Path(os.getenv("P2P3_STATE_DIR", "/var/lib/poly-dex-test/p2-p3")) / "state.json"
P1_DB = Path(os.getenv("P1_DB_PATH", "/var/lib/poly-dex-test/p1/crypto-paper.db"))
P2P3_DB = Path(os.getenv("P2P3_DB_PATH", "/var/lib/poly-dex-test/p2-p3/p2-p3.db"))
PAPER_FEED_DIR = Path(os.getenv("PAPER_FEED_DIR", "/opt/poly-dex-test/agents/out"))
PAPER_FEED_DB = Path(os.getenv("PAPER_FEED_DB_PATH", "/var/lib/poly-dex-test/paper-feeds/paper-feeds.db"))
WEATHER_FEED = PAPER_FEED_DIR / "weather_paper_state.json"
SPORTS_FEED = PAPER_FEED_DIR / "sports_paper_state.json"
PAPER_ONLY = True

# The production console consumes a single state document.  This adapter keeps
# that contract while making the test lane's paper ledger the sole source of
# truth.  No private account, wallet, or L2 credential is read here.
AGENTS = (
    ("desk", "台长调度", ("desk", "head_of_desk", "台长调度")),
    ("search", "机会猎手", ("search", "机会猎手")),
    ("whale", "聪明钱跟踪", ("whale", "聪明钱跟踪")),
    ("shill", "舆情验证", ("shill", "舆情验证")),
    ("risk", "风控合规", ("risk", "风控合规")),
    ("sniper", "订单执行", ("sniper", "订单执行")),
    ("exit", "仓位管理", ("exit", "仓位管理")),
    ("rug", "熔断兜底", ("rug", "熔断兜底")),
)

HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolyDexTest · P2/P3 Paper 控制台</title>
<style>
body{margin:0;background:#080b12;color:#e7edf7;font:14px system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1180px;margin:0 auto;padding:24px}h1{font-size:22px;margin:0 0 4px}.sub{color:#8290a8;margin-bottom:20px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#111827;border:1px solid #263349;border-radius:10px;padding:14px}.label{color:#91a0b8;font-size:12px}.value{font-size:23px;font-weight:700;margin-top:6px}.ok{color:#41d18b}.warn{color:#f8c15c}.bad{color:#ff6675}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1e293b}.row:last-child{border:0}.pill{padding:2px 7px;border-radius:99px;font-size:11px;background:#25324a}.paper{color:#72b7ff}.muted{color:#8290a8}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:7px;border-bottom:1px solid #1e293b;font-size:12px}th{color:#91a0b8;font-weight:500}@media(max-width:750px){main{padding:14px}.kpis,.grid{grid-template-columns:1fr 1fr}.grid{display:block}.card{margin-bottom:12px}}
</style></head><body><main>
<h1>PolyDexTest · P2/P3 Paper 控制台</h1><div class="sub">公共行情只读 · 所有资产 Paper / Watch-only · <span id="updated">加载中</span></div>
<div class="kpis"><div class="card"><div class="label">运行模式</div><div id="mode" class="value paper">PAPER</div></div><div class="card"><div class="label">P1 有效市场</div><div id="markets" class="value">-</div></div><div class="card"><div class="label">P2 风控资产</div><div id="risk" class="value">-</div></div><div class="card"><div class="label">P3 Paper 观察市场</div><div id="p3" class="value">-</div></div></div>
<div class="grid"><section class="card"><h3>P2 风控快照</h3><div id="riskRows" class="muted">加载中…</div></section><section class="card"><h3>P3 资产适配</h3><div id="p3Rows" class="muted">加载中…</div></section></div>
<section class="card" style="margin-top:14px"><h3>Paper 运行边界</h3><div class="row"><span>钱包私钥 / L2 凭证</span><b class="ok">未加载</b></div><div class="row"><span>真实下单路径</span><b class="ok">禁用</b></div><div class="row"><span>结算源</span><span class="muted">仅记录公开来源，逐资产审核</span></div></section>
</main><script>
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){try{const [a,b]=await Promise.all([fetch('/api/p1').then(r=>r.json()),fetch('/api/p2-p3').then(r=>r.json())]);const assets=a.assets||{};const valid=Object.values(assets).reduce((n,x)=>n+(x.markets||0),0);const risk=b.p2?.assets||{};const p3=b.p3||{};const p3n=Object.values(p3).reduce((n,x)=>n+(x.markets||0),0);document.querySelector('#markets').textContent=valid;document.querySelector('#risk').textContent=Object.keys(risk).length;document.querySelector('#p3').textContent=p3n;document.querySelector('#updated').textContent='更新 '+new Date().toLocaleTimeString();document.querySelector('#riskRows').innerHTML=Object.entries(risk).map(([k,v])=>`<div class="row"><span>${esc(k)} <small class="muted">波动 ${Number(v.volatility||0).toFixed(4)} · 点差 ${Number(v.spread||0).toFixed(3)}</small></span><b class="${v.status==='ALLOW'?'ok':v.status==='BLOCK'?'bad':'warn'}">${esc(v.status)}</b></div>`).join('')||'<span class="muted">等待 P1 数据</span>';document.querySelector('#p3Rows').innerHTML=Object.entries(p3).filter(([,v])=>v.markets).map(([k,v])=>`<div class="row"><span>${esc(k)} <small class="muted">${esc(v.category)}</small></span><b class="paper">${v.markets} · PAPER</b></div>`).join('')||'<span class="muted">暂无匹配的资产市场</span>';}catch(e){document.querySelector('#updated').textContent='数据暂不可用'}}refresh();setInterval(refresh,15000);
</script></body></html>"""


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "stale", "error": "snapshot unavailable"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rows(db_path: Path, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Read a bounded set of rows without creating or mutating a database."""
    if not db_path.exists():
        return []
    db: sqlite3.Connection | None = None
    try:
        # Explicitly close every read connection.  The previous context
        # manager only committed/rolled back and could leave a WAL reader
        # alive while the Paper worker rotated its snapshot, causing the
        # dashboard to alternate between populated and empty responses.
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=8)
        db.execute("PRAGMA busy_timeout=8000")
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query, args).fetchall()]
    except (OSError, sqlite3.Error) as exc:
        # systemd's read-only mount blocks SQLite's WAL shared-memory lock.
        # If the writer has checkpointed the WAL, immutable mode gives the
        # dashboard a safe snapshot without granting it write access.
        if db is not None:
            db.close()
            db = None
        try:
            db = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=8)
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, args).fetchall()]
        except (OSError, sqlite3.Error):
            pass
        # Keep the public response safe while leaving an actionable reason in
        # the service journal instead of silently turning a live Paper ledger
        # into an empty dashboard.
        print(f"dashboard read failed for {db_path.name}: {exc}", flush=True)
        return []
    finally:
        if db is not None:
            db.close()


def _p1_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    decisions = _rows(P1_DB, """
        SELECT id,ts,asset,slug,condition_id,side,token_id,action,reason,
               t_remaining,ask,ask_size,dry_run
        FROM decisions ORDER BY id DESC LIMIT 250
    """)
    orders = _rows(P1_DB, """
        SELECT id,ts,asset,slug,condition_id,side,token_id,size,price,status,
               settled_ts,pnl,dry_run,settlement_source,settlement_verified
        FROM paper_orders ORDER BY id DESC LIMIT 5000
    """)
    quotes = _rows(P1_DB, """
        SELECT asset,condition_id,token_id,ts,ask,ask_size,bid,bid_size
        FROM quotes ORDER BY id DESC LIMIT 2000
    """)
    return decisions, orders, quotes


def _paper_feed_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the independent WEATHER/SPORTS Paper ledger."""
    decisions = _rows(PAPER_FEED_DB, """
        SELECT id,ts,asset,market_slug,condition_id,side,token_id,
               t_remaining,ask_price AS ask,ask_size,action,reason,dry_run
        FROM decisions ORDER BY id DESC LIMIT 500
    """)
    orders = _rows(PAPER_FEED_DB, """
        SELECT id,ts,asset,market_slug,condition_id,side,token_id,
               size,price,status,filled_size,dry_run
        FROM orders ORDER BY id DESC LIMIT 1000
    """)
    for row in decisions:
        row["id"] = f"{str(row.get('asset') or 'feed').lower()}-{row.get('id')}"
        row["dry_run"] = 1
    for row in orders:
        row["id"] = f"{str(row.get('asset') or 'feed').lower()}-{row.get('id')}"
        row["dry_run"] = 1
    return decisions, orders


def _feed_snapshot(path: Path) -> dict[str, Any]:
    snapshot = read(path)
    if not snapshot:
        return {"status": "stopped", "running": False, "mode": "paper",
                "paper_only": True, "rows": [], "error": "snapshot unavailable"}
    return snapshot


def _feed_service_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(snapshot.get("enabled", True)),
        "running": bool(snapshot.get("running")),
        "status": snapshot.get("status", "stopped"),
        "mode": "paper", "live_enabled": False, "paper_only": True,
        "heartbeat_ts": snapshot.get("heartbeat_ts"),
        "markets": int(snapshot.get("market_count", snapshot.get("markets_count", 0)) or 0),
        "orders_new": int(snapshot.get("orders_new", 0) or 0),
        "error": snapshot.get("error"),
    }


def _p1_probe() -> dict[str, Any]:
    """Small non-secret diagnostic marker for the Paper dashboard itself."""
    result: dict[str, Any] = {"exists": P1_DB.exists(), "readable": os.access(P1_DB, os.R_OK)}
    try:
        result["size"] = P1_DB.stat().st_size
        db = sqlite3.connect(f"file:{P1_DB}?mode=ro&immutable=1", uri=True, timeout=8)
        result["paper_orders"] = int(db.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0])
        result["decisions"] = int(db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
        result["quotes"] = int(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0])
        db.close()
    except (OSError, sqlite3.Error) as exc:
        result["error"] = str(exc)
    return result


def _market_slug(row: dict[str, Any]) -> str:
    return str(row.get("slug") or row.get("market_slug") or "")


def _decision_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"), "ts": _number(row.get("ts")),
        "asset": row.get("asset"), "market_slug": _market_slug(row),
        "condition_id": row.get("condition_id"), "side": row.get("side"),
        "token_id": row.get("token_id"), "action": row.get("action") or "SKIP",
        "reason": row.get("reason") or "", "t_remaining": row.get("t_remaining"),
        "ask_price": row.get("ask"), "ask_size": row.get("ask_size"),
        "dry_run": 1,
    }


def _order_view(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "OPEN").lower()
    result = {"won": "WON", "lost": "LOST"}.get(status, "PENDING")
    if status == "open":
        result = "PENDING"
    size = _number(row.get("size"))
    # Preserve the ledger's lane marker.  P1 defaults this column to 1 and
    # the isolated service never writes 0, but retaining it prevents a
    # fabricated Paper result if an old/imported row is encountered.
    dry_run = 1 if row.get("dry_run") is None else int(bool(row.get("dry_run")))
    return {
        "id": row.get("id"), "ts": _number(row.get("ts")),
        "asset": row.get("asset"), "market_slug": _market_slug(row),
        "condition_id": row.get("condition_id"), "side": row.get("side"),
        "token_id": row.get("token_id"), "size": size,
        "filled_size": size if status in {"won", "lost", "filled", "matched"} else 0.0,
        "price": _number(row.get("price")), "status": status,
        "result": result, "settled_ts": row.get("settled_ts"),
        "pnl": row.get("pnl"), "dry_run": dry_run,
        "mode": "paper" if dry_run else "live",
        "settlement_source": row.get("settlement_source"),
        "settlement_verified": bool(row.get("settlement_verified")),
    }


def _latest_quotes(quotes: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    latest: dict[str, dict[str, float]] = {}
    for row in quotes:
        asset = str(row.get("asset") or "").upper()
        if not asset or asset in latest:
            continue
        bid, ask = row.get("bid"), row.get("ask")
        if bid is None and ask is None:
            continue
        bid_n, ask_n = _number(bid), _number(ask)
        latest[asset] = {
            "bid": bid_n, "ask": ask_n,
            "mid": (bid_n + ask_n) / 2 if bid is not None and ask is not None else _number(ask if ask is not None else bid),
        }
    return latest


def _price_history(quotes: list[dict[str, Any]], asset: str, limit: int = 180) -> list[dict[str, float]]:
    """Return a small midpoint series for the console's Paper charts."""
    rows = [row for row in quotes if str(row.get("asset") or "").upper() == asset.upper()]
    rows.sort(key=lambda row: _number(row.get("ts")))
    points: list[dict[str, float]] = []
    for row in rows[-limit:]:
        bid, ask = row.get("bid"), row.get("ask")
        if bid is None and ask is None:
            continue
        points.append({"ts": _number(row.get("ts")), "price": (_number(bid) + _number(ask)) / 2 if bid is not None and ask is not None else _number(ask if ask is not None else bid)})
    return points


def _pnl(orders: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [r for r in orders if str(r.get("status") or "").upper() in {"WON", "LOST"}]
    wins = sum(str(r.get("status") or "").upper() == "WON" for r in settled)
    losses = sum(str(r.get("status") or "").upper() == "LOST" for r in settled)
    realized = sum(_number(r.get("pnl")) for r in settled)
    pending = sum(str(r.get("status") or "").upper() == "OPEN" for r in orders)
    # This is a Paper ledger metric.  The period is UTC midnight; the UI can
    # label it explicitly and must not mistake it for a production wallet PnL.
    now = datetime.now(timezone.utc)
    period = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    daily = sum(_number(r.get("pnl")) for r in settled if _number(r.get("settled_ts") or r.get("ts")) >= period)
    return {
        "realized_usd": realized, "daily_realized_usd": daily,
        "wins": wins, "losses": losses, "pending": pending,
        "period_start_ts": period, "mode": "paper",
    }


def _mode_metrics(orders: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """Aggregate one execution lane from the persisted order rows.

    The test lane is Paper-only, so the live branch should normally be empty.
    We still calculate it from rows marked ``dry_run=0`` so that a diagnostic
    response reflects the database truth instead of inventing zero/filled
    positions.  No field in this helper implies that live execution is
    enabled.
    """
    is_paper = mode == "paper"
    selected = []
    for row in orders:
        # Missing legacy markers are conservatively Paper rows.  Only an
        # explicit zero can enter the live diagnostic lane.
        row_is_paper = row.get("dry_run") is None or int(bool(row.get("dry_run"))) == 1
        if row_is_paper == is_paper:
            selected.append(row)
    settled = [row for row in selected if str(row.get("status") or "").upper() in {"WON", "LOST"}]
    open_rows = [row for row in selected if str(row.get("status") or "").upper() not in {"WON", "LOST"}]
    wins = sum(str(row.get("status") or "").upper() == "WON" for row in settled)
    losses = sum(str(row.get("status") or "").upper() == "LOST" for row in settled)
    cumulative = sum(_number(row.get("pnl")) for row in settled)
    now = datetime.now(timezone.utc)
    period = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    daily = sum(_number(row.get("pnl")) for row in settled
                if _number(row.get("settled_ts") or row.get("ts")) >= period)
    open_value = sum(_number(row.get("size")) * _number(row.get("price")) for row in open_rows)
    # Keep the same accounting shape for the product cards.  A row is counted
    # as pending until it has a verified WON/LOST result; its entry notional is
    # never presented as realized PnL.
    by_asset: dict[str, dict[str, Any]] = {}
    for row in selected:
        asset = str(row.get("asset") or "UNKNOWN").upper()
        item = by_asset.setdefault(asset, {
            "orders": 0, "settled": 0, "pending": 0, "open_orders": 0,
            "open_value_usd": 0.0, "realized_usd": 0.0, "wins": 0, "losses": 0,
        })
        item["orders"] += 1
        status = str(row.get("status") or "").upper()
        if status in {"WON", "LOST"}:
            item["settled"] += 1
            item["realized_usd"] += _number(row.get("pnl"))
            item["wins"] += status == "WON"
            item["losses"] += status == "LOST"
        else:
            item["pending"] += 1
            item["open_orders"] += 1
            item["open_value_usd"] += _number(row.get("size")) * _number(row.get("price"))
    for item in by_asset.values():
        # The adapter currently reads the full bounded ledger window.  Keep a
        # separate lifetime-shaped field so the UI can use one stable schema;
        # it remains derived solely from persisted orders.
        item["cumulative_realized_usd"] = item["realized_usd"]
        item["cumulative_pnl_usd"] = item["realized_usd"]
    # A test lane may provide a paper budget explicitly.  The default is a
    # clearly labeled synthetic test baseline, never a wallet balance.
    # Do not invent an account balance.  Operators may set an explicit Paper
    # test budget through PAPER_CAPITAL_BASE_USD; otherwise the UI correctly
    # labels return as “未设置” while still showing orders and exposure.
    capital_base = _number(os.getenv("PAPER_CAPITAL_BASE_USD"), 0.0)
    return {
        "mode": mode,
        "enabled": is_paper,
        "live_enabled": False,
        "paper_only": True,
        "orders": len(selected),
        "settled": len(settled),
        "pending": len(open_rows),
        "open_orders": len(open_rows),
        "open_value_usd": open_value,
        "open_order_notional_usd": open_value,
        "wins": wins,
        "losses": losses,
        "cumulative": cumulative,
        "cumulative_pnl_usd": cumulative,
        "realized_usd": cumulative,
        "daily_pnl_usd": daily,
        "daily_realized_usd": daily,
        "capital_base_usd": capital_base if is_paper else 0.0,
        "capital_base_source": "PAPER_CAPITAL_BASE_USD (Paper 测试基数)" if is_paper else "live disabled",
        "by_asset": by_asset,
        "cumulative_by_asset": by_asset,
        "period_start_ts": period,
        "source": "p1 paper_orders ledger",
        "reason": "Paper-only lane" if is_paper else "Live lane disabled; no live order writes permitted",
    }


def _asset_registry(p1: dict, p2: dict, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for asset, item in (p1.get("assets") or {}).items():
        result[str(asset).upper()] = {
            "asset": str(asset).upper(), "category": "crypto", "mode": "paper",
            "paper_only": True, "markets": int(item.get("markets") or 0),
            "orders": int(item.get("orders_new") or 0), "status": "PAPER",
        }
    for asset, item in (p2.get("p3") or {}).items():
        key = str(asset).upper()
        entry = result.setdefault(key, {"asset": key, "mode": "paper", "paper_only": True, "orders": 0})
        # P3 is a registry/watch layer.  It must not erase an active P1 Paper
        # market or its order count when the same symbol has no P3 match.
        entry.update({"category": item.get("category") or entry.get("category") or "watch",
                      "markets": max(int(entry.get("markets") or 0), int(item.get("markets") or 0)),
                      "status": "PAPER_WATCH" if item.get("paper_only", True) else "PAPER"})
    for row in orders:
        key = str(row.get("asset") or "").upper()
        if key:
            result.setdefault(key, {"asset": key, "category": "unknown", "mode": "paper", "paper_only": True, "markets": 0, "orders": 0})["orders"] += 1
    return sorted(result.values(), key=lambda x: x["asset"])


def _agent_status(p1: dict, p2: dict, decisions: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    heartbeat = max(_number(p1.get("heartbeat_ts")), _number(p2.get("heartbeat_ts")))
    age = time.time() - heartbeat if heartbeat else float("inf")
    running = bool(heartbeat and age < 600)
    queue = len([d for d in decisions if time.time() - _number(d.get("ts")) < 300])
    status = "running" if running else "offline"
    out: dict[str, dict[str, Any]] = {}
    for role, label, _keys in AGENTS:
        # No fabricated heartbeats: all cards share the actual Paper worker
        # heartbeat, while permissions remain role-specific and read-only.
        out[role] = {
            "status": status, "mode": "paper", "live_enabled": False,
            "heartbeat_ts": heartbeat or None, "queue_depth": queue if role in {"desk", "search", "risk"} else 0,
            "market": "多品类 Paper" if running else "未启用",
            "detail": f"{label}：测试实例 Paper-only；无私钥、无真实下单权限",
        }
    return out


def build_state() -> dict[str, Any]:
    p1 = read(P1)
    p2 = read(P2P3)
    weather_feed = _feed_snapshot(WEATHER_FEED)
    sports_feed = _feed_snapshot(SPORTS_FEED)
    decisions_raw, orders_raw, quotes = _p1_rows()
    feed_decisions, feed_orders = _paper_feed_rows()
    all_decisions_raw = decisions_raw + feed_decisions
    all_orders_raw = orders_raw + feed_orders
    decisions = [_decision_view(row) for row in all_decisions_raw]
    orders = [_order_view(row) for row in all_orders_raw]
    mode_split = {
        "paper": _mode_metrics(all_orders_raw, "paper"),
        "live": _mode_metrics(all_orders_raw, "live"),
    }
    # The production-style state remains a Paper view.  Any hypothetical
    # dry_run=0 row is kept in the diagnostic mode_split.live aggregate but is
    # never exposed as a test position or allowed to drive a Paper KPI.
    paper_orders = [row for row in orders if row.get("mode") == "paper"]
    open_orders = [row for row in paper_orders if row["status"] == "open"]
    positions = [{
        "id": row["id"], "title": row["market_slug"], "outcome": row.get("side"),
        "size": row["size"], "curPrice": row["price"],
        "currentValue": row["size"] * row["price"], "asset": row.get("asset"),
        "mode": "paper", "dry_run": 1,
    } for row in open_orders]
    pnl = _pnl([row for row in all_orders_raw if row.get("dry_run") is None or int(bool(row.get("dry_run"))) == 1])
    latest = _latest_quotes(quotes)
    btc_history = _price_history(quotes, "BTC")
    eth_history = _price_history(quotes, "ETH")
    risk_assets = (p2.get("p2") or {}).get("assets") or {}
    risk_state = "BLOCKED" if any(v.get("status") == "BLOCK" for v in risk_assets.values()) else ("OK" if risk_assets else "UNKNOWN")
    all_assets = _asset_registry(p1, p2, orders)
    # Keep the two non-crypto products visible even when the current market
    # scan has no tradeable row or the strategy produced no Paper order.  The
    # worker heartbeat is the source of status; a zero market count is a
    # truthful "waiting for market" state rather than a missing product.
    for product, snapshot, category in (("WEATHER", weather_feed, "weather"), ("SPORTS", sports_feed, "sports")):
        rows = snapshot.get("rows") or snapshot.get("markets") or []
        existing = next((item for item in all_assets if item.get("asset") == product), None)
        if existing is None:
            existing = {"asset": product, "category": category, "mode": "paper",
                        "paper_only": True, "markets": 0, "orders": 0}
            all_assets.append(existing)
        existing.update({"category": category, "mode": "paper", "paper_only": True,
                         "markets": int(snapshot.get("market_count", len(snapshot.get("markets") or [])) or 0),
                         "status": "PAPER" if snapshot.get("status") != "error" else "PAPER_ERROR",
                         "worker_status": snapshot.get("status", "stopped"),
                         "heartbeat_ts": snapshot.get("heartbeat_ts")})
    all_assets.sort(key=lambda item: str(item.get("asset") or ""))
    heartbeat = max(_number(p1.get("heartbeat_ts")), _number(p2.get("heartbeat_ts")))
    return {
        "mode": "paper", "bot_mode": "paper", "paper_only": True, "live_enabled": False,
        "live_disabled_reason": "PolyDexTest 测试实例固定 Paper-only",
        "heartbeat_ts": heartbeat or None, "updated_ts": time.time(),
        "bot_running": bool(heartbeat and time.time() - heartbeat < 600),
        "wallet": {"balance_pusd": 0.0, "paper_balance_usd": 0.0, "source": "paper ledger"},
        "pnl": pnl, "orders": orders, "decisions": decisions, "positions": positions,
        "mode_split": mode_split,
        "settled_positions": [], "pending": pnl["pending"],
        "risk_snapshot": {
            "state": risk_state, "position_count": len(positions),
            "position_value_usd": sum(x["currentValue"] for x in positions),
            "open_orders": len(open_orders), "open_order_notional_usd": sum(x.get("size", 0.0) * x.get("curPrice", x.get("price", 0.0)) for x in open_orders),
            "exposure_ratio": None, "daily_realized_usd": pnl["daily_realized_usd"],
            "max_daily_loss_fraction": None, "max_open_positions": 2,
            "mode": "paper", "assets": risk_assets,
        },
        "risk_state": risk_state, "service_modes": {
            "BTC": {"enabled": True, "running": bool(p1.get("heartbeat_ts")), "live_enabled": False, "mode": "paper", "paper_only": True},
            "ETH": {"enabled": True, "running": bool(p1.get("heartbeat_ts")), "live_enabled": False, "mode": "paper", "paper_only": True},
            "WEATHER": _feed_service_state(weather_feed),
            "SPORTS": _feed_service_state(sports_feed),
        },
        "agent_status": _agent_status(p1, p2, decisions, orders),
        "assets": all_assets, "asset_registry": all_assets,
        "p3": p2.get("p3") or {}, "p2": p2.get("p2") or {},
        "btc_signal": {"current_price": latest.get("BTC", {}).get("mid"), "delta_usd": None, "mode": "paper"},
        "eth_signal": {"current_price": latest.get("ETH", {}).get("mid"), "delta_usd": None, "mode": "paper"},
        "btc_price_history": btc_history, "eth_price_history": eth_history,
        "book_up": {}, "book_down": {}, "eth_book_up": {}, "eth_book_down": {}, "eth_market": {},
        "weather": weather_feed.get("rows") or [], "sports": sports_feed.get("rows") or [],
        "paper_feeds": {"WEATHER": weather_feed, "SPORTS": sports_feed},
        "errors": list(p1.get("errors") or []) + list(p2.get("errors") or []) + [
            str(err) for err in (weather_feed.get("error"), sports_feed.get("error")) if err
        ],
        "config": {"min_entry_price": 0.0, "max_entry_price": 0.55, "max_orders_per_hour": 0,
                   "max_open_positions": 2, "one_side_per_market": True, "order_fixed_notional_usd": 2.0},
        "llm": {"usage": llm_usage(), "settings": {"enabled": False, "advisor_enabled": False}},
        "data_sources": {"p1_state": str(P1), "p2_p3_state": str(P2P3), "paper_db": str(P1_DB),
                          "paper_feed_db": str(PAPER_FEED_DB), "weather_snapshot": str(WEATHER_FEED),
                          "sports_snapshot": str(SPORTS_FEED), "paper_db_probe": _p1_probe()},
    }


def llm_usage() -> dict[str, Any]:
    return {"enabled": False, "mode": "paper", "ts": time.time(), "models": [
        {"slot": "primary", "name": "GPT-6-Astra", "model": "GPT-6-Astra", "total_tokens": 0, "last_tokens": 0, "calls": 0, "configured": False},
        {"slot": "secondary", "name": "Grok", "model": "Grok", "total_tokens": 0, "last_tokens": 0, "calls": 0, "configured": False},
    ]}


def _query_values(raw_path: str) -> dict[str, str]:
    parsed = parse_qs(urlparse(raw_path).query, keep_blank_values=True)
    return {key: (values[-1] if values else "") for key, values in parsed.items()}


def _page(rows: list[dict[str, Any]], query: dict[str, str]) -> tuple[list[dict[str, Any]], int, int, int]:
    try:
        offset = max(0, int(query.get("offset", "0")))
    except ValueError:
        offset = 0
    try:
        limit = min(200, max(1, int(query.get("limit", "20"))))
    except ValueError:
        limit = 20
    return rows[offset:offset + limit], len(rows), offset, limit


def _orders_page(query: dict[str, str]) -> dict[str, Any]:
    state = build_state()
    lane = query.get("lane", "all").lower()
    asset = query.get("asset", "").upper()
    rows = list(state["orders"])
    if lane == "paper":
        rows = [row for row in rows if row.get("dry_run", 1) != 0]
    elif lane == "live":
        rows = [row for row in rows if row.get("dry_run", 1) == 0]
    if asset:
        rows = [row for row in rows if str(row.get("asset") or "").upper() == asset]
    rows, total, offset, limit = _page(rows, query)
    return {"mode": "paper", "live_enabled": False, "rows": rows,
            "orders": rows, "total": total, "offset": offset, "limit": limit,
            "lane": lane, "asset": asset or None}


def _daily_page(query: dict[str, str]) -> dict[str, Any]:
    state = build_state()
    lane = query.get("lane", "paper").lower()
    asset = query.get("asset", "").upper()
    # The test ledger is Paper-only.  A live query is valid but intentionally
    # returns an empty lane rather than mixing Paper results into it.
    rows = state["orders"] if lane != "live" else []
    if asset:
        rows = [row for row in rows if str(row.get("asset") or "").upper() == asset]
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        result = str(row.get("result") or "").upper()
        if result not in {"WON", "LOST"}:
            continue
        ts = _number(row.get("settled_ts") or row.get("ts"))
        # The display day follows the test's Beijing accounting convention.
        local_day = (datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=8)).date().isoformat()
        bucket = buckets.setdefault(local_day, {"day": local_day, "pnl_usd": 0.0, "wins": 0, "losses": 0})
        bucket["pnl_usd"] += _number(row.get("pnl"))
        bucket["wins" if result == "WON" else "losses"] += 1
    ordered = [buckets[key] for key in sorted(buckets, reverse=True)]
    page, total, offset, limit = _page(ordered, query)
    return {"mode": "paper", "live_enabled": False, "lane": lane, "asset": asset or None,
            "rows": page, "total_days": total, "offset": offset, "limit": limit,
            "capital_base_usd": 0.0, "trading_timezone": "Asia/Shanghai"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def paper_only(self) -> None:
        self.send_json({
            "error": "paper_only",
            "detail": "PolyDexTest is a read-only Paper-only environment; live trading and configuration writes are disabled.",
            "mode": "paper", "live_enabled": False,
        }, 403)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = HTML.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/health":
            self.send_json({"status": "ok", "mode": "paper", "ts": time.time()}); return
        if path == "/api/p1":
            self.send_json(read(P1)); return
        if path == "/api/p2-p3":
            self.send_json(read(P2P3)); return
        if path == "/api/state":
            self.send_json(build_state()); return
        if path == "/api/orders":
            self.send_json(_orders_page(_query_values(self.path))); return
        if path == "/api/decisions":
            self.send_json({"mode": "paper", "decisions": build_state()["decisions"]}); return
        if path == "/api/pnl/daily":
            self.send_json(_daily_page(_query_values(self.path))); return
        if path == "/api/assets":
            state = build_state()
            self.send_json({"mode": "paper", "live_enabled": False, "assets": state["assets"], "asset_registry": state["asset_registry"], "p3": state["p3"]}); return
        if path == "/api/llm/usage":
            self.send_json(llm_usage()); return
        if path == "/api/settings":
            self.send_json({"enabled": False, "advisor_enabled": False, "paper_only": True,
                            "primary": {"enabled": False, "provider": "", "base_url": "", "model": "GPT-6-Astra", "api_key_configured": False},
                            "secondary": {"enabled": False, "provider": "", "base_url": "", "model": "Grok", "api_key_configured": False}}); return
        if path == "/api/settings/llm":
            self.send_json({"enabled": False, "advisor_enabled": False, "paper_only": True,
                            "primary": {"enabled": False, "provider": "", "base_url": "", "model": "GPT-6-Astra", "api_key_configured": False, "timeout_sec": 30, "max_tokens": 512, "temperature": 0.2, "system_prompt": ""},
                            "secondary": {"enabled": False, "provider": "", "base_url": "", "model": "Grok", "api_key_configured": False, "timeout_sec": 30, "max_tokens": 512, "temperature": 0.2, "system_prompt": ""}}); return
        self.send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        # This includes /api/live/{asset}, order actions, model settings,
        # operator-token writes, and every future mutating API by default.
        self.paper_only()

    def do_PUT(self) -> None:  # noqa: N802
        self.paper_only()

    def do_PATCH(self) -> None:  # noqa: N802
        self.paper_only()

    def do_DELETE(self) -> None:  # noqa: N802
        self.paper_only()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Operator-Token")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/health", "/api/p1", "/api/p2-p3", "/api/state", "/api/orders", "/api/decisions", "/api/pnl/daily", "/api/assets", "/api/llm/usage", "/api/settings", "/api/settings/llm"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if path in ("/", "/index.html") else "application/json; charset=utf-8")
            self.end_headers()
            return
        self.send_response(404); self.end_headers()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--host", default=os.getenv("P2P3_DASHBOARD_HOST", "127.0.0.1")); parser.add_argument("--port", type=int, default=int(os.getenv("P2P3_DASHBOARD_PORT", "8787"))); args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
