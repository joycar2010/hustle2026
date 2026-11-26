"""P1 review agent: per-window attribution from the ledger.

For each resolved market not yet reviewed, assemble a WindowReview from
trades.db (decisions + orders + resolutions), the kelly pocket table and the
kelly shadow log.  Fully deterministic; the optional LLM narrative is fetched
through the dashboard advisor endpoint only when AGENTS_LLM_ENABLED=true and
never carries decisions.

State: reviewed window ids tracked in out/reviewed_ids.txt so repeated runs
are incremental.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter

from agents.schemas import WindowReview, write_jsonl

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")


def _pocket(asset: str, t_remaining: float, ask: float):
    # mirror backtest/calibrate.py buckets
    for lo, hi in [(0, 15), (15, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 300)]:
        if lo <= t_remaining < hi:
            pb = min(int(ask / 0.02) * 0.02, 0.98)
            return f"{asset}/{lo}-{hi}s/{pb:.2f}"
    return None


def _load_qualified() -> set[str]:
    try:
        with open(os.path.join(ROOT, "backtest", "out", "kelly_pockets.json"), encoding="utf-8") as f:
            table = json.load(f)["table"]
        return {
            f"{a}/{tb}/{pb}"
            for a, tbs in table.items()
            for tb, pbs in tbs.items()
            for pb, cell in pbs.items()
            if cell.get("fraction", 0) > 0
        }
    except Exception:
        return set()


def _shadow_counts(path: str) -> Counter:
    counts: Counter = Counter()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    counts[json.loads(line).get("market")] += 1
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return counts


def run(db_path: str | None = None, limit: int = 50) -> list[WindowReview]:
    db_path = db_path or os.path.join(ROOT, "trades.db")
    seen_path = os.path.join(OUT, "reviewed_ids.txt")
    seen = set()
    if os.path.exists(seen_path):
        seen = set(open(seen_path, encoding="utf-8").read().split())

    qualified = _load_qualified()
    shadow = _shadow_counts(os.path.join(ROOT, "logs", "kelly_shadow.jsonl"))

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    resolved = con.execute(
        """SELECT r.condition_id, r.winning_token, r.resolved_ts
             FROM resolutions r ORDER BY r.resolved_ts DESC LIMIT ?""",
        (limit * 3,)).fetchall()

    reviews: list[WindowReview] = []
    for r in resolved:
        cid = r["condition_id"]
        if cid in seen or len(reviews) >= limit:
            continue
        decs = con.execute(
            """SELECT side, token_id, t_remaining, ask_price, action, reason,
                      COALESCE(asset,'BTC') AS asset, market_slug, ts
                 FROM decisions WHERE condition_id=?""", (cid,)).fetchall()
        if not decs:
            continue
        orders = con.execute(
            """SELECT side, token_id, price, size, filled_size, status, dry_run
                 FROM orders WHERE condition_id=?
                  AND status IN ('filled','matched','dry_run')""", (cid,)).fetchall()

        buys = [d for d in decs if d["action"] == "BUY"]
        skips = [d for d in decs if d["action"].startswith("SKIP")]
        pnl = 0.0
        order_rows = []
        for o in orders:
            price = o["price"] or 0
            if not (0 < price < 1):
                continue
            stake = o["filled_size"] or (o["size"] or 0) * price  # USD notional
            shares = stake / price if price else 0.0
            win = o["token_id"] == r["winning_token"]
            row_pnl = shares * (1 - price) if win else -stake
            if o["status"] != "dry_run":
                pnl += row_pnl
            order_rows.append({
                "side": o["side"], "price": price, "stake_usd": round(stake, 4),
                "result": "HIT" if win else "MISS", "dry_run": bool(o["dry_run"]),
            })

        pockets = sorted({
            p for d in buys
            if (p := _pocket(d["asset"], d["t_remaining"], d["ask_price"] or 0)) in qualified
        })
        # outcome side derived from any decision row whose token matches winner
        outcome = next(
            (d["side"] for d in decs if d["token_id"] == r["winning_token"] and d["side"]),
            "?")
        reviews.append(WindowReview(
            condition_id=cid,
            market_slug=decs[0]["market_slug"],
            asset=decs[0]["asset"],
            end_ts=max(d["ts"] + d["t_remaining"] for d in decs),
            outcome_side=outcome,
            n_buys=len(buys),
            n_skips=len(skips),
            top_skip_reasons=Counter(d["action"] for d in skips).most_common(3),
            orders=order_rows,
            pnl_usd=round(pnl, 4),
            pocket_hits=pockets,
            kelly_shadow_rows=shadow.get(decs[0]["market_slug"], 0),
        ))
    con.close()

    for rv in reviews:
        write_jsonl(os.path.join(OUT, "reviews.jsonl"), rv)
    if reviews:
        os.makedirs(OUT, exist_ok=True)
        with open(seen_path, "a", encoding="utf-8") as f:
            f.write("\n".join(rv.condition_id for rv in reviews) + "\n")
    return reviews
