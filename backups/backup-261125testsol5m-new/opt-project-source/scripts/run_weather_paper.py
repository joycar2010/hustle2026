#!/usr/bin/env python3
"""Persistent, isolated weather Paper producer for PolyDexTest.

The worker uses the existing weather parser/strategy in dry-run mode and only
writes a small JSON snapshot plus its own Paper ledger.  It never builds a
CLOB client and has no live flag by design.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Keep the feed ledger separate from the crypto P1 database.  This assignment
# must happen before importing ``bot.weather_main`` because ``bot.store`` reads
# TRADES_DB_PATH at import time.
os.environ.setdefault("TRADES_DB_PATH", "/var/lib/poly-dex-test/paper-feeds/paper-feeds.db")

from bot import config
from bot.weather_main import run_cycle
from bot.weather_data import CITY_CONFIG, configured_city_keys, fetch_ensemble_forecast
from bot.weather_markets import fetch_weather_markets


STATE_DIR = Path(os.getenv("WEATHER_STATE_DIR", "/opt/poly-dex-test/agents/out"))
STATE_PATH = STATE_DIR / "weather_paper_state.json"


def _market_view(market) -> dict[str, object]:
    return {
        "market_key": market.market_key,
        "slug": market.slug,
        "question": market.question,
        "city": market.city_name,
        "city_key": market.city_key,
        "target_date": market.target_date.isoformat(),
        "metric": market.metric,
        "kind": market.kind,
        "yes_price": market.yes_price,
        "no_price": market.no_price,
        "end_ts": market.end_ts,
        "volume": market.volume,
        "liquidity": market.liquidity,
        "mode": "paper",
        "paper_only": True,
    }


def _write(payload: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def run_once(cfg) -> dict[str, object]:
    now = time.time()
    markets = fetch_weather_markets(cfg) if cfg.weather_enabled else []
    rows = [_market_view(item) for item in markets]
    try:
        trades = int(run_cycle(cfg, live=False)) if cfg.weather_enabled else 0
        status = "ok" if markets else "no_markets"
        error = None
    except Exception as exc:  # keep a usable heartbeat during upstream outages
        trades = 0
        status = "error"
        error = str(exc)[:500]
    # Keep the weather Paper card useful when Gamma has no currently tradable
    # contract.  These are public forecast observations only; they never create
    # a simulated order and are explicitly labeled as forecast-only.
    if cfg.weather_enabled and not rows:
        target_date = datetime.now(timezone.utc).date()
        for city in configured_city_keys(cfg):
            try:
                forecast = fetch_ensemble_forecast(cfg, city, target_date)
                rows.append({
                    "city": CITY_CONFIG[city]["name"],
                    "city_key": city,
                    "target_date": target_date.isoformat(),
                    "temperature_c": round((forecast.high_mean - 32.0) * 5.0 / 9.0, 1),
                    "probability": None,
                    "source": "Open-Meteo forecast only",
                    "status": "PAPER · forecast only; no active market",
                    "mode": "paper",
                    "paper_only": True,
                    "updated_ts": now,
                })
            except Exception as exc:
                error = error or f"forecast {city}: {type(exc).__name__}"
    return {
        "updated_ts": now,
        "heartbeat_ts": now,
        "running": True,
        "enabled": bool(cfg.weather_enabled),
        "mode": "paper",
        "paper_only": True,
        "live_enabled": False,
        "live_orders": False,
        "status": status,
        "error": error,
        "trades_last_cycle": trades,
        "market_count": len(markets),
        "orders_new": trades,
        "markets": rows,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=float(os.getenv("WEATHER_PAPER_INTERVAL_SEC", "300")))
    args = parser.parse_args()
    cfg = config.load()
    while True:
        payload = run_once(cfg)
        _write(payload)
        print(f"weather paper cycle status={payload['status']} markets={len(payload['markets'])} trades={payload['trades_last_cycle']}", flush=True)
        if args.once:
            return
        time.sleep(max(args.interval, 30.0))


if __name__ == "__main__":
    main()
