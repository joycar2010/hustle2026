"""FastAPI dashboard backend.

Polls the local SQLite (trades.db), the CLOB book of the live market, the
deposit wallet's positions, and on-chain pUSD balance. Serves /api/state for
the UI to poll, and /api/events for incremental new-row pulls.

Run:  .venv/bin/uvicorn server.dashboard:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hmac
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timezone, timedelta
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import dotenv_values, load_dotenv

from server.paper_product_accounting import read_product, merge_products, public_capital
from server import product_control as pc, product_records as pr
from server.portfolio_positions import fetch_portfolio_positions, summarize_positions
from server.chain_statistics import (confirmed_activity, cashflow as chain_cashflow, live_statistics,
    number as chain_number, read_account_pages, coherent_points, summarize_activity_period)
from bot.live_risk import read_live_risk_snapshot, state_file as live_risk_state_file

from bot.book import fetch_book
from bot.btc_signal import BtcSignal, fetch_btc_signal, fetch_eth_signal
from bot.config import load as load_cfg
from bot.markets import LiveMarket, fetch_live_market
from bot.resolver import resolve_pending
from bot.risk import daily_profit_target_usd
from bot.paper_profit import active_paper_profit_stop
from bot.store import (
    realized_pnl_summary_today, realized_pnl_by_day, realized_pnl_by_asset_today,
    accounting_snapshot, consecutive_losses, local_day_start_ts, remaining_positions,
    TRADING_TIMEZONE,
)
from bot.store import _fifo_ledger
from bot.sports_main import SportsPaperService
from bot.weather_data import CITY_CONFIG, configured_city_keys, fetch_ensemble_forecast
from bot.weather_markets import fetch_weather_markets
from bot.weather_strategy import build_signal
from bot.paper_feeds import read_snapshot as read_paper_feed_snapshot

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("TRADES_DB_PATH", str(ROOT / "trades.db"))).expanduser()
# Explicit native-live certification. Legacy BTC_LIVE_ENABLED alone is never enough.
LIVE_CAPABILITY_FILE = Path(os.getenv("POLYTEST_NATIVE_LIVE_CAPABILITY_FILE", "/home/ec2-user/polymarketbot-test/state/live-capability.json")).expanduser()
LIVE_CAPABILITY_KEYS = ("shared_strategy", "real_fill_reconcile", "sell_exit", "redeem", "risk_gate")
# Native BTC5m Paper ledger is authoritative for the current polytest Paper
# worker.  Keep the legacy DB as a fallback for older deployments.
NATIVE_PAPER_DB = Path(os.getenv(
    "NATIVE_PAPER_DB",
    "/home/ec2-user/polymarketbot-test/state/paper-native-a/data/paper.db",
)).expanduser()
_NATIVE_PAPER_CACHE: dict[str, Any] = {"ts": 0.0, "account": None}
# SOL5M isolated Paper ledger.
SOL5M_PAPER_DB = Path(os.getenv(
    "SOL5M_PAPER_DB",
    "/home/ec2-user/polymarketbot-test/releases/polytest-sol5m-20261121T140426Z/data/paper_sol5m.db",
)).expanduser()

cfg = load_cfg()
PRODUCT_PAPER_CONFIG_PATH = Path(os.getenv("PRODUCT_PAPER_CONFIG_PATH",
    "/home/ec2-user/polymarketbot-test/state/product-paper-capital.json"))
_PRODUCT_PAPER_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}


def _product_paper_snapshot() -> dict[str, Any]:
    """Read both isolated Paper allocations, without changing worker risk."""
    now = time.time()
    previous = _PRODUCT_PAPER_CACHE.get("value")
    if previous is not None and now - float(_PRODUCT_PAPER_CACHE.get("ts") or 0.0) < 0.75:
        return previous
    products = {}
    for registered in pc.PRODUCTS.values():
        asset, path = registered.asset, registered.ledger
        capital, capital_source = public_capital(PRODUCT_PAPER_CONFIG_PATH, asset, path)
        identity = pc.read(registered.directory / "identity.json")
        if (identity.get("series_slug") == registered.series
                and isinstance(identity.get("paper_bankroll_usd"), (int, float))):
            capital, capital_source = identity["paper_bankroll_usd"], "product_paper_allocation"
        product = read_product(path, asset, capital, now)
        product.update(registered.meta)
        for row in (*product["positions"], *product["settled_positions"], *product["daily_rows"],
                    product["today_summary"], product["cumulative_summary"]):
            row.update(registered.meta)
        product["capital_source"] = capital_source
        cached = (previous or {}).get(asset)
        if not product["available"] and cached and cached.get("available"):
            product = {**cached, "stale": True, "error": product["error"], "read_failed_at": now}
        products[asset] = product
    products["ALL"] = merge_products(products, now)
    _PRODUCT_PAPER_CACHE.update(ts=now, value=products)
    return products


def _product_paper_daily_page(asset: str, offset: int, limit: int) -> dict[str, Any]:
    products = _product_paper_snapshot()
    product = products[asset]
    rows = product["daily_rows"]
    total = product["cumulative_summary"]
    today = product["today_summary"]
    return {"lane": "paper", "asset": asset, "source": product["source"],
        "rows": rows[offset:offset + limit], "total_days": len(rows), "offset": offset, "limit": limit,
        "trading_timezone": "Asia/Shanghai", "capital_base_usd": product["capital_base_usd"],
        "capital_by_asset": products["ALL"]["capital_by_asset"] if asset == "ALL" else {asset: product["capital_base_usd"]},
        "capital_basis": "sum_of_independent_configured_paper_allocations" if asset == "ALL" else "configured_paper_allocation",
        "capital_complete": product["capital_complete"], "daily_basis": "beijing_settlement_date",
        "valuation": "entry_cost", "slippage_included_in_execution_price": True,
        "available": product["available"], "stale": product["stale"], "error": product["error"],
        "updated_at": product["updated_at"], "today_summary": today,
        "today_economic_pnl_usd": today["net_pnl_usd"], "today_trade_pnl_usd": today["gross_pnl_usd"],
        "today_fees_usd": today["fees_usd"], "today_rebates_usd": today["rebates_usd"],
        "cumulative_summary": total,
        "by_asset": products["ALL"]["by_asset"] if asset == "ALL" else {asset: today},
        "cumulative_by_asset": products["ALL"]["cumulative_by_asset"] if asset == "ALL" else {asset: total},
        "fee_breakdown": {"total_usd": total["fees_usd"], "taker_fee_usd": total["taker_fee_usd"],
            "maker_fee_usd": total["maker_fee_usd"], "rebate_usd": total["rebate_usd"], "rebates_usd": total["rebates_usd"]},
        "data_provenance": "isolated product Paper ledgers, net includes fees once and slippage in execution prices"}


def _combined_paper_account(products: dict[str, Any]) -> dict[str, Any]:
    product = products["ALL"]
    return {**product, "pnl": {**product["today_summary"], "source": product["source"]}}


def _apply_combined_paper_lane(mode_split: dict, products: dict[str, Any]) -> None:
    """Display-only portfolio lane; the worker and risk snapshot stay BTC-owned."""
    product = products["ALL"]
    total, today = product["cumulative_summary"], product["today_summary"]
    old = dict(mode_split.get("paper") or {})
    mode_split["paper_btc"] = old
    mode_split["paper"] = {**old, **today,
        "capital_base_usd": product["capital_base_usd"], "capital_by_asset": product["capital_by_asset"],
        "capital_basis": product["capital_basis"], "capital_complete": product["capital_complete"],
        "cumulative_realized_usd": total["net_pnl_usd"], "cumulative_net_pnl_usd": total["net_pnl_usd"],
        "cumulative_wins": total["wins"], "cumulative_losses": total["losses"],
        "cumulative_by_asset": product["cumulative_by_asset"], "by_asset": product["by_asset"],
        "open_value_usd": product["open_value_usd"], "cash_usd": product["cash_usd"], "equity_usd": product["equity_usd"],
        "fees_usd": total["fees_usd"], "today_fees_usd": today["fees_usd"],
        "daily_economic_pnl_usd": today["net_pnl_usd"], "source": product["source"],
        "available": product["available"], "stale": product["stale"], "error": product["error"],
        "group": "BTC5M+BTC15M+SOL5M", "valuation": "entry_cost", "equity_valuation": "entry_cost",
        "slippage_included_in_execution_price": True}

from server import paper_comparison_view as _p3
_PAPER_COMPARISON_ENABLED = os.getenv("PAPER_COMPARISON_ENABLED", "false").lower() == "true"

def _paper_primary_group() -> str:
    return _p3.primary_group()




_NATIVE_RUNTIME_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}


def _native_paper_worker_runtime() -> dict[str, Any]:
    """Verify the native unit and expose only non-secret process settings."""
    now = time.monotonic()
    if _NATIVE_RUNTIME_CACHE.get("value") is not None and now - float(_NATIVE_RUNTIME_CACHE["ts"]) < 3.0:
        return dict(_NATIVE_RUNTIME_CACHE["value"])
    result: dict[str, Any] = {"worker_running": False, "worker_service_state": "UNKNOWN",
                             "configuration_verified": False, "ledger_source": "native_paper_ledger"}
    registered = pc.PRODUCTS["btc5m"]
    if (registered.directory / "effective.json").exists():
        current = pc.snapshot(registered)
        values = current["effective"]
        capital = pc.read(registered.directory / "identity.json").get("paper_bankroll_usd")
        config = {**values, "seconds_before_close": values.get("entry_window_sec"),
                  "entry_confirm_checks": values.get("confirm_checks"), "paper_equity_usd": capital,
                  "max_daily_loss_fraction": values["daily_loss_limit_usd"] / capital if values and capital else None,
                  "btc_live_enabled": False}
        result.update(worker_running=current["paper_enabled"], worker_pid=current["worker_pid"],
                      worker_service_state="RUNNING" if current["paper_enabled"] else "STOPPED",
                      configuration_verified=current["configuration_verified"], worker_config=config,
                      effective_config=config, native_config={k.upper():v for k,v in values.items()},
                      capital_base_usd=capital, effective_max_daily_loss_fraction=config["max_daily_loss_fraction"],
                      daily_loss_limit_source="verified_product_configuration")
        _NATIVE_RUNTIME_CACHE.update(ts=now, value=result)
        return dict(result)
    try:
        proc_result = subprocess.run(["systemctl", "show", "polymarket-test-btc-paper.service",
            "--property=MainPID,ActiveState,WorkingDirectory"], capture_output=True, text=True, timeout=1.5, check=True)
        props = dict(line.split("=", 1) for line in proc_result.stdout.splitlines() if "=" in line)
        active = props.get("ActiveState") == "active"
        result["worker_service_state"] = "STOPPED" if not active else "UNVERIFIED"
        if active:
            pid = int(props.get("MainPID") or 0)
            proc = Path("/proc") / str(pid)
            root = ROOT.parent.parent.resolve()
            cwd = (proc / "cwd").resolve(strict=True)
            declared_cwd = Path(props.get("WorkingDirectory") or "/").resolve()
            args = (proc / "cmdline").read_bytes().split(b"\0")
            module = args[args.index(b"-m") + 1] if b"-m" in args else b""
            if module != b"btc5m" or cwd != declared_cwd or root not in cwd.parents:
                raise ValueError("native unit identity mismatch")
            allowed = {"MODE", "LIVE_TRADING_ENABLED", "ALLOW_SPOT_RESOLUTION_FALLBACK", "DATA_DIR",
                "ENTRY_WINDOW_SEC", "MIN_T_REMAINING_SEC", "MIN_ENTRY_PRICE", "MAX_ENTRY_PRICE",
                "MIN_NET_EDGE", "TAKER_FEE_RATE", "CONFIRM_CHECKS", "POLL_INTERVAL_SEC",
                "DELTA_FILTER_ENABLED", "UP_MIN_DELTA_USD", "DOWN_MAX_DELTA_USD",
                "SIGNAL_REQUIRE_CONSENSUS", "SIGNAL_MIN_VENUES", "LEAD_TABLE_ENABLED",
                "OPENING_GAP_ENABLED", "ORDER_SHARES", "MAX_ORDER_USD", "DAILY_LOSS_LIMIT_USD",
                "MAX_OPEN_POSITIONS", "PAPER_BANKROLL_USD", "PAPER_SLIPPAGE_TICKS", "PAPER_SLIPPAGE_PCT"}
            env = {}
            for entry in (proc / "environ").read_bytes().split(b"\0"):
                name, sep, value = entry.partition(b"=")
                key = name.decode("ascii", "ignore")
                if sep and key in allowed:
                    env[key] = value.decode("utf-8")
            if env.get("LIVE_TRADING_ENABLED", "").lower() not in {"false", "0", "no", "off"}:
                raise ValueError("native Paper mode unverified")
            if (Path(env.get("DATA_DIR") or "/") / "paper.db").resolve() != NATIVE_PAPER_DB.resolve():
                raise ValueError("native database mismatch")
            values: dict[str, Any] = {}
            for key, value in env.items():
                if key == "DATA_DIR":
                    continue
                if value.lower() in {"true", "false"}:
                    values[key] = value.lower() == "true"
                else:
                    try: values[key] = float(value) if "." in value else int(value)
                    except ValueError: values[key] = value
            bankroll = float(values.get("PAPER_BANKROLL_USD") or 0.0)
            loss_usd = float(values.get("DAILY_LOSS_LIMIT_USD") or 0.0)
            aliases = {"min_entry_price": values.get("MIN_ENTRY_PRICE"), "max_entry_price": values.get("MAX_ENTRY_PRICE"),
                "seconds_before_close": values.get("ENTRY_WINDOW_SEC"), "min_t_remaining_sec": values.get("MIN_T_REMAINING_SEC"),
                "max_open_positions": values.get("MAX_OPEN_POSITIONS"), "paper_equity_usd": bankroll,
                "order_shares": values.get("ORDER_SHARES"), "max_order_usd": values.get("MAX_ORDER_USD"),
                "paper_slippage_ticks": values.get("PAPER_SLIPPAGE_TICKS"), "paper_slippage_pct": values.get("PAPER_SLIPPAGE_PCT"),
                "max_daily_loss_fraction": loss_usd / bankroll if bankroll > 0 else None,
                "daily_loss_limit_usd": loss_usd, "entry_confirm_checks": values.get("CONFIRM_CHECKS"),
                "btc_live_enabled": False}
            result.update(worker_running=True, worker_service_state="RUNNING", worker_pid=pid,
                configuration_verified=True, worker_config=aliases, effective_config=aliases,
                native_config=values, capital_base_usd=bankroll,
                effective_max_daily_loss_fraction=aliases["max_daily_loss_fraction"],
                daily_loss_limit_source="verified_native_worker_environment")
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    _NATIVE_RUNTIME_CACHE.update(ts=now, value=result)
    return dict(result)


def _native_paper_conn() -> Optional[sqlite3.Connection]:
    """Open the native Paper DB read-only; never mutate the execution ledger."""
    if not NATIVE_PAPER_DB.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{NATIVE_PAPER_DB}?mode=ro", uri=True, timeout=2)
        c.row_factory = sqlite3.Row
        return c
    except (OSError, sqlite3.Error):
        return None


def _bj_day(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), timezone.utc).astimezone(
        timezone(timedelta(hours=8))).strftime("%Y-%m-%d")




def _native_unavailable_account(cached: Optional[dict] = None) -> dict[str, Any]:
    if cached is not None:
        return {**cached, "stale": True, "error": "native_paper_ledger_unavailable"}
    return {"positions": [], "settled_positions": [], "native_positions": [], "native_fills": [],
            "pnl": {"realized_usd": None, "gross_pnl_usd": None, "net_pnl_usd": None,
                    "fees_usd": None, "wins": None, "losses": None, "pending": None},
            "by_asset": {}, "open_value_usd": None, "capital_base_usd": None,
            "available": False, "stale": True, "error": "native_paper_ledger_unavailable",
            "source": "native_paper_ledger", "updated_at": None}


def _native_position_net(row: dict[str, Any]) -> Optional[float]:
    if row.get("pnl_net_usd") is not None:
        return float(row["pnl_net_usd"])
    if row.get("pnl_usd") is not None:
        return float(row["pnl_usd"]) - abs(float(row.get("fee_usd") or 0.0))
    return None

def _native_paper_account_snapshot() -> Optional[dict[str, Any]]:
    """Translate native fills/positions into the dashboard's Paper contract."""
    now = time.time()
    cached = _NATIVE_PAPER_CACHE.get("account")
    if cached is not None and now - float(_NATIVE_PAPER_CACHE.get("ts", 0.0)) < 0.75:
        return cached
    c = _native_paper_conn()
    if c is None:
        return _native_unavailable_account(cached) if cached is not None or NATIVE_PAPER_DB.exists() else None
    try:
        c.execute("BEGIN")
        fills = [dict(r) for r in c.execute("SELECT * FROM fills WHERE dry_run=1 ORDER BY id").fetchall()]
        positions = [dict(r) for r in c.execute("SELECT * FROM positions WHERE dry_run=1 ORDER BY id").fetchall()]
        entries = [dict(r) for r in c.execute("SELECT id,ts,market_slug,payload FROM events WHERE kind='entry' ORDER BY id").fetchall()]
    except sqlite3.Error:
        c.close()
        return _native_unavailable_account(cached)
    finally:
        try: c.close()
        except Exception: pass
    entry_by_position: dict[int, dict[str, Any]] = {}
    for event in entries:
        try:
            payload = json.loads(event["payload"])
            if payload.get("position_id") is not None:
                entry_by_position[int(payload["position_id"])] = payload
        except (ValueError, TypeError, KeyError):
            continue
    for r in positions:
        audit = entry_by_position.get(int(r["id"])) or {}
        r["slippage_usd"] = abs(float(audit.get("paper_slippage") or 0.0) * float(audit.get("size") or r.get("size") or 0.0))
        r["quoted_price"] = audit.get("quoted_price")
        r["slippage_included_in_execution_price"] = True
    # One native entry fill owns one position. Match all identity fields and
    # timestamp rather than only market_slug to avoid assigning a second
    # entry in the same market the first entry's economics.
    available_positions = list(positions)
    for f in fills:
        candidates = [p for p in available_positions if p.get("market_slug") == f.get("market_slug")
                      and p.get("token_id") == f.get("token_id") and p.get("side") == f.get("side")]
        if candidates:
            match = min(candidates, key=lambda p: abs(float(p.get("opened_ts") or 0.0) - float(f.get("ts") or 0.0)))
            if abs(float(match.get("opened_ts") or 0.0) - float(f.get("ts") or 0.0)) <= 5.0:
                f["native_position_id"] = match["id"]
                if not float(f.get("slippage_usd") or 0.0):
                    f["slippage_usd"] = match.get("slippage_usd", 0.0)
                f["quoted_price"] = match.get("quoted_price")
                available_positions.remove(match)
    open_rows: list[dict[str, Any]] = []
    settled_rows: list[dict[str, Any]] = []
    for r in positions:
        fee = float(r.get("fee_usd") or 0.0)
        gross = r.get("pnl_usd")
        net = r.get("pnl_net_usd")
        item = {
            "id": r.get("id"), "asset": "BTC", "ts": float(r.get("opened_ts") or 0),
            "opened_ts": float(r.get("opened_ts") or 0), "closed_ts": r.get("closed_ts"),
            "market_slug": r.get("market_slug"), "condition_id": r.get("condition_id"),
            "side": r.get("side"), "token_id": r.get("token_id"),
            "size": float(r.get("size") or 0.0), "entry_price": float(r.get("entry_price") or 0.0),
            "price": float(r.get("entry_price") or 0.0),
            "notional_usd": float(r.get("size") or 0.0) * float(r.get("entry_price") or 0.0),
            "exit_price": r.get("exit_price"), "pnl_usd": gross, "gross_pnl_usd": gross,
            "fee_usd": -abs(fee), "fees_usd": -abs(fee),
            "pnl_net_usd": net, "net_pnl_usd": net,
            "slippage_usd": -abs(float(r.get("slippage_usd") or 0.0)),
            "quoted_price": r.get("quoted_price"), "slippage_included_in_execution_price": True,
            "liquidity": r.get("liquidity") or "taker", "strategy": r.get("strategy"),
            "status": r.get("status"), "dry_run": int(r.get("dry_run") or 1),
            "settled": str(r.get("status") or "") == "closed",
        }
        (settled_rows if item["settled"] else open_rows).append(item)
    today = _bj_day(now)
    closed_today = [r for r in positions if str(r.get("status") or "") == "closed"
                    and r.get("closed_ts") is not None and _bj_day(r["closed_ts"]) == today]
    def nval(row: dict, key: str) -> float:
        try: return float(row.get(key) or 0.0)
        except (TypeError, ValueError): return 0.0
    gross_today = sum(nval(r, "pnl_usd") for r in closed_today)
    fees_today = -sum(abs(nval(r, "fee_usd")) for r in closed_today)
    net_today = sum((nval(r, "pnl_net_usd") if r.get("pnl_net_usd") is not None
                     else nval(r, "pnl_usd") - abs(nval(r, "fee_usd"))) for r in closed_today)
    cumulative_gross = sum(nval(r, "pnl_usd") for r in positions if r.get("status") == "closed")
    cumulative_fees = -sum(abs(nval(r, "fee_usd")) for r in positions if r.get("status") == "closed")
    cumulative_net = sum((nval(r, "pnl_net_usd") if r.get("pnl_net_usd") is not None
                          else nval(r, "pnl_usd") - abs(nval(r, "fee_usd")))
                          for r in positions if r.get("status") == "closed")
    wins = sum(1 for r in closed_today if _native_position_net(r) is not None and _native_position_net(r) >= 0)
    losses = sum(1 for r in closed_today if _native_position_net(r) is not None and _native_position_net(r) < 0)
    cumulative_wins = sum(1 for r in positions if r.get("status") == "closed" and _native_position_net(r) is not None and _native_position_net(r) >= 0)
    cumulative_losses = sum(1 for r in positions if r.get("status") == "closed" and _native_position_net(r) is not None and _native_position_net(r) < 0)
    open_value = sum(nval(r, "notional_usd") for r in open_rows)
    open_fees = sum(abs(nval(r, "fee_usd")) for r in positions if r.get("status") != "closed")
    cumulative_slippage = sum(abs(nval(f, "slippage_usd")) for f in fills)
    by_asset = {"BTC": {"realized_usd": net_today, "wins": wins, "losses": losses,
                         "pending": len(open_rows), "open_value_usd": open_value}}
    account = {
        "positions": open_rows, "settled_positions": settled_rows,
        "pnl": {"realized_usd": net_today, "gross_pnl_usd": gross_today,
                "fees_usd": fees_today,
                "slippage_usd": -sum(abs(nval(r, "slippage_usd")) for r in closed_today),
                "rebate_usd": 0.0, "rebates_usd": 0.0,
                "net_pnl_usd": net_today, "wins": wins, "losses": losses,
                "pending": len(open_rows), "source": "native_paper_ledger"},
        "by_asset": by_asset, "open_value_usd": open_value,
        "capital_base_usd": float(_native_paper_worker_runtime().get("capital_base_usd")
                                  or getattr(cfg, "paper_equity_usd", 0.0) or 0.0),
        "cumulative_realized_usd": cumulative_net, "cumulative_gross_pnl_usd": cumulative_gross,
        "cumulative_fees_usd": cumulative_fees, "cumulative_net_pnl_usd": cumulative_net,
        "open_fees_usd": open_fees, "cumulative_slippage_usd": cumulative_slippage,
        "equity_valuation": "entry_cost", "slippage_included_in_execution_price": True,
        "cumulative_wins": cumulative_wins, "cumulative_losses": cumulative_losses,
        "native_fills": fills, "native_positions": positions,
        "source": "native_paper_ledger", "updated_at": now, "available": True, "stale": False, "error": None,
    }
    _NATIVE_PAPER_CACHE.update(ts=now, account=account)
    return account


