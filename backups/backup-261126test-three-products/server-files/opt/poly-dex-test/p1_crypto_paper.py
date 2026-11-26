#!/usr/bin/env python3
"""P1 crypto Paper lane for the isolated PolyDex test instance.

This worker only reads Polymarket's public Gamma and CLOB endpoints.  It
records deterministic shadow decisions and simulated fills in its own SQLite
database.  There is intentionally no wallet, L2 credential, or live order
client in this file.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

LOG = logging.getLogger("poly-dex-p1-paper")
GAMMA = os.getenv("P1_GAMMA_HOST", "https://gamma-api.polymarket.com").rstrip("/")
CLOB = os.getenv("P1_CLOB_HOST", "https://clob.polymarket.com").rstrip("/")
STATE_DIR = Path(os.getenv("P1_STATE_DIR", "/var/lib/poly-dex-test/p1"))
DB_PATH = Path(os.getenv("P1_DB_PATH", str(STATE_DIR / "crypto-paper.db")))
P2_RISK_PATH = Path(os.getenv("P2_RISK_PATH", "/var/lib/poly-dex-test/p2-p3/risk.json"))

# Assets identified in the P1 scope.  The API currently publishes active
# recurring 5-minute series for the first four; the rest remain discoverable
# without making the worker fail when a series does not exist.
ASSET_SERIES = {
    "BTC": "btc-up-or-down-5m",
    "ETH": "eth-up-or-down-5m",
    "SOL": "sol-up-or-down-5m",
    "XRP": "xrp-up-or-down-5m",
    "DOGE": "doge-up-or-down-5m",
    "BNB": "bnb-up-or-down-5m",
    "ADA": "ada-up-or-down-5m",
    "AVAX": "avax-up-or-down-5m",
    "LTC": "ltc-up-or-down-5m",
    "LINK": "link-up-or-down-5m",
    "SUI": "sui-up-or-down-5m",
    "NEAR": "near-up-or-down-5m",
    "AAVE": "aave-up-or-down-5m",
    "UNI": "uni-up-or-down-5m",
}

PAPER_ORDER_NOTIONAL = float(os.getenv("P1_PAPER_ORDER_NOTIONAL_USD", "2"))
PAPER_MAX_OPEN_USD = float(os.getenv("P1_PAPER_MAX_OPEN_USD", "10"))
PAPER_MAX_POSITIONS = int(os.getenv("P1_PAPER_MAX_POSITIONS", "2"))
PAPER_MAX_ENTRY = float(os.getenv("P1_PAPER_MAX_ENTRY", "0.55"))
PAPER_MIN_DISCOUNT = float(os.getenv("P1_PAPER_MIN_DISCOUNT", "0.02"))
PAPER_MIN_SECONDS = float(os.getenv("P1_PAPER_MIN_SECONDS", "30"))
PAPER_MAX_SECONDS = float(os.getenv("P1_PAPER_MAX_SECONDS", "270"))
HTTP_TIMEOUT = float(os.getenv("P1_HTTP_TIMEOUT_SEC", "8"))


@dataclass(frozen=True)
class Market:
    asset: str
    slug: str
    condition_id: str
    tokens: tuple[str, str]
    start_ts: float
    end_ts: float
    neg_risk: bool

    @property
    def remaining(self) -> float:
        return self.end_ts - time.time()


def _ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# P2 is deliberately implemented as deterministic paper-side gates.  These
# controls do not sign or submit orders; they only decide whether a simulated
# fill should be recorded.  Keeping the defaults conservative makes the lane
# useful for shadow validation without changing the P1 paper contract.
P2_ENABLED = _bool(os.getenv("P2_ENABLED", "1"))
P2_MAX_SLIPPAGE_BPS = float(os.getenv("P2_MAX_SLIPPAGE_BPS", "150"))
P2_MAX_VOLATILITY = float(os.getenv("P2_MAX_VOLATILITY", "0.15"))
P2_MIN_VOLATILITY_SAMPLES = int(os.getenv("P2_MIN_VOLATILITY_SAMPLES", "6"))
P2_MAX_CORRELATED_EXPOSURE_USD = float(os.getenv("P2_MAX_CORRELATED_EXPOSURE_USD", "20"))
P2_REQUIRE_SETTLEMENT_SOURCE = _bool(os.getenv("P2_REQUIRE_SETTLEMENT_SOURCE", "1"))
P2_VOLATILITY_MODE = os.getenv("P2_VOLATILITY_MODE", "absolute").strip().lower()
P2_ALLOWED_SETTLEMENT_HOSTS = tuple(
    x.strip().lower()
    for x in os.getenv("P2_ALLOWED_SETTLEMENT_HOSTS", "data.chain.link,chain.link").split(",")
    if x.strip()
)


def _tokens(value: Any) -> tuple[str, str] | None:
    try:
        rows = json.loads(value) if isinstance(value, str) else value
        if isinstance(rows, list) and len(rows) == 2 and all(str(x) for x in rows):
            return str(rows[0]), str(rows[1])
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return None


def _request_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def discover(asset: str, series: str) -> list[Market]:
    payload = _request_json(f"{GAMMA}/events", {"series_slug": series, "closed": "false", "limit": 100})
    now = time.time()
    found: list[Market] = []
    for event in payload if isinstance(payload, list) else []:
        for raw in event.get("markets") or []:
            if _bool(raw.get("closed")) or not _bool(raw.get("active", True)):
                continue
            tokens = _tokens(raw.get("clobTokenIds"))
            start = _ts(raw.get("eventStartTime") or raw.get("startDate"))
            end = _ts(raw.get("endDate") or raw.get("endDateIso"))
            if not tokens or not start or not end or end <= now:
                continue
            if raw.get("enableOrderBook") is False:
                continue
            found.append(Market(asset, str(raw.get("slug") or event.get("slug") or ""),
                                str(raw.get("conditionId") or ""), tokens, start, end,
                                _bool(raw.get("negRisk"))))
    # Keep the current market first, then the next two windows.  De-duplicate
    # because Gamma events can contain the same market in multiple records.
    unique = {m.condition_id: m for m in found if m.condition_id}
    return sorted(unique.values(), key=lambda m: (m.start_ts > now, m.start_ts))[:3]


def quote(token: str) -> dict[str, float | None]:
    data = _request_json(f"{CLOB}/book", {"token_id": token})
    asks = []
    bids = []
    for row in data.get("asks") or []:
        try:
            p, s = float(row["price"]), float(row["size"])
            if 0 < p < 1 and s > 0:
                asks.append((p, s))
        except (KeyError, TypeError, ValueError):
            continue
    for row in data.get("bids") or []:
        try:
            p, s = float(row["price"]), float(row["size"])
            if 0 < p < 1 and s > 0:
                bids.append((p, s))
        except (KeyError, TypeError, ValueError):
            continue
    asks.sort()
    bids.sort(reverse=True)
    return {"ask": asks[0][0] if asks else None, "ask_size": asks[0][1] if asks else 0.0,
            "bid": bids[0][0] if bids else None, "bid_size": bids[0][1] if bids else 0.0,
            # Keep the full public depth in memory for a paper-only VWAP and
            # slippage check.  The database still stores best-level fields.
            "asks": asks, "bids": bids}


def vwap_for_notional(levels: list[tuple[float, float]], notional: float) -> tuple[float, float] | None:
    """Return (VWAP, quantity) for a simulated marketable buy.

    A missing level or insufficient visible depth is a risk rejection.  The
    function is intentionally side-effect free and never calls a trading API.
    """
    if notional <= 0 or not levels:
        return None
    remaining = float(notional)
    quantity = 0.0
    cost = 0.0
    for price, available in levels:
        if price <= 0 or available <= 0:
            continue
        take = min(float(available), remaining / float(price))
        if take <= 0:
            continue
        quantity += take
        cost += take * float(price)
        remaining -= take * float(price)
        if remaining <= 1e-9:
            return cost / quantity, quantity
    return None


def slippage_bps(levels: list[tuple[float, float]], notional: float) -> tuple[float, float, float] | None:
    """Return (slippage_bps, vwap, quantity) for a buy-side paper fill."""
    if not levels:
        return None
    result = vwap_for_notional(levels, notional)
    if result is None:
        return None
    vwap, quantity = result
    best = float(levels[0][0])
    if best <= 0:
        return None
    return max(0.0, (vwap - best) / best * 10000.0), vwap, quantity


def quote_volatility(db: sqlite3.Connection, condition_id: str, token_id: str) -> float | None:
    """Estimate short-window volatility from recorded public quote mids.

    Volatility is deliberately expressed as the standard deviation of log
    returns per polling interval.  We only gate when enough observations are
    available; a newly discovered market therefore remains testable while its
    history warms up.
    """
    rows = db.execute(
        "SELECT ts,ask,bid FROM quotes WHERE condition_id=? AND token_id=? "
        "ORDER BY ts DESC LIMIT ?",
        (condition_id, token_id, max(P2_MIN_VOLATILITY_SAMPLES + 1, 20)),
    ).fetchall()
    mids: list[float] = []
    for _ts_value, ask, bid in reversed(rows):
        try:
            ask_f = float(ask) if ask is not None else 0.0
            bid_f = float(bid) if bid is not None else 0.0
            if ask_f > 0 and bid_f > 0:
                mids.append((ask_f + bid_f) / 2.0)
            elif ask_f > 0:
                mids.append(ask_f)
            elif bid_f > 0:
                mids.append(bid_f)
        except (TypeError, ValueError):
            continue
    if len(mids) < P2_MIN_VOLATILITY_SAMPLES:
        return None
    returns: list[float] = []
    for prev, current in zip(mids, mids[1:]):
        if P2_VOLATILITY_MODE == "relative":
            returns.append((current - prev) / max(abs(prev), 0.10))
        else:
            # Binary outcome prices are probabilities.  Absolute probability
            # changes are bounded and comparable across a near-zero quote.
            returns.append(current - prev)
    if len(returns) < max(2, P2_MIN_VOLATILITY_SAMPLES - 1):
        return None
    return float(statistics.pstdev(returns))


def open_correlated_exposure(db: sqlite3.Connection) -> tuple[float, int]:
    """Return total open crypto exposure for this isolated paper lane."""
    placeholders = ",".join("?" for _ in ASSET_SERIES)
    row = db.execute(
        f"SELECT COALESCE(SUM(size*price),0), COUNT(*) FROM paper_orders "
        f"WHERE status='OPEN' AND asset IN ({placeholders})",
        tuple(ASSET_SERIES),
    ).fetchone()
    return float(row[0] or 0.0), int(row[1] or 0)


def settlement_source(raw: dict[str, Any]) -> tuple[bool, str]:
    """Validate the public resolution source before settling a paper fill."""
    source = str(raw.get("resolutionSource") or raw.get("resolution_source") or "").strip()
    if not source:
        # A description is useful evidence when Gamma omits the dedicated
        # field, but it must still name Chainlink for this crypto lane.
        description = str(raw.get("description") or "")
        if "chain.link" in description.lower() or "chainlink" in description.lower():
            source = "description:chainlink"
    source_lower = source.lower()
    allowed = any(host in source_lower for host in P2_ALLOWED_SETTLEMENT_HOSTS)
    if allowed:
        return True, source
    if not P2_REQUIRE_SETTLEMENT_SOURCE and source:
        return True, source
    return False, source or "missing"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT NOT NULL,
            slug TEXT, condition_id TEXT, side TEXT, token_id TEXT, action TEXT NOT NULL,
            reason TEXT NOT NULL, t_remaining REAL, ask REAL, ask_size REAL, dry_run INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS paper_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT NOT NULL,
            slug TEXT, condition_id TEXT UNIQUE, side TEXT, token_id TEXT, size REAL, price REAL,
            status TEXT NOT NULL, settled_ts REAL, pnl REAL, dry_run INTEGER NOT NULL DEFAULT 1,
            settlement_source TEXT, settlement_verified INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT NOT NULL,
            condition_id TEXT, token_id TEXT, ask REAL, ask_size REAL, bid REAL, bid_size REAL
        );
        CREATE INDEX IF NOT EXISTS idx_p1_decisions_ts ON decisions(ts);
        CREATE INDEX IF NOT EXISTS idx_p1_orders_status ON paper_orders(status);
        """)
        # Existing P1 databases are upgraded in place.  SQLite has no
        # conditional ADD COLUMN, so inspect the schema before adding fields.
        columns = {row[1] for row in db.execute("PRAGMA table_info(paper_orders)").fetchall()}
        if "settlement_source" not in columns:
            db.execute("ALTER TABLE paper_orders ADD COLUMN settlement_source TEXT")
        if "settlement_verified" not in columns:
            db.execute("ALTER TABLE paper_orders ADD COLUMN settlement_verified INTEGER NOT NULL DEFAULT 0")


