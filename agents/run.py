"""Slow-loop entry point: one pass of the role graph.

Usage:  py -3 -m agents.run [--db path] [--limit 50]
Outputs land in agents/out/ (reviews.jsonl, digests.jsonl, proposals.jsonl,
agent_status.json).  Designed to be run by cron/systemd-timer; a single pass
is cheap and idempotent (reviews are incremental).
"""
from __future__ import annotations

import argparse
import os

from agents import desk_agent, review_agent, search_agent, shill_agent, whale_agent
from agents.graph import Node, RoleGraph

ROOT = os.path.dirname(os.path.dirname(__file__))


def _review_node(ctx: dict) -> dict:
    reviews = review_agent.run(ctx.get("db"), ctx.get("limit", 50))
    return {"reviews": reviews, "n_reviews": len(reviews)}


def _search_node(ctx: dict) -> dict:
    drifts, proposals = search_agent.run(ctx.get("db"))
    return {"drifts": drifts, "proposals_raw": proposals,
            "n_degraded": sum(1 for d in drifts if d.verdict == "degraded")}


def build_graph() -> RoleGraph:
    g = RoleGraph()
    g.add(Node("review", _review_node, kind="agent"))
    g.add(Node("search", _search_node, kind="agent"))
    g.add(Node("whale", lambda ctx: {
        "whale_profile": (p := whale_agent.run()) and p.to_dict() or None,
        "whale_trades": p.n_trades if p else 0,
    }, kind="agent"))
    g.add(Node("shill", lambda ctx: {
        "regimes": [r.to_dict() for r in shill_agent.run(ctx.get("db"))],
    }, kind="agent"))
    g.add(Node("desk", lambda ctx: {
        "digest": desk_agent.run(
            ctx.get("reviews", []), ctx.get("drifts", []),
            ctx.get("proposals_raw", []), period=ctx.get("period", "session"),
            extras={"whale": ctx.get("whale_profile"),
                    "regimes": ctx.get("regimes")}),
    }, needs=["review", "search", "whale", "shill"], kind="agent"))
    # execution-side roles stay deterministic in the fast loop
    for role in ("risk", "sniper", "exit", "rug"):
        g.add(Node(role, None, kind="external"))
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "trades.db"))
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    g = build_graph()
    ctx = g.run({"db": args.db, "limit": args.limit, "period": "session"})
    digest = ctx.get("digest")
    reviews = ctx.get("reviews", [])
    drifts = ctx.get("drifts", [])
    print(f"reviews written: {len(reviews)} | pockets checked: {len(drifts)} "
          f"| degraded: {sum(1 for d in drifts if d.verdict == 'degraded')}")
    if digest:
        print(f"digest: pnl=${digest.total_pnl_usd} win_rate={digest.win_rate} "
              f"proposals={len(digest.proposals)} (all PENDING_HUMAN)")
    if ctx.get("errors"):
        print("role errors:", list(ctx["errors"]))
    print(f"outputs -> {os.path.join(os.path.dirname(__file__), 'out')}")


if __name__ == "__main__":
    main()
