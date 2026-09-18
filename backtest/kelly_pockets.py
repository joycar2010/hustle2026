"""Pocket-level Kelly sizing: turn the calibration curve into a position-size table.

Background (phase-1 verdicts): the quote is the best per-tick probability
estimate (Q2b), but specific pockets -- (asset, t_remaining bucket, price
bucket) cells -- show persistent post-fee edge (e.g. BTC 120-180s @ 0.84-0.90).
Sizing should therefore be pocket-driven: bet only where the pocket has proven
edge, with a fraction that scales with that edge, replacing the current flat
risk fraction (live BUY logs show risk=100% of equity per order).

Method
------
observation unit   one (market, side) pair per pocket (ticks deduplicated, so
                   autocorrelated 350ms polling cannot inflate the evidence)
p-hat              Beta-shrunk win rate anchored on the pocket's average ask:
                   p = (wins + m*avg_ask) / (n + m), m = PRIOR_STRENGTH.
                   With little evidence the pocket collapses to the market
                   quote (edge -> 0, size -> 0); only sustained outperformance
                   earns size.  This encodes the Q2b verdict.
fee-adjusted cost  a' = avg_ask + 0.07*ask*(1-ask)   (strategy.py fee model)
Kelly              f* = (p - a') / (1 - a')  for a binary claim paying $1
final fraction     f  = clamp(LAMBDA * f*, 0, CAP_FRACTION)
qualification      n >= MIN_OBS and p - a' >= MIN_EDGE, else f = 0 (no entry
                   under the Kelly regime; shadow mode logs what it would do)

Outputs
-------
out/kelly_pockets.json   runtime lookup {asset: {t_bucket: {price_bucket:
                         {fraction, p_hat, edge, n}}}} + meta
out/kelly_pockets.md     design report: qualifying pockets, rejected pockets,
                         integration and governance notes

Usage:  py -3 backtest/kelly_pockets.py [--db trades.db] [--out backtest/out]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import calibrate  # shared loaders, buckets, fee model

# Env-overridable so approved gate proposals (POCKET_*) apply here directly.
PRIOR_STRENGTH = int(float(os.environ.get("POCKET_PRIOR_STRENGTH", 40)))  # pseudo-obs toward the quote
LAMBDA = float(os.environ.get("KELLY_LAMBDA", 0.25))                      # quarter-Kelly default
CAP_FRACTION = float(os.environ.get("KELLY_CAP_FRACTION", 0.10))          # per-order equity hard cap
MIN_OBS = int(float(os.environ.get("POCKET_MIN_OBS", 30)))                # distinct (market, side) to qualify
MIN_EDGE = float(os.environ.get("POCKET_MIN_EDGE", 0.005))                # fee-adjusted edge floor


def build_pockets(winners, decisions):
    """(asset, t_bucket, price_bucket) -> dedup'd win/loss evidence."""
    per_key = {}
    for d in decisions:
        win_tok = winners.get(d["condition_id"])
        if win_tok is None:
            continue
        tb = calibrate.t_bucket(d["t_remaining"])
        p = d["ask_price"]
        if tb is None or not (0.0 < p < 1.0):
            continue
        pb = round(min(int(p / calibrate.PRICE_STEP) * calibrate.PRICE_STEP, 0.98), 2)
        # one observation per (pocket, market, side); keep the last ask seen
        key = (d["asset"], tb, pb, d["condition_id"], d["side"])
        per_key[key] = (p, 1 if d["token_id"] == win_tok else 0)

    pockets = defaultdict(lambda: {"n": 0, "w": 0, "ask_sum": 0.0})
    for (asset, tb, pb, _cid, _side), (ask, win) in per_key.items():
        a = pockets[(asset, tb, pb)]
        a["n"] += 1
        a["w"] += win
        a["ask_sum"] += ask
    return pockets


