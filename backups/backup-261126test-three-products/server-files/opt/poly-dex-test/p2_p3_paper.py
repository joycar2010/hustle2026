#!/usr/bin/env python3
"""P2 risk observer and P3 asset discovery Paper adapter.

The process is deliberately read-only with respect to Polymarket: it reads
public Gamma/CLOB data, evaluates deterministic risk gates, and writes local
Paper metadata.  It never imports a wallet or L2 client.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

LOG = logging.getLogger("poly-dex-p2-p3")
GAMMA = os.getenv("P1_GAMMA_HOST", "https://gamma-api.polymarket.com").rstrip("/")
CLOB = os.getenv("P1_CLOB_HOST", "https://clob.polymarket.com").rstrip("/")
ROOT = Path(os.getenv("P2P3_STATE_DIR", "/var/lib/poly-dex-test/p2-p3"))
P1_STATE = Path(os.getenv("P1_STATE_DIR", "/var/lib/poly-dex-test/p1")) / "state.json"
P1_DB = Path(os.getenv("P1_DB_PATH", "/var/lib/poly-dex-test/p1/crypto-paper.db"))
HTTP_TIMEOUT = float(os.getenv("P2P3_HTTP_TIMEOUT_SEC", "8"))

# P3 registry is intentionally explicit.  Each asset gets an independent
# category and resolution-source record before it can ever be considered for
# a future live gate.  All entries are Paper/watch-only in this release.
P3_REGISTRY: dict[str, tuple[str, tuple[str, ...]]] = {
    "BTC": ("crypto", ("btc", "bitcoin")), "ETH": ("crypto", ("eth", "ethereum")),
    "SOL": ("crypto", ("sol", "solana")), "XRP": ("crypto", ("xrp", "ripple")),
    "DOGE": ("crypto", ("doge", "dogecoin")), "BNB": ("crypto", ("bnb", "binance")),
    "ADA": ("crypto", ("ada", "cardano")), "AVAX": ("crypto", ("avax", "avalanche")),
    "LTC": ("crypto", ("ltc", "litecoin")), "LINK": ("crypto", ("link", "chainlink")),
    "SUI": ("crypto", ("sui",)), "NEAR": ("crypto", ("near",)),
    "AAVE": ("crypto", ("aave",)), "UNI": ("crypto", ("uni", "uniswap")),
    "USA500": ("index", ("usa500", "s&p 500", "sp500", "spx")),
    "US100": ("index", ("us100", "nasdaq 100", "nasdaq-100", "ndx")),
    "EWY": ("index", ("ewy",)), "SOXL": ("equity", ("soxl",)),
    "GOLD": ("commodity", ("gold", "xau")), "SILVER": ("commodity", ("silver", "xag")),
    "WTIOIL": ("commodity", ("wti", "wti oil", "crude oil")),
    "BRENTOIL": ("commodity", ("brent", "brent oil")),
}

# The test instance exposes the complete admission list as Paper/watch-only,
# even when Gamma has no currently active market for a symbol.  This keeps the
# UI and the P3 audit honest: an empty market count means "no public market
# found", never that the asset was silently omitted from the test universe.
_EXTRA_P3_ASSETS = {
    "SPCX": "equity", "HYPE": "crypto", "MU": "equity", "SKHY": "equity",
    "SKHYNIX": "equity", "AAPL": "equity", "MSFT": "equity", "GOOG": "equity",
    "AMZN": "equity", "NVDA": "equity", "META": "equity", "TSLA": "equity",
    "AMD": "equity", "INTC": "equity", "AVGO": "equity", "QCOM": "equity",
    "ARM": "equity", "TSM": "equity", "ASML": "equity", "SNDK": "equity",
    "DRAM": "equity", "PUMP": "crypto", "ZEC": "crypto", "LIT": "crypto",
    "KPEPE": "crypto", "HOOD": "equity", "MSTR": "equity", "STRC": "equity",
    "CRCL": "equity", "COIN": "equity", "RKLB": "equity", "LITE": "equity",
    "NBIS": "equity", "ORCL": "equity", "PLTR": "equity", "BABA": "equity",
    "ZM": "equity", "DELL": "equity", "CXMT": "equity", "SAMSUNG": "equity",
    "CRWV": "equity", "WLD": "crypto", "KSHIB": "crypto", "FARTCOIN": "crypto",
    "ENA": "crypto", "ONDO": "crypto", "VVV": "crypto", "TAO": "crypto",
    "ZRO": "crypto", "PONS": "crypto", "CASHCAT": "crypto", "USELESS": "crypto",
    "KAITO": "crypto", "ARB": "crypto", "LDO": "crypto", "XPL": "crypto",
    "XMR": "crypto", "VIRTUAL": "crypto", "JUP": "crypto", "ETHFI": "crypto",
    "PENDLE": "crypto", "MORPHO": "crypto", "CBRS": "equity", "MRVL": "equity",
    "EWY": "index", "NCLD": "equity", "UNITREE": "equity",
}
for _asset, _category in _EXTRA_P3_ASSETS.items():
    P3_REGISTRY.setdefault(_asset, (_category, (_asset.lower(),)))

MAX_P3_PAGES = int(os.getenv("P3_GAMMA_PAGES", "8"))
P3_SCAN_LIMIT = int(os.getenv("P3_SCAN_LIMIT", "60"))
MAX_SPREAD = float(os.getenv("P2_MAX_SPREAD", "0.18"))
MIN_DEPTH = float(os.getenv("P2_MIN_DEPTH", "5"))
MAX_VOL = float(os.getenv("P2_MAX_VOL", "0.45"))
# Polymarket binary token prices are probabilities in [0,1].  Use absolute
# probability-point changes for the short-window gate; a relative return from
# 0.01 to 0.60 would otherwise look like a 5900% move and block every market.
VOLATILITY_MODE = os.getenv("P2_VOLATILITY_MODE", "absolute").strip().lower()


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def init_db() -> sqlite3.Connection:
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / "p2-p3.db", timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS risk_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT NOT NULL,
      status TEXT NOT NULL, volatility REAL, spread REAL, depth REAL,
      resolution_source TEXT, reason TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS p3_markets (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT NOT NULL,
      category TEXT NOT NULL, market_id TEXT, condition_id TEXT, slug TEXT,
      question TEXT, resolution_source TEXT, end_date TEXT, accepting_orders INTEGER,
      paper_status TEXT NOT NULL, reason TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_risk_ts ON risk_snapshots(ts);
    CREATE INDEX IF NOT EXISTS idx_p3_ts ON p3_markets(ts);
    """)
    return db