def _native_paper_daily_rows() -> list[dict[str, Any]]:
    account = _native_paper_account_snapshot()
    if not account:
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for r in account.get("native_positions", []):
        if r.get("status") != "closed" or r.get("closed_ts") is None:
            continue
        day = _bj_day(r["closed_ts"])
        item = grouped.setdefault(day, {"day": day, "pnl_usd": 0.0, "gross_pnl_usd": 0.0,
            "fees_usd": 0.0, "slippage_usd": 0.0, "rebate_usd": 0.0, "net_pnl_usd": 0.0,
            "wins": 0, "losses": 0, "trades": 0, "settled": 0, "pending": 0,
            "maker_fee_usd": 0.0, "taker_fee_usd": 0.0,
            "maker_rebate_usd": 0.0, "taker_rebate_usd": 0.0,
            "rebates_usd": 0.0, "trade_pnl_usd": 0.0,
            "fee_status": "paper_execution_model", "fees_source": "native_paper_fills",
            "slippage_included_in_execution_price": True,
            "source": "native_paper_ledger"})
        gross = float(r.get("pnl_usd") or 0.0)
        fee = -abs(float(r.get("fee_usd") or 0.0))
        net = float(r.get("pnl_net_usd") if r.get("pnl_net_usd") is not None else gross + fee)
        item["pnl_usd"] += gross; item["gross_pnl_usd"] += gross
        item["fees_usd"] += fee; item["net_pnl_usd"] += net
        item["trade_pnl_usd"] += gross
        item["slippage_usd"] -= abs(float(r.get("slippage_usd") or 0.0))
        item["maker_fee_usd" if str(r.get("liquidity") or "taker").lower() == "maker" else "taker_fee_usd"] += fee
        item["wins" if net >= 0 else "losses"] += 1
        item["trades"] += 1; item["settled"] += 1
    for item in grouped.values():
        item["return_rate"] = (item["net_pnl_usd"] / float(account.get("capital_base_usd") or 1.0)) * 100.0
        item["capital_base_usd"] = account.get("capital_base_usd")
    return sorted(grouped.values(), key=lambda x: x["day"], reverse=True)


def _native_paper_orders_page(offset: int, limit: int, start_ts: Optional[float] = None,
                              end_ts: Optional[float] = None) -> dict[str, Any]:
    account = _native_paper_account_snapshot()
    if not account:
        return {"rows": [], "total": 0, "today_total": 0, "offset": offset, "limit": limit,
                "source": "native_paper_ledger"}
    pos_by_id = {r["id"]: r for r in account.get("native_positions", [])}
    rows = []
    for f in account.get("native_fills", []):
        ts = float(f.get("ts") or 0.0)
        if start_ts is not None and ts < float(start_ts): continue
        if end_ts is not None and ts >= float(end_ts): continue
        p = pos_by_id.get(f.get("native_position_id")) or {}
        gross = p.get("pnl_usd")
        net = _native_position_net(p)
        fee = -abs(float(f.get("fee_usd") or 0.0))
        rows.append({"id": f.get("id"), "ts": ts, "market_slug": f.get("market_slug"),
            "condition_id": f.get("condition_id"), "token_id": f.get("token_id"), "asset": "BTC",
            "side": f.get("side"), "size": float(f.get("size") or 0.0), "price": float(f.get("price") or 0.0),
            "order_id": f.get("order_id") or f"native-fill:{f.get('id')}", "status": "dry_run",
            "filled_size": float(f.get("size") or 0.0), "error": None,
            "entry_rule": f.get("note") or "native btc5m Paper", "dry_run": 1,
            "winning_token": p.get("token_id") if p.get("exit_price") is not None and float(p["exit_price"]) >= 0.999 else None,
            "resolved_ts": p.get("closed_ts"), "result": "HIT" if net is not None and float(net) >= 0 else "MISS" if net is not None else "NONE",
            "result_basis": "net_pnl_after_fees",
            "settled": p.get("status") == "closed", "fee_usd": fee, "fees_usd": fee,
            "slippage_usd": -abs(float(f.get("slippage_usd") or 0.0)), "liquidity": f.get("liquidity"),
            "gross_pnl_usd": gross, "pnl_usd": gross, "net_pnl_usd": net,
            "quoted_price": f.get("quoted_price"), "slippage_included_in_execution_price": True,
            "fee_source": "native_paper_execution_model", "fee_status": "paper_model",
            "source": "native_paper_ledger", "record_key": f"paper-native:{f.get('id')}"})
    rows.sort(key=lambda x: (x["ts"], x["id"]), reverse=True)
    today_start = local_day_start_ts()
    return {"rows": rows[offset:offset + limit], "total": len(rows),
            "today_total": sum(1 for r in rows if r["ts"] >= today_start),
            "offset": offset, "limit": limit, "source": "native_paper_ledger"}

# Scope this site's presentation to BTC without changing trading accounting.
_all_accounting_snapshot = accounting_snapshot
_all_fifo_ledger = _fifo_ledger
_all_remaining_positions = remaining_positions


def accounting_snapshot(dry_run: bool, now: Optional[float] = None) -> dict:
    account = _all_accounting_snapshot(dry_run, now=now)
    positions = [row for row in account["positions"] if str(row.get("asset", "")).upper() == "BTC"]
    item = dict(account["by_asset"].get("BTC") or {"realized_usd": 0.0, "wins": 0, "losses": 0, "pending": 0, "open_value_usd": 0.0})
    pnl = {**account["pnl"], **{key: item[key] for key in ("realized_usd", "wins", "losses")}, "pending": len(positions)}
    return {**account, "pnl": pnl, "positions": positions, "by_asset": {"BTC": item}, "open_value_usd": sum(float(row["notional_usd"]) for row in positions)}


def realized_pnl_summary_today(dry_run: bool) -> dict:
    return accounting_snapshot(dry_run)["pnl"]


def _fifo_ledger(dry_run: bool):
    lots, events, resolutions = _all_fifo_ledger(dry_run)
    return ([row for row in lots if str(row.get("asset", "")).upper() == "BTC"],
            [row for row in events if str(row.get("asset", "")).upper() == "BTC"], resolutions)


def remaining_positions(dry_run: bool, asset: Optional[str] = None) -> list[dict]:
    return _all_remaining_positions(dry_run, asset="BTC")

# Live controls are deliberately protected by a separate operator token.  The
# dashboard is reachable through the public HTTPS hostname, so exposing a
# start/stop route without authentication would allow anybody to place real
# orders.  The token is read from .env for every request so rotating it does
# not require a dashboard restart.
_live_control_lock = threading.Lock()


def _deployment_instance_name() -> str:
    """Return the public deployment identity without conflating polytest with polyauto."""
    configured = os.environ.get("INSTANCE_NAME", "").strip()
    if configured:
        return configured
    return "polyauto" if _is_polyauto_instance() else "main"


def _is_polyauto_instance() -> bool:
    """Return deployment identity without relying on a copied main .env."""
    value = os.environ.get("POLYAUTO_INSTANCE", "").strip().lower()
    if value in ("1", "true", "yes", "on", "auto"):
        return True
    return str(getattr(cfg, "instance_name", "main")).strip().lower() == "polyauto"


LIVE_SERVICE_IDS = ("BTC",)


def _control_env_values() -> dict[str, str]:
    # .env contains long provider prompts and is expensive to parse. State is
    # pushed every second, so cache the normalized values until the file is
    # actually changed (or a short safety TTL expires).
    path = ROOT / ".env"
    try:
        stat = path.stat()
        marker = (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        marker = (0, 0)
    now = time.monotonic()
    cached = globals().get("_DOTENV_CACHE")
    if isinstance(cached, dict) and cached.get("marker") == marker and now - float(cached.get("ts", 0.0)) < 30.0:
        return cached["values"]
    values = dotenv_values(path)
    normalized = {str(k): str(v or "") for k, v in values.items()}
    globals()["_DOTENV_CACHE"] = {"marker": marker, "ts": now, "values": normalized}
    return normalized


def _live_execution_capability() -> dict[str, Any]:
    """Read the non-secret native-live capability marker.

    The marker remains absent/false until P1/P2 implementation and P3
    evidence are complete. A legacy .env live flag cannot satisfy this gate.
    """
    required = list(LIVE_CAPABILITY_KEYS)
    result = {"ready": False, "capabilities": {k: False for k in required},
              "missing": required, "config_hash": "", "strategy_source": "native-btc5m",
              "marker": str(LIVE_CAPABILITY_FILE)}
    try:
        payload = json.loads(LIVE_CAPABILITY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        result["reason"] = "P0/P1/P2 未完成：缺少 native live capability marker；实盘保持关闭"
        return result
    if not isinstance(payload, dict):
        result["reason"] = "live capability marker 格式无效；实盘保持关闭"
        return result
    caps = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else payload
    # Capability markers are an authorization boundary.  Accept only JSON
    # booleans; strings such as "false" must not be truthy-coerced.
    normalized = {
        k: (caps.get(k) if isinstance(caps.get(k), bool) else False)
        for k in required
    }
    config_hash = str(payload.get("config_hash") or "").strip()
    ready = bool(payload.get("ready", False)) and all(normalized.values()) and bool(config_hash)
    result.update({"ready": ready, "capabilities": normalized,
                   "missing": [k for k, v in normalized.items() if not v],
                   "config_hash": config_hash,
                   "strategy_source": str(payload.get("strategy_source") or "native-btc5m")})
    if not ready:
        missing = result["missing"] or (["config_hash"] if not config_hash else [])
        result["reason"] = "P0/P1/P2 未完成：缺少 " + ", ".join(missing) + "；实盘保持关闭"
    else:
        result["reason"] = "native live capability 已认证"
    return result


def _service_status_snapshot() -> dict[str, Any]:
    """Expose independent, truthful live gates for each polyauto service."""
    env = _control_env_values()
    auto = _is_polyauto_instance()
    assets = _live_process_status_base()
    paper_assets = _paper_process_status_base()
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
        "BTC": {"live_enabled": btc_enabled, "can_enable_live": True, "mode": ("live" if assets["BTC"] else "paper"), "running": bool(assets["BTC"] or paper_assets["BTC"]), "live_running": assets["BTC"], "paper_running": paper_assets["BTC"]},
        # polyauto explicitly opts into BTC and ETH live independently.  The
        # weather and sports services remain paper-only below.
        "ETH": {"live_enabled": eth_enabled, "can_enable_live": True, "mode": ("live" if assets["ETH"] else "paper"), "running": bool(assets["ETH"] or paper_assets["ETH"]), "live_running": assets["ETH"], "paper_running": paper_assets["ETH"]},
        "WEATHER": {"live_enabled": False, "can_enable_live": False, "mode": "paper", "running": bool(read_paper_feed_snapshot("WEATHER").get("running"))},
        "SPORTS": {"live_enabled": False, "can_enable_live": False, "mode": "paper", "running": bool(read_paper_feed_snapshot("SPORTS").get("running"))},
    }
    if auto:
        # Weather and sports remain paper-only in the isolated instance.
        for service in ("WEATHER", "SPORTS"):
            policy[service]["live_enabled"] = False
            policy[service]["mode"] = "paper"
    capability = _live_execution_capability()
    policy["BTC"].update({
        "can_enable_live": bool(capability["ready"]),
        "execution_ready": bool(capability["ready"]),
        "execution_capabilities": capability["capabilities"],
        "live_block_reason": capability.get("reason", ""),
        "strategy_source": capability.get("strategy_source", "native-btc5m"),
        "config_hash": capability.get("config_hash", ""),
    })
    return {"BTC": policy["BTC"]}


def _pid_command_line(path: Path) -> str:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        if not _pid_alive(path):
            return ""
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except (FileNotFoundError, OSError, ValueError):
        return ""


def _pid_is_live(path: Path) -> bool:
    command = _pid_command_line(path)
    return bool(command and re.search(r"(?:^|\s)--live(?:\s|$)", command))


def _pid_is_paper(path: Path) -> bool:
    command = _pid_command_line(path)
    if not command or _pid_is_live(path):
        return False
    return (("bot.main" in command and "--asset" in command)
            or (globals().get("_PAPER_COMPARISON_ENABLED", False) and "scripts/run_paper_p3.py" in command))


def _live_process_status_base() -> dict[str, bool]:
    return {
        "BTC": _pid_is_live(ROOT / "bot_btc.pid") or _pid_is_live(ROOT / "bot.pid"),
        "ETH": _pid_is_live(ROOT / "bot_eth.pid"),
    }


def _paper_process_status_base() -> dict[str, bool]:
    return {
        "BTC": bool(_native_paper_worker_runtime().get("worker_running")) or _pid_is_paper(ROOT / "bot_btc.pid") or _pid_is_paper(ROOT / "bot.pid"),
        "ETH": _pid_is_paper(ROOT / "bot_eth.pid"),
    }


def _operator_token() -> str:
    values = _control_env_values()
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


_POLY_PROFILE_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}

_POLY_LIVE_SUMMARY_CACHE: dict[str, Any] = {"ts": 0., "value": None}
_POLY_LIVE_SUMMARY_LOCK = threading.Lock()
_POLY_FINANCIAL_INPUTS: dict[str, Any] = {}
_POLY_ACTIVITY_CACHE: dict[str, Any] = {"ts": 0., "value": None}
_POLY_ACTIVITY_LOCK = threading.Lock()
_POLY_CLOSED_CACHE: dict[str, Any] = {"ts": 0., "value": None}
_POLY_CLOSED_LOCK = threading.Lock()


def _closed_positions_snapshot() -> dict[str, Any]:
    wallet = _deposit_wallet_address()
    if not wallet:
        raise requests.RequestException("wallet_unconfigured")
    with _POLY_CLOSED_LOCK:
        cached = _POLY_CLOSED_CACHE.get("value")
        if cached and cached.get("wallet") == wallet and time.time() - _POLY_CLOSED_CACHE["ts"] < 15.:
            return dict(cached)
        try:
            rows = read_account_pages(requests.get, "https://data-api.polymarket.com/v2/positions",
                                      {"user": wallet, "status": "CLOSED", "limit": 500, "sort_by": "TIMESTAMP"},
                                      timeout=_POLY_READ_TIMEOUT)
            value = {"rows": rows, "wallet": wallet, "available": True, "stale": False,
                     "updated_at": time.time(), "error": None}
        except (requests.RequestException, ValueError) as exc:
            if not cached or cached.get("wallet") != wallet:
                raise requests.RequestException(str(exc)) from exc
            value = {**cached, "stale": True, "error": str(exc)}
        _POLY_CLOSED_CACHE.update(ts=time.time(), value=value)
        return dict(value)


def _activity_snapshot() -> dict[str, Any]:
    """Share complete cursor-paginated confirmed history across all readers."""
    wallet = _deposit_wallet_address()
    if not wallet:
        raise requests.RequestException("wallet_unconfigured")
    with _POLY_ACTIVITY_LOCK:
        now = time.time()
        cached = _POLY_ACTIVITY_CACHE.get("value")
        if cached and cached.get("wallet") == wallet and now - _POLY_ACTIVITY_CACHE["ts"] < 10.:
            return dict(cached)
        try:
            records = read_account_pages(requests.get, "https://data-api.polymarket.com/v2/activity",
                                         {"user": wallet, "limit": 500}, timeout=_POLY_READ_TIMEOUT)
            value = {"rows": confirmed_activity(records), "wallet": wallet, "available": True,
                     "stale": False, "updated_at": time.time(), "error": None}
            _POLY_ACTIVITY_CACHE.update(ts=time.time(), value=value)
            return dict(value)
        except (requests.RequestException, ValueError) as exc:
            if cached and cached.get("wallet") == wallet:
                value = {**cached, "stale": True, "error": str(exc)}
                _POLY_ACTIVITY_CACHE.update(ts=time.time(), value=value)
                return dict(value)
            raise requests.RequestException(str(exc)) from exc


def _summary_with_age(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    as_of = result.get("data_as_of")
    age = max(0., time.time() - as_of) if as_of else None
    result["data_age_sec"] = age
    result["stale"] = bool(result.get("error")) or not result.get("available") or bool(age and age > 7200.)
    return result


def _polymarket_live_summary() -> dict[str, Any]:
    """One coherent official financial snapshot for every live presentation."""
    wallet = _deposit_wallet_address()
    if not wallet:
        return {**live_statistics([], {}, [], time.time(), activity_available=False),
                "wallet": wallet, "error": "wallet_unconfigured", "stale": True}
    with _POLY_LIVE_SUMMARY_LOCK:
        if _POLY_FINANCIAL_INPUTS.get("wallet") != wallet:
            _POLY_FINANCIAL_INPUTS.clear()
            _POLY_FINANCIAL_INPUTS["wallet"] = wallet
        cached = _POLY_LIVE_SUMMARY_CACHE.get("value")
        if (cached and cached.get("wallet") == wallet
                and time.time() - _POLY_LIVE_SUMMARY_CACHE["ts"] < 15.
                and local_day_start_ts(cached.get("updated_at") or 0.) == local_day_start_ts()):
            return _summary_with_age(cached)
        errors = []

        def fetch_financial(name):
            params = {"user": wallet}
            if name == "user-pnl":
                params.update(interval="all", fidelity="1h")
            response = requests.get("https://data-api.polymarket.com/v2/" + name,
                                    params=params, timeout=_POLY_READ_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", payload) if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise ValueError("invalid " + name + " payload")
            return data

        closed = {"rows": None, "updated_at": None, "stale": True}
        with ThreadPoolExecutor(max_workers=3) as pool:
            closed_future = pool.submit(_closed_positions_snapshot)
            futures = {name: pool.submit(fetch_financial, name) for name in ("user-pnl", "user-stats")}
            for name, future in futures.items():
                try:
                    _POLY_FINANCIAL_INPUTS[name] = future.result()
                except (requests.RequestException, ValueError) as exc:
                    errors.append(name + ": " + str(exc))
            try:
                closed = closed_future.result()
                if closed.get("error"):
                    errors.append("positions: " + closed["error"])
            except requests.RequestException as exc:
                errors.append("positions: " + str(exc))
        history = _POLY_FINANCIAL_INPUTS.get("user-pnl") or {}
        stats = (_POLY_FINANCIAL_INPUTS.get("user-stats") or {}).get("all_time_pnl") or {}
        activity = {"rows": [], "updated_at": None, "stale": True, "available": False}
        try:
            activity = _activity_snapshot()
            if activity.get("error"):
                errors.append(activity["error"])
        except requests.RequestException as exc:
            errors.append("activity: " + str(exc))
        result = live_statistics(history.get("points") or [], stats, activity["rows"], time.time(),
                                 source_fidelity=history.get("source_fidelity"), positions=closed["rows"],
                                 activity_available=activity.get("available", False))
        result.update(wallet=wallet, error="; ".join(errors) or None,
                      activity_updated_at=activity.get("updated_at"), activity_stale=activity.get("stale", False),
                      outcomes_updated_at=closed.get("updated_at"), outcomes_stale=closed.get("stale", False))
        _POLY_LIVE_SUMMARY_CACHE.update(ts=time.time(), value=result)
        return _summary_with_age(result)


_FUNDING_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}
_FUNDING_SCAN_LOCK = threading.Lock()
_FUNDING_SCAN_ACTIVE = False
_POLY_READ_TIMEOUT = 8


def _portfolio_snapshot(holdings: Optional[dict] = None) -> dict[str, Any]:
    """Return public identity plus fresh wallet value and external PnL."""
    wallet = _deposit_wallet_address()
    now = time.time()
    cached = _POLY_PROFILE_CACHE.get("value")
    if cached is None or now - float(_POLY_PROFILE_CACHE.get("ts", 0.0)) >= 300.0:
        profile: dict[str, Any] = {"available": False, "source": "gamma_public_profile", "proxy_wallet": wallet or None}
        if wallet:
            try:
                response = requests.get(
                    "https://gamma-api.polymarket.com/public-profile",
                    params={"address": wallet},
                    timeout=_POLY_READ_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    profile.update({
                        "available": True,
                        "name": data.get("name") or data.get("displayUsername"),
                        "pseudonym": data.get("pseudonym"),
                        "proxy_wallet": data.get("proxyWallet") or wallet,
                        "verified_badge": bool(data.get("verifiedBadge")),
                    })
            except Exception as exc:
                profile["error"] = str(exc)
        _POLY_PROFILE_CACHE.update(ts=now, value=profile)
        cached = profile
    profile = dict(cached or {"available": False, "proxy_wallet": wallet or None})
    # These values are updated by the 2-second wallet poller. Do not keep them
    # inside the identity cache: a manual redeem must move the top bar and
    # position/portfolio cards on the next state frame.
    balance = _state.get("balance_pusd")
    holdings = holdings if holdings is not None else _account_positions_snapshot()
    position_value = holdings.get("total_value_usd")
    try:
        balance_value = float(balance) if balance is not None else None
    except (TypeError, ValueError):
        balance_value = None
    try:
        position_value_num = float(position_value) if position_value is not None else None
    except (TypeError, ValueError):
        position_value_num = None
    pending_deposit = _state.get("balance_usdce")
    try:
        pending_deposit_num = float(pending_deposit) if pending_deposit is not None else None
    except (TypeError, ValueError):
        pending_deposit_num = None
    if pending_deposit_num is not None and (not math.isfinite(pending_deposit_num) or pending_deposit_num < 0):
        pending_deposit_num = None
    profile["balance_usd"] = balance_value
    profile["pending_deposit_usd"] = pending_deposit_num
    profile["fund_activation"] = {
        "asset": "USDC.e",
        "status": "pending_user_signature" if pending_deposit_num is not None and pending_deposit_num > 0.000001 else "none_detected",
        "amount_usd": pending_deposit_num,
        "automatic_confirmation": False,
        "reason": "USDC.e 转入 pUSD 需要钱包签名" if pending_deposit_num is not None and pending_deposit_num > 0.000001 else None,
    }
    profile["position_value_usd"] = position_value_num
    profile["positions_available"] = bool(holdings.get("available"))
    profile["positions_stale"] = bool(holdings.get("stale"))
    profile["positions_updated_at"] = holdings.get("updated_at")
    profile["pending_count"] = holdings.get("pending_count")
    profile["redeemable_count"] = holdings.get("redeemable_count")
    profile["pending_value_usd"] = holdings.get("pending_value_usd")
    profile["redeemable_value_usd"] = holdings.get("redeemable_value_usd")
    profile["portfolio_value_usd"] = (
        round(balance_value + (pending_deposit_num or 0.0) + position_value_num, 4)
        if balance_value is not None and position_value_num is not None
        else None
    )
    # Public account PnL/activity is separate from the local worker ledger so
    # manual Polymarket redemptions are reflected without editing local history.
    profile["live_summary"] = _polymarket_live_summary()
    return profile

# Receipt-backed trade fees are read asynchronously, separate from the live
# strategy, financial snapshot and local execution ledger.
from server.trade_fee_evidence import receipt_fee_evidence, activity_fee_evidence
from server.trade_fee_cache import ReceiptFeeCache


def _fee_exchange_addresses() -> set[str]:
    from py_clob_client_v2.config import get_contract_config
    contracts = get_contract_config(cfg.chain_id)
    return {str(getattr(contracts, name)).lower() for name in
            ("exchange", "exchange_v2", "neg_risk_exchange", "neg_risk_exchange_v2")
            if getattr(contracts, name, None)}


def _fee_receipt_read(tx: str) -> dict:
    # Receipt lookups are public read-only RPC calls. Configured provider first,
    # with public Polygon endpoints as failover. Never log provider credentials.
    endpoints = list(dict.fromkeys(filter(None, [getattr(cfg, "polygon_rpc_url", None),
                         "https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"])))
    for endpoint in endpoints:
        try:
            response = requests.post(endpoint, json={"jsonrpc": "2.0", "id": 1,
                    "method": "eth_getTransactionReceipt", "params": [tx]}, timeout=8)
            response.raise_for_status()
            result = response.json().get("result")
            if isinstance(result, dict) and result.get("transactionHash", "").lower() == tx:
                return result
        except (requests.RequestException, ValueError, AttributeError):
            continue
    raise ValueError("Transaction receipt temporarily unavailable")


def _fee_authenticated_trades() -> list[dict]:
    from bot.orders import build_client
    from py_clob_client_v2.clob_types import TradeParams
    client = build_client(cfg)
    result = client.get_trades(TradeParams(), only_first_page=False)
    if not isinstance(result, list):
        raise ValueError("Authenticated trade history unavailable")
    return result


_TRADE_FEE_EVIDENCE = ReceiptFeeCache(
    Path(os.getenv("POLYTEST_FEE_CACHE_DIR", str(ROOT.parent.parent / "state" / "fill-fees"))),
    load_receipt=_fee_receipt_read,
    decode_receipt=lambda receipt, wallet: receipt_fee_evidence(receipt, wallet,
                                            allowed_exchanges=_fee_exchange_addresses()),
    load_trades=_fee_authenticated_trades,
    resolve_activity=activity_fee_evidence,
)


def _polymarket_activity_rows(limit: int = 50, offset: int = 0, kind: str = "",
                               start_ts: Optional[float] = None, end_ts: Optional[float] = None,
                               include_period: bool = False) -> dict[str, Any]:
    snapshot = _activity_snapshot()
    normalized_kind = kind.strip().upper()
    records = [row for row in snapshot["rows"]
               if (not normalized_kind or row["type"] == normalized_kind)
               and (start_ts is None or row["timestamp"] >= start_ts)
               and (end_ts is None or row["timestamp"] < end_ts)]
    # The period summary covers every filtered fill, independently of page.
    selected = records if include_period else records[offset:offset + limit]
    # Confirm exact fill fees from OrderFilled receipts. CLOB metadata supplies
    # only the user's liquidity role; rate_bps=0 is not a zero-fee receipt.
    fee_evidence = _TRADE_FEE_EVIDENCE.snapshot(selected, snapshot["rows"], snapshot["wallet"])
    rows = []
    for index, item in enumerate(selected):
        ts = float(item["timestamp"])
        size = chain_number(item, "size") or 0.
        price = chain_number(item, "price") or 0.
        kind_value = item["type"]
        tx = str(item.get("transaction_hash") or "").lower()
        fee = fee_evidence[index]
        side = str(item.get("side") or kind_value)
        record_key = "chain:" + hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        row = {**item, "id": -int(record_key[-12:], 16), "ts": ts,
               "record_key": record_key,
               "asset": "BTC", "market_slug": item.get("slug") or item.get("event_slug") or "",
               "side": side, "size": size, "price": price, "filled_size": size,
               "order_id": item.get("transaction_hash"), "error": None, "status": "confirmed",
               "dry_run": 0, "entry_rule": "Polymarket", "winning_token": None, "resolved_ts": None,
               "settled": kind_value in ("REDEEM", "MERGE"), "result": "NONE",
               "activity_type": kind_value, "source": "polymarket", "pnl_usd": None,
               "cashflow_usd": chain_cashflow(item)}
        if fee:
            row.update(fee)
        rows.append(row)
    period_summary = None
    if include_period:
        closed = _closed_positions_snapshot()
        history = _POLY_FINANCIAL_INPUTS.get("user-pnl") or {}
        stats = (_POLY_FINANCIAL_INPUTS.get("user-stats") or {}).get("all_time_pnl") or {}
        if not history and not stats:
            _polymarket_live_summary()
            history = _POLY_FINANCIAL_INPUTS.get("user-pnl") or {}
            stats = (_POLY_FINANCIAL_INPUTS.get("user-stats") or {}).get("all_time_pnl") or {}
        points, _ = coherent_points(history.get("points") or [], stats)
        period_summary = summarize_activity_period(rows, start_ts=start_ts, end_ts=end_ts,
            positions=closed.get("rows") if closed.get("available") else None, points=points, now=time.time())
        period_summary.update(official_scope="wallet", activity_scope="wallet",
                              closed_positions_stale=closed.get("stale", False))
        rows = rows[offset:offset + limit]
    return {"rows": rows, "period_summary": period_summary,
            "total": len(records), "offset": offset, "limit": limit,
            "source": "data_api_v2", "available": snapshot["available"], "stale": snapshot["stale"],
            "updated_at": snapshot["updated_at"], "activity_as_of": max((row["timestamp"] for row in records), default=None),
            "wallet": snapshot["wallet"], "kind": normalized_kind or "ALL", "error": snapshot.get("error"),
            "fee_sync": {"source": "polygon_order_filled", "confirmed": sum(row.get("fee_status") == "confirmed" for row in rows),
                         "pending": sum(row.get("fee_status") == "pending" for row in rows),
                         "not_applicable": sum(row.get("fee_status") == "not_applicable" for row in rows)}}


def _rpc_transfer_chunk(args: tuple[str, int, int, str, str, str]) -> list[dict[str, Any]]:
    rpc_url, lo, hi, contract, wallet_topic, direction = args
    topic0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef"
    direction, topic_index = ("deposit", 1) if direction == "in" else ("withdrawal", 2)
    topics = [topic0, wallet_topic if topic_index == 1 else None, wallet_topic if topic_index == 2 else None]
    try:
        response = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [{
                "fromBlock": hex(lo), "toBlock": hex(hi), "address": contract, "topics": topics,
            }]},
            timeout=12,
        )
        payload = response.json()
        logs = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(logs, list):
            return []
        out: list[dict[str, Any]] = []
        for log in logs:
            if not isinstance(log, dict):
                continue
            try:
                raw_amount = int(str(log.get("data") or "0x0"), 16)
            except (TypeError, ValueError):
                continue
            out.append({
                "direction": direction,
                "amount_usd": round(raw_amount / 1_000_000, 6),
                "tx_hash": log.get("transactionHash"),
                "transaction_hash": log.get("transactionHash"),
                "block_number": int(str(log.get("blockNumber") or "0x0"), 16),
                "log_index": int(str(log.get("logIndex") or "0x0"), 16),
                "token_contract": contract,
            })
        return out
    except Exception:
        return []


