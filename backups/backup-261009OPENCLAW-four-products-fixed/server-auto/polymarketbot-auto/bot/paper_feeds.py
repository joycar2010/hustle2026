"""Single-writer WEATHER/SPORTS paper workers and dashboard snapshots.

There is deliberately no live order client in this module. Public market
data, deterministic risk gates, SQLite paper orders and public settlements
form the complete simulation path. Dashboard only reads atomic snapshots.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
import time

from bot import config, store

log = logging.getLogger("bot.paper_feeds")
ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "agents" / "out"
_SPORTS_CONFIRMATIONS: dict[str, int] = {}


def read_snapshot(asset: str) -> dict:
    try:
        snap = json.loads((SNAPSHOT_DIR / f"{asset.lower()}_paper_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "stopped", "running": False, "mode": "paper", "rows": [], "error": "paper worker has no heartbeat"}
    age = time.time() - float(snap.get("heartbeat_ts") or 0)
    try:
        pid = int(snap.get("pid") or 0)
        if pid <= 0:
            raise ProcessLookupError()
        os.kill(pid, 0)
        alive = True
    except (OSError, ValueError, TypeError):
        alive = False
    snap["running"] = alive and snap.get("enabled", True) and snap.get("status") != "disabled" and age < max(float(snap.get("interval_sec") or 300) * 3, 600)
    if not snap["running"]:
        snap["status"] = "stale"
        snap["error"] = "paper worker heartbeat expired"
    return snap


def write_snapshot(asset: str, data: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{asset.lower()}_paper_state.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _open_exposure(asset: str) -> float:
    with store.db() as c:
        row = c.execute("SELECT COALESCE(SUM(o.size*o.price),0) FROM orders o LEFT JOIN resolutions r ON r.condition_id=o.condition_id WHERE o.dry_run=1 AND o.asset=? AND o.status='dry_run' AND o.side IN ('UP','DOWN') AND r.condition_id IS NULL", (asset,)).fetchone()
    return float(row[0])


def _record_decision(asset: str, market, *, action: str, reason: str,
                     token: str | None = None, side: str | None = None, price: float | None = None) -> None:
    store.log_decision(asset=asset, market_slug=market.slug, condition_id=market.condition_id,
                       token_id=token, side=side, t_remaining=max(market.end_ts-time.time(), 0),
                       ask_price=price, ask_size=None, action=action, reason=reason, dry_run=True)


def _paper_buy(cfg, asset: str, market, token: str, side: str, price: float,
               size: float, reason: str, max_exposure: float) -> tuple[bool, str]:
    """Atomic duplicate/cap gate; all rows are unconditionally dry_run=1."""
    from bot.risk import allowed_to_trade
    cost = price * size
    if not all(math.isfinite(x) for x in (price, size, cost)) or not 0 < price < 1 or size <= 0:
        return False, "invalid quote or size"
    # Weather and sports are independent Paper lanes. A pending weather
    # market must not consume the BTC/ETH/global slot and starve sports.
    lane_cap = int(os.environ.get(f"{asset}_PAPER_MAX_OPEN_POSITIONS", "3"))
    allowed, why = allowed_to_trade(cfg, True, equity_usd=cfg.paper_equity_usd,
                                     order_cost_usd=cost,
                                     risk_fraction=float(cfg.weather_order_risk_fraction) if asset == "WEATHER" else float(cfg.order_risk_fraction),
                                     asset=asset, max_open_positions=lane_cap)
    if not allowed:
        return False, why
    with store.db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM orders WHERE condition_id=? AND dry_run=1 AND status='dry_run' LIMIT 1", (market.condition_id,)).fetchone():
            return False, "paper position already recorded"
        exposure = c.execute("SELECT COALESCE(SUM(o.size*o.price),0) FROM orders o LEFT JOIN resolutions r ON r.condition_id=o.condition_id WHERE o.dry_run=1 AND o.asset=? AND o.status='dry_run' AND o.side IN ('UP','DOWN') AND r.condition_id IS NULL", (asset,)).fetchone()[0]
        if float(exposure) + cost > max_exposure + 1e-8:
            return False, "paper exposure cap reached"
        c.execute("INSERT INTO orders(ts,asset,market_slug,condition_id,token_id,side,size,price,order_id,status,filled_size,error,entry_rule,dry_run) VALUES(?,?,?,?,?,?,?,?,NULL,'dry_run',0,NULL,?,1)",
                  (time.time(), asset, market.slug, market.condition_id, token, side, size, price, asset.lower()+"_paper"))
    return True, reason


def settle_asset(cfg, asset: str) -> int:
    from bot.resolver import _winning_token_for
    with store.db() as c:
        pending = c.execute("SELECT DISTINCT o.condition_id,o.market_slug FROM orders o LEFT JOIN resolutions r ON r.condition_id=o.condition_id WHERE o.asset=? AND o.dry_run=1 AND o.status='dry_run' AND r.condition_id IS NULL", (asset,)).fetchall()
    count = 0
    for cid, slug in pending[:40]:
        if str(cid).startswith("kalshi:"):
            continue
        token = _winning_token_for(cfg, slug)
        if token:
            store.record_resolution(cid, token)
            count += 1
    if asset == "WEATHER":
        from bot.feeds.kalshi_weather import resolve_kalshi_settlements
        count += resolve_kalshi_settlements()
    return count


def sports_cycle(cfg, source) -> dict:
    from bot.book import fetch_book
    from bot.sports_markets import fetch_sports_markets
    from bot.sports_strategy import build_signal, signal_is_allowed
    from dataclasses import replace

    if not cfg.sports_enabled:
        return {"status": "disabled", "enabled": False, "rows": []}
    settled = settle_asset(cfg, "SPORTS")
    markets = fetch_sports_markets(cfg)
    rows, decisions = [], []
    orders_new = 0
    if source is not None:
        source.matches = 0
    for market in markets:
        signal = build_signal(market, source)
        allowed, why = False, "no independent odds match"
        if source is not None and signal.source != "market_implied":
            try:
                book = fetch_book(cfg.clob_host, signal.token_id)
                ask = book.best_ask
                if ask is None or book.ask_size <= 0:
                    why = "no executable CLOB ask"
                else:
                    signal = replace(signal, market_price=ask, edge=signal.model_probability-ask)
                    allowed, why = signal_is_allowed(cfg, signal, exposure_usd=_open_exposure("SPORTS"))
                    if allowed:
                        count = _SPORTS_CONFIRMATIONS.get(market.condition_id, 0) + 1
                        _SPORTS_CONFIRMATIONS[market.condition_id] = count
                        needed = max(int(getattr(cfg, "sports_confirm_checks", 1)), 1)
                        if count < needed:
                            allowed, why = False, f"confirmation {count}/{needed}"
                    else:
                        _SPORTS_CONFIRMATIONS.pop(market.condition_id, None)
                    if allowed:
                        size = min(float(cfg.sports_order_size), float(book.ask_size))
                        allowed, why = _paper_buy(cfg, "SPORTS", market, signal.token_id,
                                                 "UP" if signal.token_id == market.token_ids[0] else "DOWN",
                                                 ask, size, signal.reason, float(cfg.sports_max_exposure_usd))
                        orders_new += int(allowed)
            except Exception as exc:
                why = f"CLOB quote unavailable: {type(exc).__name__}"
        action = "BUY" if allowed else "SKIP_SPORTS"
        if signal.source == "market_implied":
            _SPORTS_CONFIRMATIONS.pop(market.condition_id, None)
        reason = f"{signal.reason}; {why}"
        _record_decision("SPORTS", market, action=action, reason=reason,
                         token=signal.token_id, price=signal.market_price,
                         side="UP" if signal.token_id == market.token_ids[0] else "DOWN")
        decisions.append({"slug":market.slug,"action":action,"reason":reason,"source":signal.source})
        rows.append({"league": market.league or market.sport, "event":market.event_name,
                     "status": "PAPER · 已模拟买入" if allowed else "PAPER · " + why,
                     "start_ts":market.event_start_ts,"home_team":market.outcomes[0],"away_team":market.outcomes[1],
                     "probability_home": (signal.model_probability if signal.outcome == market.outcomes[0] else 1-signal.model_probability) if signal.source != "market_implied" else None,
                     "source":signal.source,"market_slug":market.slug,"neg_risk":market.neg_risk})
    health = source.health() if source is not None else {"source":"disabled", "remaining":None,"matches":0,"events_cached":0,"error":"ODDS_API_KEY or source not configured"}
    return {"status":"ok" if not health.get("error") else "waiting_data","enabled":True,
            "rows":rows[:8],"markets_count":len(markets),"market_count":len(markets),
            "decision_count":len(decisions),"orders_new":orders_new,"recent_decisions":decisions[-50:],
            "feed":health,"settled_new":settled,"error":health.get("error")}


def weather_cycle(cfg) -> dict:
    from bot.book import fetch_book
    from bot.weather_markets import fetch_weather_markets
    from bot.weather_data import fetch_ensemble_forecast, configured_city_keys, CITY_CONFIG
    from bot.weather_strategy import build_signal, signal_is_allowed
    from bot.feeds.kalshi_weather import fetch_kalshi_weather_markets, LAST_STATS
    from datetime import datetime, timezone
    if not cfg.weather_enabled:
        return {"status":"disabled","enabled":False,"rows":[]}
    settled = settle_asset(cfg, "WEATHER")
    errors = []
    try:
        markets = fetch_weather_markets(cfg)
    except Exception as exc:
        markets = []
        errors.append(f"Gamma weather: {type(exc).__name__}")
    if os.environ.get("KALSHI_WEATHER_ENABLED", "true").lower() in ("true","1","yes","on"):
        markets += fetch_kalshi_weather_markets()
    forecasts, rows = {}, []
    orders_new = 0
    for market in markets:
        try:
            key = (market.city_key, market.target_date)
            if key not in forecasts:
                forecasts[key] = fetch_ensemble_forecast(cfg, *key)
            forecast = forecasts[key]
            signal = build_signal(cfg, market, forecast)
            reference = market.condition_id.startswith("kalshi:")
            ask, size_cap = signal.entry_price, float("inf")
            if not reference:
                book = fetch_book(cfg.clob_host, signal.token_id)
                ask, size_cap = book.best_ask, book.ask_size
            if ask is None or ask <= 0 or size_cap <= 0:
                allowed, why = False, "no executable ask"
            else:
                probability = signal.model_yes_probability if signal.side == "UP" else signal.model_no_probability
                allowed, why = signal_is_allowed(cfg, signal, entry_price=ask, edge=probability-ask)
                if allowed and orders_new >= max(int(cfg.weather_max_markets_per_cycle), 1):
                    allowed, why = False, "cycle entry cap reached"
                if allowed:
                    amount = min(1.0, cfg.paper_equity_usd * cfg.weather_order_risk_fraction)
                    size = min(round(amount/ask, 4), size_cap)
                    allowed, why = _paper_buy(cfg,"WEATHER",market,signal.token_id,signal.side,ask,size,signal.reason,
                                               float(os.environ.get("WEATHER_PAPER_MAX_EXPOSURE_USD", "5")))
                    orders_new += int(allowed)
            _record_decision("WEATHER",market,action="BUY" if allowed else "SKIP_WEATHER",
                             reason=("Kalshi reference-only paper; " if reference else "")+signal.reason+"; "+why,
                             token=signal.token_id,side=signal.side,price=ask)
            rows.append({"city":market.city_name,"condition":market.question,
                         "temperature_c":round((forecast.high_mean-32)*5/9,1),
                         "probability":signal.model_yes_probability,"source":"Kalshi reference + Open-Meteo" if reference else "Polymarket + Open-Meteo",
                         "updated_ts":time.time(),"market_slug":market.slug,"target_date":market.target_date.isoformat(),
                         "status":"PAPER · BUY" if allowed else "PAPER · "+why})
        except Exception as exc:
            errors.append(f"{market.slug}: {type(exc).__name__}")
    if not rows:
        today = datetime.now(timezone.utc).date()
        for city in configured_city_keys(cfg):
            try:
                forecast = fetch_ensemble_forecast(cfg,city,today)
                rows.append({"city":CITY_CONFIG[city]["name"],"condition":"等待可交易天气合约",
                             "temperature_c":round((forecast.high_mean-32)*5/9,1),"probability":None,
                             "source":"Open-Meteo forecast only","updated_ts":time.time(),"market_slug":None,
                             "target_date":today.isoformat()})
            except Exception as exc:
                errors.append(f"{city}: {type(exc).__name__}")
    feed = dict(LAST_STATS)
    feed.update({"markets":sum(m.condition_id.startswith("kalshi:") for m in markets),"settled_new":settled,"ts":time.time()})
    if feed.get("error"):
        errors.append(str(feed["error"]))
    return {"status":"ok" if not errors else "waiting_data","enabled":True,"rows":rows[:8],
            "market_count":len(markets),"decision_count":len(markets),"orders_new":orders_new,
            "settled_new":settled,"feed":feed,"error":"; ".join(errors[:8]) or None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", choices=("WEATHER","SPORTS"))
    parser.add_argument("--once",action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load()
    source = None
    if args.asset == "SPORTS" and os.environ.get("ODDS_API_KEY", "").strip() and os.environ.get("SPORTS_ODDS_SOURCE","the-odds-api").lower() not in ("off","0","false","none"):
        from bot.feeds.odds_consensus import OddsConsensusSource
        source = OddsConsensusSource(os.environ["ODDS_API_KEY"].strip())
    interval = max(float(cfg.weather_scan_interval_sec) if args.asset == "WEATHER" else 300,60)
    while True:
        started = time.time()
        prev = read_snapshot(args.asset)
        prev.update({"heartbeat_ts":started,"status":"scanning","interval_sec":interval,
                     "mode":"paper","paper_only":True,"live_orders":False,"pid":os.getpid()})
        write_snapshot(args.asset,prev)
        try:
            result = weather_cycle(cfg) if args.asset == "WEATHER" else sports_cycle(cfg,source)
        except Exception as exc:
            log.exception("%s paper cycle failed",args.asset)
            result = {"status":"error","rows":prev.get("rows",[]),"error":type(exc).__name__}
        result.update({"heartbeat_ts":time.time(),"interval_sec":interval,"mode":"paper","paper_only":True,"live_orders":False,"pid":os.getpid()})
        write_snapshot(args.asset,result)
        log.info("%s status=%s markets=%s new_orders=%s",args.asset,result["status"],result.get("market_count",0),result.get("orders_new",0))
        if args.once:
            return
        time.sleep(max(interval-(time.time()-started),1))


if __name__ == "__main__":
    main()
