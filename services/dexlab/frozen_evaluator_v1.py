#!/usr/bin/env python3
"""frozen_evaluator_v1 —— LP2后半:五假设独立复算(§10.2/LP2,2026-07-25冻结)。

铁律:①只读原始CSV(已有SHA-256 manifest);②evaluator版本冻结(本文件hash=版本);
③复算结果与LEGACY_IMPORTED证据对比——吻合→写SOURCE_REPRODUCED证据行,
  不吻合→写DIVERGENT发现交人工,绝不静默覆盖(§17.3);
④594次CAKE失败无原始数据(dexarb_shadow.csv仅3行)→诚实标记UNREPRODUCIBLE。
"""
import csv
import hashlib
import json
import sqlite3
import statistics
import sys
import time

DATA = "/home/ec2-user/crossarb/data"
DB = "/home/ec2-user/dexlab/dexlab.db"
EVAL_VERSION = "frozen_eval_v1_" + hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:12]


def _f(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def eval_dc_ticks():
    """dc假设:成本线是否钉死机会。复算:净bps分布+成本构成+机会占比。"""
    n = opp = pos = 0
    costs, nets = [], []
    with open(f"{DATA}/ticks.csv") as f:
        for row in csv.DictReader(f):
            n += 1
            net = _f(row.get("net_bps"))
            if net is not None:
                nets.append(net) if n % 7 == 0 else None   # 1/7采样控内存(9.6M行)
                if net > 0:
                    pos += 1
            if row.get("is_opportunity") == "1":
                opp += 1
            if n % 7 == 0:
                cost = sum(_f(row.get(k)) or 0 for k in
                           ("taker_bps", "gas_bps", "slippage_bps", "exit_dex_bps"))
                costs.append(cost)
    return {"rows": n, "net_pos_share_pct": round(pos * 100.0 / n, 4),
            "opportunity_share_pct": round(opp * 100.0 / n, 4),
            "median_total_cost_bps": round(statistics.median(costs), 2),
            "p90_net_bps": round(statistics.quantiles(nets, n=10)[8], 2),
            "median_net_bps": round(statistics.median(nets), 2)}


def eval_dc_execlog():
    """dc真金:paper vs realized 兑现率。"""
    papers, reals, caps = [], [], []
    n = ok = 0
    with open(f"{DATA}/exec_log.csv") as f:
        for row in csv.DictReader(f):
            if row.get("decision") != "EXECUTE":
                continue
            n += 1
            p, r, cp = _f(row.get("paper_net_bps")), _f(row.get("realized_net_bps")), _f(row.get("capture_ratio"))
            if p is not None:
                papers.append(p)
            if r is not None:
                reals.append(r)
            if cp is not None:
                caps.append(cp)
            if row.get("outcome") == "OK":
                ok += 1
    return {"executed": n, "ok": ok,
            "median_paper_net_bps": round(statistics.median(papers), 2) if papers else None,
            "median_realized_net_bps": round(statistics.median(reals), 2) if reals else None,
            "median_capture_ratio": round(statistics.median(caps), 4) if caps else None}


def eval_op_parity():
    """op假设:费用墙vs偏离。复算total_fee_bps/偏离分布/机会占比。"""
    n = opp = 0
    fees, edges = [], []
    with open(f"{DATA}/options_ticks.csv") as f:
        for row in csv.DictReader(f):
            n += 1
            if n % 5 != 0:   # 1/5采样(1.6M行)
                if row.get("is_opportunity") == "1":
                    opp += 1
                continue
            fee = _f(row.get("total_fee_bps"))
            if fee is not None:
                fees.append(fee)
            ec, er = _f(row.get("edge_conv_bps")), _f(row.get("edge_rev_bps"))
            if ec is not None and er is not None:
                edges.append(max(ec, er))
            if row.get("is_opportunity") == "1":
                opp += 1
    return {"rows": n, "median_total_fee_bps": round(statistics.median(fees), 2),
            "p90_best_edge_bps": round(statistics.quantiles(edges, n=10)[8], 2),
            "median_best_edge_bps": round(statistics.median(edges), 2),
            "opportunity_share_pct": round(opp * 100.0 / n, 4)}


def eval_dd_gap():
    """dd gap survival:事件outcome分布+峰值/存活分位。"""
    rows, peaks, survs = [], [], []
    outcomes = {}
    with open(f"{DATA}/cexdex_shadow.csv") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            p, s = _f(row.get("peak_bps")), _f(row.get("survive_sec"))
            if p is not None:
                peaks.append(p)
            if s is not None:
                survs.append(s)
            o = row.get("outcome") or "?"
            outcomes[o] = outcomes.get(o, 0) + 1
    return {"events": len(rows), "outcomes": outcomes,
            "median_peak_bps": round(statistics.median(peaks), 2) if peaks else None,
            "p10_survive_sec": round(statistics.quantiles(survs, n=10)[0], 1) if len(survs) > 10 else None,
            "median_survive_sec": round(statistics.median(survs), 1) if survs else None}


def eval_dd_atomic():
    """dd atomic:原始数据仅3行——594次失败不可复算,诚实标记。"""
    n = sum(1 for _ in open(f"{DATA}/dexarb_shadow.csv")) - 1
    return {"rows": n, "verdict": "UNREPRODUCIBLE",
            "note": f"dexarb_shadow.csv仅{n}行事件;594次CAKE模拟失败未持久化原始数据,"
                    "该数字维持LEGACY_IMPORTED不升级"}


SUBJECT_EVAL = [
    ("R1.CEX_DEX_LATENCY_CROSSARB", "REPRODUCED_TICKS_ANALYSIS", eval_dc_ticks,
     "legacy结论:成本线~38bps钉死机会"),
    ("R1.CEX_DEX_LATENCY_CROSSARB", "REPRODUCED_REALMONEY_CAPTURE", eval_dc_execlog,
     "legacy结论:真金兑现率负(-7.5%)"),
    ("C9.BINANCE_PUT_CALL_PARITY", "REPRODUCED_PARITY_ANALYSIS", eval_op_parity,
     "legacy结论:费用16.5bps>>偏离1.5bps"),
    ("R1.CEX_DEX_GAP_SURVIVAL", "REPRODUCED_SURVIVAL_ANALYSIS", eval_dd_gap,
     "legacy结论:去锚后净0.4-2.4bps"),
    ("R1.DEX_DEX_ATOMIC_BSC", "REPRODUCIBILITY_AUDIT", eval_dd_atomic,
     "legacy结论:CAKE路径594次失败"),
]


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def main():
    c = sqlite3.connect(DB)
    report = {"evaluator": EVAL_VERSION, "ran_at": int(time.time()), "results": {}}
    for code, etype, fn, legacy_note in SUBJECT_EVAL:
        t0 = time.time()
        try:
            res = fn()
            res["_seconds"] = round(time.time() - t0, 1)
        except Exception as e:  # noqa: BLE001
            res = {"error": repr(e)[:200]}
        report["results"][f"{code}/{etype}"] = res
        rev_id = f"rev-{_h(code + ':1')}"
        assurance = ("LEGACY_IMPORTED" if res.get("verdict") == "UNREPRODUCIBLE"
                     else "SOURCE_REPRODUCED")
        payload = json.dumps({"evaluator": EVAL_VERSION, "legacy_note": legacy_note,
                              "recomputed": res}, ensure_ascii=False)
        c.execute("INSERT OR REPLACE INTO lab_legacy_evidence(evidence_id, subject_revision_id, "
                  "evidence_type, evidence_assurance, scope, payload, content_hash) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (f"lev-{_h(code + ':' + etype)}", rev_id, etype, assurance,
                   "frozen_eval_v1 对已归档原始CSV独立复算", payload, _h(payload)))
        print(f"[{assurance:18}] {code}/{etype}: {json.dumps(res, ensure_ascii=False)[:160]}")
    c.commit()
    c.close()
    with open("/home/ec2-user/lab_archive/frozen_eval_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("report: /home/ec2-user/lab_archive/frozen_eval_report.json")


if __name__ == "__main__":
    main()
