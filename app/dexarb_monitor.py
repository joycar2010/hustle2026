"""DEX-DEX 影子测量数据聚合 —— 供 dd.hustle2026.xyz 网页。只读 dexarb_shadow.csv。"""
from __future__ import annotations

import csv
import os
import time
from collections import defaultdict

SHADOW_LOG = "./data/dexarb_shadow.csv"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def shadow_snapshot() -> dict:
    rows = []
    try:
        with open(SHADOW_LOG, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        pass

    now = time.time() * 1000
    h24 = now - 86400_000
    recent = [r for r in rows if _f(r.get("ts")) >= h24]

    # 按 outcome 聚合(回查完成的才有 outcome)
    done = [r for r in rows if r.get("outcome") in ("SURVIVED", "DECAYED")]
    survived = [r for r in done if r["outcome"] == "SURVIVED"]
    decayed = [r for r in done if r["outcome"] == "DECAYED"]

    # 按交易对统计
    by_pair = defaultdict(lambda: {"opps": 0, "survived": 0, "best_net": -1e9})
    for r in done:
        p = r.get("pair", "?")
        by_pair[p]["opps"] += 1
        if r["outcome"] == "SURVIVED":
            by_pair[p]["survived"] += 1
        by_pair[p]["best_net"] = max(by_pair[p]["best_net"], _f(r.get("net_bps"), -1e9))
    pairs = []
    for p, d in sorted(by_pair.items(), key=lambda x: -x[1]["opps"]):
        pairs.append({"pair": p, "opps": d["opps"], "survived": d["survived"],
                      "survive_rate": round(d["survived"] / d["opps"] * 100, 1) if d["opps"] else 0,
                      "best_net": round(d["best_net"], 1) if d["best_net"] > -1e9 else None})

    # 存活机会的净利分布(这才是"后来者真能抓的")
    surv_nets = sorted(_f(r.get("net_bps")) for r in survived)
    surv_stats = None
    if surv_nets:
        n = len(surv_nets)
        surv_stats = {"count": n, "min": round(surv_nets[0], 1), "max": round(surv_nets[-1], 1),
                      "median": round(surv_nets[n // 2], 1)}

    # 最近机会(含未回查的)
    recent_opps = []
    for r in rows[-30:][::-1]:
        recent_opps.append({
            "pair": r.get("pair"), "buy": r.get("buy_dex"), "sell": r.get("sell_dex"),
            "notional": r.get("notional"), "spread_bps": r.get("spread_bps"),
            "net_bps": r.get("net_bps"), "survive_blocks": r.get("survive_blocks"),
            "outcome": r.get("outcome") or "(待回查)",
        })

    # 运行时长估算
    span_h = None
    if rows:
        tss = [_f(r.get("ts")) for r in rows if _f(r.get("ts")) > 0]
        if tss:
            span_h = round((max(tss) - min(tss)) / 3600_000, 1)

    return {
        "now_bj": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now / 1000 + 8 * 3600)),
        "total_opps_logged": len(done),
        "survived": len(survived), "decayed": len(decayed),
        "survive_rate": round(len(survived) / len(done) * 100, 1) if done else 0,
        "opps_24h": len([r for r in recent if r.get("outcome") in ("SURVIVED", "DECAYED")]),
        "span_hours": span_h,
        "surv_net_stats": surv_stats,
        "by_pair": pairs,
        "recent": recent_opps,
        "verdict": _verdict(done, survived),
    }


def _verdict(done, survived) -> str:
    """给一句话裁决:后来者有没有边。"""
    if not done:
        return "采集中,暂无回查完成的机会(或无机会达标)"
    sr = len(survived) / len(done) * 100
    if len(survived) == 0:
        return f"已测{len(done)}个理论机会,存活0个 → 全部被抢跑/塌缩,轮询后来者无边"
    if sr < 20:
        return f"存活率{sr:.0f}%(低),绝大多数被抢跑;偶有存活但频率极低,边很薄"
    return f"存活率{sr:.0f}%,有{len(survived)}个机会N块后仍在 → 值得深究可捕获性"
