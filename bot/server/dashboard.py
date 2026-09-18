"""FastAPI dashboard backend.

Polls the local SQLite (trades.db), the CLOB book of the live market, the
deposit wallet's positions, and on-chain pUSD balance. Serves /api/state for
the UI to poll, and /api/events for incremental new-row pulls.

Run:  .venv/bin/uvicorn server.dashboard:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import asyncio
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from bot.book import fetch_book
from bot.btc_signal import BtcSignal, fetch_btc_signal, fetch_eth_signal
from bot.config import load as load_cfg
from bot.markets import LiveMarket, fetch_live_market
from bot.resolver import resolve_pending
from bot.store import realized_pnl_summary_today

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "trades.db"

cfg = load_cfg()

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
    "balance_pusd": None,     # on-chain pUSD in deposit wallet
    "positions": [],          # data-api positions for deposit wallet
    "value_usd": None,        # data-api value endpoint
    "bot_running": False,
    "bot_assets": {"BTC": False, "ETH": False},
    "errors": {},             # last error per poller for debugging
}


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
            exit_effective = item["status"] in ("exit_filled", "exit_matched", "exit_partial", "exit_dry_run")
            effective = (
                item["side"] in ("UP", "DOWN") and item["status"] in ("filled", "matched")
                or (item["dry_run"] == 1 and item["status"] == "dry_run")
            )
            if is_exit:
                if item["status"] == "exit_partial":
                    item["result"] = "PARTIAL_EXIT"
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
            _state["errors"].pop("btc_signal", None)
        except Exception as e:
            _state["btc_signal"] = None
            _state["errors"]["btc_signal"] = str(e)
        await asyncio.sleep(1.0)


async def poll_eth_signal_loop():
    while True:
        m = _state.get("eth_market")
        if not m or not cfg.eth_market_enabled or not cfg.eth_delta_filter_enabled:
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
            _state["errors"].pop("eth_signal", None)
        except Exception as e:
            _state["eth_signal"] = None
            _state["errors"]["eth_signal"] = str(e)
        await asyncio.sleep(1.0)


async def poll_positions_loop():
    while True:
        try:
            r = await asyncio.to_thread(
                requests.get,
                "https://data-api.polymarket.com/positions",
                params={"user": cfg.funder_address},
                timeout=3,
            )
            r.raise_for_status()
            _state["positions"] = r.json()
            _state["errors"].pop("positions", None)
        except Exception as e:
            _state["errors"]["positions"] = str(e)

        try:
            r = await asyncio.to_thread(
                requests.get,
                "https://data-api.polymarket.com/value",
                params={"user": cfg.funder_address},
                timeout=3,
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                _state["value_usd"] = float(data[0].get("value") or 0.0)
            _state["errors"].pop("value", None)
        except Exception as e:
            _state["errors"]["value"] = str(e)

        await asyncio.sleep(2.0)


async def poll_balance_loop():
    """Read pUSD balance of deposit wallet on-chain."""
    PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
    SELECTOR = "0x70a08231"
    while True:
        try:
            data = SELECTOR + cfg.funder_address.lower().replace("0x", "").rjust(64, "0")
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
            raw = r.json().get("result")
            if raw:
                _state["balance_pusd"] = int(raw, 16) / 1e6
            _state["errors"].pop("balance", None)
        except Exception as e:
            _state["errors"]["balance"] = str(e)
        await asyncio.sleep(5.0)


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
    asyncio.create_task(poll_bot_running_loop())
    asyncio.create_task(poll_resolution_loop())


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


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


def _filter_active_positions(positions: list[dict]) -> list[dict]:
    """data-api keeps resolved positions in the list at curPrice=0; drop them."""
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
        out.append(p)
    return out


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
        "risk_state": _risk_state(pnl),
        "wallet": {
            "eoa": cfg.wallet_address,
            "deposit": cfg.funder_address,
            "balance_pusd": _state.get("balance_pusd"),
            "value_usd": _state.get("value_usd"),
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
        "positions": _filter_active_positions(_state.get("positions") or []),
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
        },
        "decisions": recent_decisions(limit=80),
        "orders": recent_orders(limit=30),
        "errors": _state.get("errors") or {},
    }


@app.get("/api/events")
def events(since_decision: int = Query(0), since_order: int = Query(0)):
    return {
        "decisions": recent_decisions(limit=200, since_id=since_decision),
        "orders": recent_orders(limit=50, since_id=since_order),
    }