def open_exposure(db: sqlite3.Connection, asset: str) -> tuple[float, int]:
    row = db.execute("SELECT COALESCE(SUM(size*price),0), COUNT(*) FROM paper_orders WHERE asset=? AND status='OPEN'", (asset,)).fetchone()
    return float(row[0] or 0), int(row[1] or 0)


def record_decision(db: sqlite3.Connection, market: Market, action: str, reason: str,
                    side: str | None, token: str | None, remaining: float,
                    ask: float | None, ask_size: float | None) -> None:
    db.execute("INSERT INTO decisions(ts,asset,slug,condition_id,side,token_id,action,reason,t_remaining,ask,ask_size) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (time.time(), market.asset, market.slug, market.condition_id, side, token,
                action, reason, remaining, ask, ask_size))


def _resolved_market(condition_id: str) -> tuple[dict[str, Any], tuple[str, str] | None, tuple[str, str] | None]:
    """Read a closed public market from Gamma, then CLOB as an archive fallback.

    Gamma eventually removes older recurring markets from its ``/markets``
    search.  The CLOB market endpoint keeps the closed record and exposes the
    winning token directly, so Paper positions must use it when Gamma returns
    no record.  Both sources remain public and settlement-source validation is
    still applied by ``settle_expired``.
    """
    try:
        matches = _request_json(f"{GAMMA}/markets", {"condition_ids": condition_id})
    except Exception as exc:  # noqa: BLE001 - try the archive endpoint below
        LOG.debug("Gamma settlement lookup failed for %s: %s", condition_id, exc)
        matches = []
    raw = matches[0] if isinstance(matches, list) and matches else {}
    prices = _tokens(raw.get("outcomePrices"))
    raw_tokens = _tokens(raw.get("clobTokenIds"))
    if raw and prices and raw_tokens and _bool(raw.get("closed")):
        return raw, prices, raw_tokens

    try:
        archived = _request_json(f"{CLOB}/markets/{condition_id}")
    except Exception as exc:  # noqa: BLE001 - unresolved rows remain OPEN
        LOG.debug("CLOB settlement lookup failed for %s: %s", condition_id, exc)
        return {}, None, None
    tokens = archived.get("tokens") if isinstance(archived, dict) else None
    if not isinstance(tokens, list) or len(tokens) != 2:
        return {}, None, None
    token_ids: list[str] = []
    outcome_prices: list[str] = []
    for item in tokens:
        if not isinstance(item, dict) or not item.get("token_id"):
            return {}, None, None
        token_ids.append(str(item["token_id"]))
        outcome_prices.append("1" if bool(item.get("winner")) else "0")
    normalized = dict(archived)
    normalized["closed"] = bool(archived.get("closed"))
    normalized["description"] = str(archived.get("description") or "")
    # The CLOB archive embeds the exact Chainlink stream URL in the
    # description instead of Gamma's dedicated resolutionSource field.
    # Preserve that verifiable URL so the existing allowed-host gate remains
    # fail-closed for non-Chainlink markets.
    match = re.search(
        r"https?://[^\s)\"]*chain\.link[^\s)\"]*",
        normalized["description"],
        flags=re.IGNORECASE,
    )
    if match:
        normalized["resolutionSource"] = match.group(0).rstrip(".,;:])")
    return normalized, (outcome_prices[0], outcome_prices[1]), (token_ids[0], token_ids[1])