def kelly_for(pocket):
    n, w, avg_ask = pocket["n"], pocket["w"], pocket["ask_sum"] / pocket["n"]
    p_hat = (w + PRIOR_STRENGTH * avg_ask) / (n + PRIOR_STRENGTH)
    cost = avg_ask + calibrate.fee_per_share(avg_ask)
    edge = p_hat - cost
    f_full = edge / (1.0 - cost) if cost < 1.0 else 0.0
    f = max(0.0, min(LAMBDA * f_full, CAP_FRACTION))
    qualified = n >= MIN_OBS and edge >= MIN_EDGE
    return {
        "n": n, "win_rate": round(w / n, 4), "avg_ask": round(avg_ask, 4),
        "p_hat": round(p_hat, 4), "edge": round(edge, 4),
        "kelly_full": round(max(0.0, f_full), 4),
        "fraction": round(f if qualified else 0.0, 4),
        "qualified": qualified,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "trades.db"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "out"))
    args = ap.parse_args()

    winners, decisions, _ = calibrate.load_rows(args.db)
    pockets = build_pockets(winners, decisions)

    table = defaultdict(lambda: defaultdict(dict))
    rows = []
    for (asset, tb, pb), agg in sorted(pockets.items()):
        r = kelly_for(agg)
        rows.append({"asset": asset, "t_bucket": tb, "price_bucket": f"{pb:.2f}", **r})
        table[asset][tb][f"{pb:.2f}"] = {
            "fraction": r["fraction"], "kelly_full": r["kelly_full"] if r["qualified"] else 0.0,
            "p_hat": r["p_hat"], "edge": r["edge"], "n": r["n"],
        }

    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prior_strength": PRIOR_STRENGTH, "lambda": LAMBDA,
        "cap_fraction": CAP_FRACTION, "min_obs": MIN_OBS, "min_edge": MIN_EDGE,
        "fee_model": "0.07 * ask * (1 - ask) per share",
        "observation_unit": "one (market, side) pair per pocket (dedup'd ticks)",
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "kelly_pockets.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "table": table}, f, ensure_ascii=False, indent=1)

    qual = [r for r in rows if r["qualified"]]
    qual.sort(key=lambda r: -r["fraction"])
    near = [r for r in rows if not r["qualified"] and r["edge"] > 0 and r["n"] >= 10]
    near.sort(key=lambda r: -r["edge"])
    lines = [
        "# Pocket-level Kelly sizing table", "",
        f"generated: {meta['generated_utc']} | prior m={PRIOR_STRENGTH} | "
        f"lambda={LAMBDA} | cap={CAP_FRACTION:.0%} | qualify: n>={MIN_OBS}, "
        f"edge>={MIN_EDGE}", "",
        f"pockets total: {len(rows)} | qualified: {len(qual)}", "",
        "## Qualified pockets (bet here, fraction = % of equity)", "",
        "| asset | t_bucket | ask | n | win_rate | p_hat | edge | full Kelly | **fraction** |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in qual:
        lines.append(
            f"| {r['asset']} | {r['t_bucket']} | {r['price_bucket']} | {r['n']} "
            f"| {r['win_rate']:.3f} | {r['p_hat']:.3f} | {r['edge']:+.4f} "
            f"| {r['kelly_full']:.3f} | **{r['fraction']:.2%}** |")
    lines += [
        "", "## Near-miss pockets (positive raw edge, failed qualification)", "",
        "| asset | t_bucket | ask | n | edge | why rejected |", "|---|---|---|---|---|---|",
    ]
    for r in near[:12]:
        why = []
        if r["n"] < MIN_OBS:
            why.append(f"n<{MIN_OBS}")
        if r["edge"] < MIN_EDGE:
            why.append(f"edge<{MIN_EDGE}")
        lines.append(f"| {r['asset']} | {r['t_bucket']} | {r['price_bucket']} "
                     f"| {r['n']} | {r['edge']:+.4f} | {', '.join(why)} |")
    lines += [
        "", "## Integration design", "",
        "1. Runtime reads `kelly_pockets.json`; on each BUY decision the",
        "   (asset, t_bucket, price_bucket) lookup replaces the flat",
        "   `order_risk_fraction` (live logs showed risk=100% per order).",
        "2. fraction = 0 (unqualified pocket) means NO ENTRY under the Kelly",
        "   regime -- entries concentrate where evidence exists.",
        "3. Existing hard limits stay on top: balance reserve, max open",
        "   positions, hourly caps, daily loss circuit, book ask_size clamp.",
        "4. Rollout: shadow first (log would-be fraction next to actual),",
        "   then flip sizing only -- entry rules unchanged in step one.",
        "5. Refresh the table on a schedule (e.g. daily) from the growing",
        "   ledger; PRIOR_STRENGTH keeps thin pockets glued to the quote.",
    ]
    with open(os.path.join(args.out, "kelly_pockets.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"pockets: {len(rows)} | qualified: {len(qual)} | outputs -> {os.path.abspath(args.out)}")
    for r in qual[:10]:
        print(f"  {r['asset']} {r['t_bucket']} @{r['price_bucket']}: "
              f"f={r['fraction']:.2%} (edge {r['edge']:+.4f}, n={r['n']})")


if __name__ == "__main__":
    main()
