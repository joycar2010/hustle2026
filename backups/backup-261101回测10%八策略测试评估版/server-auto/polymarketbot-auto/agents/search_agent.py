"""P2 search agent (机会猎手 v1): pocket drift detection.

Compares each QUALIFIED pocket's recent labeled outcomes against the table's
shrunk p_hat.  A pocket whose recent window results sit significantly below
expectation (one-sided z < Z_FLAG with enough samples) is flagged `degraded`
and becomes a POCKET_DISABLE proposal for the desk to weigh.

Deterministic; recency window and thresholds are explicit constants.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import defaultdict

from agents.schemas import PocketDrift, Proposal

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)

RECENT_MARKETS = 250   # most recent resolved markets to test against
MIN_RECENT_N = 15      # per-pocket sample floor before judging
Z_FLAG = -1.64         # one-sided 95%


def _pocket_key(asset, t_remaining, ask):
    for lo, hi in [(0, 15), (15, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 300)]:
        if lo <= t_remaining < hi:
            pb = min(int(ask / 0.02) * 0.02, 0.98)
            return f"{asset}/{lo}-{hi}s/{pb:.2f}"
    return None


def run(db_path: str | None = None) -> tuple[list[PocketDrift], list[Proposal]]:
    db_path = db_path or os.path.join(ROOT, "trades.db")
    with open(os.path.join(ROOT, "backtest", "out", "kelly_pockets.json"), encoding="utf-8") as f:
        table = json.load(f)["table"]
    qualified = {
        f"{a}/{tb}/{pb}": cell
        for a, tbs in table.items() for tb, pbs in tbs.items()
        for pb, cell in pbs.items() if cell.get("fraction", 0) > 0
    }
    if not qualified:
        return [], []

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    recent_cids = [r["condition_id"] for r in con.execute(
        "SELECT condition_id FROM resolutions ORDER BY resolved_ts DESC LIMIT ?",
        (RECENT_MARKETS,))]
    winners = {r["condition_id"]: r["winning_token"] for r in con.execute(
        "SELECT condition_id, winning_token FROM resolutions")}

    # one observation per (pocket, market, side) -- dedup autocorrelated ticks
    obs: dict[str, dict[tuple, int]] = defaultdict(dict)
    marks = ",".join("?" * len(recent_cids))
    for d in con.execute(
            f"""SELECT condition_id, token_id, side, t_remaining, ask_price,
                       COALESCE(asset,'BTC') AS asset
                  FROM decisions
                 WHERE side IN ('UP','DOWN') AND ask_price IS NOT NULL
                   AND token_id IS NOT NULL AND token_id != ''
                   AND condition_id IN ({marks})""", recent_cids):
        key = _pocket_key(d["asset"], d["t_remaining"], d["ask_price"])
        if key not in qualified:
            continue
        obs[key][(d["condition_id"], d["side"])] = int(
            d["token_id"] == winners[d["condition_id"]])
    con.close()

    drifts: list[PocketDrift] = []
    proposals: list[Proposal] = []
    for key, cell in sorted(qualified.items()):
        rows = obs.get(key, {})
        n = len(rows)
        p0 = float(cell["p_hat"])
        if n < MIN_RECENT_N:
            drifts.append(PocketDrift(key, p0, 0.0, n, 0.0, "insufficient"))
            continue
        wr = sum(rows.values()) / n
        z = (wr - p0) / math.sqrt(max(p0 * (1 - p0) / n, 1e-9))
        verdict = "degraded" if z < Z_FLAG else "ok"
        drifts.append(PocketDrift(key, p0, round(wr, 4), n, round(z, 2), verdict))
        if verdict == "degraded":
            proposals.append(Proposal(
                key="POCKET_DISABLE", current="enabled", proposed=key,
                reason=(f"recent win rate {wr:.3f} over {n} obs vs table "
                        f"p_hat {p0:.3f} (z={z:.2f} < {Z_FLAG})"),
                source_agent="search",
            ))
    return drifts, proposals