def settle_expired(db: sqlite3.Connection) -> int:
    # Settlement is best-effort and remains public-data-only.  Markets not yet
    # resolved stay OPEN and are never treated as a win or loss.
    rows = db.execute("SELECT id,condition_id,token_id,price,size FROM paper_orders WHERE status='OPEN' AND ts < ?",
                      (time.time() - 20,)).fetchall()
    settled = 0
    for oid, cid, token, price, size in rows:
        try:
            raw, prices, raw_tokens = _resolved_market(str(cid))
            if not prices or not raw_tokens or not raw.get("closed"):
                continue
            source_ok, source = settlement_source(raw)
            if not source_ok:
                # Never convert an unverified outcome into a win/loss.  The
                # source is retained for diagnostics and the position stays
                # OPEN until Gamma exposes an allowed oracle source.
                db.execute("UPDATE paper_orders SET settlement_source=? WHERE id=?", (source, oid))
                LOG.warning("settlement source rejected for %s: %s", cid, source)
                continue
            winner = None
            # outcomePrices corresponds to the market's token order in the API;
            # 1.0 identifies the winning outcome when resolved.
            for i, value in enumerate(prices):
                if str(value) in {"1", "1.0"}:
                    winner = i
            if winner is None:
                continue
            win = str(token) == str(raw_tokens[winner])
            pnl = (float(size) * (1.0 - float(price))) if win else -(float(size) * float(price))
            db.execute(
                "UPDATE paper_orders SET status=?,settled_ts=?,pnl=?,settlement_source=?,settlement_verified=1 WHERE id=?",
                ("WON" if win else "LOST", time.time(), pnl, source, oid),
            )
            settled += 1
        except Exception as exc:  # noqa: BLE001 - one stale market must not stop the lane
            LOG.debug("settlement lookup failed for %s: %s", cid, exc)
    return settled


