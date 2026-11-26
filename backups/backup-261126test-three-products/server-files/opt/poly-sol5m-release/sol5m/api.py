"""Read-only SOL5M Paper API and WebSocket health surface."""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from btc5m.config import load
from sol5m.markets import fetch_live_market
from sol5m.profile import SOL5M, assert_paper_env
from sol5m.store import Sol5mStore
from sol5m.ws import status as ws_status


app = FastAPI(title="SOL5M Paper API", docs_url=None, redoc_url=None)


def _cfg():
    # A release API must never inherit SERIES_SLUG=btc... from a shared shell.
    return load(series=SOL5M.key)


def _ledger_snapshot() -> dict[str, Any]:
    store = Sol5mStore()
    try:
        positions = store.conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_n "
            "FROM positions"
        ).fetchone()
        events = store.conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return {
            "path": str(store.path),
            "positions": int(positions[0] or 0),
            "open_positions": int(positions[1] or 0),
            "events": int(events[0] or 0),
        }
    finally:
        store.conn.close()


@app.get("/api/health")
def health() -> dict[str, Any]:
    cfg = _cfg()
    # Keep this check explicit: service templates call this endpoint as a
    # deployment smoke test and should fail if a live env leaked in.
    assert_paper_env()
    return {
        "ok": True,
        "product": SOL5M.key,
        "series_slug": cfg.series_slug,
        "asset": cfg.crypto_asset,
        "mode": "PAPER",
        "live": False,
        "live_trading_enabled": bool(cfg.live_trading_enabled),
        "db": _ledger_snapshot(),
        "ws": ws_status(),
        "ts": time.time(),
    }


@app.get("/api/profile")
def profile() -> dict[str, Any]:
    cfg = _cfg()
    store = Sol5mStore()
    try:
        db_path = str(store.path)
    finally:
        store.conn.close()
    return {
        "key": SOL5M.key,
        "series_slug": cfg.series_slug,
        "market_slug_prefix": cfg.market_slug_prefix,
        "window_sec": cfg.window_sec,
        "crypto_asset": cfg.crypto_asset,
        "db": db_path,
        "live": False,
        "live_trading_enabled": bool(cfg.live_trading_enabled),
    }


@app.get("/api/market")
def market() -> dict[str, Any]:
    cfg = _cfg()
    try:
        m = fetch_live_market(cfg.gamma_host)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "product": SOL5M.key, "error": str(exc)}
    if m is None:
        return {"ok": True, "product": SOL5M.key, "market": None}
    return {
        "ok": True,
        "product": SOL5M.key,
        "market": {
            "condition_id": m.condition_id,
            "market_slug": m.market_slug,
            "title": m.title,
            "up_token": m.up_token,
            "down_token": m.down_token,
            "start_ts": m.start_ts,
            "end_ts": m.end_ts,
            "remaining_sec": m.t_remaining(),
        },
    }


@app.get("/api/ws/status")
def websocket_status() -> dict[str, Any]:
    return ws_status()


@app.websocket("/ws")
async def websocket_health(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await websocket.send_json({"product": SOL5M.key, "type": "health", "ws": ws_status()})
        while True:
            # A tiny heartbeat keeps the endpoint useful to a dashboard while
            # avoiding any market/order side effects.
            await websocket.receive_text()
            await websocket.send_json({"product": SOL5M.key, "type": "health", "ws": ws_status(), "ts": time.time()})
    except WebSocketDisconnect:
        return


__all__ = ["app"]