def _funding_snapshot_sync() -> dict[str, Any]:
    """Read the same official funding history used by Polymarket portfolio.

    The portfolio History tab is backed by Data API v2 activity with
    ``exclude_deposits_withdrawals=false``.  Polygon ERC-20 transfer logs are
    deliberately not used here because they include bridge/protocol internal
    transfers and produce misleading micro entries.
    """
    now = time.time()
    cached = _FUNDING_CACHE.get("value")
    wallet = _deposit_wallet_address()
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet or ""):
        value = {
            "available": False, "source": "wallet_unconfigured", "wallet": None,
            "records": [], "deposits": [], "withdrawals": [], "total": 0,
            "loading": False, "stale": False, "updated_at": now,
            "error": "wallet_unconfigured",
        }
        _FUNDING_CACHE.update(ts=now, value=value)
        return value

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    endpoint = "https://data-api.polymarket.com/v2/activity"
    for activity_type, direction in (("DEPOSIT", "deposit"), ("WITHDRAWAL", "withdrawal")):
        cursor: Optional[str] = None
        for _ in range(20):
            params: dict[str, Any] = {
                "user": wallet,
                "limit": 500,
                "type": activity_type,
                "exclude_deposits_withdrawals": "false",
                "sort_by": "TIMESTAMP",
                "sort_direction": "DESC",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                response = requests.get(endpoint, params=params, timeout=_POLY_READ_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("funding response is not an object")
                batch = payload.get("data")
                if not isinstance(batch, list):
                    batch = []
                for item in batch:
                    if not isinstance(item, dict) or str(item.get("type") or "").upper() != activity_type:
                        continue
                    try:
                        amount = float(item.get("usdc_size"))
                    except (TypeError, ValueError):
                        try:
                            amount = float(item.get("size") or 0.0)
                        except (TypeError, ValueError):
                            continue
                    if not math.isfinite(amount) or amount < 0:
                        continue
                    try:
                        timestamp = float(item.get("timestamp")) if item.get("timestamp") is not None else None
                    except (TypeError, ValueError):
                        timestamp = None
                    tx_hash = str(item.get("transaction_hash") or "").strip() or None
                    records.append({
                        "direction": direction,
                        "type": activity_type,
                        "amount_usd": round(amount, 6),
                        "asset": "pUSD",
                        "token_symbol": "pUSD",
                        "tx_hash": tx_hash,
                        "transaction_hash": tx_hash,
                        "timestamp": timestamp,
                        "status": "confirmed",
                        "confirmed": True,
                        "wallet": item.get("proxy_wallet") or wallet,
                        "source": "polymarket_data_api_v2_activity",
                        "provider_type": activity_type,
                    })
                pagination = payload.get("pagination")
                pagination = pagination if isinstance(pagination, dict) else {}
                next_cursor = pagination.get("next_cursor")
                if not pagination.get("has_more") or not next_cursor or not batch:
                    break
                cursor = str(next_cursor)
            except Exception as exc:
                errors.append(f"{activity_type}: {exc}")
                break

    if records:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in sorted(records, key=lambda item: float(item.get("timestamp") or 0.0), reverse=True):
            key = f"{row.get('transaction_hash') or ''}:{row.get('direction')}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        value = {
            "available": True,
            "source": "polymarket_data_api_v2_activity",
            "wallet": wallet,
            "records": unique,
            "deposits": [row for row in unique if row.get("direction") == "deposit"],
            "withdrawals": [row for row in unique if row.get("direction") == "withdrawal"],
            "total": len(unique),
            "updated_at": now,
            "data_as_of": max((float(row.get("timestamp") or 0.0) for row in unique), default=None),
            "stale": False,
            "loading": False,
            "error": "; ".join(errors) if errors else None,
            "message": None,
            "balance_usd": _state.get("balance_pusd"),
            "portfolio_value_usd": None,
        }
        _FUNDING_CACHE.update(ts=now, value=value)
        return value

    # Keep only a previously successful official snapshot during an upstream
    # outage. Never fall back to the old ERC-20 transfer snapshot here.
    if isinstance(cached, dict) and cached.get("source") == "polymarket_data_api_v2_activity" and cached.get("records"):
        value = {**cached, "stale": True, "loading": False, "last_attempt_ts": now,
                 "error": "; ".join(errors) or "official funding activity returned no rows"}
        _FUNDING_CACHE.update(ts=now, value=value)
        return value
    value = {
        "available": False,
        "source": "polymarket_data_api_v2_activity",
        "wallet": wallet,
        "records": [], "deposits": [], "withdrawals": [], "total": 0,
        "updated_at": now, "stale": True, "loading": False,
        "last_attempt_ts": now,
        "error": "; ".join(errors) or "official funding activity returned no rows",
    }
    _FUNDING_CACHE.update(ts=now, value=value)
    return value

def _verified_funding_seed(wallet: str) -> Optional[dict[str, Any]]:
    """Load the last verified wallet transfer snapshot without network I/O."""
    try:
        payload = json.loads((ROOT / "funding_seed.json").read_text(encoding="utf-8"))
        if str(payload.get("wallet") or "").lower() != wallet.lower():
            return None
        contracts = {
            "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb": "pUSD",
            "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC.e",
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
        }
        out: list[dict[str, Any]] = []
        for item in payload.get("records", []):
            if not isinstance(item, dict):
                continue
            direction = str(item.get("direction") or "").lower()
            if direction not in ("deposit", "withdrawal"):
                continue
            raw = item.get("rawContract") or {}
            contract = str(raw.get("address") or item.get("token_contract") or "").lower()
            if contract not in contracts:
                continue
            try:
                amount = float(item.get("value")) if item.get("value") is not None else float(item.get("amount_usd") or 0.0)
            except (TypeError, ValueError):
                continue
            block_raw = str(item.get("blockNum") or item.get("block_number") or "0x0")
            try:
                block_number = int(block_raw, 16) if block_raw.lower().startswith("0x") else int(block_raw)
            except (TypeError, ValueError):
                block_number = int(item.get("block_number") or 0)
            timestamp = item.get("timestamp")
            if timestamp is None:
                metadata = item.get("metadata") or {}
                raw_timestamp = metadata.get("blockTimestamp") if isinstance(metadata, dict) else None
                if raw_timestamp:
                    try:
                        timestamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00")).timestamp()
                    except (TypeError, ValueError):
                        timestamp = None
            out.append({
                "direction": direction,
                "amount_usd": round(max(0.0, amount), 6),
                "asset": item.get("asset") or item.get("token_symbol") or contracts[contract],
                "token_symbol": item.get("asset") or item.get("token_symbol") or contracts[contract],
                "tx_hash": item.get("hash") or item.get("tx_hash"),
                "transaction_hash": item.get("hash") or item.get("transaction_hash") or item.get("tx_hash"),
                "block_number": block_number,
                "timestamp": timestamp,
                "from": item.get("from"), "to": item.get("to"),
                "token_contract": contract,
                "status": "confirmed", "confirmed": True,
                "source": "verified_chain_snapshot",
                "unique_id": item.get("uniqueId") or f"{item.get('hash') or item.get('tx_hash')}:{direction}:{block_number}:{contract}",
            })
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in sorted(out, key=lambda item: (float(item.get("timestamp") or 0.0), int(item.get("block_number") or 0)), reverse=True):
            key = str(row.get("unique_id"))
            if key in seen:
                continue
            seen.add(key)
            row.pop("unique_id", None)
            unique.append(row)
        fetched_at = float(payload.get("fetched_at") or 0.0) or None
        return {
            "available": bool(unique),
            "source": "verified_chain_snapshot",
            "wallet": wallet,
            "records": unique[:500],
            "deposits": [row for row in unique if row.get("direction") == "deposit"][:250],
            "withdrawals": [row for row in unique if row.get("direction") == "withdrawal"][:250],
            "updated_at": fetched_at,
            "snapshot_at": fetched_at,
            "stale": True,
            "loading": False,
            "message": "实时索引暂不可用，显示已核验链上快照",
            "balance_usd": _state.get("balance_pusd"),
            "portfolio_value_usd": None,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None

def _funding_snapshot() -> dict[str, Any]:
    """Return cached funding history immediately and refresh it in background."""
    global _FUNDING_SCAN_ACTIVE
    now = time.time()
    cached = _FUNDING_CACHE.get("value")
    if cached is not None and now - float(_FUNDING_CACHE.get("ts", 0.0)) < 15.0:
        return dict(cached)
    if _FUNDING_SCAN_LOCK.acquire(blocking=False):
        if not _FUNDING_SCAN_ACTIVE:
            _FUNDING_SCAN_ACTIVE = True
            def refresh() -> None:
                global _FUNDING_SCAN_ACTIVE
                try:
                    _funding_snapshot_sync()
                finally:
                    _FUNDING_SCAN_ACTIVE = False
                    _FUNDING_SCAN_LOCK.release()
            threading.Thread(target=refresh, name="funding-history-refresh", daemon=True).start()
        else:
            _FUNDING_SCAN_LOCK.release()
    if cached is not None:
        # A verified snapshot is usable immediately even while a later live
        # refresh is rate-limited. Do not make the UI poll forever.
        return {**dict(cached), "loading": False, "stale": bool(cached.get("stale", True)), "last_attempt_ts": now}
    return {
        "available": False, "source": "polygon_transfer_logs", "wallet": _deposit_wallet_address(),
        "records": [], "deposits": [], "withdrawals": [], "loading": True,
        "stale": True, "last_attempt_ts": now,
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
    values = _control_env_values()
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
# The public Data API is eventually consistent after a trade/redeem. Keep the
# last confirmed open value for a short grace period so a transient empty/0
# response never flashes a false zero in the live dashboard.
_POSITION_VALUE_CACHE: dict[str, Any] = {"ts": 0.0, "value": None, "positions": []}
_POSITION_VALUE_GRACE_SEC = 15.0

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
    "balance_usdce": None,    # on-chain bridged USDC.e awaiting activation
    "positions": [],          # data-api positions for deposit wallet
    "value_usd": None,        # active live position market value
    "value_source": None,     # data_api_v2 or live_ledger_entry_cost_fallback
    "polymarket_profile": None,
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

# The OpenClaw heartbeat publisher owns the eight workflow roles below.  The
# weather/sports paper feeds are separate workers and intentionally do not
# publish OpenClaw role heartbeats.  Keep the two sets distinct so a missing
# optional feed cannot invalidate an otherwise healthy heartbeat and make the
# UI fall back to an all-zero queue snapshot.
OPENCLAW_AGENT_IDS = ("desk", "search", "whale", "shill", "risk", "sniper", "exit", "rug")
OPENCLAW_WORKFLOW_AGENT_IDS = ("desk", "search", "whale", "shill", "risk", "sniper", "exit", "rug")


def _openclaw_scope_defaults() -> tuple[dict[str, str], dict[str, Any]]:
    """Build market-data and execution scopes independently."""
    env = _control_env_values()
    try:
        process_mode = (ROOT / "bot.mode").read_text(encoding="utf-8").strip().lower()
    except OSError:
        process_mode = "paper"
    data_scope = {"BTC": "live" if process_mode in ("live", "paper") else "paper"}
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

AGENTS_STATUS_PATH = ROOT / "agents" / "out" / "agent_status.json"
_SLOW_LOOP_ALIAS = {"review": "desk"}  # review work surfaces under the desk card
_SLOW_LOOP_MAX_AGE_SEC = 1200          # timer cadence 10min + margin


def _slow_loop_overlay(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Overlay REAL per-role slow-loop status (agents/run.py) onto the base
    snapshot.  Roles the slow loop actually ran show their true stage and
    timings; everything else keeps the base entry.  Read-only and failure-
    silent: a missing or stale file changes nothing."""
    try:
        if not AGENTS_STATUS_PATH.exists():
            return snapshot
        if time.time() - AGENTS_STATUS_PATH.stat().st_mtime > _SLOW_LOOP_MAX_AGE_SEC:
            return snapshot
        payload = json.loads(AGENTS_STATUS_PATH.read_text(encoding="utf-8"))
        for role, info in (payload.get("roles") or {}).items():
            if not isinstance(info, dict) or info.get("kind") != "agent":
                continue
            target = _SLOW_LOOP_ALIAS.get(role, role)
            entry = snapshot.get(target)
            if entry is None:
                continue
            slow = entry.setdefault("slow_loop", {})
            slow[role] = {k: info.get(k) for k in (
                "status", "workflow_stage", "duration_ms", "heartbeat_ts",
                "n_reviews", "n_degraded", "whale_trades", "detail") if k in info}
            stage = info.get("workflow_stage")
            if stage and stage != "-" and role == target:
                entry["workflow_stage"] = f"slow-loop:{stage}"
            if info.get("status") == "error" and role == target:
                entry["status"] = "error"
                entry["detail"] = info.get("detail") or entry.get("detail")
    except (OSError, ValueError, TypeError):
        pass
    return snapshot


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
                if instance == expected and pid_alive and isinstance(roles, dict) and all(role in roles for role in OPENCLAW_WORKFLOW_AGENT_IDS):
                    default_scope, default_execution = _openclaw_scope_defaults()
                    payload_models = payload.get("model_calls") or payload.get("models") or {}
                    normalized: dict[str, Any] = {}
                    for role in OPENCLAW_AGENT_IDS:
                        item = dict(roles.get(role) or {})
                        # Weather and sports are isolated Paper producers, not
                        # OpenClaw workflow roles.  Add a truthful synthetic
                        # status for their cards while retaining the real
                        # queue/heartbeat values for the eight roles above.
                        if role not in roles:
                            meta = _state.get(f"{role}_meta") or {}
                            running_feed = bool(meta.get("running"))
                            feed_queue = meta.get("queue_depth")
                            if feed_queue is None:
                                feed_queue = meta.get("orders_new") or 0
                            item = {
                                "status": "running" if running_feed else "offline",
                                "heartbeat_ts": meta.get("heartbeat_ts"),
                                "queue_depth": int(feed_queue or 0),
                                "market": role.upper(),
                                "mode": "paper",
                                "detail": "独立 Paper 数据服务；无 OpenClaw 下单权限",
                                "last_decision_id": 0,
                                "last_order_id": 0,
                            }
                        item.setdefault("data_scope", dict(default_scope))
                        if isinstance(item.get("data_scope"), str):
                            item["data_scope"] = dict(default_scope)
                        item.setdefault("execution_scope", default_execution.get(role, "read_only"))
                        item.setdefault("model_calls", payload_models if isinstance(payload_models, dict) else {})
                        normalized[role] = item
                    return _slow_loop_overlay(normalized)
    except (OSError, ValueError, TypeError):
        pass
    running = bool(_state.get("bot_running"))
    paper_mode = _state.get("bot_mode") != "live"
    default_scope, default_execution = _openclaw_scope_defaults()

    # Fetch lifetime last IDs for fallback when today_counts is unavailable
    last_decision_id = 0
    last_order_id = 0
    try:
        import sqlite3
        conn = db()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(id) FROM decisions")
        row = cursor.fetchone()
        last_decision_id = int(row[0] or 0)
        cursor.execute("SELECT MAX(id) FROM orders")
        row = cursor.fetchone()
        last_order_id = int(row[0] or 0)
        conn.close()
    except Exception:
        pass

    result: dict[str, Any] = {}
    for agent in OPENCLAW_AGENT_IDS:
        # The local Paper publisher represents all eight roles.  A role with
        # an empty queue is healthy and waiting, so expose it as running;
        # Paper mode itself remains the permission boundary for execution.
        status = "running" if running else "offline"
        result[agent] = {"status": status, "heartbeat_ts": time.time() if running else None, "queue_depth": 0, "market": "BTC", "mode": "paper" if paper_mode else "live", "detail": "Paper service; no OpenClaw signing permission" if paper_mode else "driven by strategy service", "last_decision_id": last_decision_id, "last_order_id": last_order_id}
        result[agent].update({"data_scope": dict(default_scope), "execution_scope": default_execution.get(agent, "read_only"), "model_calls": {"primary": "waiting", "secondary": "waiting"}})
    return _slow_loop_overlay(result)

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
# WEATHER/SPORTS are produced by independent Paper workers. The dashboard
# consumes atomic snapshots and never starts a second trading/scanning loop.

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
    # Dashboard-only views keep historical products in the underlying ledger.
    # Trading workers continue to use bot.store and the original tables.
    for table in ("orders", "decisions"):
        c.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM main.{table} WHERE UPPER(COALESCE(asset, ''))='BTC'")
    return c


def _row(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


def local_day_start_ts(now: Optional[float] = None) -> float:
    """Start of the current Beijing trading day, shared with bot.store."""
    local_now = datetime.fromtimestamp(now if now is not None else time.time(), TRADING_TIMEZONE)
    return datetime.combine(local_now.date(), dt_time.min, tzinfo=TRADING_TIMEZONE).timestamp()


def recent_decisions(limit: int = 50, since_id: int = 0, lane: str = "all") -> list[dict]:
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and lane != "live" and not (_service_status_snapshot().get("BTC") or {}).get("live_enabled"):
        return _p3.decisions(limit, since_id)
    if not DB_PATH.exists():
        return []
    with db() as c:
        # BTC/ETH emit many SKIP rows per cycle. A single global LIMIT hid the
        # independent WEATHER/SPORTS Paper activity from the realtime panel.
        # Keep incremental consumers lossless; for the dashboard preview use a
        # bounded newest-per-asset window and merge it by event id.
        lane_where = ""
        lane_params: tuple[Any, ...] = ()
        if lane in ("paper", "live"):
            lane_where = " AND dry_run=?"
            lane_params = (1 if lane == "paper" else 0,)
        if since_id:
            rows = c.execute(
                "SELECT id, ts, asset, market_slug, side, t_remaining, ask_price, ask_size, "
                "action, reason, dry_run FROM decisions WHERE id > ?" + lane_where + " "
                "ORDER BY id DESC LIMIT ?",
                (since_id, *lane_params, limit),
            ).fetchall()
            return [_row(r) for r in rows]
        assets = ("BTC",)
        per_asset = max(4, min(30, math.ceil(max(1, int(limit)) / len(assets))))
        rows: list[dict] = []
        for asset in assets:
            asset_rows = c.execute(
                "SELECT id, ts, asset, market_slug, side, t_remaining, ask_price, ask_size, "
                "action, reason, dry_run FROM decisions WHERE asset=?" + lane_where + " "
                "ORDER BY id DESC LIMIT ?",
                (asset, *lane_params, per_asset),
            ).fetchall()
            rows.extend(_row(r) for r in asset_rows)
        rows.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
        return rows[:max(1, int(limit))]


def recent_orders(limit: int = 50, since_id: int = 0, *, offset: int = 0,
                  lane: str = "all", connection: Optional[sqlite3.Connection] = None) -> list[dict]:
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and lane != "live" and not (_service_status_snapshot().get("BTC") or {}).get("live_enabled"):
        return [row for row in _p3.orders_page(offset, limit)["rows"] if row["id"] > since_id]
    if lane not in ("all", "paper", "live"):
        raise ValueError("invalid order lane")
    if connection is None:
        with closing(db()) as c:
            btc_rows = recent_orders(limit, since_id, offset=offset, lane=lane, connection=c)
        if lane != "live":
            sol_rows = _sol5m_orders_page(0, max(1, int(limit)), "paper")["rows"]
            return sorted(btc_rows + sol_rows, key=lambda row: (float(row.get("ts") or 0), int(row.get("id") or 0)), reverse=True)[:max(1, int(limit))]
        return btc_rows
    if not DB_PATH.exists():
        return []
    # The history route passes its read transaction so COUNT and rows use the
    # same SQLite snapshot. Reuse the established result/exit projection.
    with connection as c:
        lane_filter = "" if lane == "all" else " AND o.dry_run=?"
        params = [since_id]
        if lane != "all":
            params.append(1 if lane == "paper" else 0)
        params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
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
            f"WHERE o.id > ?{lane_filter} ORDER BY o.id DESC LIMIT ? OFFSET ?",
            params,
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


def _orders_total(connection: Optional[sqlite3.Connection] = None, lane: str = "all") -> int:
    """Count ledger rows, including exits/rejections, never the 30-row window."""
    if not DB_PATH.exists():
        return 0
    if lane not in ("all", "paper", "live"):
        raise ValueError("invalid order lane")
    if connection is None:
        with closing(db()) as c:
            return _orders_total(c, lane)
    where = "" if lane == "all" else " WHERE dry_run=?"
    params = () if lane == "all" else (1 if lane == "paper" else 0,)
    return int(connection.execute("SELECT COUNT(*) FROM orders" + where, params).fetchone()[0])


def _decisions_total(connection: Optional[sqlite3.Connection] = None, lane: str = "all") -> int:
    """Count all decision rows without materializing the realtime window."""
    if not DB_PATH.exists():
        return 0
    if lane not in ("all", "paper", "live"):
        raise ValueError("invalid decision lane")
    if connection is None:
        with closing(db()) as c:
            return _decisions_total(c, lane)
    where = "" if lane == "all" else " WHERE dry_run=?"
    params = () if lane == "all" else (1 if lane == "paper" else 0,)
    return int(connection.execute("SELECT COUNT(*) FROM decisions" + where, params).fetchone()[0])


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


def _today_counts() -> dict[str, Any]:
    """Return Beijing-trading-day cumulative decision and order counts.

    Resets at 00:00 Beijing time (UTC+8). Falls back to zero when the DB is
    unavailable; the frontend degrades to lifetime last_*_id when this returns None.
    """
    try:
        # Use the same Beijing trading day as the worker risk gate and daily PnL.
        since_ts = int(local_day_start_ts())

        import sqlite3
        conn = db()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM decisions WHERE ts >= ?", (since_ts,))
        decisions = int(cursor.fetchone()[0] or 0)

        cursor.execute("SELECT COUNT(*) FROM orders WHERE ts >= ?", (since_ts,))
        orders = int(cursor.fetchone()[0] or 0)

        conn.close()

        return {"decisions": decisions, "orders": orders, "since": since_ts}
    except Exception:
        return {"decisions": 0, "orders": 0, "since": 0}


def _lane_counts() -> dict[str, dict[str, int]]:
    """Return Beijing-day and lifetime counts split by Paper/live lane."""
    result: dict[str, dict[str, int]] = {}
    if not DB_PATH.exists():
        return {"paper": {"decisions": 0, "orders": 0}, "live": {"decisions": 0, "orders": 0}}
    since_ts = int(local_day_start_ts())
    try:
        with db() as c:
            for lane, dry_run in (("paper", 1), ("live", 0)):
                result[lane] = {
                    "decisions": int(c.execute("SELECT COUNT(*) FROM decisions WHERE dry_run=?", (dry_run,)).fetchone()[0] or 0),
                    "orders": int(c.execute("SELECT COUNT(*) FROM orders WHERE dry_run=?", (dry_run,)).fetchone()[0] or 0),
                    "today_decisions": int(c.execute("SELECT COUNT(*) FROM decisions WHERE dry_run=? AND ts>=?", (dry_run, since_ts)).fetchone()[0] or 0),
                    "today_orders": int(c.execute("SELECT COUNT(*) FROM orders WHERE dry_run=? AND ts>=?", (dry_run, since_ts)).fetchone()[0] or 0),
                }
    except Exception:
        return {"paper": {"decisions": 0, "orders": 0}, "live": {"decisions": 0, "orders": 0}}
    return result


def realized_pnl_today() -> dict:
    """Read the same canonical PnL summary used by the bot risk gate.

    Resolution lookups run in the background; the API must remain a local,
    bounded-latency read even when Gamma is slow or unavailable.
    """
    # Select the active ledger; Paper must not read the live wallet ledger.
    return realized_pnl_summary_today(_state.get("bot_mode") != "live")


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


def _normalize_data_api_position(position: dict[str, Any]) -> dict[str, Any]:
    """Normalize Polymarket Data API v2 positions to the dashboard schema.

    Data API v1 used camelCase fields (``size``, ``curPrice``,
    ``currentValue``) while v2 returns snake_case fields and wraps the list
    in ``data``.  Keeping one internal shape prevents the risk snapshot and
    position modal from silently treating live positions as empty.
    """
    if not isinstance(position, dict):
        return {}
    row = dict(position)

    def first(*keys: str):
        for key in keys:
            value = position.get(key)
            if value is not None:
                return value
        return None

    size = first("size", "current_size", "currentSize", "total_size", "totalSize")
    price = first("curPrice", "current_price", "currentPrice")
    value = first("currentValue", "current_value", "currentValueUsd")
    token_id = first("tokenId", "token_id")
    condition_id = first("conditionId", "condition_id")
    if size is not None:
        row["size"] = size
    if price is not None:
        row["curPrice"] = price
    if value is None and size is not None and price is not None:
        try:
            value = float(size) * float(price)
        except (TypeError, ValueError):
            value = None
    if value is not None:
        row["currentValue"] = value
    if token_id is not None:
        row["tokenId"] = token_id
    if condition_id is not None:
        row["conditionId"] = condition_id
    row.setdefault("asset", "BTC" if "btc" in str(first("slug", "title") or "").lower() else "")
    return row


def _normalize_ledger_position(position: dict[str, Any]) -> dict[str, Any]:
    """Expose a matched local live lot when Data API v2 is briefly empty."""
    if not isinstance(position, dict):
        return {}
    row = dict(position)
    row.setdefault("asset", str(position.get("asset") or "BTC").upper())
    row.setdefault("conditionId", position.get("condition_id"))
    row.setdefault("tokenId", position.get("token_id"))
    row.setdefault("slug", position.get("market_slug"))
    row.setdefault("size", position.get("size"))
    row.setdefault("curPrice", position.get("price"))
    row.setdefault("currentValue", position.get("notional_usd"))
    return row


def _account_positions_snapshot() -> dict[str, Any]:
    """One immutable display snapshot, independent of worker mode/ledger."""
    return _state.get("portfolio_positions") or {
        "available": False, "stale": False, "source": "data_api_v2_positions",
        "updated_at": None, "error": None, "positions": [], "settled_positions": [],
        "pending_count": None, "redeemable_count": None,
        "pending_value_usd": None, "redeemable_value_usd": None, "total_value_usd": None,
    }


_POSITION_ACTIVITY_CACHE: dict[str, Any] = {"ts": 0.0, "wallet": "", "value": None}


def _activity_position_fallback(wallet: str) -> dict[str, Any] | None:
    """Reconstruct a short-lived holding while the v2 position index catches up.

    The activity feed is public and read-only.  It is deliberately used only
    when the authoritative positions endpoint returns an empty page; the
    result is marked stale so the UI never presents an inferred mark as a
    fresh chain snapshot.
    """
    now = time.time()
    if (_POSITION_ACTIVITY_CACHE.get("wallet") == wallet
            and now - float(_POSITION_ACTIVITY_CACHE.get("ts") or 0.0) < 10.0):
        return _POSITION_ACTIVITY_CACHE.get("value")
    try:
        response = requests.get(
            "https://data-api.polymarket.com/v2/activity",
            params={"user": wallet, "limit": 500}, timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        events = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(events, list):
            return None
    except Exception:
        _POSITION_ACTIVITY_CACHE.update(ts=now, wallet=wallet, value=None)
        return None
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for event in reversed([row for row in events if isinstance(row, dict)]):
        token = str(event.get("token_id") or "")
        condition = str(event.get("condition_id") or "")
        if not token or not condition:
            continue
        key = (condition.lower(), token)
        item = groups.setdefault(key, {
            "condition_id": condition, "token_id": token, "size": 0.0,
            "cost": 0.0, "last_price": 0.0, "last_ts": 0.0,
            "last_event": "", "template": event,
        })
        try:
            size = max(0.0, float(event.get("size") or 0.0))
            amount = max(0.0, float(event.get("usdc_size") or 0.0))
            price = max(0.0, float(event.get("price") or 0.0))
            ts = float(event.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        kind = str(event.get("type") or "").upper()
        side = str(event.get("side") or "").upper()
        if kind == "TRADE" and side == "BUY":
            item["size"] += size
            item["cost"] += amount or size * price
        elif kind == "TRADE" and side == "SELL":
            item["size"] = max(0.0, item["size"] - size)
        elif kind in ("REDEEM", "MERGE"):
            item["size"] = 0.0
        if ts >= item["last_ts"]:
            item.update(last_price=price, last_ts=ts, last_event=f"{kind}:{side}", template=event)
    rows: list[dict[str, Any]] = []
    for item in groups.values():
        size = float(item["size"])
        if size <= 0.000001:
            continue
        template = item["template"]
        price = float(item["last_price"] or 0.0)
        avg = float(item["cost"] / size) if item["cost"] > 0 else price
        # Match the official portfolio page's filter_amount=0.1. Activity
        # contains historical dust left by partial fills; publishing that
        # dust as current holdings would turn an authoritative empty result
        # into dozens of phantom positions.
        mark = price if price > 0 else avg
        if size * mark < 0.1:
            continue
        rows.append({
            "proxy_wallet": wallet, "token_id": item["token_id"],
            "condition_id": item["condition_id"], "current_size": size,
            "avg_price": avg, "current_price": price,
            "current_value": size * price, "total_size": size,
            "status": "OPEN", "redeemable": False, "mergeable": False,
            "title": template.get("title"), "slug": template.get("slug"),
            "event_slug": template.get("event_slug"), "outcome": template.get("outcome"),
            "outcome_index": template.get("outcome_index"),
            "last_event_at": item["last_ts"],
        })
    if not rows:
        _POSITION_ACTIVITY_CACHE.update(ts=now, wallet=wallet, value=None)
        return None
    summary = summarize_positions(rows)
    summary.update({
        "available": True, "stale": True,
        "source": "data_api_v2_activity_fallback",
        "wallet": wallet, "updated_at": now,
        "sync_status": "indexing",
        "error": "positions index temporarily empty; reconstructed from activity",
    })
    _POSITION_ACTIVITY_CACHE.update(ts=now, wallet=wallet, value=summary)
    return summary


def _should_hold_last_position_snapshot(wallet: str, prior: dict[str, Any]) -> bool:
    """Keep a recent good snapshot across a transient empty index response."""
    if not prior.get("available") or not prior.get("total_count"):
        return False
    updated = float(prior.get("updated_at") or 0.0)
    if updated <= 0 or time.time() - updated > 60.0:
        return False
    try:
        response = requests.get(
            "https://data-api.polymarket.com/v2/activity",
            params={"user": wallet, "limit": 100}, timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        events = payload.get("data", []) if isinstance(payload, dict) else []
        latest: dict[tuple[str, str], tuple[float, str]] = {}
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            key = (str(event.get("condition_id") or "").lower(), str(event.get("token_id") or ""))
            if not key[0] or not key[1]:
                continue
            ts = float(event.get("timestamp") or 0.0)
            if ts >= latest.get(key, (0.0, ""))[0]:
                latest[key] = (ts, f"{str(event.get('type') or '').upper()}:{str(event.get('side') or '').upper()}")
        prior_rows = prior.get("positions", []) + prior.get("settled_positions", [])
        keys = {(str(row.get("condition_id") or row.get("conditionId") or "").lower(), str(row.get("token_id") or row.get("tokenId") or "")) for row in prior_rows}
        terminal = {"TRADE:SELL", "REDEEM:", "MERGE:"}
        # If the latest activity for every prior token is terminal, the empty
        # response is a real settlement and should be published immediately.
        known = [latest[key][1] for key in keys if key in latest]
        if keys and len(known) == len(keys) and all(value in terminal for value in known):
            return False
    except Exception:
        # A failed activity check is itself an upstream outage; keep the last
        # known chain snapshot for this short grace period.
        pass
    return True


async def poll_positions_loop():
    while True:
        wallet = _deposit_wallet_address()
        try:
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet or ""):
                raise ValueError("wallet_unconfigured")
            snapshot = await asyncio.to_thread(fetch_portfolio_positions, wallet, timeout=5)
            if snapshot.get("total_count", 0) == 0:
                prior = _account_positions_snapshot()
                fallback = await asyncio.to_thread(_activity_position_fallback, wallet)
                if fallback is not None:
                    snapshot = fallback
                elif _should_hold_last_position_snapshot(wallet, prior):
                    snapshot = {**prior, "stale": True, "sync_status": "indexing",
                                "source": "data_api_v2_positions+last_good",
                                "last_empty_ts": time.time(),
                                "error": "positions index temporarily empty; retained last good snapshot"}
            # Publish rows, subtotals and counts together. Do not substitute
            # local entry costs when the indexer has no account holdings.
            _state["portfolio_positions"] = snapshot
            _state["positions"] = snapshot["positions"] + snapshot["settled_positions"]
            _state["value_usd"] = snapshot["total_value_usd"]
            _state["value_source"] = snapshot["source"]
            _state["errors"].pop("positions", None)
            _state["errors"].pop("value", None)
        except Exception as exc:
            prior = _account_positions_snapshot()
            snapshot = {**prior, "stale": bool(prior.get("available")),
                        "sync_status": "unavailable" if not prior.get("available") else "indexing",
                        "error": str(exc), "last_attempt_ts": time.time()}
            _state["portfolio_positions"] = snapshot
            _state["errors"]["positions"] = str(exc)
        await asyncio.sleep(2.0)


async def poll_balance_loop():
    """Read pUSD and bridged USDC.e balances of the configured deposit wallet.

    The Polymarket ``Activate Funds`` prompt is backed by the bridged USDC.e
    balance until the wallet has wrapped it into pUSD.  Reading that balance
    is safe and lets the dashboard include the pending amount in the portfolio
    total; it does not submit an approval or wrap transaction.
    """
    PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
    USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    SELECTOR = "0x70a08231"
    deposit_wallet = _deposit_wallet_address()
    while True:
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", deposit_wallet):
            _state["balance_pusd"] = None
            _state["balance_usdce"] = None
            _state["errors"].pop("balance", None)
            await asyncio.sleep(10.0)
            continue
        try:
            data = SELECTOR + deposit_wallet.lower().replace("0x", "").rjust(64, "0")
            def read_token(token: str) -> float:
                response = requests.post(
                    cfg.polygon_rpc,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_call",
                        "params": [{"to": token, "data": data}, "latest"],
                    },
                    timeout=5,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("error"):
                    raise RuntimeError(f"RPC error: {payload['error']}")
                raw = payload.get("result")
                if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", raw):
                    raise ValueError("RPC balance response missing 32-byte result")
                value = int(raw, 16) / 1e6
                if not math.isfinite(value) or value < 0:
                    raise ValueError("RPC balance returned invalid value")
                return value

            _state["balance_pusd"] = read_token(PUSD)
            _state["balance_usdce"] = read_token(USDCE)
            _state["errors"].pop("balance", None)
            _state["errors"].pop("balance_usdce", None)
        except Exception as e:
            _state["balance_pusd"] = None
            _state["balance_usdce"] = None
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
    today = datetime.now(TRADING_TIMEZONE).date()
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
    """Consume the weather worker's persisted Paper state without producing orders."""
    while True:
        try:
            snapshot = await asyncio.to_thread(read_paper_feed_snapshot, "WEATHER")
            _state["weather"] = snapshot.get("rows") or []
            _state["weather_meta"] = snapshot
            if snapshot.get("error"):
                _state["errors"]["weather"] = str(snapshot["error"])[:500]
            else:
                _state["errors"].pop("weather", None)
        except Exception as exc:
            _state["weather"] = []
            _state["errors"]["weather"] = str(exc)
        await asyncio.sleep(3.0)


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
    """Read the sole sports Paper producer instead of a second in-memory scanner."""
    while True:
        try:
            snapshot = await asyncio.to_thread(read_paper_feed_snapshot, "SPORTS")
            _state["sports"] = snapshot.get("rows") or []
            _state["sports_meta"] = snapshot
            if snapshot.get("error"):
                _state["errors"]["sports"] = str(snapshot["error"])[:500]
            else:
                _state["errors"].pop("sports", None)
        except Exception as exc:
            _state["sports"] = []
            _state["sports_meta"] = {"enabled": bool(getattr(cfg, "sports_enabled", False)), "mode": "paper", "status": "error", "paper_only": True, "live_orders": False}
            _state["errors"]["sports"] = str(exc)
        await asyncio.sleep(3.0)


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


_RISK_WORKER_FIELDS = {
    'max_daily_loss_fraction': 'MAX_DAILY_LOSS_FRACTION',
    'max_daily_realized_profit_fraction': 'MAX_DAILY_REALIZED_PROFIT_FRACTION',
    'max_daily_realized_profit_usd': 'MAX_DAILY_REALIZED_PROFIT_USD',
    'paper_equity_usd': 'PAPER_EQUITY_USD',
    'min_entry_price': 'MIN_ENTRY_PRICE',
    'max_entry_price': 'MAX_ENTRY_PRICE',
    'seconds_before_close': 'SECONDS_BEFORE_CLOSE',
    'min_t_remaining_sec': 'MIN_T_REMAINING_SEC',
    'reversal_exit_window_sec': 'REVERSAL_EXIT_WINDOW_SEC',
    'reversal_held_bid_drawdown': 'REVERSAL_HELD_BID_DRAWDOWN',
    'confirm_checks': 'CONFIRM_CHECKS',
    'reversal_confirm_checks': 'REVERSAL_CONFIRM_CHECKS',
    'order_risk_fraction': 'ORDER_RISK_FRACTION',
    'max_open_positions': 'MAX_OPEN_POSITIONS',
    'sell_fok_slippage_ticks': 'SELL_FOK_SLIPPAGE_TICKS',
    'sell_exit_max_depth_ticks': 'SELL_EXIT_MAX_DEPTH_TICKS',
    'sell_exit_max_depth_levels': 'SELL_EXIT_MAX_DEPTH_LEVELS',
}
# Execution controls are kept separate from the risk thresholds above so the
# dashboard can persist maker/taker and exit policy without exposing secrets.
_EXECUTION_WORKER_FIELDS = {
    'entry_order_mode': 'ENTRY_ORDER_MODE',
    'entry_maker_order_type': 'ENTRY_MAKER_ORDER_TYPE',
    'entry_maker_ttl_sec': 'ENTRY_MAKER_TTL_SEC',
    'entry_maker_post_only': 'ENTRY_MAKER_POST_ONLY',
    'entry_maker_fallback_taker': 'ENTRY_MAKER_FALLBACK_TAKER',
    'profit_exit_enabled': 'PROFIT_EXIT_ENABLED',
    'profit_exit_confirm_checks': 'PROFIT_EXIT_CONFIRM_CHECKS',
    'profit_exit_fraction': 'PROFIT_EXIT_FRACTION',
    'take_profit_enabled': 'TAKE_PROFIT_ENABLED',
    'take_profit_min_gain_fraction': 'TAKE_PROFIT_MIN_GAIN_FRACTION',
    'take_profit_exit_fraction': 'TAKE_PROFIT_EXIT_FRACTION',
    'max_hold_seconds': 'MAX_HOLD_SECONDS',
    'expiry_exit_enabled': 'EXPIRY_EXIT_ENABLED',
    'expiry_exit_seconds': 'EXPIRY_EXIT_SECONDS',
    'expiry_exit_fraction': 'EXPIRY_EXIT_FRACTION',
    'profit_exit_order_mode': 'PROFIT_EXIT_ORDER_MODE',
    'profit_target_fraction': 'PROFIT_TARGET_FRACTION',
    'profit_target_ticks': 'PROFIT_TARGET_TICKS',
    'profit_maker_order_type': 'PROFIT_MAKER_ORDER_TYPE',
    'profit_maker_ttl_sec': 'PROFIT_MAKER_TTL_SEC',
    'profit_maker_post_only': 'PROFIT_MAKER_POST_ONLY',
    'profit_maker_fallback_taker': 'PROFIT_MAKER_FALLBACK_TAKER',
    'stop_exit_order_mode': 'STOP_EXIT_ORDER_MODE',
    'reversal_exit_order_mode': 'REVERSAL_EXIT_ORDER_MODE',
    'near_close_exit_enabled': 'NEAR_CLOSE_EXIT_ENABLED',
    'near_close_exit_window_sec': 'NEAR_CLOSE_EXIT_WINDOW_SEC',
    'near_close_exit_order_mode': 'NEAR_CLOSE_EXIT_ORDER_MODE',
    'reversal_partial_exit_fraction': 'REVERSAL_PARTIAL_EXIT_FRACTION',
    'reversal_partial_exit_enabled': 'REVERSAL_PARTIAL_EXIT_ENABLED',
    'sell_exit_fak_fallback_enabled': 'SELL_EXIT_FAK_FALLBACK_ENABLED',
    'sell_exit_reconcile_trades': 'SELL_EXIT_RECONCILE_TRADES',
}

_paper_worker_loss_cache = {}

_kelly_flag_cache = {"ts": 0.0}

_risk_settings_lock = asyncio.Lock()

def _risk_env_paths() -> list[Path]:
    """Return every env file consumed by the active Paper worker.

    The polyauto dashboard runs from ``ROOT/.env`` while the restored C
    strategy is selected by a systemd drop-in that points the BTC worker at a
    release-specific ``.env``.  Updating only ROOT therefore made the panel
    show one threshold while the running worker enforced another one.  Read
    the unit's EnvironmentFiles property so future release switches follow
    the active unit automatically.
    """
    paths: list[Path] = [ROOT / ".env"]
    service = _service_status_snapshot().get("BTC") or {}
    if service.get("live_running") or (service.get("live_enabled") and not service.get("paper_running")):
        # The managed Live unit and dashboard consume this release's .env.
        # An optional Paper unit owns a different configuration and ledger.
        return paths
    if True:
        try:
            result = subprocess.run(
                ["systemctl", "show", "--property=EnvironmentFiles", "--value", "polymarket-test-btc-paper.service"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            # EnvironmentFiles is a whitespace-separated list.  A leading
            # '-' means systemd treats a file as optional; strip it before
            # resolving the actual path.
            for raw in result.stdout.split():
                value = raw[1:] if raw.startswith("-") else raw
                if value.endswith(".env"):
                    candidate = Path(value).expanduser()
                    if candidate.is_file():
                        paths.append(candidate)
        except (OSError, subprocess.SubprocessError):
            # ROOT/.env remains the safe fallback; the endpoint will still
            # reject an invalid request before restarting the worker.
            pass
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique

def _update_env_keys(changes: dict[str, str]) -> list[str]:
    """Atomically update dashboard and active-worker env files.

    Every file is backed up beside its original before replacement.  Returning
    the updated paths lets the API expose an auditable confirmation without
    returning any secret values.
    """
    stamp = time.strftime('%Y%m%d-%H%M%S')
    updated: list[str] = []
    for env_path in _risk_env_paths():
        if not env_path.exists():
            continue
        backup = env_path.with_name(env_path.name + f".before-risk.{stamp}")
        text = env_path.read_text(encoding="utf-8")
        backup.write_text(text, encoding="utf-8")
        os.chmod(backup, 0o600)
        lines = text.splitlines()
        seen = set()
        for i, line in enumerate(lines):
            for key, value in changes.items():
                if line.startswith(key + "="):
                    lines[i] = f"{key}={value}"
                    seen.add(key)
        for key, value in changes.items():
            if key not in seen:
                lines.append(f"{key}={value}")
        tmp = env_path.with_name(env_path.name + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(env_path)
        updated.append(str(env_path))
    if not updated:
        raise HTTPException(status_code=500, detail="未找到可写入的 worker 配置文件")
    return updated

def _valid_daily_loss_fraction(value: Any) -> Optional[float]:
    """Zero disables this gate; malformed runtime values must stay unknown."""
    try:
        fraction = float(value)
        return fraction if not isinstance(value, bool) and math.isfinite(fraction) and fraction >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None

def _live_worker_runtime(asset: str = "BTC") -> dict[str, Any]:
    """Report the actual live bot process used by this dashboard instance."""
    paths = (ROOT / "bot_btc.pid", ROOT / "bot.pid") if asset == "BTC" else (ROOT / "bot_eth.pid",)
    for pid_path in paths:
        command = _pid_command_line(pid_path)
        if command and re.search(r"(?:^|\s)--live(?:\s|$)", command) and re.search(r"(?:^|\s)--asset\s+" + re.escape(asset) + r"(?:\s|$)", command):
            try:
                pid = int(pid_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = None
            try:
                if not pid or Path(f"/proc/{pid}/cwd").resolve(strict=True) != ROOT.resolve():
                    continue
            except OSError:
                continue
            result = {"worker_running": True, "worker_service_state": "RUNNING", "worker_pid": pid,
                    "mode": "live", "asset": asset, "command_verified": True}
            manifest_path = Path(os.getenv("LIVE_WORKER_STATE_DIR", str(live_risk_state_file().parent))) / "live-worker-runtime.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (manifest.get("pid") == pid and manifest.get("mode") == "live"
                        and manifest.get("running") is True
                        and Path(manifest.get("release_root") or "/").resolve() == ROOT.resolve()):
                    result.update(effective_config=manifest.get("effective_config"),
                                  configuration_sha256=manifest.get("configuration_sha256"),
                                  configuration_matches_saved=manifest.get("configuration_sha256") == hashlib.sha256((ROOT / ".env").read_bytes()).hexdigest(),
                                  started_at=manifest.get("started_at"),
                                  unit=os.getenv("LIVE_WORKER_SYSTEMD_UNIT"),
                                  daily_loss_limit_source="worker_startup_manifest")
                    actual_cfg = manifest.get("effective_config") or {}
                    result["effective_max_daily_loss_fraction"] = actual_cfg.get("max_daily_loss_fraction")
            except (OSError, ValueError, TypeError):
                pass
            return result
    result = {"worker_running": False, "worker_service_state": "STOPPED", "worker_pid": None,
              "mode": "live", "asset": asset, "command_verified": False}
    try:
        manifest_path = Path(os.getenv("LIVE_WORKER_STATE_DIR", str(live_risk_state_file().parent))) / "live-worker-runtime.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("mode") == "live" and manifest.get("asset") == asset and not manifest.get("running"):
            result.update(last_exit_reason=manifest.get("exit_reason"),
                          last_exit_code=manifest.get("exit_code"), stopped_at=manifest.get("stopped_at"))
    except (OSError, ValueError, TypeError):
        pass
    return result

def _paper_worker_daily_loss(unit: str, root: Path, db_path: Path) -> dict[str, Any]:
    """Read only a verified Paper worker's initial environment, cached for 5s.

    Launchers/systemd must export the threshold before exec: /proc does not
    reliably include variables loaded later by Python dotenv. Missing values
    deliberately stay unknown rather than falling back to a saved setting.
    """
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and unit == "polymarket-test-btc-paper.service":
        return _p3.read_runtime()
    if unit == "polymarket-test-btc-paper.service" and NATIVE_PAPER_DB.exists():
        return _native_paper_worker_runtime()
    key = (unit, str(root), str(db_path))
    now = time.monotonic()
    cached = _paper_worker_loss_cache.get(key)
    if cached and now - cached[0] < 5.0:
        return dict(cached[1])
    result = {"effective_max_daily_loss_fraction": None,
              "daily_loss_limit_source": "unavailable", "worker_running": None,
              "worker_service_state": "UNKNOWN"}
    try:
        service = subprocess.run(
            ["systemctl", "show", unit, "--property=MainPID,ActiveState,WorkingDirectory"],
            capture_output=True, text=True, timeout=1.5, check=True,
        )
        props = dict(line.split("=", 1) for line in service.stdout.splitlines() if "=" in line)
        active = props.get("ActiveState", "")
        if active in {"inactive", "failed"}:
            result.update(worker_running=False, worker_service_state="STOPPED")
        elif active == "active":
            pid = int(props.get("MainPID") or 0)
            if pid <= 1:
                raise ValueError("missing worker")
            proc = Path("/proc") / str(pid)
            expected_root = root.resolve()
            working_dir = Path(props.get("WorkingDirectory") or "/").resolve()
            cwd = (proc / "cwd").resolve(strict=True)
            if (working_dir != expected_root and expected_root not in working_dir.parents
                    or cwd != expected_root and expected_root not in cwd.parents):
                raise ValueError("worker directory mismatch")
            args = (proc / "cmdline").read_bytes().split(b"\0")
            module = args[args.index(b"-m") + 1] if b"-m" in args else b""
            expected_module = b"bot.protection_runner" if "-protection-" in unit else b"bot.main"
            if module != expected_module or any(arg == b"--live" or arg.startswith(b"--live=") for arg in args):
                raise ValueError("worker command mismatch")
            if module == b"bot.main" and (b"--asset" not in args or args[args.index(b"--asset") + 1] != b"BTC"):
                raise ValueError("worker asset mismatch")
            # Retain only these non-secret values; neither raw env nor errors
            # are returned, logged, or cached.
            allowed = {b"TRADES_DB_PATH", b"BTC_LIVE_ENABLED", b"KELLY_SIZING_ENABLED",
                       *[name.encode("ascii") for name in _RISK_WORKER_FIELDS.values()],
                       *[name.encode("ascii") for name in _EXECUTION_WORKER_FIELDS.values()]}
            env = {}
            for entry in (proc / "environ").read_bytes().split(b"\0"):
                name, separator, value = entry.partition(b"=")
                if separator and name in allowed:
                    env[name.decode("ascii")] = value.decode("utf-8")
            if env.get("BTC_LIVE_ENABLED", "").strip().lower() not in {"false", "0", "no", "off"}:
                raise ValueError("paper mode unverified")
            worker_db = Path(env.get("TRADES_DB_PATH") or "/")
            if not worker_db.is_absolute():
                worker_db = cwd / worker_db
            if worker_db.resolve() != db_path.resolve():
                raise ValueError("worker ledger mismatch")
            worker_config = {}
            for field, name in _RISK_WORKER_FIELDS.items():
                number = _valid_daily_loss_fraction(env.get(name))
                if number is not None:
                    worker_config[field] = number
            for field, name in {**_RISK_WORKER_FIELDS, **_EXECUTION_WORKER_FIELDS}.items():
                raw = env.get(name)
                if raw is None:
                    continue
                if (field.endswith("_enabled") or field.endswith("_post_only")
                        or field.endswith("_fallback_taker") or field.endswith("_reconcile_trades")):
                    worker_config[field] = raw.strip().lower() in {"true", "1", "yes", "on"}
                elif field in {"entry_order_mode", "entry_maker_order_type", "profit_exit_order_mode", "profit_maker_order_type", "stop_exit_order_mode", "reversal_exit_order_mode", "near_close_exit_order_mode"}:
                    worker_config[field] = raw.strip().upper()
                else:
                    try:
                        worker_config[field] = float(raw) if "." in raw else int(raw)
                    except (TypeError, ValueError):
                        worker_config[field] = raw
            if "KELLY_SIZING_ENABLED" in env:
                worker_config["kelly_sizing_enabled"] = env["KELLY_SIZING_ENABLED"].lower() in {"true", "1", "yes", "on"}
            result.update(worker_running=True, worker_service_state="RUNNING",
                          worker_pid=pid, worker_config=worker_config)
            effective = _valid_daily_loss_fraction(env.get("MAX_DAILY_LOSS_FRACTION"))
            if effective is not None:
                result.update(effective_max_daily_loss_fraction=effective,
                              daily_loss_limit_source="worker_environment")
    except (OSError, ValueError, IndexError, RuntimeError, subprocess.SubprocessError):
        pass
    _paper_worker_loss_cache[key] = (now, result)
    return dict(result)

def _validate_risk_settings(body: Any) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Validate the complete request before changing configuration or files."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="参数必须为 JSON 对象")
    limits = {
        # Keep labels in the save response encoding-stable.  This release
        # previously carried double-decoded Chinese literals, producing
        # mojibake after a successful save.
        "max_daily_loss_fraction": (0., .5, True, "日亏损熔断"),
        "max_daily_realized_profit_fraction": (0., 1., True, "日止盈收益率"),
        "max_daily_realized_profit_usd": (0., 10000., True, "每日止盈金额"),
        "paper_equity_usd": (10., 100000., True, "模拟本金"),
        "min_entry_price": (0., 1., False, "入场价格下限"),
        "max_entry_price": (0., 1., False, "入场价格上限"),
        "seconds_before_close": (0., 600., True, "入场窗口"),
        "min_t_remaining_sec": (0., 600., True, "最小剩余时间"),
        "reversal_held_bid_drawdown": (0., 1., False, "回撤止损"),
        "reversal_exit_window_sec": (0., 600., True, "反转退出窗口"),
        "confirm_checks": (0., 20., True, "入场确认次数"),
        "reversal_confirm_checks": (0., 20., True, "反转确认次数"),
        "order_risk_fraction": (0., 1., False, "单笔风险"),
        "max_open_positions": (1., 20., True, "最大持仓"),
        "sell_fok_slippage_ticks": (0., 100., True, "卖出 FOK 滑点"),
        "sell_exit_max_depth_ticks": (0., 100., True, "卖出深度跳数"),
        "sell_exit_max_depth_levels": (0., 100., True, "卖出深度档位"),
        "entry_maker_ttl_sec": (0.5, 60., True, "入场 Maker TTL"),
        "profit_target_fraction": (0., 1., True, "盈利目标"),
        "profit_exit_confirm_checks": (1., 20., True, "盈利退出确认次数"),
        "profit_exit_fraction": (0., 1., True, "盈利退出比例"),
        "take_profit_min_gain_fraction": (0., 1., True, "止盈最小收益"),
        "take_profit_exit_fraction": (0., 1., True, "止盈退出比例"),
        "max_hold_seconds": (0., 86400., True, "最大持仓秒数"),
        "expiry_exit_seconds": (0., 3600., True, "结算退出秒数"),
        "expiry_exit_fraction": (0., 1., True, "结算退出比例"),
        "profit_target_ticks": (0., 100., True, "盈利目标跳数"),
        "profit_maker_ttl_sec": (0.5, 60., True, "盈利 Maker TTL"),
        "near_close_exit_window_sec": (0., 300., True, "临近结算窗口"),
        "reversal_partial_exit_fraction": (0., 1., True, "部分退出比例"),
    }
    values: dict[str, Any] = {}
    changes: dict[str, str] = {}
    notes: list[str] = []
    for field, (low, high, inclusive, label) in limits.items():
        if field not in body:
            continue
        raw = body[field]
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(status_code=400, detail=label + "必须为有效数字")
        if isinstance(raw, bool) or not math.isfinite(value) or value > high or (value < low if inclusive else value <= low):
            raise HTTPException(status_code=400, detail=label + "超出允许范围")
        values[field] = value
        env_name = (_RISK_WORKER_FIELDS | _EXECUTION_WORKER_FIELDS).get(field)
        if not env_name:
            raise HTTPException(status_code=400, detail="unknown setting field")
        changes[env_name] = f"{value:g}"
        if field.endswith("_usd"):
            display = f"${value:g}"
        elif field.endswith("_fraction") or field.endswith("_pct"):
            display = f"{value:.2%}"
        elif field.endswith("_sec") or field.endswith("_ticks") or field.endswith("_levels") or field in {"confirm_checks", "reversal_confirm_checks", "max_open_positions"}:
            display = f"{value:g}"
        else:
            display = f"{value:g}"
        notes.append(f"{label}={display}")
    enum_fields = {
        "entry_order_mode": ("ENTRY_ORDER_MODE", {"TAKER": "TAKER", "MAKER": "MAKER_FIRST", "HYBRID": "MAKER_FIRST", "MAKER_FIRST": "MAKER_FIRST"}, "入场模式"),
        "entry_maker_order_type": ("ENTRY_MAKER_ORDER_TYPE", {"GTC": "GTC", "GTD": "GTD"}, "入场 Maker 类型"),
        "profit_exit_order_mode": ("PROFIT_EXIT_ORDER_MODE", {"TAKER": "TAKER", "MAKER": "MAKER_FIRST", "HYBRID": "MAKER_FIRST", "MAKER_FIRST": "MAKER_FIRST"}, "盈利退出模式"),
        "profit_maker_order_type": ("PROFIT_MAKER_ORDER_TYPE", {"GTC": "GTC", "GTD": "GTD"}, "盈利 Maker 类型"),
        "stop_exit_order_mode": ("STOP_EXIT_ORDER_MODE", {"TAKER": "TAKER", "MAKER": "MAKER_FIRST", "HYBRID": "MAKER_FIRST", "MAKER_FIRST": "MAKER_FIRST"}, "止损模式"),
        "reversal_exit_order_mode": ("REVERSAL_EXIT_ORDER_MODE", {"TAKER": "TAKER", "MAKER": "MAKER_FIRST", "HYBRID": "MAKER_FIRST", "MAKER_FIRST": "MAKER_FIRST"}, "反转模式"),
        "near_close_exit_order_mode": ("NEAR_CLOSE_EXIT_ORDER_MODE", {"TAKER": "TAKER", "MAKER": "MAKER_FIRST", "HYBRID": "MAKER_FIRST", "MAKER_FIRST": "MAKER_FIRST"}, "临近结算模式"),
    }
    for field, (env_name, choices, label) in enum_fields.items():
        if field not in body:
            continue
        raw = str(body[field]).strip().upper()
        if raw not in choices:
            raise HTTPException(status_code=400, detail=label + " invalid")
        values[field] = choices[raw]
        changes[env_name] = choices[raw]
        notes.append(f"{label}={raw}")
    for field in ("entry_maker_post_only", "entry_maker_fallback_taker", "profit_exit_enabled", "take_profit_enabled", "expiry_exit_enabled", "near_close_exit_enabled", "profit_maker_post_only", "profit_maker_fallback_taker", "reversal_partial_exit_enabled", "sell_exit_fak_fallback_enabled", "sell_exit_reconcile_trades"):
        if field not in body:
            continue
        if not isinstance(body[field], bool):
            raise HTTPException(status_code=400, detail=field + " must be boolean")
        values[field] = body[field]
        changes[_EXECUTION_WORKER_FIELDS[field]] = "true" if body[field] else "false"
        notes.append(f"{field}={'on' if body[field] else 'off'}")
    if "kelly_sizing_enabled" in body:
        if not isinstance(body["kelly_sizing_enabled"], bool):
            raise HTTPException(status_code=400, detail="凯利开关必须为布尔值")
        values["kelly_sizing_enabled"] = body["kelly_sizing_enabled"]
        changes["KELLY_SIZING_ENABLED"] = "true" if body["kelly_sizing_enabled"] else "false"
        notes.append("kelly sizing=" + ("on" if body["kelly_sizing_enabled"] else "off"))
    if "restart_workers" in body and not isinstance(body["restart_workers"], bool):
        raise HTTPException(status_code=400, detail="重启开关必须为布尔值")
    if not changes:
        raise HTTPException(status_code=400, detail="没有可应用的字段")
    return values, changes, notes

def _verify_live_worker(expected: dict[str, Any], previous_pid: Optional[int]) -> dict[str, Any]:
    """Verify that the real BTC Live process reloaded the saved settings."""
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        runtime = _live_worker_runtime("BTC")
        pid = runtime.get("worker_pid")
        if (runtime.get("worker_running") is True and pid and pid != previous_pid
                and runtime.get("configuration_matches_saved") is True):
            actual = runtime.get("effective_config") or {}
            if all(field in actual and _worker_setting_matches(actual[field], value)
                   for field, value in expected.items()):
                return runtime
        time.sleep(0.4)
    raise HTTPException(status_code=503, detail="配置已保存，但 BTC 实盘 Worker 未能重新加载；请检查服务日志。")


def _worker_setting_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-10)
        except (TypeError, ValueError):
            return False
    return str(actual).strip().upper() == str(expected).strip().upper()


def _verify_risk_worker(expected: dict[str, Any], previous_pid: Optional[int]) -> dict[str, Any]:
    """Confirm that the optional BTC Paper process loaded the saved settings.

    Paper and Live use separate ledgers and processes.  This check therefore
    only accepts a verified ``polymarket-test-btc-paper.service`` process and
    never treats the live PID as a successful Paper restart.
    """
    if globals().get("_PAPER_COMPARISON_ENABLED", False):
        applied = _p3.read_runtime().get("worker_config") or {}
        expected = {key:value for key,value in expected.items() if key in applied}
    deadline = time.monotonic() + 20.0
    consecutive = 0
    last_pid: Optional[int] = None
    while time.monotonic() < deadline:
        _paper_worker_loss_cache.clear()
        runtime = _paper_worker_daily_loss(
            "polymarket-test-btc-paper.service", ROOT.parent.parent, DB_PATH
        )
        pid = runtime.get("worker_pid")
        actual = runtime.get("worker_config") or {}
        matches = bool(
            runtime.get("worker_running") is True
            and pid
            and pid != previous_pid
            and all(
                field in actual
                and _worker_setting_matches(actual[field], value)
                for field, value in expected.items()
            )
        )
        consecutive = consecutive + 1 if matches and pid == last_pid else (1 if matches else 0)
        if consecutive >= 3:
            return runtime
        last_pid = pid
        # systemd reports STOPPED briefly between the restart transaction and
        # the new process. Keep polling until the deadline so a normal
        # restart is not reported as a failed Paper reload.
        time.sleep(0.4)
    raise HTTPException(
        status_code=503,
        detail="Configuration saved, but BTC Paper Worker did not reload all settings; check service logs and retry",
    )


def _verify_saved_without_worker(expected: dict[str, Any]) -> dict[str, Any]:
    """Return saved values when the optional Paper worker is unavailable."""
    persisted = _control_env_values()
    actual: dict[str, Any] = {}
    for field, name in (_RISK_WORKER_FIELDS | _EXECUTION_WORKER_FIELDS).items():
        if name in persisted:
            raw = persisted[name]
            if (field.endswith("_enabled") or field.endswith("_post_only")
                    or field.endswith("_fallback_taker") or field.endswith("_reconcile_trades")):
                actual[field] = str(raw).lower() in {"true", "1", "yes", "on"}
            elif field in {"entry_order_mode", "entry_maker_order_type", "profit_exit_order_mode", "profit_maker_order_type", "stop_exit_order_mode", "reversal_exit_order_mode", "near_close_exit_order_mode"}:
                actual[field] = str(raw).strip().upper()
            else:
                try:
                    actual[field] = float(raw)
                except (TypeError, ValueError):
                    pass
    return {"worker_running": False, "worker_service_state": "STOPPED",
            "worker_config": actual, "effective_config": actual,
            "warning": "Configuration saved, but BTC Paper Worker was not running; live mode is unaffected."}


def _apply_risk_settings(body: dict[str, Any]) -> dict[str, Any]:
    values, changes, notes = _validate_risk_settings(body)
    expected = dict(values)
    persisted = _control_env_values()
    for field, name in (_RISK_WORKER_FIELDS | _EXECUTION_WORKER_FIELDS).items():
        if field not in expected and name in persisted:
            raw = persisted[name]
            if (field.endswith("_enabled") or field.endswith("_post_only")
                    or field.endswith("_fallback_taker") or field.endswith("_reconcile_trades")):
                expected[field] = str(raw).lower() in {"true", "1", "yes", "on"}
            elif field in {"entry_order_mode", "entry_maker_order_type", "profit_exit_order_mode", "profit_maker_order_type", "stop_exit_order_mode", "reversal_exit_order_mode", "near_close_exit_order_mode"}:
                expected[field] = str(raw).strip().upper()
            else:
                try:
                    expected[field] = float(raw)
                except (TypeError, ValueError):
                    pass

    service = _service_status_snapshot().get("BTC") or {}
    live_mode = bool(service.get("live_running") or (service.get("live_enabled") and not service.get("paper_running")))
    previous_pid = None
    if body.get("restart_workers", True):
        if live_mode:
            previous_pid = _live_worker_runtime("BTC").get("worker_pid")
        else:
            _paper_worker_loss_cache.clear()
            previous_pid = _paper_worker_daily_loss("polymarket-test-btc-paper.service", ROOT.parent.parent, DB_PATH).get("worker_pid")

    if globals().get("_PAPER_COMPARISON_ENABLED", False) and not live_mode:
        try:
            _p3.export_public_config({**persisted, **changes})
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid Paper comparison settings") from exc
    updated = _update_env_keys(changes)
    paper_only_saved = []
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and not live_mode:
        public_cfg = _p3.export_public_config(_control_env_values(), _p3.experiment_root()/"public-config.json")
        paper_only_saved = [field for field in values if field not in public_cfg]
        expected = {field:value for field,value in expected.items() if field in public_cfg}
    for field, value in values.items():
        if field != "kelly_sizing_enabled":
            object.__setattr__(cfg, field, value)
    _kelly_flag_cache["ts"] = 0.0
    _paper_worker_loss_cache.clear()
    restarted: list[str] = []
    runtime: dict[str, Any] = {}

    if body.get("restart_workers", True):
        if live_mode:
            # The instance launcher controls the dedicated BTC service when
            # configured; restart only that worker to load the saved settings.
            try:
                stop = subprocess.run(["/usr/bin/env", "bash", str(ROOT / "scripts" / "stop_live_asset.sh"), "BTC"],
                                      cwd=ROOT, text=True, capture_output=True, timeout=30, check=False)
                if stop.returncode != 0:
                    raise RuntimeError(_process_output(stop))
                launcher_env = os.environ.copy()
                for key, value in dotenv_values(ROOT / ".env").items():
                    if value is not None:
                        launcher_env[str(key)] = str(value)
                # Test and polyauto releases use different guarded launchers.
                # The former must use run_live.sh; run_live_polyauto.sh
                # deliberately rejects POLYAUTO_INSTANCE=false.
                launcher = "run_live_polyauto.sh" if _is_polyauto_instance() else "run_live.sh"
                start = subprocess.run(["/usr/bin/env", "bash", str(ROOT / "scripts" / launcher)],
                                       cwd=ROOT, env=launcher_env, text=True, capture_output=True, timeout=180, check=False)
                if start.returncode != 0:
                    raise RuntimeError(_process_output(start))
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                raise HTTPException(status_code=503, detail=f"Configuration saved, but BTC live Worker restart failed: {exc}")
            runtime = _verify_live_worker(expected, previous_pid)
            restarted.append("btc-live")
        else:
            # Paper is optional on this BTC-live deployment. Restart it when
            # requested, but do not report a false failure if its independent
            # strategy manifest is in CrashLoop; the saved values remain clear.
            unit = "polymarket-test-btc-paper.service"
            try:
                subprocess.run(["sudo", "-n", "systemctl", "restart", unit], check=True, capture_output=True, timeout=30)
                runtime = _verify_risk_worker(expected, previous_pid)
            except (OSError, subprocess.SubprocessError, HTTPException):
                runtime = _verify_saved_without_worker(expected)
            restarted.append("btc-paper")

    # Keep the success message ASCII-stable at the API boundary.  Earlier
    # releases joined UTF-8 text with a mojibake separator (``；``), so the
    # browser displayed corrupted labels after a save/restart.  The API is
    # consumed by both the dashboard and CLI checks; stable key/value output
    # avoids a second encoding/decoding pass while preserving every value.
    return {"ok": True, "applied": changes, "workers_restarted": restarted,
            "worker_env_files": updated, "worker_pid": runtime.get("worker_pid"),
            "effective_config": runtime.get("effective_config") or runtime.get("worker_config"),
            "worker_mode": "live" if live_mode else "paper",
            "saved_for_live_only": paper_only_saved,
            "paper_execution_model": "fixed_same_hybrid_execution_both_groups" if globals().get("_PAPER_COMPARISON_ENABLED", False) else None,
            "warning": runtime.get("warning"),
            "note": "; ".join(notes) + ("（BTC 实盘 Worker 已重启并验证生效）" if live_mode and restarted else "（配置已保存）")}

@app.put("/api/settings/risk")
async def put_risk_settings(request: Request):
    _require_operator(request)
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="请求不是有效 JSON")
    async with _risk_settings_lock:
        # Restart verification must not block the shared state/WebSocket loop.
        return await asyncio.to_thread(_apply_risk_settings, body)


@app.websocket("/api/ws/state")
async def state_websocket(websocket: WebSocket):
    """Push the same state payload used by REST polling."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await asyncio.to_thread(state))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


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
    asyncio.create_task(poll_book_loop())
    asyncio.create_task(poll_btc_signal_loop())
    asyncio.create_task(poll_positions_loop())
    asyncio.create_task(poll_balance_loop())
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
    live_assets = _live_process_status_base()
    paper_assets = _paper_process_status_base()
    live_running = any(live_assets.values())
    paper_running = any(paper_assets.values())
    running = live_running or paper_running
    mode = "live" if live_running else ("paper" if paper_running else "stopped")
    capability = _live_execution_capability()
    return {
        "running": running,
        "mode": mode,
        "paper_running": paper_running,
        "live_running": live_running,
        "assets": live_assets,
        "paper_assets": paper_assets,
        "execution_ready": bool(capability["ready"]),
        "execution_capabilities": capability["capabilities"],
        "live_block_reason": capability.get("reason", ""),
        "strategy_source": capability.get("strategy_source", "native-btc5m"),
        "config_hash": capability.get("config_hash", ""),
        "services": _service_status_snapshot(),
    }


def _process_output(result: subprocess.CompletedProcess[str]) -> str:
    """Return a bounded, secret-free command diagnostic for the UI."""
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    for key in ("PRIVATE_KEY", "CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"):
        text = re.sub(rf"(?im)({key}\s*[=:]\s*)\S+", r"\1[已隐藏]", text)
    return text[-3000:]


PAPER_SERVICE_UNITS = {p.asset: p.unit for p in pc.PRODUCTS.values()}


def _stop_paper_for_live() -> bool:
    """Stop the isolated BTC Paper unit before a live handoff.

    Paper and live use the same release PID files and ledger path.  The
    handoff is therefore a single-owner operation: if Paper is active, stop
    that systemd unit and wait until its process disappears before invoking
    the guarded live launcher.  The return value records whether this request
    actually stopped a running Paper unit so a failed handoff can restore it.
    """
    unit = PAPER_SERVICE_UNITS["BTC"]
    was_active = _systemd_active(unit) or bool(_paper_process_status_base().get("BTC"))
    if not was_active:
        return False
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "stop", unit],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = _process_output(result)
        raise RuntimeError("停止 BTC Paper Worker 失败" + (f"：{diagnostic}" if diagnostic else ""))
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if not _systemd_active(unit) and not _paper_process_status_base().get("BTC"):
            return True
        time.sleep(0.25)
    raise RuntimeError("BTC Paper Worker 停止超时，未执行实盘切换")


def _restore_paper_after_live_failure(should_restore: bool) -> str:
    """Best-effort Paper recovery after a failed live preflight/start."""
    if not should_restore:
        return ""
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "start", PAPER_SERVICE_UNITS["BTC"]],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            diagnostic = _process_output(result)
            return "；Paper Worker 自动恢复失败" + (f"：{diagnostic}" if diagnostic else "")
        return "；实盘预检失败，已自动恢复 Paper Worker"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"；Paper Worker 自动恢复失败：{exc}"


def _systemd_active(unit: str) -> bool:
    try:
        result = subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False, capture_output=True, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _systemd_enabled(unit: str) -> bool:
    try:
        result = subprocess.run(["systemctl", "is-enabled", "--quiet", unit], check=False, capture_output=True, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _paper_services_snapshot() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for asset, unit in PAPER_SERVICE_UNITS.items():
        product = next((item for item in pc.PRODUCTS.values() if item.asset == asset), None)
        active = _systemd_active(unit)
        product_health = pc.health(product) if product is not None else {
            "worker_active": active,
            "worker_state": "RUNNING" if active else "STOPPED",
            "worker_pid": 0,
            "freshness": "unknown",
            "allow_entries": False,
            "circuit_reason": "product_unregistered",
        }
        result[asset] = {
            "service": unit, "enabled": _systemd_enabled(unit), "active": active,
            "running": active, "paper_active": active, "mode": "paper",
            "worker_active": product_health.get("worker_active", active),
            "worker_state": product_health.get("worker_state"),
            "worker_pid": product_health.get("worker_pid"),
            "health": product_health,
            "decorative_agent": {
                "status": "offline",
                "connected": False,
                "read_only": True,
                "detail": "Paper Worker 使用确定性策略，无 OpenClaw 签名权限",
            },
        }
    return result


class PaperTogglePayload(BaseModel):
    enabled: bool


@app.get("/api/paper/services")
def paper_services():
    return {"ok": True, "services": _paper_services_snapshot(), "ts": time.time()}


@app.get("/api/products")
def registered_products():
    return {"products": [pc.snapshot(p) for p in pc.PRODUCTS.values()]}


@app.get("/api/observations/paper")
def paper_observations():
    directory = pc.ROOT / "state/three-products-observation"
    result = {}
    for name in ("schedule", "latest", "smoke-24h", "comparison-48h"):
        try:
            result[name] = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result[name] = None
    return result


@app.get("/api/products/{key}/config")
def product_config(key: str):
    return pc.config(pc.find(key))


@app.put("/api/products/{key}/config")
async def save_product(key: str, request: Request):
    _require_operator(request)
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(422, "请求必须为 JSON")
    return await asyncio.to_thread(pc.save, pc.find(key), body)


@app.put("/api/products/{key}/paper")
def toggle_product(key: str, payload: PaperTogglePayload, request: Request):
    _require_operator(request)
    product = pc.find(key)
    if product.asset == "BTC" and _live_process_status_base().get("BTC"):
        raise HTTPException(409, "请先停止该产品实盘服务")
    return pc.toggle(product, payload.enabled)


@app.get("/api/products/{key}/orders")
def product_orders(key: str, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=200)):
    return pr.fills([pc.find(key)], offset, limit)


@app.get("/api/products/{key}/positions")
def product_positions(key: str):
    p = pc.find(key)
    item = _product_paper_snapshot()[p.asset]
    return {**p.meta, "available": item["available"], "positions": item["positions"],
            "settled_positions": item["settled_positions"]}


@app.get("/api/products/{key}/history")
def product_history(key: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=365)):
    return _product_paper_daily_page(pc.find(key).asset, offset, limit)


@app.get("/api/products/{key}/decisions")
def product_decisions(key: str, limit: int = Query(50, ge=1, le=200)):
    p = pc.find(key)
    return {**p.meta, "rows": pr.decisions(p, limit)}


@app.put("/api/paper/services/{asset}")
def paper_service_toggle(asset: str, payload: PaperTogglePayload, request: Request):
    _require_operator(request)
    service = asset.strip().upper()
    unit = PAPER_SERVICE_UNITS.get(service)
    if unit is None:
        raise HTTPException(status_code=404, detail="未知 Paper 服务")
    if _live_process_status_base().get(service):
        raise HTTPException(status_code=409, detail="BTC 实盘正在运行；不能并行切换 Paper Worker")
    action = "start" if payload.enabled else "stop"
    try:
        result = subprocess.run(["sudo", "-n", "systemctl", action, unit], cwd=ROOT, text=True, capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Paper worker 操作超时")
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Paper Worker 操作失败：{exc}")
    if result.returncode != 0:
        diagnostic = _process_output(result)
        raise HTTPException(status_code=502, detail=("Paper Worker 操作失败：" + (f" {diagnostic}" if diagnostic else ""))[:1200])
    active = _systemd_active(unit)
    return {
        "ok": True, "service": service, "unit": unit,
        "enabled": _systemd_enabled(unit), "active": active,
        "running": active, "paper_active": active,
        "note": "BTC Paper worker 已启动" if payload.enabled else "BTC Paper worker 已停止；历史账目保留",
        "ts": time.time(),
    }


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
        raise HTTPException(status_code=403, detail="ETH 服务仅支持 Paper；禁止实盘")
    if service == "WEATHER" and payload.live_enabled and _is_polyauto_instance():
        raise HTTPException(status_code=403, detail="天气服务仅支持 Paper；禁止实盘")
    key = {"BTC": "BTC_LIVE_ENABLED", "ETH": "ETH_TRADING_ENABLED", "WEATHER": "WEATHER_LIVE_TRADING_ENABLED"}.get(service)
    if key is None:
        if not payload.live_enabled:
            return {"ok": True, "service": service, "live_enabled": False, "services": _service_status_snapshot()}
        raise HTTPException(status_code=403, detail="该服务没有实盘执行器")
    _write_control_flag(key, payload.live_enabled)
    return {"ok": True, "service": service, "live_enabled": payload.live_enabled, "services": _service_status_snapshot(), "note": "重启对应 worker 线程"}


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
    return {"ok": True, "instance": _deployment_instance_name(), "services": _service_status_snapshot(), "ts": time.time()}


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
    """Run native live only after explicit P1/P2/P3 capability certification."""
    _require_operator(request)
    capability = _live_execution_capability()
    if not capability["ready"]:
        # Check before stopping Paper, editing .env, or invoking a launcher.
        raise HTTPException(status_code=409, detail={
            "code": "LIVE_CAPABILITY_NOT_READY",
            "message": capability.get("reason", "实盘能力未认证，保持关闭"),
            "missing": capability.get("missing", []),
            "strategy_source": capability.get("strategy_source", "native-btc5m"),
            "config_hash": capability.get("config_hash", ""),
        })
    with _live_control_lock:
        current = _live_process_status()
        # Starting an already-live worker is idempotent.  This avoids showing
        # a false failure when the browser retries a request after a slow
        # preflight, while still making the actual mode explicit.
        if current["live_running"]:
            return {
                "ok": True,
                "already_running": True,
                "message": "实盘机器人已经在运行，无需重复开启",
                **current,
                "ts": time.time(),
            }
        # A Paper worker owns the same PID file and database path.  The
        # operator's explicit Live action performs an atomic handoff: stop
        # Paper first, then run the guarded preflight/launcher.  If anything
        # fails, the original Paper service is restored before returning the
        # error so the dashboard never leaves both modes stopped.
        paper_was_running = bool(current["paper_running"])
        paper_stopped = False
        if current["running"]:
            if not paper_was_running:
                raise HTTPException(
                    status_code=409,
                    detail="检测到运行中的机器人但无法确认模式，请先停止该进程后再开启实盘",
                )
            try:
                paper_stopped = _stop_paper_for_live()
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                raise HTTPException(status_code=503, detail=f"无法安全停止 Paper Worker，实盘未启动：{exc}")
        elif paper_was_running:
            try:
                paper_stopped = _stop_paper_for_live()
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                raise HTTPException(status_code=503, detail=f"无法安全停止 Paper Worker，实盘未启动：{exc}")
        # The explicit top-level 开启实盘 action is itself the operator's
        # BTC live consent.  Enable the gate just for the guarded launcher;
        # every preflight/verification failure rolls it back below.
        auto_enabled_live_gate = False
        if _is_polyauto_instance() and not _service_status_snapshot()["BTC"]["live_enabled"]:
            _write_control_flag("BTC_LIVE_ENABLED", True)
            auto_enabled_live_gate = True
        launcher = "run_live_polyauto.sh" if _is_polyauto_instance() else "run_live.sh"
        try:
            # systemd keeps the Dashboard environment from service start. A
            # live toggle edits ROOT/.env at request time, so pass the current
            # release environment to the launcher; otherwise bot.main can see
            # a stale BTC_LIVE_ENABLED=false and exit immediately.
            launcher_env = os.environ.copy()
            for key, value in dotenv_values(ROOT / ".env").items():
                if value is not None:
                    launcher_env[str(key)] = str(value)
            result = subprocess.run(
                ["/usr/bin/env", "bash", str(ROOT / "scripts" / launcher)],
                cwd=ROOT,
                env=launcher_env,
                text=True,
                capture_output=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired:
            if auto_enabled_live_gate:
                _write_control_flag("BTC_LIVE_ENABLED", False)
            recovery = _restore_paper_after_live_failure(paper_stopped)
            raise HTTPException(status_code=504, detail="实盘预检或启动超时，请查看 logs/ 日志" + recovery)
        diagnostic = _process_output(result)
        if result.returncode != 0:
            if auto_enabled_live_gate:
                _write_control_flag("BTC_LIVE_ENABLED", False)
            recovery = _restore_paper_after_live_failure(paper_stopped)
            raise HTTPException(
                status_code=502,
                detail=("实盘未启动；预检/启动失败。" + (f" {diagnostic}" if diagnostic else "") + recovery)[:3500],
            )
        status = _live_process_status()
        if not status["live_running"]:
            if auto_enabled_live_gate:
                _write_control_flag("BTC_LIVE_ENABLED", False)
            recovery = _restore_paper_after_live_failure(paper_stopped)
            raise HTTPException(status_code=502, detail="实盘启动命令已返回，但未检测到 BTC Live Worker" + recovery)
        return {"ok": True, **status, "diagnostic": diagnostic, "paper_stopped": paper_stopped, "live_gate_auto_enabled": auto_enabled_live_gate, "ts": time.time()}


@app.post("/api/live/stop")
def live_stop(request: Request):
    """Stop workers only; this never submits a sell or otherwise liquidates."""
    _require_operator(request)
    with _live_control_lock:
        current = _live_process_status()
        if current["paper_running"]:
            raise HTTPException(
                status_code=409,
                detail="当前运行的是 Paper 机器人；实盘停止接口不会停止 Paper，请使用 Paper 服务控制",
            )
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
    """Return only the explicitly configured model.

    Automatic compatibility fallbacks can silently route a reviewer request to
    an unintended legacy model. The configured model is therefore the sole
    candidate; an unavailable model is reported to the caller.
    """
    value = (model or "").strip()
    return [value] if value else []


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
        if last_exc is not None:
            text = str(last_exc)
            lowered = text.lower()
            if "model_not_found" in lowered or "no available channel" in lowered:
                raise RuntimeError(
                    f"模型 {model} 在当前上游没有可用通道。请点击“拉取模型”并选择当前接口返回的有效模型。"
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
        "instance": _deployment_instance_name(),
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
            return {"slot": slot, "enabled": True, "model": candidate, "text": str(text)[:8000], "error": None,
                    "usage": data.get("usage")}
        except Exception as exc:
            last = exc
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


_paper_model_lock = threading.Lock()


@app.post("/api/paper/model-advisor")
def paper_model_advisor(payload: LlmAdvisorPayload, request: Request):
    """Local Paper hypothesis consultation; never calls an order or signer."""
    if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
            or request.headers.get("x-forwarded-for") or request.headers.get("forwarded")):
        raise HTTPException(status_code=403, detail="Paper advisor requires loopback access")
    if not _paper_model_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Paper advisor is busy")
    def consult(slot):
        started = time.monotonic()
        role = ("Act as Scout/Trader: assess the settlement evidence, direction, fees and queue-adjusted edge. "
                if slot == "primary" else
                "Act as Auditor/Mechanic: independently veto risk, stale evidence, execution and inventory faults. ")
        result = _llm_advisor_call(slot, role + payload.prompt)
        return {**result, "latency_sec": time.monotonic() - started}
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="paper-model") as pool:
            primary = pool.submit(consult, "primary")
            secondary = pool.submit(consult, "secondary")
            results = {"primary": primary.result(), "secondary": secondary.result()}
    finally:
        _paper_model_lock.release()
    return {"ok": True, "lead_id": payload.lead_id, **results, "mode": "paper",
            "trading_allowed": False, "requires_risk": True}


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


def _paper_guard_snapshot() -> dict[str, Any]:
    """Read worker-owned guard files; UI reads never approve or unlock BUYs."""
    enabled = bool(getattr(cfg, "loss_cap_recovery_enabled", False))
    result: dict[str, Any] = {
        "enabled": enabled, "asset": "BTC", "mode": "paper",
        "state": "DISABLED" if not enabled else "WAITING_UPDATE",
        "allow_entries": False, "entries_used": 0,
        "max_entries_per_day": int(getattr(cfg, "loss_cap_recovery_max_entries_per_day", 0)),
        "min_net_pnl_fraction": float(getattr(cfg, "loss_cap_recovery_min_net_pnl_fraction", 0.0)),
        "confirm_samples": int(getattr(cfg, "loss_cap_recovery_confirm_samples", 0)),
        "confirm_window_sec": float(getattr(cfg, "loss_cap_recovery_confirm_window_sec", 0.0)),
        "profit_stop": None,
    }
    if _state.get("bot_mode") == "live":
        result.update(enabled=False, state="DISABLED", mode="live")
        return result
    now = time.time()
    try:
        stop = active_paper_profit_stop("BTC", now=now, db_path=DB_PATH)
        result["profit_stop"] = stop
        if stop:
            result.update(state="PROFIT_TAKE", resume_ts=stop["resume_ts"], reason=stop["reason"])
            return result
        if not enabled:
            return result
        path = DB_PATH.with_name(DB_PATH.name + ".loss-recovery-BTC.json")
        if not path.exists():
            return result
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("asset") != "BTC" or float(record.get("day_start_ts", -1)) != local_day_start_ts(now):
            return result
        age = now - float(record.get("last_mark_ts", 0))
        fresh = math.isfinite(age) and 0 <= age <= float(getattr(cfg, "loss_cap_recovery_mark_max_age_sec", 5.0))
        running = bool(_live_process_status_base().get("BTC"))
        used = int(record.get("entries_used", 0))
        result.update(
            state=record["mode"] if fresh and running else "WAITING_UPDATE",
            last_worker_state=record.get("mode"), entries_used=used,
            net_pnl_usd=record.get("last_net_pnl_usd"), last_mark_ts=record.get("last_mark_ts"),
            samples=len(record.get("samples") or []), fresh=fresh, worker_running=running,
        )
        result["allow_entries"] = (
            result["state"] == "RECOVERY_ACTIVE" and 0 <= used < result["max_entries_per_day"]
        )
    except Exception:
        # A malformed guard file must not turn /api/state into an HTTP 500.
        result.update(state="UNAVAILABLE", allow_entries=False)
    return result


def _risk_state(pnl: dict) -> str:
    """Project the worker gate with its lane and bankroll, never wallet/Paper mix."""
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and not (_service_status_snapshot().get("BTC") or {}).get("live_enabled"):
        document = _p3.read_summary()
        group = (document.get("groups") or {}).get(_paper_primary_group()) or {}
        if document.get("stale"):
            return "PAPER_DATA_UNAVAILABLE"
        # A cursor gap is retained in the experiment audit record for
        # coverage accounting. It is not a current risk circuit once the
        # worker has resynchronised and health is RUNNING. Only expose a
        # coverage/source reason as the headline state while the current
        # health gate is actually blocked; daily risk blocks still win.
        daily_block = group.get("daily_block_reason")
        if daily_block:
            return daily_block
        health = document.get("health") or {}
        if str(health.get("status") or "").upper() != "RUNNING":
            return health.get("source_reason") or group.get("coverage_block") or "PAPER_DATA_UNAVAILABLE"
        return "OK"
    live = _state.get("bot_mode") == "live"
    if live:
        balance = _state.get("balance_pusd")
        equity = (float(balance) if balance is not None else 0.0) + float(_state.get("value_usd") or 0.0)
    else:
        equity = float(cfg.paper_equity_usd)
        guard = _paper_guard_snapshot()
        if guard["state"] == "PROFIT_TAKE":
            return "PROFIT_TAKE"
        if guard["state"] == "UNAVAILABLE":
            return "GUARD_UNAVAILABLE"
    profit_target = daily_profit_target_usd(cfg, not live)
    if profit_target is not None and pnl["realized_usd"] >= profit_target:
        return "PROFIT_TAKE"
    if cfg.max_daily_loss_fraction > 0 and pnl["realized_usd"] <= -(equity * cfg.max_daily_loss_fraction):
        if not live and guard["allow_entries"]:
            return "RECOVERY_ACTIVE"
        return "LOSS_CAP"
    streak = consecutive_losses(not live)
    if cfg.consecutive_loss_kill > 0 and streak >= cfg.consecutive_loss_kill:
        return f"LOSS_STREAK({streak})"
    return "OK"

_live_account_cache: dict[str, Any] = {"ts": 0.0, "account": None}
_cumulative_cache: dict[str, Any] = {"ts": 0.0, "value": None}


def _cumulative_performance() -> dict[str, Any]:
    """Return all-recorded settled performance, separate from today's risk PnL.

    ``accounting_snapshot`` intentionally uses the current Beijing day for risk
    gating.  The console's cumulative cards need a different, explicit
    lifetime scope; keeping this calculation separate prevents a quiet day
    from looking like an empty ledger.
    """
    now = time.time()
    cached = _cumulative_cache.get("value")
    if cached is not None and now - float(_cumulative_cache.get("ts", 0.0)) < 5.0:
        return cached
    result: dict[str, Any] = {}
    for lane, dry_run in (("paper", True), ("live", False)):
        # Build the FIFO ledger once per lane. Calling realized_pnl_by_day
        # five times rescanned the 300MB database and made the first dashboard
        # frame appear blank for many seconds.
        _, events, _ = _fifo_ledger(dry_run)
        realized = sum(float(event.get("pnl") or 0.0) for event in events)
        wins = sum(1 for event in events if float(event.get("pnl") or 0.0) >= 0)
        losses = sum(1 for event in events if float(event.get("pnl") or 0.0) < 0)
        by_asset: dict[str, dict[str, Any]] = {asset: {"realized_usd": 0.0, "wins": 0, "losses": 0} for asset in ("BTC",)}
        for event in events:
            asset = str(event.get("asset") or "").upper()
            if asset not in by_asset:
                continue
            pnl = float(event.get("pnl") or 0.0)
            by_asset[asset]["realized_usd"] += pnl
            by_asset[asset]["wins" if pnl >= 0 else "losses"] += 1
        result[lane] = {
            "realized_usd": realized,
            "wins": wins,
            "losses": losses,
            "by_asset": by_asset,
        }
    if globals().get("_PAPER_COMPARISON_ENABLED", False):
        doc = _p3.read_summary()
        group = (doc.get("groups") or {}).get(_paper_primary_group()) or {}
        daily = group.get("daily_rows") or []
        item = {"realized_usd": group.get("realized_pnl_usd"),
                "wins": sum(r.get("wins", 0) for r in daily),
                "losses": sum(r.get("losses", 0) for r in daily)}
        result["paper"] = {**item, "by_asset": {"BTC": item}}
    _cumulative_cache.update(ts=now, value=result)
    return result


def _mode_split_snapshot(pnl: dict, paper_account: Optional[dict] = None) -> dict[str, Any]:
    """Separate ledgers with one FIFO basis for holdings and performance."""
    paper = paper_account if paper_account is not None else _paper_account_snapshot()
    # The live ledger is read-only while this dashboard is in Paper mode, but
    # rebuilding its FIFO book on every websocket frame scanned the full order
    # history. Refresh it at most every two seconds; Paper accounting remains
    # on its one-second worker-aligned cache above.
    now = time.time()
    live = _live_account_cache.get("account")
    if live is None or now - float(_live_account_cache.get("ts", 0.0)) >= 2.0:
        live = accounting_snapshot(False, now=now)
        _live_account_cache.update(ts=now, account=live)
    balance = float(_state.get("balance_pusd") or 0.0)
    value = float(_state.get("value_usd") or 0.0)
    result = {}
    cumulative = _cumulative_performance()
    for lane, account in (("paper", paper), ("live", live)):
        summary = account["pnl"]
        by_asset = {
            asset: {"realized_usd": 0.0, "wins": 0, "losses": 0, "pending": 0, "open_value_usd": 0.0}
            for asset in ("BTC",)
        }
        by_asset.update(account["by_asset"])
        result[lane] = {
            "capital_base_usd": float(account.get("capital_base_usd") or cfg.paper_equity_usd) if lane == "paper" else max(balance + value, 1.0),
            **summary,
            "open_value_usd": account["open_value_usd"] if lane == "paper" else value,
            "valuation": "entry_cost" if lane == "paper" else "market",
            "by_asset": by_asset,
            "cumulative_realized_usd": (account.get("cumulative_realized_usd") if lane == "paper" and account.get("source") == "native_paper_ledger" else cumulative[lane]["realized_usd"]),
            "cumulative_wins": (account.get("cumulative_wins") if lane == "paper" and account.get("source") == "native_paper_ledger" else cumulative[lane]["wins"]),
            "cumulative_losses": (account.get("cumulative_losses") if lane == "paper" and account.get("source") == "native_paper_ledger" else cumulative[lane]["losses"]),
            "cumulative_by_asset": ({"BTC": {"realized_usd": account.get("cumulative_realized_usd", 0.0), "wins": account.get("cumulative_wins", 0), "losses": account.get("cumulative_losses", 0)}} if lane == "paper" and account.get("source") == "native_paper_ledger" else cumulative[lane]["by_asset"]),
            "gross_pnl_usd": account.get("pnl", {}).get("gross_pnl_usd"),
            "fees_usd": account.get("cumulative_fees_usd", account.get("pnl", {}).get("fees_usd")),
            "today_fees_usd": account.get("pnl", {}).get("fees_usd"),
            "slippage_usd": account.get("pnl", {}).get("slippage_usd"),
            "rebate_usd": account.get("pnl", {}).get("rebate_usd"),
            "net_pnl_usd": account.get("pnl", {}).get("net_pnl_usd"),
            # Fields consumed by the current Paper KPI/UI. They stay in the
            # Paper lane and are never mixed with live account values.
            "cash_usd": (float(account.get("capital_base_usd") or 0.0)
                         + float(account.get("cumulative_net_pnl_usd") or 0.0)
                         - float(account.get("open_value_usd") or 0.0)
                         - float(account.get("open_fees_usd") or 0.0)) if lane == "paper" and account.get("source") == "native_paper_ledger" else None,
            "equity_usd": (float(account.get("capital_base_usd") or 0.0)
                           + float(account.get("cumulative_net_pnl_usd") or 0.0)
                           - float(account.get("open_fees_usd") or 0.0)) if lane == "paper" and account.get("source") == "native_paper_ledger" else None,
            "daily_economic_pnl_usd": account.get("pnl", {}).get("net_pnl_usd") if lane == "paper" and account.get("source") == "native_paper_ledger" else None,
            "group": "NATIVE" if lane == "paper" and account.get("source") == "native_paper_ledger" else None,
            "stale": account.get("stale", False) if lane == "paper" and account.get("source") == "native_paper_ledger" else None,
            "equity_valuation": account.get("equity_valuation"),
            "slippage_included_in_execution_price": account.get("slippage_included_in_execution_price"),
            "source": account.get("source"),
        }
    if globals().get("_PAPER_COMPARISON_ENABLED", False):
        doc = _p3.read_summary()
        group = (doc.get("groups") or {}).get(_paper_primary_group()) or {}
        result["paper"].update(capital_base_usd=(doc.get("configuration") or {}).get("capital_usd"),
            equity_usd=group.get("equity_usd"), cash_usd=group.get("cash_usd"),
            fees_usd=group.get("fees_usd"), source="isolated_p3_public_paper", group=_paper_primary_group(),
            daily_economic_pnl_usd=group.get("daily_net_pnl_usd"), stale=doc.get("stale", True))
    return result

_paper_open_cache: dict[str, Any] = {"ts": 0.0, "day": 0.0, "account": None}


def _paper_account_snapshot() -> dict:
    """Use the native btc5m Paper ledger, falling back to legacy accounting."""
    native = _native_paper_account_snapshot()
    if native is not None:
        return native
    if globals().get("_PAPER_COMPARISON_ENABLED", False):
        return _p3.account()
    now = time.time()
    day = local_day_start_ts(now)
    account = _paper_open_cache.get("account")
    if account is None or now - float(_paper_open_cache["ts"]) >= 1.0 or _paper_open_cache["day"] != day:
        account = accounting_snapshot(True, now=now)
        _paper_open_cache.update(ts=now, day=day, account=account)
    return account


def _paper_positions_snapshot() -> list[dict]:
    return _paper_account_snapshot()["positions"]


def _paper_open_stats(positions: Optional[list[dict]] = None) -> tuple[int, float]:
    """Outstanding shares after FIFO exits; valuation is remaining entry cost."""
    rows = positions if positions is not None else _paper_positions_snapshot()
    return len(rows), round(sum(float(p["notional_usd"]) for p in rows), 4)


def _risk_snapshot(pnl: dict, paper_positions: Optional[list[dict]] = None) -> dict[str, Any]:
    if _native_paper_available() and not bool((_service_status_snapshot().get("BTC") or {}).get("live_enabled")):
        runtime = _native_paper_worker_runtime()
        account = _native_paper_account_snapshot() or {}
        actual = runtime.get("worker_config") or {}
        net = float((account.get("pnl") or {}).get("net_pnl_usd") or 0.0)
        limit_usd = actual.get("daily_loss_limit_usd")
        blocked = limit_usd is not None and float(limit_usd) > 0 and net <= -float(limit_usd)
        account_valid = bool(account.get("available") and not account.get("stale"))
        state_name = "NATIVE_RISK_UNAVAILABLE" if not account_valid or not runtime.get("configuration_verified") else "DAILY_LOSS_LIMIT" if blocked else "OK"
        return {"mode": "paper", "state": state_name, "source": "native_paper_ledger",
            "allow_entries": bool(runtime.get("worker_running") and runtime.get("configuration_verified") and account_valid and not blocked),
            "position_count": len(account.get("positions", [])), "position_value_usd": account.get("open_value_usd", 0.0),
            "valuation": "entry_cost", "capital_base_usd": account.get("capital_base_usd"),
            "max_open_positions": actual.get("max_open_positions"), "max_open_positions_per_asset": actual.get("max_open_positions"),
            "daily_realized_usd": net, "daily_pnl_usd": net, "daily_loss_limit_usd": limit_usd,
            "max_daily_loss_fraction": actual.get("max_daily_loss_fraction"),
            "daily_loss_limit_source": runtime.get("daily_loss_limit_source"),
            "worker_running": runtime.get("worker_running"), "worker_service_state": runtime.get("worker_service_state"),
            "updated_at": time.time(), "circuit_reason": "native daily loss limit" if blocked else None}
    live_enabled = bool((_service_status_snapshot().get("BTC") or {}).get("live_enabled"))
    if live_enabled:
        observed = read_live_risk_snapshot(cfg)
        holdings = _account_positions_snapshot()
        runtime = _live_worker_runtime("BTC")
        observed.update(position_count=observed.get("open_positions_count", holdings.get("pending_count")),
            position_value_usd=observed.get("position_value_usd", holdings.get("total_value_usd")),
            valuation="marked_account_equity", position_scope="BTC_account",
            max_open_positions=cfg.max_open_positions, max_open_positions_per_asset=cfg.max_open_positions,
            loss_recovery={"enabled": False, "mode": "live", "state": "DISABLED"},
            worker_running=runtime.get("worker_running"),
            worker_service_state=runtime.get("worker_service_state"))
        if not runtime.get("worker_running"):
            observed.update(allow_entries=False, execution_state="WORKER_STOPPED")
        return observed
    if globals().get("_PAPER_COMPARISON_ENABLED", False):
        doc = _p3.read_summary(); group = (doc.get("groups") or {}).get(_paper_primary_group()) or {}
        config = doc.get("configuration") or {}; runtime = _p3.read_runtime()
        return {"mode": "paper", "state": group.get("daily_block_reason") or "PAPER",
            "allow_entries": bool(runtime.get("worker_running") and not doc.get("stale") and group.get("daily_allow_entries")),
            "equity_usd": group.get("equity_usd"), "position_count": group.get("open_positions_count"),
            "position_value_usd": sum(float(p.get("cost_usd") or 0.) for p in group.get("positions", [])),
            "open_orders": group.get("pending_orders"), "max_open_positions": config.get("max_open_positions"),
            "max_daily_loss_fraction": config.get("max_daily_loss_fraction"),
            "max_daily_realized_profit_fraction": config.get("max_daily_realized_profit_fraction"),
            "daily_pnl_usd": group.get("daily_net_pnl_usd"), "source": "isolated_p3_public_paper",
            "worker_running": runtime.get("worker_running"), "worker_service_state": runtime.get("worker_service_state"),
            "loss_recovery": {"enabled": False, "state": "DISABLED"}}
    live_positions = _filter_active_positions(_state.get("positions") or [])
    position_value = 0.0
    for item in live_positions:
        try:
            position_value += float(item.get("size") or 0) * float(item.get("curPrice") or 0)
        except (TypeError, ValueError):
            continue
    if _state.get("bot_mode") == "live":
        positions = live_positions
    else:
        paper_count, paper_value = _paper_open_stats(paper_positions)
        positions = [None] * paper_count
        position_value = paper_value
    # Orders are read from SQLite rather than `_state`: the dashboard keeps
    # recent orders as a response-only query, so relying on `_state.orders`
    # silently reported zero open orders.
    open_order_notional = 0.0
    try:
        with closing(db()) as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(COALESCE(size, 0) * COALESCE(price, 0)), 0) FROM orders WHERE LOWER(COALESCE(status, '')) "
                "IN ('submitted','open','partial','partially_filled','pending') AND dry_run=?",
                (0 if _state.get("bot_mode") == "live" else 1,),
            ).fetchone()
        open_orders = int(row[0] or 0) if row else 0
        open_order_notional = float(row[1] or 0.0) if row else 0.0
    except Exception:
        open_orders = 0
    balance = _state.get("balance_pusd")
    equity = ((float(balance) if balance is not None else 0.0) + position_value
              if _state.get("bot_mode") == "live"
              else float(getattr(cfg, "paper_equity_usd", 0.0)))
    exposure_ratio = position_value / equity if equity > 0 else None
    risk_state = _risk_state(pnl)
    return {
        "state": risk_state,
        "position_count": len(positions),
        "position_value_usd": round(position_value, 4),
        "valuation": "market" if _state.get("bot_mode") == "live" else "entry_cost",
        "capital_base_usd": equity,
        "open_orders": open_orders,
        "open_order_notional_usd": round(open_order_notional, 4),
        "exposure_ratio": round(exposure_ratio, 6) if exposure_ratio is not None else None,
        "circuit_reason": None if risk_state == "OK" else risk_state,
        "daily_realized_usd": pnl.get("realized_usd"),
        "max_daily_realized_profit_fraction": float(getattr(cfg, "max_daily_realized_profit_fraction", 0.0) or 0.0),
        "daily_profit_target_usd": daily_profit_target_usd(cfg, _state.get("bot_mode") != "live"),
        "loss_recovery": _paper_guard_snapshot(),
        "daily_profit_rate": (
            float(pnl.get("realized_usd") or 0.0) / equity if equity > 0 else None
        ),
        "max_daily_loss_fraction": cfg.max_daily_loss_fraction,
        # Paper lanes are isolated by asset; expose both the per-asset gate
        # and the aggregate display capacity so 5/12 is not misread as 5/3.
        "max_open_positions": cfg.max_open_positions * (4 if _state.get("bot_mode") != "live" else 2),
        "max_open_positions_per_asset": cfg.max_open_positions,
        "position_scope": "per_asset",
        "updated_at": time.time(),
    }


def _stop_loss_snapshot() -> dict[str, Any]:
    """Expose the deterministic maybe_reversal_exit guard and last event."""
    mode = "live" if (_service_status_snapshot().get("BTC") or {}).get("live_enabled") else "paper"
    enabled = bool(getattr(cfg, "reversal_exit_enabled", False) or getattr(cfg, "early_reversal_exit_enabled", False))
    threshold = float(getattr(cfg, "reversal_held_bid_threshold", 0.0) or 0.0)
    drawdown = float(getattr(cfg, "reversal_held_bid_drawdown", 0.0) or 0.0)
    trigger = (f"持仓盘口 ≤ {threshold:.2f}" if threshold > 0 else f"持仓盘口回撤 ≥ {drawdown * 100:.1f}%")
    # Disabled early-exit settings must not override the active 90s guard.
    normal_enabled = bool(getattr(cfg, "reversal_exit_enabled", False))
    early_enabled = bool(getattr(cfg, "early_reversal_exit_enabled", False))
    window = max(float(getattr(cfg, "reversal_exit_window_sec", 0.0)) if normal_enabled else 0.0,
                 float(getattr(cfg, "early_reversal_exit_window_sec", 0.0)) if early_enabled else 0.0)
    confirmations = max(int(getattr(cfg, "reversal_confirm_checks", 0)) if normal_enabled else 0,
                        int(getattr(cfg, "early_reversal_confirm_checks", 0)) if early_enabled else 0)
    result: dict[str, Any] = {}
    # The Paper worker has a separate PID marker and must not be reported as
    # a stopped protection process merely because the live worker is off.
    workers = _paper_process_status_base() if mode == "paper" else _live_process_status_base()
    open_paper = remaining_positions(True) if mode == "paper" else []
    for asset in ("BTC",):
        item: dict[str, Any] = {"enabled": enabled, "mode": mode, "status": ("已启用 · 等待触发" if enabled else "未启用"), "trigger": trigger, "window_sec": window, "confirmations": confirmations, "last_exit": None}
        if mode == "paper" and normal_enabled:
            item.update(coverage="configured_window", window_sec=window)
        try:
            dry = 0 if mode == "live" else 1
            with db() as c:
                row = c.execute("SELECT ts,status,side,error,price,filled_size FROM orders WHERE UPPER(COALESCE(asset,''))=? AND dry_run=? AND side LIKE 'SELL_%' ORDER BY id DESC LIMIT 1", (asset, dry)).fetchone()
            if row:
                status = str(row[1] or "")
                item["last_exit"] = {"ts": row[0], "status": status, "side": row[2], "reason": row[3], "price": row[4], "filled_size": row[5]}
                if enabled:
                    effective = status in ("exit_filled", "exit_matched", "exit_partial", "exit_dry_run")
                    item["status"] = (("已启用 · 有 Paper 退出" if dry else "已启用 · 有实盘退出") if effective else "已启用 · 最近退出待核查")
            if mode == "paper" and enabled:
                pending_conditions = {p["condition_id"] for p in open_paper if p.get("asset") == asset}
                if pending_conditions:
                    with db() as c:
                        decision = c.execute(
                            "SELECT ts,condition_id,action,reason FROM decisions WHERE asset=? AND dry_run=1 "
                            "AND action IN ('SKIP_EXIT_BOOK','SKIP_EXIT_SIZE') AND ts>? ORDER BY id DESC LIMIT 1",
                            (asset, time.time() - 30),
                        ).fetchone()
                    if decision and decision[1] in pending_conditions:
                        item["status"] = "已启用 · 等待盘口" if decision[2] == "SKIP_EXIT_BOOK" else "已启用 · 等待成交深度"
                        item["execution_wait"] = {"ts": decision[0], "action": decision[2], "reason": decision[3]}
        except Exception:
            pass
        item["running"] = bool(workers.get(asset))
        if enabled and not item["running"]:
            item["status"] = "保护进程未运行"
        result[asset] = item
    return result


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
            if float(cp) < 0.0 or float(sz) <= 0.0:
                continue
        except Exception:
            continue
        if bool(p.get("redeemable")):
            continue
        out.append(p)
    return out


def _filter_settled_positions(positions: list[dict]) -> list[dict]:
    """Keep resolved positions visible in a separate settlement section."""
    out: list[dict] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        if bool(position.get("redeemable")) and float(position.get("size") or 0) > 0:
            out.append(position)
    return out


def _compact_sports_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Keep the 500ms dashboard poll small; detailed sports data is not needed by the card."""
    if not isinstance(meta, dict):
        return {}
    compact = {key: meta.get(key) for key in ("enabled", "mode", "status", "paper_only", "live_orders", "running", "heartbeat_ts", "market_count", "decision_count", "order_count", "orders_new", "settled_new", "error") if key in meta}
    if isinstance(meta.get("recent_decisions"), list):
        compact["recent_decisions"] = meta["recent_decisions"][-10:]
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


def _feed_snapshot() -> dict[str, Any]:
    weather = _state.get("weather_meta") or {}
    sports = _state.get("sports_meta") or {}
    return {
        "kalshi_weather": dict(weather.get("feed") or {}),
        "odds": dict(sports.get("feed") or {}),
    }


@app.get("/api/polymarket/profile")
def polymarket_profile():
    return _portfolio_snapshot()


@app.get("/api/polymarket/activity")
def polymarket_activity(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), kind: str = Query("", max_length=16)):
    try:
        return _polymarket_activity_rows(limit=limit, offset=offset, kind=kind)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Polymarket activity temporarily unavailable") from exc


@app.get("/api/polymarket/ledger")
def polymarket_ledger():
    return _funding_snapshot()



def _native_paper_available() -> bool:
    return _native_paper_account_snapshot() is not None


def _sol5m_orders_page(offset: int = 0, limit: int = 50, lane: str = "paper",
                       start_ts: Optional[float] = None, end_ts: Optional[float] = None) -> dict[str, Any]:
    """Normalize SOL5M Paper fills into the dashboard order contract."""
    empty = {"rows": [], "total": 0, "today_total": 0, "offset": offset, "limit": limit,
             "source": "sol5m-paper-ledger"}
    if lane == "live" or not SOL5M_PAPER_DB.exists():
        return empty
    try:
        with sqlite3.connect(SOL5M_PAPER_DB, timeout=3.0) as c:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout=3000")
            where = ["dry_run=1"]; params: list[Any] = []
            if start_ts is not None: where.append("ts>=?"); params.append(start_ts)
            if end_ts is not None: where.append("ts<?"); params.append(end_ts)
            clause = " WHERE " + " AND ".join(where)
            total = int(c.execute("SELECT COUNT(*) FROM fills" + clause, params).fetchone()[0] or 0)
            today_total = int(c.execute("SELECT COUNT(*) FROM fills" + clause + " AND ts>=?",
                                        [*params, local_day_start_ts()]).fetchone()[0] or 0)
            rows = c.execute(
                "SELECT id,ts,market_slug,condition_id,side,token_id,size,price,notional_usd,"
                "fee_usd,slippage_usd,liquidity,strategy,dry_run,order_id,note FROM fills"
                + clause + " ORDER BY ts DESC,id DESC LIMIT ? OFFSET ?",
                [*params, max(1, min(int(limit), 200)), max(0, int(offset))]).fetchall()
            positions = c.execute(
                "SELECT market_slug,token_id,status,pnl_usd,pnl_net_usd,closed_ts FROM positions "
                "WHERE dry_run=1 ORDER BY id DESC").fetchall()
    except (OSError, sqlite3.Error):
        return empty
    pos_by_key: dict[tuple[str, str], sqlite3.Row] = {}
    for pos in positions:
        pos_by_key.setdefault((str(pos["market_slug"]), str(pos["token_id"])), pos)
    out=[]
    for row in rows:
        item=dict(row); source_id=int(item["id"])
        pos=pos_by_key.get((str(item.get("market_slug") or ""), str(item.get("token_id") or "")))
        closed=bool(pos and pos["closed_ts"] is not None); net=None if not pos else pos["pnl_net_usd"]
        # A fill's stored fee is a positive absolute cost in this legacy
        # table. Expose the dashboard contract with signed cash economics so
        # every consumer displays the cost as a negative amount.
        notional = abs(float(item.get("notional_usd") or 0.0))
        gross_pnl = None if pos is None else pos["pnl_usd"]
        item.update({"id": 2_000_000_000+source_id, "source_id": source_id, "asset": "SOL",
            "product": "SOL5M", "source": "sol5m-paper-ledger", "cashflow_usd": -notional,
            "fee_usd": -abs(float(item.get("fee_usd") or 0.0)),
            "fees_usd": -abs(float(item.get("fee_usd") or 0.0)),
            "filled_size": item.get("size"), "status": "filled", "error": None,
            "entry_rule": item.get("strategy") or "sol5m", "record_key": "sol-paper:"+str(source_id),
            "result": ("HIT" if float(net or 0.0)>=0 else "MISS") if closed and net is not None else "PENDING",
            "settled": closed, "winning_token": None, "resolved_ts": pos["closed_ts"] if pos else None,
            "pnl_usd": gross_pnl, "gross_pnl_usd": gross_pnl,
            "pnl_net_usd": net, "net_pnl_usd": net})
        out.append(item)
    return {"rows": out, "total": total, "today_total": today_total, "offset": offset,
            "limit": limit, "source": "sol5m-paper-ledger"}

def _sol5m_daily_rows() -> list[dict[str, Any]]:
    """Daily settled SOL5M Paper rows, isolated from the BTC ledger."""
    if not SOL5M_PAPER_DB.exists():
        return []
    try:
        with sqlite3.connect(SOL5M_PAPER_DB, timeout=3.0) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT closed_ts,pnl_usd,pnl_net_usd,fee_usd,liquidity "
                             "FROM positions WHERE dry_run=1 AND closed_ts IS NOT NULL").fetchall()
    except (OSError, sqlite3.Error):
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = _bj_day(row["closed_ts"])
        item = grouped.setdefault(day, {"day": day, "pnl_usd": 0.0, "gross_pnl_usd": 0.0,
            "fees_usd": 0.0, "slippage_usd": 0.0, "rebate_usd": 0.0, "net_pnl_usd": 0.0,
            "wins": 0, "losses": 0, "trades": 0, "settled": 0, "pending": 0,
            "maker_fee_usd": 0.0, "taker_fee_usd": 0.0, "source": "sol5m-paper-ledger"})
        gross=float(row["pnl_usd"] or 0.0); fee=-abs(float(row["fee_usd"] or 0.0))
        net=float(row["pnl_net_usd"] if row["pnl_net_usd"] is not None else gross+fee)
        item["pnl_usd"] += gross; item["gross_pnl_usd"] += gross; item["fees_usd"] += fee
        item["net_pnl_usd"] += net; item["wins" if net >= 0 else "losses"] += 1
        item["trades"] += 1; item["settled"] += 1
        item["maker_fee_usd" if str(row["liquidity"] or "taker").lower() == "maker" else "taker_fee_usd"] += fee
    for item in grouped.values():
        item["return_rate"] = None
    return sorted(grouped.values(), key=lambda x: x["day"], reverse=True)

def _local_orders_page(offset: int, limit: int, lane: str, audit: bool = False,
                       start_ts: Optional[float] = None, end_ts: Optional[float] = None) -> dict[str, Any]:
    """Keep execution attempts in the audit view; display only Paper fills."""
    if lane == "paper" and not audit and _native_paper_available():
        return _native_paper_orders_page(offset, limit, start_ts, end_ts)
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and lane == "paper" and not audit:
        return _p3.orders_page(offset, limit, start_ts, end_ts)
    if not DB_PATH.exists():
        return {"rows": [], "total": 0, "today_total": 0, "offset": offset, "limit": limit, "source": "ledger"}
    with closing(db()) as c:
        c.execute("BEGIN")
        where = ["UPPER(COALESCE(o.asset,'BTC'))='BTC'"]
        params = []
        if not audit:
            where.extend(["o.dry_run=1", "o.size>0", "o.status IN ('dry_run','exit_dry_run','filled','matched','exit_filled','exit_matched','exit_partial')"])
        elif lane != "all":
            where.append("o.dry_run=?")
            params.append(1 if lane == "paper" else 0)
        if start_ts is not None:
            where.append("o.ts>=?")
            params.append(start_ts)
        if end_ts is not None:
            where.append("o.ts<?")
            params.append(end_ts)
        clause = " WHERE " + " AND ".join(where)
        total = int(c.execute("SELECT COUNT(*) FROM orders o" + clause, params).fetchone()[0] or 0)
        today_total = int(c.execute("SELECT COUNT(*) FROM orders o" + clause + " AND o.ts>=?", [*params, local_day_start_ts()]).fetchone()[0] or 0)
        rows_sql = """SELECT o.id,o.ts,o.market_slug,o.condition_id,o.token_id,o.asset,o.side,
                    o.size,o.price,o.order_id,o.status,o.filled_size,o.error,o.dry_run,o.entry_rule,
                    r.winning_token, r.resolved_ts
                    FROM orders o LEFT JOIN resolutions r ON r.condition_id=o.condition_id""" + clause + " ORDER BY o.ts DESC,o.id DESC LIMIT ? OFFSET ?"
        rows = [dict(row) for row in c.execute(rows_sql, [*params, limit, offset]).fetchall()]
    for row in rows:
        row.update(source="ledger", record_key=("paper:" if row["dry_run"] else "audit-live:") + str(row["id"]), result="NONE", settled=False)
    return {"rows": rows, "total": total, "today_total": today_total, "offset": offset, "limit": limit, "source": "ledger"}


@app.get("/api/orders/audit")
def orders_audit(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200),
                 lane: Literal["all", "paper", "live"] = "all"):
    return {**_local_orders_page(offset, limit, lane, audit=True), "lane": lane, "source": "execution_audit"}


@app.get("/api/orders")
def orders_page(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200),
                lane: Literal["all", "paper", "live"] = "all", asset: str = "",
                start_ts: Optional[float] = Query(None, ge=0),
                end_ts: Optional[float] = Query(None, ge=0)):
    # Direct Python callers, unlike FastAPI requests, receive Query defaults.
    start_ts = start_ts if isinstance(start_ts, (int, float)) else None
    end_ts = end_ts if isinstance(end_ts, (int, float)) else None
    if ((start_ts is not None and not math.isfinite(start_ts))
            or (end_ts is not None and not math.isfinite(end_ts))
            or (start_ts is not None and end_ts is not None and end_ts <= start_ts)):
        raise HTTPException(status_code=422, detail="起止时间无效：结束时间必须晚于开始时间")
    asset_name = asset.strip().upper() or "ALL"
    if lane == "paper":
        selected = pc.PRODUCTS.values() if asset_name == "ALL" else [pc.find(asset_name)]
        return {**pr.fills(selected, offset, limit, start_ts, end_ts), "asset": asset_name}
    if asset_name == "BTC5M":
        asset_name = "BTC"
    if asset_name == "BTC15M":
        if lane == "all":
            return {**pr.fills([pc.find(asset_name)], offset, limit, start_ts, end_ts),
                    "asset": asset_name, "lane": "all"}
        return {"rows": [], "total": 0, "today_total": 0, "lane": lane, "asset": asset_name,
                "source": "inactive_live_lane", "available": False, "offset": offset, "limit": limit}
    if asset_name in ("SOL", "SOL5M"):
        page = _sol5m_orders_page(offset, limit, "paper" if lane != "live" else "live", start_ts, end_ts)
        return {**page, "lane": lane, "asset": "SOL"}
    if asset_name not in ("BTC", "ALL"):
        raise HTTPException(status_code=422, detail="Unsupported asset")
    try:
        chain = _polymarket_activity_rows(limit=limit if lane == "live" else offset + limit,
                                          offset=offset if lane == "live" else 0,
                                          start_ts=start_ts, end_ts=end_ts, include_period=True)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Polymarket activity temporarily unavailable") from exc
    if lane == "live":
        return {**chain, "lane": lane, "asset": asset_name}
    selected = pc.PRODUCTS.values() if asset_name == "ALL" else [pc.find(asset_name)]
    paper = pr.fills(selected, 0, offset + limit, start_ts, end_ts)
    combined = sorted(chain["rows"] + paper["rows"], key=lambda row: (float(row.get("ts") or 0), str(row.get("record_key") or row.get("id") or "")), reverse=True)
    return {**chain, "rows": combined[offset:offset + limit], "total": chain["total"] + paper["total"],
            "offset": offset, "limit": limit, "source": "chain_and_product_paper", "lane": lane, "asset": asset_name}


@app.get("/api/state")
def state():
    m = _state.get("market")
    eth_m = _state.get("eth_market")
    now = time.time()
    # In Paper mode the isolated ledger is the only source used by the
    # dashboard.  Avoid synchronously querying Polymarket profile/PnL/activity
    # on every state frame: those public endpoints can take 8--20 seconds and
    # previously left the WebSocket and REST UI blank while Paper was healthy.
    # Live mode still executes the full chain snapshot below.
    service_modes = _service_status_snapshot()
    active_lane = "live" if (service_modes.get("BTC") or {}).get("live_enabled") else "paper"
    btc_paper_account = _paper_account_snapshot()
    product_paper = _product_paper_snapshot()
    paper_account = _combined_paper_account(product_paper)
    if active_lane == "live":
        holdings = _account_positions_snapshot()
    else:
        holdings = {
            "available": paper_account.get("available", True), "stale": paper_account.get("stale", False), "source": paper_account.get("source", "native_paper_ledger"),
            "updated_at": paper_account.get("updated_at", now), "error": paper_account.get("error"),
            "positions": paper_account.get("positions", []),
            "settled_positions": paper_account.get("settled_positions", []),
            "pending_count": paper_account.get("pending"),
            # Native closed positions have already credited Paper cash.
            # They are history, not chain positions waiting for redemption.
            "redeemable_count": 0,
            "settled_count": len(paper_account.get("settled_positions", [])),
            "pending_value_usd": paper_account.get("open_value_usd", 0.0),
            "active_value_usd": paper_account.get("open_value_usd", 0.0),
            "redeemable_value_usd": 0.0,
            "total_value_usd": paper_account.get("open_value_usd", 0.0),
        }
    active_positions = holdings["positions"]
    settled_positions = holdings["settled_positions"]
    pending_settlement_count = holdings.get("pending_count")
    redeemable_count = holdings.get("redeemable_count")
    portfolio = _portfolio_snapshot(holdings) if active_lane == "live" else {
        "available": bool(paper_account.get("available")), "source": paper_account.get("source", "native_paper_ledger"),
        "balance_usd": paper_account.get("cash_usd"),
        "position_value_usd": holdings.get("total_value_usd"),
        "pending_count": holdings.get("pending_count", 0), "redeemable_count": holdings.get("redeemable_count", 0),
        "pending_value_usd": holdings.get("pending_value_usd", 0.0), "redeemable_value_usd": holdings.get("redeemable_value_usd", 0.0),
        "portfolio_value_usd": paper_account.get("equity_usd"),
        "live_summary": None,
    }
    external = portfolio.get("live_summary") if isinstance(portfolio, dict) else None
    risk_pnl = realized_pnl_today() if _state.get("bot_mode") == "live" else btc_paper_account["pnl"]
    pnl = ({**risk_pnl, "realized_usd": (external or {}).get("today_economic_pnl_usd"),
            "wins": (external or {}).get("today_wins"), "losses": (external or {}).get("today_losses"),
            "pending": pending_settlement_count, "source": "chain"}
           if active_lane == "live" else paper_account["pnl"])
    paper_positions = paper_account["positions"]
    use_decision_log_fallback = "rtds" not in cfg.price_signal_source.strip().lower()
    btc_signal = _state.get("btc_signal") or (
        _fallback_signal_from_decisions("BTC") if use_decision_log_fallback else None
    )
    eth_signal = _state.get("eth_signal") or (
        _fallback_signal_from_decisions("ETH") if use_decision_log_fallback else None
    )
    mode_split = _mode_split_snapshot(pnl, btc_paper_account)
    _apply_combined_paper_lane(mode_split, product_paper)
    if active_lane == "live":
        mode_split["live"].update({
            "pending": pending_settlement_count, "redeemable_count": redeemable_count,
            "open_value_usd": holdings.get("total_value_usd"),
            "pending_value_usd": holdings.get("pending_value_usd"),
            "redeemable_value_usd": holdings.get("redeemable_value_usd"),
        })
    # The account lane is chain-authoritative whenever the live gate is enabled,
    # even if the worker is currently stopped. This keeps the dashboard aligned
    # with Polymarket after a manual trade or redemption.
    if isinstance(external, dict):
        live_lane = dict(mode_split.get("live") or {})
        today_realized = external.get("today_realized_usd")
        live_realized = external.get("realized_usd")
        live_wins = external.get("wins")
        live_losses = external.get("losses")
        today_wins = external.get("today_wins")
        today_losses = external.get("today_losses")
        live_lane.update({
            # Top-level lane values are today's values; cumulative_* are the
            # account-wide values from Polymarket v2 user-pnl/activity.
            "realized_usd": today_realized,
            "wins": today_wins,
            "losses": today_losses,
            "cumulative_realized_usd": live_realized,
            "cumulative_trade_pnl_usd": external.get("trade_pnl_usd"),
            "cumulative_economic_pnl_usd": external.get("economic_usd"),
            "fees_usd": external.get("fees_usd"),
            "today_trade_pnl_usd": external.get("today_trade_pnl_usd"),
            "today_economic_pnl_usd": external.get("today_economic_pnl_usd", today_realized),
            "today_fees_usd": external.get("today_fees_usd"),
            "today_rebates_usd": external.get("today_rebates_usd"),
            "cumulative_wins": live_wins,
            "cumulative_losses": live_losses,
            "pending": pending_settlement_count,
            "external_source": external.get("source"),
            "rolling_24h_usd": external.get("rolling_24h_usd"),
            "rolling_24h_base_ts": external.get("rolling_24h_base_ts"),
            "rolling_24h_updated_ts": external.get("rolling_24h_updated_ts"),
        })
        live_lane["cumulative_by_asset"] = {"BTC": {
            "realized_usd": live_realized,
            "wins": live_wins,
            "losses": live_losses,
            "pending": pending_settlement_count,
            "open_value_usd": float(holdings.get("total_value_usd") or 0.0),
        }}
        live_lane["capital_base_usd"] = _live_day_capital()
        live_lane["live_risk"] = read_live_risk_snapshot(cfg)
        live_lane["by_asset"] = {"BTC": {
            "realized_usd": live_lane.get("realized_usd"),
            "wins": live_lane.get("wins", 0),
            "losses": live_lane.get("losses", 0),
            "pending": live_lane.get("pending", 0),
            "open_value_usd": float(holdings.get("total_value_usd") or 0.0),
        }}
        mode_split["live"] = live_lane
    chain_snapshot = {
        "available": bool(isinstance(external, dict) and external.get("available")),
        "stale": bool(isinstance(external, dict) and external.get("stale")),
        "source": (external or {}).get("source") if isinstance(external, dict) else None,
        "data_provenance": "Polymarket Data API v2 user-pnl + user-stats + activity",
        "data_as_of": (external or {}).get("data_as_of") if isinstance(external, dict) else None,
        "data_age_sec": (external or {}).get("data_age_sec") if isinstance(external, dict) else None,
        "updated_at": (external or {}).get("updated_at") if isinstance(external, dict) else None,
        "financial_source": (external or {}).get("financial_source"),
        "source_fidelity": (external or {}).get("source_fidelity"),
        "activity_as_of": (external or {}).get("activity_as_of"),
        "activity_updated_at": (external or {}).get("activity_updated_at"),
        "activity_ahead_of_pnl": (external or {}).get("activity_ahead_of_pnl"),
        "activity_stale": (external or {}).get("activity_stale"),
        "today_summary": next((row for row in (external or {}).get("daily_rows", []) if row.get("day") == datetime.fromtimestamp(now, timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")), None) if isinstance(external, dict) else None,
        "live_summary": external if isinstance(external, dict) else None,
        "holdings": holdings if active_lane == "live" else None,
    }
    product_views = {key: pr.details(p, product_paper[p.asset], pc.snapshot(p), pr.fills([p], 0, 30))
                     for key, p in pc.PRODUCTS.items()}
    paper_order_total = sum(v["order_count"] for v in product_views.values())
    today_paper_total = sum(v["today_order_count"] for v in product_views.values())
    product_decisions = sorted((r for v in product_views.values() for r in v["decisions"]),
                               key=lambda r: (r["ts"], r["product_key"], r["id"]), reverse=True)
    product_orders = sorted((r for v in product_views.values() for r in v["orders"]),
                            key=lambda r: (r["ts"], r["product_key"], r["id"]), reverse=True)
    live_order_total = (external or {}).get("activity_count")
    lane_counts = _lane_counts()
    today_counts = _today_counts()
    since = int(local_day_start_ts())
    decision_total = (sum(v["decision_count"] for v in product_views.values())
                      if all(v["decision_count"] is not None for v in product_views.values()) else None)
    today_decisions = (sum(v["today_decision_count"] for v in product_views.values())
                       if decision_total is not None else None)
    lane_counts["paper"] = {"orders": paper_order_total, "today_orders": today_paper_total,
                            "decisions": decision_total, "today_decisions": today_decisions, "since": since}
    if active_lane == "paper":
        today_counts = {"orders": today_paper_total, "decisions": today_decisions, "since": since}
    if globals().get("_PAPER_COMPARISON_ENABLED", False):
        counts = _p3.counts()
        lane_counts["paper"] = counts
        if active_lane == "paper":
            today_counts = {"decisions": counts["today_decisions"], "orders": counts["today_orders"], "since": counts["since"]}
    return {
        "now": now,
        "paper_comparison": _p3.read_summary() if globals().get("_PAPER_COMPARISON_ENABLED", False) else None,
        "bot_running": bool((service_modes.get("BTC") or {}).get("running")),
        "production_runtime": (_live_worker_runtime("BTC") if active_lane == "live" else _paper_worker_daily_loss("polymarket-test-btc-paper.service", ROOT.parent.parent, DB_PATH)),
        "bot_mode": active_lane if bool((service_modes.get("BTC") or {}).get("running")) else "stopped",
        "bot_assets": {v["asset"]: v["paper_enabled"] for v in product_views.values()} if active_lane=="paper" else {"BTC": bool(_state.get("bot_assets", {}).get("BTC"))},
        "products_by_key": product_views,
        "instance": _deployment_instance_name(),
        "service_modes": service_modes,
        "paper_services": _paper_services_snapshot(),
        "risk_state": (read_live_risk_snapshot(cfg).get("state", "ACCOUNTING_UNAVAILABLE") if active_lane == "live" else (_risk_snapshot(risk_pnl, btc_paper_account.get("positions", [])).get("state") if _native_paper_available() else _risk_state(risk_pnl))),
        "risk_snapshot": _risk_snapshot(risk_pnl, btc_paper_account.get("positions", [])),
        "stop_loss": _stop_loss_snapshot(),
        "wallet": {
            "eoa": cfg.wallet_address,
            "deposit": _deposit_wallet_address(),
            "funder": cfg.funder_address,
            "balance_pusd": _state.get("balance_pusd"),
            "pending_deposit_usd": _state.get("balance_usdce"),
            "fund_activation": portfolio.get("fund_activation"),
            "value_usd": holdings.get("total_value_usd"),
            "value_source": holdings.get("source"),
            "position_value_usd": holdings.get("active_value_usd"),
            "pending_value_usd": holdings.get("pending_value_usd"),
            "redeemable_value_usd": holdings.get("redeemable_value_usd"),
            "pending_count": pending_settlement_count,
            "redeemable_count": redeemable_count,
            "snapshot_updated_at": holdings.get("updated_at"),
            "snapshot_stale": bool(holdings.get("stale")),
            "binding": _wallet_status(),
            "polymarket_profile": portfolio,
        },
        "polymarket_profile": portfolio,
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
        "feeds": _feed_snapshot(),
        "agent_status": _agent_status_snapshot(),
        "openclaw_bridge": _openclaw_bridge_snapshot(),
        "llm": {
            "settings": {
                "primary_model": _llm_settings_response().get("primary", {}).get("model", ""),
                "secondary_model": _llm_settings_response().get("secondary", {}).get("model", ""),
            },
            "usage": _llm_usage_snapshot(),
        },
        "positions": active_positions,
        "product_paper": product_paper,
        "paper_risk_by_asset": {v["asset"]: v["risk"] for v in product_views.values()},
        "paper_positions": paper_positions,
        "paper_settled_positions": paper_account.get("settled_positions", []),
        "paper_settled_count": len(paper_account.get("settled_positions", [])),
        "settled_positions": settled_positions,
        "portfolio_positions": holdings,
        "pending_settlement_count": pending_settlement_count,
        "redeemable_count": redeemable_count,
        "paper_holdings": holdings if active_lane == "paper" else None,
        "chain_holdings": {
            "pending_count": pending_settlement_count if active_lane == "live" else None,
            "redeemable_count": redeemable_count if active_lane == "live" else None,
            "pending_value_usd": holdings.get("pending_value_usd") if active_lane == "live" else None,
            "redeemable_value_usd": holdings.get("redeemable_value_usd") if active_lane == "live" else None,
            "total_value_usd": holdings.get("total_value_usd") if active_lane == "live" else None,
            "available": bool(active_lane == "live" and holdings.get("available")),
            "stale": bool(active_lane == "live" and holdings.get("stale")),
            "updated_at": holdings.get("updated_at") if active_lane == "live" else None,
            "sync_status": holdings.get("sync_status", "ok" if not holdings.get("stale") else "indexing") if active_lane == "live" else "inactive_lane",
            "last_empty_ts": holdings.get("last_empty_ts") if active_lane == "live" else None,
            "source": holdings.get("source") if active_lane == "live" else None,
        },
        # This is included in every REST and WebSocket state frame so the UI
        # does not need a second polling path for official live PnL/fees.
        "chain_snapshot": chain_snapshot,
        "pnl": pnl,
        "mode_split": mode_split,
        "active_lane": active_lane,
        "active_lane_counts": lane_counts,
        "today_counts": today_counts,
        "orders_total": paper_order_total + live_order_total if live_order_total is not None else None,
        "audit_orders_total": _orders_total(),
        "order_counts": {"paper": paper_order_total, "live": live_order_total,
                         "today_paper": today_paper_total,
                         "today_live": (external or {}).get("today_activity_count")},
        "decisions_total": decision_total if active_lane == "paper" else _decisions_total(),
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
            "entry_order_mode": cfg.entry_order_mode,
            "entry_maker_order_type": cfg.entry_maker_order_type,
            "entry_maker_ttl_sec": cfg.entry_maker_ttl_sec,
            "entry_maker_post_only": cfg.entry_maker_post_only,
            "entry_maker_fallback_taker": cfg.entry_maker_fallback_taker,
            "profit_exit_enabled": cfg.profit_exit_enabled,
            "profit_exit_confirm_checks": cfg.profit_exit_confirm_checks,
            "profit_exit_fraction": cfg.profit_exit_fraction,
            "take_profit_enabled": getattr(cfg, "take_profit_enabled", cfg.profit_exit_enabled),
            "take_profit_min_gain_fraction": getattr(cfg, "take_profit_min_gain_fraction", cfg.profit_target_fraction),
            "take_profit_exit_fraction": getattr(cfg, "take_profit_exit_fraction", cfg.profit_exit_fraction),
            "max_hold_seconds": cfg.max_hold_seconds,
            "expiry_exit_enabled": getattr(cfg, "expiry_exit_enabled", False),
            "expiry_exit_seconds": getattr(cfg, "expiry_exit_seconds", 30.0),
            "expiry_exit_fraction": getattr(cfg, "expiry_exit_fraction", 1.0),
            "profit_exit_order_mode": cfg.profit_exit_order_mode,
            "profit_target_fraction": cfg.profit_target_fraction,
            "profit_target_ticks": cfg.profit_target_ticks,
            "profit_maker_order_type": cfg.profit_maker_order_type,
            "profit_maker_ttl_sec": cfg.profit_maker_ttl_sec,
            "profit_maker_post_only": cfg.profit_maker_post_only,
            "profit_maker_fallback_taker": cfg.profit_maker_fallback_taker,
            "stop_exit_order_mode": cfg.stop_exit_order_mode,
            "reversal_exit_order_mode": cfg.reversal_exit_order_mode,
            "near_close_exit_enabled": cfg.near_close_exit_enabled,
            "near_close_exit_window_sec": cfg.near_close_exit_window_sec,
            "near_close_exit_order_mode": cfg.near_close_exit_order_mode,
            "max_daily_loss_fraction": cfg.max_daily_loss_fraction,
            "max_daily_realized_profit_fraction": getattr(cfg, "max_daily_realized_profit_fraction", 0.0),
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
        "decisions": product_decisions[:80] if active_lane == "paper" else recent_decisions(limit=80,lane="live"),
        "orders": product_orders[:30] if active_lane == "paper" else recent_orders(limit=30,lane="live"),
        "errors": _state.get("errors") or {},
    }


@app.get("/api/sports/summary")
def sports_summary():
    """Read the durable worker snapshot even during dashboard cold start."""
    return read_paper_feed_snapshot("SPORTS")


def _live_day_capital(day: Optional[str] = None) -> Optional[float]:
    """Only a proved and frozen Beijing midnight equity is an ROI base."""
    if day is None:
        capital = chain_number(read_live_risk_snapshot(cfg), "capital_base_usd")
        if capital is not None and capital > 0:
            return capital
        # A frozen midnight proof remains valid as an ROI denominator even
        # when the worker's current valuation has expired. Entry admission
        # continues to require a fresh complete shared risk snapshot.
        day = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return None
    wallet = _deposit_wallet_address().lower()
    target = live_risk_state_file()
    baseline = target.with_name(f"{target.stem}.{wallet}.{day}.baseline.json")
    try:
        value = json.loads(baseline.read_text(encoding="utf-8"))
        if value.get("wallet") != wallet:
            return None
        capital = chain_number(value, "day_start_equity_usd")
        return capital if capital is not None and capital > 0 else None
    except (OSError, ValueError, TypeError):
        return None


def _chain_capital_base() -> Optional[float]:
    balance = chain_number(_state, "balance_pusd")
    value = chain_number(_account_positions_snapshot(), "total_value_usd")
    return balance + value if balance is not None and value is not None and balance + value > 0 else None


@app.get("/api/pnl/daily")
def pnl_daily(lane: Literal["paper", "live"] = "paper",
              offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=365),
              asset: str = "", source: Literal["ledger", "chain"] = "ledger"):
    """Return daily PnL with an explicit lane-owned source of truth.

    Live account history is authoritative from Polymarket's public PnL
    snapshots.  Older clients omitted ``source`` and therefore accidentally
    read the local execution ledger; that ledger contains failed/cancelled
    attempts and is valid only for Paper.  Keep the query parameter for
    compatibility, but force the safe source by lane.
    """
    from server.pnl_history import daily_rows
    asset_name = asset.strip().upper() or "BTC"
    if lane == "paper":
        selected = "ALL" if asset_name == "ALL" else pc.find(asset_name).asset
        return _product_paper_daily_page(selected, offset, limit)
    if asset_name == "BTC5M":
        asset_name = "BTC"
    if lane == "live" and asset_name in ("SOL", "SOL5M", "BTC15M"):
        return {"lane": lane, "asset": asset_name, "rows": [], "total_days": 0,
                "capital_base_usd": None, "offset": offset, "limit": limit,
                "available": False, "stale": False, "error": "SOL live accounting is not enabled",
                "source": "inactive_live_lane"}
    if asset_name != "BTC":
        raise HTTPException(status_code=422, detail="Unsupported asset")
    if globals().get("_PAPER_COMPARISON_ENABLED", False) and lane == "paper":
        return _p3.daily_page(offset, limit)
    effective_source = "chain" if lane == "live" else "ledger"
    if lane == "live" and effective_source == "chain":
        external = _polymarket_live_summary()
        rows = [dict(row, capital_base_usd=_live_day_capital(row.get("day")))
                for row in (external.get("daily_rows") or [])] if isinstance(external, dict) else []
        bj = timezone(timedelta(hours=8))
        today_day = datetime.fromtimestamp(time.time(), timezone.utc).astimezone(bj).strftime("%Y-%m-%d")
        today_summary = next((row for row in rows if row.get("day") == today_day), None)
        return {"lane": lane, "asset": asset_name, "source": "data_api_v2_user_pnl_activity",
                "rows": rows[offset:offset + limit], "total_days": len(rows),
                "offset": offset, "limit": limit, "trading_timezone": "Asia/Shanghai",
                 "capital_base_usd": _live_day_capital(),
                 "fee_breakdown": external.get("fee_breakdown") if isinstance(external, dict) else None,
                  "data_provenance": "Polymarket Data API v2 user-pnl + user-stats + activity",
                 "available": external.get("available", False),
                 "financial_source": external.get("financial_source"),
                 "source_fidelity": external.get("source_fidelity"),
                 "activity_as_of": external.get("activity_as_of"),
                 "activity_updated_at": external.get("activity_updated_at"),
                 "activity_ahead_of_pnl": external.get("activity_ahead_of_pnl"),
                 "activity_stale": external.get("activity_stale"),
                 "outcomes_updated_at": external.get("outcomes_updated_at"),
                 "outcomes_stale": external.get("outcomes_stale"),
                 "error": external.get("error"),
                "data_as_of": external.get("data_as_of") if isinstance(external, dict) else None,
                "data_age_sec": external.get("data_age_sec") if isinstance(external, dict) else None,
                "updated_at": external.get("updated_at") if isinstance(external, dict) else None,
                 "stale": bool(external.get("stale")) if isinstance(external, dict) else True,
                 "today_summary": today_summary,
                 "today_economic_pnl_usd": external.get("today_economic_pnl_usd") if isinstance(external, dict) else None,
                 "today_trade_pnl_usd": external.get("today_trade_pnl_usd") if isinstance(external, dict) else None,
                 "today_fees_usd": external.get("today_fees_usd") if isinstance(external, dict) else None,
                 "today_rebates_usd": external.get("today_rebates_usd") if isinstance(external, dict) else None}
    if lane == "paper" and _native_paper_available():
        native_rows = _native_paper_daily_rows()
        return {
            "lane": lane, "asset": asset_name, "source": "native_paper_ledger",
            "rows": native_rows[offset:offset + limit], "total_days": len(native_rows),
            "offset": offset, "limit": limit, "trading_timezone": "Asia/Shanghai",
            "capital_base_usd": (_native_paper_account_snapshot() or {}).get("capital_base_usd"),
            "fee_breakdown": {"taker_fee_usd": sum(float(r.get("fees_usd") or 0.0) for r in native_rows),
                               "maker_fee_usd": 0.0, "rebate_usd": 0.0},
            "available": (_native_paper_account_snapshot() or {}).get("available", False),
            "stale": (_native_paper_account_snapshot() or {}).get("stale", False),
            "error": (_native_paper_account_snapshot() or {}).get("error"),
            "data_provenance": "native btc5m Paper fills + positions",
        }
    try:
        history = daily_rows(DB_PATH, lane == "paper")
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="盈亏历史暂不可用，请稍后重试") from exc
    rows = []
    for row in history:
        bucket = row["by_asset"].get("BTC") or {}
        if bucket:
            rows.append({"day": row["day"], **bucket})
    balance = float(_state.get("balance_pusd") or 0.)
    value = float(_state.get("value_usd") or 0.)
    return {"lane": lane, "asset": asset_name, "source": "ledger", "rows": rows[offset:offset + limit], "total_days": len(rows),
            "offset": offset, "limit": limit, "trading_timezone": "Asia/Shanghai",
            "capital_base_usd": float(cfg.paper_equity_usd) if lane == "paper" else max(balance + value, 1.)}

@app.get("/api/events")
def events(since_decision: int = Query(0), since_order: int = Query(0)):
    return {
        "decisions": recent_decisions(limit=200, since_id=since_decision),
        "orders": recent_orders(limit=50, since_id=since_order),
    }





@app.get("/api/paper/comparison")
def paper_comparison_summary():
    return _p3.read_summary() if _PAPER_COMPARISON_ENABLED else {"available": False, "mode": "paper", "reason": "DISABLED"}


@app.get("/api/paper/comparison/{group}/daily")
def paper_comparison_daily(group: Literal["BASELINE", "FILTERED"], offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=365)):
    return _p3.daily_page(offset, limit, group) if _PAPER_COMPARISON_ENABLED else {"available": False, "rows": []}


@app.get("/api/paper/comparison/{group}/orders")
def paper_comparison_orders(group: Literal["BASELINE", "FILTERED"], offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
    return _p3.orders_page(offset, limit, group=group) if _PAPER_COMPARISON_ENABLED else {"available": False, "rows": []}
