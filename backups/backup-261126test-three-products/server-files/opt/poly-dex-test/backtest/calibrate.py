"""Phase-1 calibration pipeline: build the statistical ground for the p-hat engine.

Reads the historical ledger (trades.db: decisions + orders + resolutions) and produces:

  out/calibration_curve.csv  -- empirical win rate vs quoted ask, bucketed by
                                (asset, t_remaining bucket, price bucket), with
                                fee-adjusted expected value per share.
  out/lr_table.json          -- log likelihood-ratio table for spot delta
                                observations, bucketed by (asset, t bucket,
                                delta bucket).  Runtime shape: posterior odds
                                O_new = O_old * exp(log_lr).
  out/rule_performance.csv   -- per entry_rule realized performance of actual
                                filled orders (win rate, avg price, PnL/$).
  out/summary.md             -- human-readable digest of the findings.

Stdlib only (sqlite3/json/csv/math/re) so it runs on the bare system Python.
Selection-bias caveat: resolutions only exist for markets the bot traded, so
labels over-represent windows that passed the entry filters.  Bucket rows carry
`n_markets` (distinct windows) alongside `n_ticks` to expose the effective
sample size; consecutive ticks of one window are strongly autocorrelated.

Ledger quirk (verified 2026-09-17): decision rows for SKIP_PRICE, SKIP_EDGE
and SKIP_SIZE were logged WITHOUT a token_id (NULL) until strategy.py was
fixed on 2026-09-17 to backfill the considered side's token.  Rows lacking a
token_id are excluded from all label-dependent aggregates; post-fix rows carry
the token and enter automatically.

Usage:  py -3 backtest/calibrate.py [--db trades.db] [--out backtest/out]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

TAKER_FEE_RATE = 0.07  # mirrors strategy.py fee model: fee/share = rate * p * (1-p)

T_BUCKETS = [(0, 15), (15, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 300)]
PRICE_STEP = 0.02
# Delta buckets are asset-scaled (ETH moves ~1/10 of BTC in USD terms).
DELTA_EDGES = {
    "BTC": [-1e18, -100, -50, -25, -10, -5, 0, 5, 10, 25, 50, 100, 1e18],
    "ETH": [-1e18, -10, -5, -2.5, -1, -0.5, 0, 0.5, 1, 2.5, 5, 10, 1e18],
}
DELTA_RE = re.compile(r"delta=([+-]?\d+(?:\.\d+)?)")


def t_bucket(t: float) -> str | None:
    for lo, hi in T_BUCKETS:
        if lo <= t < hi:
            return f"{lo}-{hi}s"
    return None


def delta_bucket(asset: str, d: float) -> str:
    edges = DELTA_EDGES.get(asset, DELTA_EDGES["BTC"])
    for lo, hi in zip(edges, edges[1:]):
        if lo <= d < hi:
            fmt = lambda x: ("-inf" if x <= -1e17 else "+inf" if x >= 1e17 else f"{x:+g}")
            return f"[{fmt(lo)},{fmt(hi)})"
    return "?"


def fee_per_share(price: float) -> float:
    return TAKER_FEE_RATE * price * (1.0 - price)


def load_rows(db_path: str):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # winning token per resolved market
    winners = {
        r["condition_id"]: r["winning_token"]
        for r in cur.execute("SELECT condition_id, winning_token FROM resolutions")
    }

    # labeled decision ticks (only markets that later resolved); rows without
    # a token_id (pre-fix SKIP_PRICE/SKIP_EDGE/SKIP_SIZE logging, see module
    # docstring) are dropped because their win label cannot be derived.
    decisions = cur.execute(
        """SELECT condition_id, token_id, side, t_remaining, ask_price, reason,
                  COALESCE(asset,'BTC') AS asset
             FROM decisions
            WHERE side IN ('UP','DOWN') AND ask_price IS NOT NULL
              AND token_id IS NOT NULL AND token_id != ''""",
    ).fetchall()

    orders = cur.execute(
        """SELECT condition_id, token_id, side, size, price, filled_size, status,
                  dry_run, COALESCE(entry_rule,'(none)') AS entry_rule,
                  COALESCE(asset,'BTC') AS asset
             FROM orders
            WHERE side IN ('UP','DOWN')""",
    ).fetchall()
    con.close()
    return winners, decisions, orders


def build_calibration(winners, decisions):
    """(asset, t_bucket, price_bucket) -> tick/market counts and win rate."""
    agg = defaultdict(lambda: {"n": 0, "w": 0, "markets": set(), "price_sum": 0.0})
    for d in decisions:
        win_tok = winners.get(d["condition_id"])
        if win_tok is None:
            continue
        tb = t_bucket(d["t_remaining"])
        if tb is None:
            continue
        p = d["ask_price"]
        if not (0.0 < p < 1.0):
            continue
        pb = min(int(p / PRICE_STEP) * PRICE_STEP, 0.98)
        key = (d["asset"], tb, round(pb, 2))
        a = agg[key]
        a["n"] += 1
        a["w"] += 1 if d["token_id"] == win_tok else 0
        a["markets"].add(d["condition_id"])
        a["price_sum"] += p
    rows = []
    for (asset, tb, pb), a in sorted(agg.items()):
        wr = a["w"] / a["n"]
        avg_p = a["price_sum"] / a["n"]
        ev = wr - avg_p - fee_per_share(avg_p)  # EV per share at avg quoted ask
        rows.append({
            "asset": asset, "t_bucket": tb, "price_bucket": f"{pb:.2f}",
            "n_ticks": a["n"], "n_markets": len(a["markets"]),
            "win_rate": round(wr, 4), "avg_ask": round(avg_p, 4),
            "ev_per_share": round(ev, 4),
        })
    return rows


def build_lr_table(winners, decisions):
    """log-LR of observing a delta bucket given UP-win vs DOWN-win.

    Outcome is per market (did the UP token win), independent of which side the
    decision row was evaluating; delta sign is already UP-positive.
    """
    # market -> up_token (derived from any UP-side decision row)
    up_token = {}
    for d in decisions:
        if d["side"] == "UP":
            up_token.setdefault(d["condition_id"], d["token_id"])

    counts = defaultdict(lambda: [0, 0])  # (asset, tb, db) -> [n_up_win, n_down_win]
    totals = defaultdict(lambda: [0, 0])  # (asset, tb) -> totals for normalization
    used = 0
    for d in decisions:
        win_tok = winners.get(d["condition_id"])
        ut = up_token.get(d["condition_id"])
        if win_tok is None or ut is None:
            continue
        m = DELTA_RE.search(d["reason"] or "")
        if not m:
            continue
        tb = t_bucket(d["t_remaining"])
        if tb is None:
            continue
        up_won = 1 if win_tok == ut else 0
        db = delta_bucket(d["asset"], float(m.group(1)))
        counts[(d["asset"], tb, db)][0 if up_won else 1] += 1
        totals[(d["asset"], tb)][0 if up_won else 1] += 1
        used += 1

    table = defaultdict(dict)
    for (asset, tb, db), (nu, nd) in sorted(counts.items()):
        tu, td = totals[(asset, tb)]
        if tu == 0 or td == 0:
            continue
        # Laplace-smoothed conditional frequencies
        p_up = (nu + 1) / (tu + 2)
        p_dn = (nd + 1) / (td + 2)
        table[asset].setdefault(tb, {})[db] = {
            "log_lr": round(math.log(p_up / p_dn), 4),
            "n_up_win": nu, "n_down_win": nd,
        }
    return table, used


def build_rule_performance(winners, orders):
    agg = defaultdict(lambda: {"n": 0, "w": 0, "stake": 0.0, "pnl": 0.0, "price_sum": 0.0})
    for o in orders:
        if o["status"] not in ("filled", "matched"):
            continue
        win_tok = winners.get(o["condition_id"])
        if win_tok is None:
            continue
        price = o["price"] or 0.0
        if not (0 < price < 1):
            continue
        # filled_size is USD notional (size*price, verified 2026-09-17);
        # convert to shares so the $1-per-winning-share payout is correct.
        stake_usd = o["filled_size"] or ((o["size"] or 0.0) * price)
        shares = stake_usd / price
        if shares <= 0:
            continue
        key = (o["entry_rule"], "live" if o["dry_run"] == 0 else "paper")
        a = agg[key]
        win = o["token_id"] == win_tok
        a["n"] += 1
        a["w"] += 1 if win else 0
        a["stake"] += stake_usd
        a["pnl"] += shares * (1 - price) if win else -stake_usd
        a["price_sum"] += price
    rows = []
    for (rule, mode), a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        rows.append({
            "entry_rule": rule, "mode": mode, "n_orders": a["n"],
            "win_rate": round(a["w"] / a["n"], 4),
            "avg_entry_price": round(a["price_sum"] / a["n"], 4),
            "stake_usd": round(a["stake"], 2), "pnl_usd": round(a["pnl"], 2),
            "pnl_per_dollar": round(a["pnl"] / a["stake"], 4) if a["stake"] else 0.0,
        })
    return rows


def write_outputs(out_dir, cal_rows, lr_table, lr_used, rule_rows, meta):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "calibration_curve.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cal_rows[0].keys()))
        w.writeheader(); w.writerows(cal_rows)
    with open(os.path.join(out_dir, "lr_table.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta | {"labeled_delta_ticks": lr_used}, "table": lr_table}, f,
                  ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "rule_performance.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rule_rows[0].keys()))
        w.writeheader(); w.writerows(rule_rows)

    # digest: the buckets that matter most for the current strategy (>=0.84 ask)
    hot = [r for r in cal_rows if float(r["price_bucket"]) >= 0.84 and r["n_markets"] >= 10]
    hot.sort(key=lambda r: (r["asset"], r["t_bucket"], r["price_bucket"]))
    lines = [
        "# Phase-1 calibration digest", "",
        f"generated: {meta['generated_utc']}  |  db: {meta['db']}", "",
        f"- labeled decision ticks: {meta['labeled_ticks']:,} across {meta['n_markets']:,} resolved markets",
        f"- delta-parsed ticks used for LR table: {lr_used:,}",
        "- caveat: labels exist only for windows the bot traded (selection bias);",
        "  n_markets is the effective sample size, ticks are autocorrelated.", "",
        "## High-price buckets (ask >= 0.84, n_markets >= 10): win rate vs cost",
        "", "| asset | t_bucket | ask bucket | n_markets | win_rate | avg_ask | EV/share |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in hot:
        lines.append(
            f"| {r['asset']} | {r['t_bucket']} | {r['price_bucket']} | {r['n_markets']} "
            f"| {r['win_rate']:.3f} | {r['avg_ask']:.3f} | {r['ev_per_share']:+.4f} |")
    lines += ["", "## Entry-rule realized performance (filled orders)", "",
              "| rule | mode | n | win_rate | avg_price | PnL $ | PnL/$ |", "|---|---|---|---|---|---|---|"]
    for r in rule_rows:
        lines.append(
            f"| {r['entry_rule']} | {r['mode']} | {r['n_orders']} | {r['win_rate']:.3f} "
            f"| {r['avg_entry_price']:.3f} | {r['pnl_usd']:+.2f} | {r['pnl_per_dollar']:+.4f} |")
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "trades.db"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "out"))
    args = ap.parse_args()

    winners, decisions, orders = load_rows(args.db)
    labeled = sum(1 for d in decisions if d["condition_id"] in winners)
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db": os.path.abspath(args.db),
        "labeled_ticks": labeled,
        "n_markets": len(winners),
        "t_buckets": [f"{a}-{b}s" for a, b in T_BUCKETS],
        "fee_model": f"{TAKER_FEE_RATE} * p * (1-p) per share",
    }
    cal_rows = build_calibration(winners, decisions)
    lr_table, lr_used = build_lr_table(winners, decisions)
    rule_rows = build_rule_performance(winners, orders)

    # Sanity gate: on clean data a side quoted >=0.96 must win far more often
    # than not.  A failure here means label semantics broke again (as they
    # would have with the inverted SKIP_PRICE/SKIP_EDGE token_ids).
    hi = [(r["n_ticks"], r["win_rate"]) for r in cal_rows if float(r["price_bucket"]) >= 0.96]
    if hi:
        n = sum(t for t, _ in hi)
        wr = sum(t * w for t, w in hi) / n
        if wr < 0.70:
            raise SystemExit(
                f"SANITY GATE FAILED: pooled win rate at ask>=0.96 is {wr:.3f} "
                f"over {n} ticks -- label semantics look inverted; refusing to "
                "write misleading outputs.")
        print(f"sanity gate ok: ask>=0.96 pooled win rate {wr:.3f} over {n:,} ticks")
    write_outputs(args.out, cal_rows, lr_table, lr_used, rule_rows, meta)
    print(f"labeled ticks: {labeled:,} | delta ticks for LR: {lr_used:,} | "
          f"calibration buckets: {len(cal_rows)} | rule rows: {len(rule_rows)}")
    print(f"outputs -> {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
