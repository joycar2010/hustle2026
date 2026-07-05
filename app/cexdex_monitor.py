"""CEX-DEX 价差存活测量聚合(加固版:多对×双门槛) —— 供 dd 网页。只读 cexdex_shadow.csv。"""
from __future__ import annotations

import csv
import time
from collections import defaultdict

LOG = "./data/cexdex_shadow.csv"
COST_RETAIL = 38.0
COST_PRO = 25.0


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

    # 按 (pair, threshold) 分组
    grp = defaultdict(lambda: {"gaps": 0, "survived": 0, "peaks": [], "survs": []})
    for r in done:
        k = (r.get("pair", "?"), r.get("threshold", "?"))
        g = grp[k]
        g["gaps"] += 1
        if r["outcome"] == "SURVIVED":
            g["survived"] += 1
        g["peaks"].append(_f(r.get("peak_bps")))
        g["survs"].append(_f(r.get("survive_sec")))
    by_group = []
    for (pair, thr), g in sorted(grp.items()):
        cost = COST_RETAIL if thr == "retail" else COST_PRO
        max_meat = (max(g["peaks"]) - cost) if g["peaks"] else 0
        by_group.append({
            "pair": pair, "threshold": thr, "gaps": g["gaps"], "survived": g["survived"],
            "survive_rate": round(g["survived"] / g["gaps"] * 100, 1) if g["gaps"] else 0,
            "peak_max": round(max(g["peaks"]), 1) if g["peaks"] else None,
            "max_meat_bps": round(max_meat, 1),
            "surv_median_sec": round(sorted(g["survs"])[len(g["survs"]) // 2], 1) if g["survs"] else None,
        })

    span_h = None
    if rows:
        ts = [_f(r.get("open_ts")) for r in rows if _f(r.get("open_ts")) > 0]
        if ts:
            span_h = round((max(ts) - min(ts)) / 3600_000, 1)

    retail = [r for r in done if r.get("threshold") == "retail"]
    pro = [r for r in done if r.get("threshold") == "pro"]

    recent = []
    for r in rows[-25:][::-1]:
        recent.append({"pair": r.get("pair"), "threshold": r.get("threshold"),
                       "peak_bps": r.get("peak_bps"), "survive_sec": r.get("survive_sec"),
                       "survive_blocks": r.get("survive_blocks"), "outcome": r.get("outcome") or "(进行中)"})

    return {
        "now_bj": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 8 * 3600)),
        "total_gaps": len(done), "span_hours": span_h,
        "retail_gaps": len(retail), "pro_gaps": len(pro),
        "by_group": by_group, "recent": recent,
        "verdict": _verdict(done, retail, pro, span_h, by_group),
    }


def _verdict(done, retail, pro, span_h, by_group) -> str:
    if not done:
        return "采集中,暂无缝隙张开到门槛(市场高效,平静期无机会)"
    per_day_r = len(retail) / (span_h / 24) if span_h and span_h > 0 else 0
    per_day_p = len(pro) / (span_h / 24) if span_h and span_h > 0 else 0
    # 最厚肉(散户视角)
    meats = [g["max_meat_bps"] for g in by_group if g["threshold"] == "retail"]
    max_meat = max(meats) if meats else 0
    if len(retail) < 5 or max_meat < 5:
        return (f"散户门槛(38bps)缝隙{per_day_r:.1f}个/天、最厚肉{max_meat:.1f}bps;"
                f"专业门槛(25bps)也仅{per_day_p:.1f}个/天 → 池被更快玩家焊死在成本线内,"
                f"频率灾难×肉薄,经济性KILL(样本{len(done)},{span_h}h)")
    return f"散户缝隙{per_day_r:.1f}个/天 最厚肉{max_meat:.0f}bps,专业{per_day_p:.1f}个/天 → 值得深究"
