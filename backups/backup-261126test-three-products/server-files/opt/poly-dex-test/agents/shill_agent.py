"""P2 shill agent v1 (舆情): market-internal regime proxy.

No external news/sentiment feed is wired yet, and this module says so in its
output instead of pretending.  What it CAN measure deterministically from the
ledger: the recent outcome series per asset -- UP share and flip rate over
the last N resolved windows -- which separates trending tape (streaky, low
flip rate) from choppy tape (high flip rate).  The desk uses this as context;
a real news source can replace the proxy behind the same RegimeReport shape.
"""
from __future__ import annotations

import os
import sqlite3

from agents.schemas import RegimeReport

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
WINDOWS = 60
TREND_FLIP = 0.35
CHOP_FLIP = 0.65


def run(db_path: str | None = None) -> list[RegimeReport]:
    db_path = db_path or os.path.join(ROOT, "trades.db")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # market -> UP token (from any UP-side decision row with a real token)
    up_tok = {}
    for d in con.execute(
            """SELECT condition_id, token_id FROM decisions
                WHERE side='UP' AND token_id IS NOT NULL AND token_id != ''"""):
        up_tok.setdefault(d["condition_id"], d["token_id"])
    asset_of = {r["condition_id"]: r["asset"] for r in con.execute(
        """SELECT condition_id, COALESCE(asset,'BTC') AS asset
             FROM decisions GROUP BY condition_id""")}

    series: dict[str, list[int]] = {}
    for r in con.execute(
            "SELECT condition_id, winning_token, resolved_ts FROM resolutions "
            "ORDER BY resolved_ts DESC LIMIT ?", (WINDOWS * 3,)):
        ut = up_tok.get(r["condition_id"])
        asset = asset_of.get(r["condition_id"])
        if ut is None or asset is None:
            continue
        lst = series.setdefault(asset, [])
        if len(lst) < WINDOWS:
            lst.append(1 if r["winning_token"] == ut else 0)
    con.close()

    reports = []
    for asset, outcomes in sorted(series.items()):
        n = len(outcomes)
        if n < 10:
            continue
        flips = sum(1 for a, b in zip(outcomes, outcomes[1:]) if a != b)
        flip_rate = flips / (n - 1)
        regime = ("trending" if flip_rate < TREND_FLIP
                  else "choppy" if flip_rate > CHOP_FLIP else "neutral")
        reports.append(RegimeReport(
            asset=asset, windows=n,
            up_share=round(sum(outcomes) / n, 3),
            flip_rate=round(flip_rate, 3),
            regime=regime,
        ))
    return reports
