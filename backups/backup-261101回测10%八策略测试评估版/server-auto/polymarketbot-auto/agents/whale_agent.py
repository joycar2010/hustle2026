"""P2 whale agent (聪明钱 v1): entry-behavior profile of trader 0x3725.

Uses the static research capture (trader_0x3725_trades*.json, Polymarket
data-api activity rows) that has sat unused in the repo.  Deterministic
profiling only: where in (t_remaining, price) space does this trader enter,
per asset, weighted by notional.  Window timing is recovered from the market
slug (…-15m-<start_ts> => end = start + 900s), so t_remaining at entry is
exact.  No win rates are fabricated -- the capture carries no resolutions.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from agents.schemas import WhaleProfile

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
FILES = ("trader_0x3725_trades.json", "trader_0x3725_trades_more.json")
SLUG_RE = re.compile(r"([a-z]+)-updown-(\d+)m-(\d+)$")
T_BANDS = [(0, 60), (60, 180), (180, 420), (420, 900)]
PRICE_STEP = 0.05


def _t_band(t: float) -> str | None:
    for lo, hi in T_BANDS:
        if lo <= t < hi:
            return f"{lo}-{hi}s"
    return None


def run() -> WhaleProfile | None:
    rows = []
    for name in FILES:
        path = os.path.join(ROOT, name)
        try:
            rows.extend(json.load(open(path, encoding="utf-8")))
        except Exception:
            continue
    if not rows:
        return None

    cells: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "notional": 0.0})
    assets: set[str] = set()
    total_notional = 0.0
    seen = set()
    n_used = 0
    for r in rows:
        key = (r.get("conditionId"), r.get("timestamp"), r.get("price"), r.get("size"))
        if key in seen or str(r.get("side", "")).upper() != "BUY":
            continue
        seen.add(key)
        m = SLUG_RE.search(str(r.get("slug", "")))
        price = float(r.get("price") or 0)
        size = float(r.get("size") or 0)
        if not m or not (0 < price < 1) or size <= 0:
            continue
        asset, minutes, start = m.group(1).upper(), int(m.group(2)), int(m.group(3))
        end_ts = start + minutes * 60
        t_rem = end_ts - float(r.get("timestamp") or 0)
        band = _t_band(t_rem)
        if band is None:
            continue
        pb = f"{min(int(price / PRICE_STEP) * PRICE_STEP, 0.95):.2f}"
        notional = price * size
        c = cells[(asset, band, pb)]
        c["n"] += 1
        c["notional"] += notional
        assets.add(asset)
        total_notional += notional
        n_used += 1

    if not n_used:
        return None
    top = sorted(cells.items(), key=lambda kv: -kv[1]["notional"])[:8]
    return WhaleProfile(
        trader="0x3725 (almach)",
        n_trades=n_used,
        assets=sorted(assets),
        top_cells=[{
            "asset": a, "t_band": tb, "price_band": pb,
            "share": round(v["notional"] / total_notional, 4), "n": v["n"],
        } for (a, tb, pb), v in top],
        avg_notional_usd=round(total_notional / n_used, 2),
        source="static research capture (data-api activity), resolutions absent",
    )