def p2_gate(asset: str) -> tuple[bool, str]:
    """Apply a fresh P2 block decision when the risk observer has one.

    Missing or stale risk output never turns into a live path; it only leaves
    the original Paper baseline running.  A BLOCK decision is fail-closed for
    the Paper entry itself and is recorded in the decision log.
    """
    try:
        payload = json.loads(P2_RISK_PATH.read_text(encoding="utf-8"))
        age = time.time() - float(payload.get("heartbeat_ts") or 0)
        if age > 600:
            return True, "P2 risk snapshot stale; baseline Paper only"
        item = (payload.get("assets") or {}).get(asset) or {}
        if item.get("status") == "BLOCK":
            return False, "P2 risk blocked: " + str(item.get("reason") or "unspecified")
        return True, "P2 risk " + str(item.get("status") or "REVIEW")
    except (OSError, ValueError, TypeError):
        return True, "P2 risk snapshot unavailable; baseline Paper only"


def cycle() -> dict[str, Any]:
    init_db()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    summary: dict[str, Any] = {
        "mode": "paper",
        "live_enabled": False,
        "assets": {},
        "errors": [],
        "p2": {
            "enabled": P2_ENABLED,
            "max_slippage_bps": P2_MAX_SLIPPAGE_BPS,
            "max_volatility": P2_MAX_VOLATILITY,
            "volatility_mode": P2_VOLATILITY_MODE,
            "max_correlated_exposure_usd": P2_MAX_CORRELATED_EXPOSURE_USD,
            "settlement_source_required": P2_REQUIRE_SETTLEMENT_SOURCE,
        },
    }
    settled = settle_expired(db)
    summary["settled"] = settled
    for asset, series in ASSET_SERIES.items():
        item: dict[str, Any] = {"asset": asset, "series": series, "markets": 0, "orders_new": 0, "rows": []}
        try:
            markets = discover(asset, series)
            item["markets"] = len(markets)
            for market in markets:
                remaining = market.remaining
                if remaining < PAPER_MIN_SECONDS or remaining > PAPER_MAX_SECONDS:
                    reason = f"remaining {remaining:.1f}s outside {PAPER_MIN_SECONDS:.0f}-{PAPER_MAX_SECONDS:.0f}s"
                    record_decision(db, market, "SKIP_TIME", reason, None, None, remaining, None, None)
                    item["rows"].append({"slug": market.slug, "action": "SKIP_TIME", "reason": reason})
                    continue
                up, down = quote(market.tokens[0]), quote(market.tokens[1])
                for token, q in ((market.tokens[0], up), (market.tokens[1], down)):
                    db.execute("INSERT INTO quotes(ts,asset,condition_id,token_id,ask,ask_size,bid,bid_size) VALUES(?,?,?,?,?,?,?,?)",
                               (time.time(), asset, market.condition_id, token, q["ask"], q["ask_size"], q["bid"], q["bid_size"]))
                candidates = [(up.get("ask"), up.get("ask_size"), "UP", market.tokens[0], up),
                              (down.get("ask"), down.get("ask_size"), "DOWN", market.tokens[1], down)]
                candidates = [x for x in candidates if x[0] is not None and float(x[1] or 0) > 0]
                if not candidates:
                    reason = "no executable public ask"
                    record_decision(db, market, "SKIP_BOOK", reason, None, None, remaining, None, None)
                    item["rows"].append({"slug": market.slug, "action": "SKIP_BOOK", "reason": reason})
                    continue
                ask, ask_size, side, token, selected_quote = min(candidates, key=lambda x: float(x[0]))
                other = max(candidates, key=lambda x: float(x[0]))[0]
                exposure, positions = open_exposure(db, asset)
                risk_ok, risk_reason = p2_gate(asset)
                can_buy = (risk_ok and float(ask) <= PAPER_MAX_ENTRY and float(other) - float(ask) >= PAPER_MIN_DISCOUNT
                            and exposure < PAPER_MAX_OPEN_USD and positions < PAPER_MAX_POSITIONS)
                if not can_buy:
                    reason = (f"baseline gate ask={float(ask):.3f}, discount={float(other)-float(ask):.3f}, "
                              f"exposure={exposure:.2f}, positions={positions}; {risk_reason}")
                    record_decision(db, market, "SKIP_SIGNAL", reason, side, token, remaining, float(ask), float(ask_size))
                    item["rows"].append({"slug": market.slug, "action": "SKIP_SIGNAL", "side": side, "ask": ask, "reason": reason})
                    continue

                # P2 risk gates run before recording a simulated fill.  They
                # use only the public order book and our own paper ledger.
                simulated_price = float(ask)
                size = min(PAPER_ORDER_NOTIONAL / simulated_price, float(ask_size), 20.0)
                p2_reason: list[str] = []
                p2_slippage = None
                p2_volatility = None
                if P2_ENABLED:
                    p2_slippage = slippage_bps(
                        selected_quote.get("asks") or [], PAPER_ORDER_NOTIONAL
                    )
                    if p2_slippage is None:
                        reason = "P2 slippage gate: insufficient visible ask depth"
                        record_decision(db, market, "SKIP_SLIPPAGE", reason, side, token, remaining, float(ask), float(ask_size))
                        item["rows"].append({"slug": market.slug, "action": "SKIP_SLIPPAGE", "side": side, "reason": reason})
                        continue
                    slip_bps, vwap, vwap_size = p2_slippage
                    p2_reason.append(f"slippage={slip_bps:.1f}bps")
                    if slip_bps > P2_MAX_SLIPPAGE_BPS:
                        reason = f"P2 slippage {slip_bps:.1f}bps > {P2_MAX_SLIPPAGE_BPS:.1f}bps"
                        record_decision(db, market, "SKIP_SLIPPAGE", reason, side, token, remaining, float(ask), float(ask_size))
                        item["rows"].append({"slug": market.slug, "action": "SKIP_SLIPPAGE", "side": side, "reason": reason})
                        continue
                    p2_volatility = quote_volatility(db, market.condition_id, token)
                    if p2_volatility is not None:
                        p2_reason.append(f"volatility={p2_volatility:.4f}")
                        if p2_volatility > P2_MAX_VOLATILITY:
                            reason = f"P2 volatility {p2_volatility:.4f} > {P2_MAX_VOLATILITY:.4f}"
                            record_decision(db, market, "SKIP_VOLATILITY", reason, side, token, remaining, float(ask), float(ask_size))
                            item["rows"].append({"slug": market.slug, "action": "SKIP_VOLATILITY", "side": side, "reason": reason})
                            continue
                    correlated_exposure, correlated_positions = open_correlated_exposure(db)
                    projected = correlated_exposure + PAPER_ORDER_NOTIONAL
                    p2_reason.append(f"correlated={correlated_exposure:.2f}/{P2_MAX_CORRELATED_EXPOSURE_USD:.2f}")
                    if projected > P2_MAX_CORRELATED_EXPOSURE_USD:
                        reason = (f"P2 correlated exposure {projected:.2f} > "
                                  f"{P2_MAX_CORRELATED_EXPOSURE_USD:.2f}")
                        record_decision(db, market, "SKIP_CORRELATION", reason, side, token, remaining, float(ask), float(ask_size))
                        item["rows"].append({"slug": market.slug, "action": "SKIP_CORRELATION", "side": side, "reason": reason})
                        continue
                    # Use the depth-aware VWAP/quantity for the simulated
                    # order.  This makes reported paper PnL reflect the
                    # same visible liquidity checked above.
                    simulated_price = float(vwap)
                    size = min(float(vwap_size), 20.0)
                cost = size * simulated_price
                with db:
                    inserted = db.execute("INSERT OR IGNORE INTO paper_orders(ts,asset,slug,condition_id,side,token_id,size,price,status) VALUES(?,?,?,?,?,?,?,?,?)",
                                          (time.time(), asset, market.slug, market.condition_id, side, token, size, simulated_price, "OPEN")).rowcount
                    reason = f"baseline discount {float(other)-float(ask):.3f}"
                    if p2_reason:
                        reason += "; " + ", ".join(p2_reason)
                    record_decision(db, market, "PAPER_BUY", reason, side, token, remaining, simulated_price, float(ask_size))
                if inserted:
                    item["orders_new"] += 1
                    item["rows"].append({"slug": market.slug, "action": "PAPER_BUY", "side": side, "price": simulated_price, "size": size, "cost": cost,
                                         "slippage_bps": p2_slippage[0] if p2_slippage else 0.0,
                                         "volatility": p2_volatility})
        except Exception as exc:  # noqa: BLE001 - continue scanning other assets
            LOG.warning("%s scan failed: %s", asset, exc)
            item["error"] = f"{type(exc).__name__}: {exc}"
            summary["errors"].append(f"{asset}: {item['error']}")
        summary["assets"][asset] = item
    db.commit()
    row = db.execute("SELECT COUNT(*), COALESCE(SUM(pnl),0) FROM paper_orders WHERE status IN ('WON','LOST')").fetchone()
    summary["paper_orders_total"] = int(row[0] or 0) + int(db.execute("SELECT COUNT(*) FROM paper_orders WHERE status='OPEN'").fetchone()[0] or 0)
    summary["paper_realized_pnl"] = float(row[1] or 0)
    summary["heartbeat_ts"] = time.time()
    summary["db_path"] = str(DB_PATH)
    db.close()
    tmp = STATE_DIR / "state.json.tmp"
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_DIR / "state.json")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=float(os.getenv("P1_INTERVAL_SEC", "60")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        result = cycle()
        LOG.info("P1 paper cycle: markets=%s orders=%s settled=%s errors=%s",
                 sum(v.get("markets", 0) for v in result["assets"].values()),
                 sum(v.get("orders_new", 0) for v in result["assets"].values()),
                 result.get("settled", 0), len(result.get("errors", [])))
        if args.once:
            return
        time.sleep(max(args.interval, 10.0))


if __name__ == "__main__":
    main()
