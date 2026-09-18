"""P2 desk agent (台长 v1): aggregate reviews + drift into a digest and vetted
proposals.

Deterministic aggregation first; when AGENTS_LLM_ENABLED=true it additionally
asks the dashboard's dual-model CONSENSUS endpoint to sanity-check the digest
(advisory only -- disagreement downgrades proposal confidence, it never
creates or applies anything).
"""
from __future__ import annotations

import json
import os
import urllib.request

from agents import gate
from agents.schemas import DeskDigest, Proposal, write_jsonl

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "out")


def _post_json(url: str, payload: dict, timeout: int = 60) -> dict | None:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None  # advisory channel down != desk down


def _llm_consensus(summary: str) -> dict | None:
    """Two-step dual-model check: /api/llm/advisor obtains BOTH models'
    answers to a constrained one-token question, then /api/llm/consensus
    arbitrates by normalized exact match over {BUY, SELL, HOLD}.  BUY is the
    protocol token for "digest healthy, proposals may go to human review";
    HOLD means "anomaly, pause".  Advisory only either way."""
    if os.environ.get("AGENTS_LLM_ENABLED", "false").lower() not in ("1", "true", "yes", "on"):
        return None
    base = os.environ.get("AGENTS_DASHBOARD_URL", "http://127.0.0.1:8887")
    prompt = (
        "你是交易台风控复核。只允许回答一个词，不要任何其他文字或标点：\n"
        "BUY  = 摘要数据健康，参数提案可以提交人工审批\n"
        "HOLD = 数据异常或风险信号，需要暂停并人工介入\n"
        f"摘要：{summary}"
    )
    adv = _post_json(f"{base}/api/llm/advisor", {"prompt": prompt}, timeout=90)
    if not adv:
        return None
    p_text = str(((adv.get("primary") or {}).get("text")) or "").strip()
    s_text = str(((adv.get("secondary") or {}).get("text")) or "").strip()
    if not p_text or not s_text:
        return {"ok": False, "decision": "HOLD",
                "reason": "顾问通道未同时返回双模型答案",
                "primary_text": p_text[:120], "secondary_text": s_text[:120]}
    cons = _post_json(f"{base}/api/llm/consensus",
                      {"primary": p_text, "secondary": s_text}) or {}
    cons["primary_text"] = p_text[:120]
    cons["secondary_text"] = s_text[:120]
    return cons


def run(reviews, drifts, raw_proposals: list[Proposal], period: str = "session",
        extras: dict | None = None) -> DeskDigest:
    vetted = gate.vet_all(list(raw_proposals))
    pnl = round(sum(r.pnl_usd for r in reviews), 4)
    settled = [o for r in reviews for o in r.orders if not o["dry_run"]]
    wins = sum(1 for o in settled if o["result"] == "HIT")
    win_rate = round(wins / len(settled), 4) if settled else None

    degraded = [d for d in drifts if d.verdict == "degraded"]
    summary = (
        f"period={period} reviews={len(reviews)} pnl=${pnl} "
        f"win_rate={win_rate} degraded_pockets={[d.pocket for d in degraded]} "
        f"proposals={[(p.key, p.proposed) for p in vetted]}"
    )
    consensus = _llm_consensus(summary)
    # Agreement is signaled by the arbiter's reason string; a unanimous HOLD
    # is still agreement (both models want a pause).  Disagreement or no
    # check keeps proposal confidence untouched except optimizer-grade highs.
    agreed = bool(consensus and "一致" in str(consensus.get("reason") or ""))
    for p in vetted:
        if p.confidence != "high":
            p.confidence = "medium" if agreed else "low"

    digest = DeskDigest(
        period=period,
        reviews=len(reviews),
        total_pnl_usd=pnl,
        win_rate=win_rate,
        drifts=[d.to_dict() for d in drifts],
        proposals=[p.to_dict() for p in vetted],
        consensus=consensus,
        extras=extras,
        narrative=summary,
    )
    write_jsonl(os.path.join(OUT, "digests.jsonl"), digest)
    for p in vetted:
        write_jsonl(os.path.join(OUT, "proposals.jsonl"), p)
    return digest