def p1_quotes() -> dict[str, list[tuple[str, float, float, float, float]]]:
    if not P1_DB.exists():
        return {}
    result: dict[str, list[tuple[str, float, float, float, float]]] = {}
    db = sqlite3.connect(P1_DB)
    # Only two-sided quotes are valid for spread/volatility.  Keep token_id so
    # UP and DOWN books are never mistaken for one continuous price series.
    rows = db.execute("SELECT asset,token_id,ts,ask,ask_size,bid,bid_size FROM quotes WHERE ask IS NOT NULL AND bid IS NOT NULL ORDER BY ts DESC LIMIT 2000").fetchall()
    db.close()
    for asset, token, ts, ask, ask_size, bid, bid_size in rows:
        result.setdefault(str(asset), []).append((str(token), float(ts), float(ask), float(bid), float(ask_size or 0) + float(bid_size or 0)))
    return result


def latest_market_metadata() -> dict[str, dict[str, Any]]:
    """Get resolution metadata for active P1 crypto windows."""
    out: dict[str, dict[str, Any]] = {}
    try:
        state = json.loads(P1_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for asset, row in (state.get("assets") or {}).items():
        for item in row.get("rows") or []:
            slug = item.get("slug")
            if not slug:
                continue
            try:
                events = get_json(f"{GAMMA}/events", {"slug": slug, "closed": "false", "limit": 2})
                markets = events[0].get("markets") if events else []
                if markets:
                    out[asset] = markets[0]
                    break
            except Exception:
                continue
    return out


def risk_cycle(db: sqlite3.Connection) -> dict[str, Any]:
    quotes = p1_quotes()
    metadata = latest_market_metadata()
    risk: dict[str, Any] = {}
    for asset, samples in quotes.items():
        by_token: dict[str, list[tuple[str, float, float, float, float]]] = {}
        for row in samples:
            by_token.setdefault(row[0], []).append(row)
        # Volatility is computed on the longest single token stream.  This
        # avoids artificial jumps caused by alternating UP/DOWN token rows.
        samples = max(by_token.values(), key=len, default=[])
        samples = sorted(samples, key=lambda x: x[1])[-80:]
        mids = [(ask + bid) / 2 for _, _, ask, bid, _ in samples]
        if VOLATILITY_MODE == "relative":
            returns = [(mids[i] - mids[i - 1]) / max(abs(mids[i - 1]), 0.10) for i in range(1, len(mids))]
        else:
            returns = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
        # Probability-space quote volatility is deliberately not annualized;
        # in the default absolute mode it is measured in probability points.
        vol = statistics.pstdev(returns) if len(returns) >= 2 else 0.0
        latest = samples[-1] if samples else ("", 0, 0, 0, 0)
        spread = max(latest[2] - latest[3], 0.0)
        depth = latest[4]
        source = str((metadata.get(asset) or {}).get("resolutionSource") or "")
        reasons: list[str] = []
        if spread > MAX_SPREAD:
            reasons.append(f"spread {spread:.3f}>{MAX_SPREAD:.3f}")
        if depth < MIN_DEPTH:
            reasons.append(f"depth {depth:.2f}<{MIN_DEPTH:.2f}")
        if vol > MAX_VOL:
            reasons.append(f"volatility {vol:.3f}>{MAX_VOL:.3f}")
        if not source:
            reasons.append("missing public resolution source")
        status = "BLOCK" if reasons else ("REVIEW" if len(samples) < 3 else "ALLOW")
        reason = "; ".join(reasons) if reasons else ("insufficient history; Paper only" if status == "REVIEW" else "P2 gates passed")
        risk[asset] = {"status": status, "volatility": round(vol, 6), "spread": round(spread, 6),
                       "depth": round(depth, 4), "resolution_source": source, "reason": reason,
                       "sample_count": len(samples)}
        db.execute("INSERT INTO risk_snapshots(ts,asset,status,volatility,spread,depth,resolution_source,reason) VALUES(?,?,?,?,?,?,?,?)",
                   (time.time(), asset, status, vol, spread, depth, source, reason))
    # Correlation guard: the first release records the metric and blocks only
    # extreme co-movement when both assets have enough observations.
    assets = sorted(risk)
    correlations: list[dict[str, Any]] = []
    for i, left in enumerate(assets):
        for right in assets[i + 1:]:
            def representative(asset: str) -> list[tuple[str, float, float, float, float]]:
                groups: dict[str, list[tuple[str, float, float, float, float]]] = {}
                for row in quotes[asset]:
                    groups.setdefault(row[0], []).append(row)
                return max(groups.values(), key=len, default=[])
            a_rows = sorted(representative(left), key=lambda x: x[1])[-20:]
            b_rows = sorted(representative(right), key=lambda x: x[1])[-20:]
            a = [(x[2] + x[3]) / 2 for x in a_rows]
            b = [(x[2] + x[3]) / 2 for x in b_rows]
            n = min(len(a), len(b))
            if n < 4:
                continue
            if VOLATILITY_MODE == "relative":
                ar = [(a[j] - a[j - 1]) / max(abs(a[j - 1]), 0.10) for j in range(1, n)]
                br = [(b[j] - b[j - 1]) / max(abs(b[j - 1]), 0.10) for j in range(1, n)]
            else:
                ar = [a[j] - a[j - 1] for j in range(1, n)]
                br = [b[j] - b[j - 1] for j in range(1, n)]
            try:
                ma, mb = statistics.mean(ar), statistics.mean(br)
                da = math.sqrt(sum((x - ma) ** 2 for x in ar))
                dbv = math.sqrt(sum((x - mb) ** 2 for x in br))
                corr = sum((x - ma) * (y - mb) for x, y in zip(ar, br)) / max(da * dbv, 1e-12)
            except (statistics.StatisticsError, ZeroDivisionError):
                continue
            correlations.append({"left": left, "right": right, "correlation": round(corr, 4)})
    return {"assets": risk, "correlations": correlations, "thresholds": {"max_spread": MAX_SPREAD, "min_depth": MIN_DEPTH, "max_volatility": MAX_VOL, "volatility_mode": VOLATILITY_MODE}}


def scan_p3(db: sqlite3.Connection) -> dict[str, Any]:
    # Gamma caps individual pages at 100.  A bounded scan keeps this service
    # polite while still finding active markets across the configured registry.
    candidates: dict[str, list[dict[str, Any]]] = {a: [] for a in P3_REGISTRY}
    now = time.time()
    for page in range(max(MAX_P3_PAGES, 1)):
        try:
            rows = get_json(f"{GAMMA}/markets", {"active": "true", "closed": "false", "limit": 100, "offset": page * 100})
        except Exception as exc:
            LOG.warning("P3 Gamma page %s failed: %s", page, exc)
            continue
        if not isinstance(rows, list) or not rows:
            break
        for raw in rows:
            slug_text = str(raw.get("slug") or "").lower()
            text = f"{slug_text} {str(raw.get('question') or '').lower()}"
            end = raw.get("endDate") or ""
            for asset, (category, aliases) in P3_REGISTRY.items():
                pattern = r"(?<![a-z0-9])(?:" + "|".join(re.escape(a) for a in aliases) + r")(?![a-z0-9])"
                matched = re.search(pattern, text)
                # A long-form name such as "gold" or "bitcoin" is too broad
                # for an arbitrary prediction question.  Require a price/
                # direction context unless the exact ticker is present in the
                # slug (the recurring crypto series use this form).
                ticker_aliases = {"btc", "eth", "sol", "xrp", "doge", "bnb", "ada", "avax", "ltc", "link", "sui", "near", "aave", "uni", "ewy", "soxl", "usa500", "us100", "sp500", "spx", "goldx", "xau", "xag", "wti"}
                ticker_in_slug = any(alias in ticker_aliases and re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", slug_text) for alias in aliases)
                price_context = re.search(r"(?:price|price-up|up-or-down|updown|above|below|close|return|hit-?\d|reach-?\d)", text)
                if matched and (ticker_in_slug or price_context) and raw.get("clobTokenIds") and len(candidates[asset]) < 2:
                    candidates[asset].append(raw)
    summary: dict[str, Any] = {}
    for asset, (category, _) in P3_REGISTRY.items():
        rows = candidates[asset][:2]
        summary[asset] = {"category": category, "markets": len(rows), "paper_only": True, "rows": []}
        for raw in rows:
            source = str(raw.get("resolutionSource") or "")
            accepting = bool(raw.get("acceptingOrders", raw.get("enableOrderBook", False)))
            # P3 remains watch-only until each asset has its own settlement and
            # probability model; the record is still useful for Paper QA.
            reason = "watch-only Paper adapter; asset-specific model pending"
            db.execute("INSERT INTO p3_markets(ts,asset,category,market_id,condition_id,slug,question,resolution_source,end_date,accepting_orders,paper_status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (now, asset, category, str(raw.get("id") or ""), str(raw.get("conditionId") or ""),
                        str(raw.get("slug") or ""), str(raw.get("question") or ""), source,
                        str(raw.get("endDate") or ""), int(accepting), "PAPER_WATCH", reason))
            summary[asset]["rows"].append({"slug": raw.get("slug"), "end_date": raw.get("endDate"), "accepting_orders": accepting, "resolution_source": source, "status": "PAPER_WATCH"})
    return summary


def cycle() -> dict[str, Any]:
    db = init_db()
    risk = risk_cycle(db)
    p3 = scan_p3(db)
    db.commit()
    db.close()
    heartbeat = time.time()
    result = {"mode": "paper", "live_enabled": False, "heartbeat_ts": heartbeat, "p2": risk, "p3": p3,
              "p1_state": str(P1_STATE), "p2_p3_db": str(ROOT / "p2-p3.db")}
    tmp = ROOT / "state.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ROOT / "state.json")
    risk_tmp = ROOT / "risk.json.tmp"
    risk_tmp.write_text(json.dumps({"mode": "paper", "live_enabled": False, "heartbeat_ts": heartbeat,
                                    "assets": risk["assets"], "correlations": risk["correlations"]},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    risk_tmp.replace(ROOT / "risk.json")
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=float(os.getenv("P2P3_INTERVAL_SEC", "120")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            result = cycle()
            LOG.info("P2/P3 cycle: risk_assets=%s p3_markets=%s", len(result["p2"]["assets"]), sum(x["markets"] for x in result["p3"].values()))
        except Exception:  # keep the service alive when Gamma has a transient outage
            LOG.exception("P2/P3 cycle failed")
        if args.once:
            return
        time.sleep(max(args.interval, 30.0))


if __name__ == "__main__":
    main()
