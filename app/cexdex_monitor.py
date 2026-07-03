"""CEX-DEX 价差存活测量聚合 —— 供 dd 网页。只读 cexdex_shadow.csv。"""
from __future__ import annotations

import csv
import time

LOG = "./data/cexdex_shadow.csv"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def cexdex_snapshot() -> dict:
    rows = []
    try:
        with open(LOG, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        pass

    done = [r for r in rows if r.get("outcome") in ("SURVIVED", "SNIPED")]
    survived = [r for r in done if r["outcome"] == "SURVIVED"]
    sniped = [r for r in done if r["outcome"] == "SNIPED"]

    # 存活秒数分布
    survs = sorted(_f(r.get("survive_sec")) for r in done)
    surv_stats = None
    if survs:
        n = len(survs)
        surv_stats = {"count": n, "min": round(survs[0], 1), "median": round(survs[n // 2], 1),
                      "max": round(survs[-1], 1)}

    # peak 价差分布
    peaks = sorted(_f(r.get("peak_bps")) for r in done)
    peak_stats = None
    if peaks:
        n = len(peaks)
        peak_stats = {"median": round(peaks[n // 2], 1), "max": round(peaks[-1], 1)}

    span_h = None
    if rows:
        ts = [_f(r.get("open_ts")) for r in rows if _f(r.get("open_ts")) > 0]
        if ts:
            span_h = round((max(ts) - min(ts)) / 3600_000, 1)

    recent = []
    for r in rows[-25:][::-1]:
        recent.append({"peak_bps": r.get("peak_bps"), "open_bps": r.get("open_bps"),
                       "survive_sec": r.get("survive_sec"), "survive_blocks": r.get("survive_blocks"),
                       "outcome": r.get("outcome") or "(进行中)"})

    return {
        "now_bj": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 8 * 3600)),
        "total_gaps": len(done), "survived": len(survived), "sniped": len(sniped),
        "survive_rate": round(len(survived) / len(done) * 100, 1) if done else 0,
        "span_hours": span_h,
        "surv_sec_stats": surv_stats, "peak_stats": peak_stats,
        "recent": recent,
        "verdict": _verdict(done, survived),
    }


def _verdict(done, survived) -> str:
    if not done:
        return "采集中,暂无张开到成本线以上的缝隙(市场高效,平静期无机会)"
    sr = len(survived) / len(done) * 100
    if len(survived) == 0:
        return (f"已捕{len(done)}个>成本缝隙,存活0个 → 全部秒内闭合(被专业玩家同块吃掉),"
                f"轮询型后来者碰不到,DEX-CEX+MEV 无边")
    if sr < 20:
        return f"存活率{sr:.0f}%(低),绝大多数缝隙秒内被抢;边极薄"
    return f"存活率{sr:.0f}%,有{len(survived)}个缝隙撑过≥2区块 → 轮询型或有空间,值得深究"
