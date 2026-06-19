"""影子运行统计报告:读全量 ticks.csv,算逐市场机会频率/净基差分布/分时段聚集,
   并给出【假设性累计净值曲线】与【最佳时段/最佳机会 Top-N】。

供 /api/report 调用。按 (文件 mtime, 阈值) 缓存,避免每次重读大 CSV。纯 stdlib。

⚠ 净值曲线是【假设上限】:把每段"机会 episode"(net 连续 > 阈值的一段)按【一次入场、
入场时 net、该样本名义额】估收益,未计执行折损/未必成交/下单冲击;同一错位持续多拍只算一次。
"""
from __future__ import annotations

import csv
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

HIST_LO, HIST_HI, HIST_STEP = -100, 50, 5
TOP_N = 8
CST = timezone(timedelta(hours=8))  # 北京时间 UTC+8(固定偏移,不依赖系统tzdata)

_cache: dict = {}
_lock = threading.Lock()


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _hist_edges():
    return [float(x) for x in range(HIST_LO, HIST_HI + 1, HIST_STEP)]


def _bin_index(v, edges):
    if v < edges[0]:
        return 0
    for i in range(len(edges) - 1):
        if edges[i] <= v < edges[i + 1]:
            return i + 1
    return len(edges)


def _episodes(seq, threshold):
    """seq: 已按 ts 升序的 [(ts, net, notional)]。返回机会 episode 列表。
    一段 net 连续 > 阈值 = 一次机会;pnl 按入场样本(保守)= notional*entry_net/1e4。"""
    eps = []
    cur = None
    for ts, net, notional in seq:
        if net > threshold:
            if cur is None:
                cur = {"start_ts": ts, "end_ts": ts, "entry_net": net, "peak_net": net,
                       "notional": notional, "n": 1}
            else:
                cur["end_ts"] = ts
                cur["peak_net"] = max(cur["peak_net"], net)
                cur["n"] += 1
        else:
            if cur is not None:
                eps.append(cur)
                cur = None
    if cur is not None:
        eps.append(cur)
    for e in eps:
        e["pnl"] = e["notional"] * e["entry_net"] / 1e4
        e["dur_sec"] = round((e["end_ts"] - e["start_ts"]) / 1000, 1)
    return eps


def _empty_market(key):
    edges = _hist_edges()
    return {
        "market": key, "binance_symbol": "", "samples": 0, "opp_count": 0, "opp_rate_pct": 0.0,
        "episode_count": 0, "est_pnl": 0.0,
        "net": {"min": None, "p50": None, "p90": None, "p95": None, "p99": None, "max": None, "avg": None},
        "gross_avg": None, "exit_dex_avg": None, "gas_bps_avg": None, "slippage_avg": None, "net_max_at": None,
        "histogram": {"edges": edges, "counts": [0] * (len(edges) + 1)},
        "hourly": [{"hour": h, "samples": 0, "opp": 0, "opp_rate_pct": 0.0} for h in range(24)],
    }


def _compute(csv_path, threshold):
    edges = _hist_edges()
    acc: dict = {}
    total_rows = 0

    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    mk = row["market"]
                    net = float(row["net_bps"]); gross = float(row["gross_bps"])
                    exitd = float(row["exit_dex_bps"]); gasb = float(row["gas_bps"])
                    slip = float(row["slippage_bps"]); ts = int(row["ts"])
                    notional = float(row["notional_usd"])
                except (KeyError, ValueError):
                    continue
                total_rows += 1
                a = acc.get(mk)
                if a is None:
                    a = acc[mk] = {"sym": row.get("binance_symbol", ""), "nets": [], "seq": [],
                                   "gross_sum": 0.0, "exit_sum": 0.0, "gas_sum": 0.0, "slip_sum": 0.0,
                                   "opp": 0, "net_max": -1e18, "net_max_ts": None,
                                   "hist": [0] * (len(edges) + 1), "hs": [0] * 24, "ho": [0] * 24}
                a["nets"].append(net); a["seq"].append((ts, net, notional))
                a["gross_sum"] += gross; a["exit_sum"] += exitd; a["gas_sum"] += gasb; a["slip_sum"] += slip
                if net > threshold:
                    a["opp"] += 1
                if net > a["net_max"]:
                    a["net_max"] = net; a["net_max_ts"] = ts
                a["hist"][_bin_index(net, edges)] += 1
                hour = datetime.fromtimestamp(ts / 1000, tz=CST).hour  # 北京时间小时分桶
                a["hs"][hour] += 1
                if net > threshold:
                    a["ho"][hour] += 1

    markets = {}
    all_eps = []
    g_hs = [0] * 24; g_ho = [0] * 24; g_hp = [0.0] * 24  # 全局分时:样本/机会/捕获pnl
    for mk, a in acc.items():
        a["seq"].sort(key=lambda x: x[0])
        nets = sorted(a["nets"]); n = len(nets)
        eps = _episodes(a["seq"], threshold)
        for e in eps:
            e["market"] = mk; e["sym"] = a["sym"]
            all_eps.append(e)
            g_hp[datetime.fromtimestamp(e["start_ts"] / 1000, tz=CST).hour] += e["pnl"]
        m = _empty_market(mk)
        m["binance_symbol"] = a["sym"]; m["samples"] = n
        m["opp_count"] = a["opp"]; m["opp_rate_pct"] = round(a["opp"] / n * 100, 3) if n else 0.0
        m["episode_count"] = len(eps); m["est_pnl"] = round(sum(e["pnl"] for e in eps), 2)
        m["net"] = {"min": round(nets[0], 2), "max": round(nets[-1], 2),
                    "p50": round(_percentile(nets, 0.50), 2), "p90": round(_percentile(nets, 0.90), 2),
                    "p95": round(_percentile(nets, 0.95), 2), "p99": round(_percentile(nets, 0.99), 2),
                    "avg": round(sum(nets) / n, 2)}
        m["gross_avg"] = round(a["gross_sum"] / n, 2); m["exit_dex_avg"] = round(a["exit_sum"] / n, 2)
        m["gas_bps_avg"] = round(a["gas_sum"] / n, 4); m["slippage_avg"] = round(a["slip_sum"] / n, 2)
        m["net_max_at"] = a["net_max_ts"]
        m["histogram"] = {"edges": edges, "counts": a["hist"]}
        m["hourly"] = [{"hour": h, "samples": a["hs"][h], "opp": a["ho"][h],
                        "opp_rate_pct": round(a["ho"][h] / a["hs"][h] * 100, 2) if a["hs"][h] else 0.0}
                       for h in range(24)]
        markets[mk] = m
        for h in range(24):
            g_hs[h] += a["hs"][h]; g_ho[h] += a["ho"][h]

    # 假设性累计净值曲线(按 episode 起始时间排序累加)
    all_eps.sort(key=lambda e: e["start_ts"])
    equity = []
    cum = 0.0
    for e in all_eps:
        cum += e["pnl"]
        equity.append({"ts": e["start_ts"], "cum_pnl": round(cum, 2),
                       "market": e["market"], "pnl": round(e["pnl"], 2)})
    if len(equity) > 500:  # 下采样保留首尾
        step = math.ceil(len(equity) / 500)
        equity = equity[::step] + [equity[-1]]

    # 最佳时段 Top-N(全局,按机会数→捕获pnl 排序)
    best_hours = sorted(
        [{"hour": h, "samples": g_hs[h], "opp": g_ho[h],
          "opp_rate_pct": round(g_ho[h] / g_hs[h] * 100, 2) if g_hs[h] else 0.0,
          "pnl": round(g_hp[h], 2)} for h in range(24) if g_hs[h] > 0],
        key=lambda x: (x["opp"], x["pnl"]), reverse=True)[:TOP_N]

    # 最佳机会 Top-N(按单段 pnl)
    best_eps = sorted(all_eps, key=lambda e: e["pnl"], reverse=True)[:TOP_N]
    best_episodes = [{"market": e["market"], "binance_symbol": e["sym"], "start_ts": e["start_ts"],
                      "dur_sec": e["dur_sec"], "entry_net": round(e["entry_net"], 2),
                      "peak_net": round(e["peak_net"], 2), "samples": e["n"],
                      "pnl": round(e["pnl"], 2)} for e in best_eps]

    market_list = [markets[k] for k in sorted(markets)]
    tot_s = sum(m["samples"] for m in market_list)
    tot_o = sum(m["opp_count"] for m in market_list)
    return {
        "threshold_bps": threshold, "total_rows": total_rows, "generated_ts": int(time.time() * 1000),
        "hist_meta": {"lo": HIST_LO, "hi": HIST_HI, "step": HIST_STEP},
        "est_total_pnl": round(cum, 2), "episode_count": len(all_eps),
        "totals": {"samples": tot_s, "opp_count": tot_o,
                   "opp_rate_pct": round(tot_o / tot_s * 100, 3) if tot_s else 0.0},
        "equity": equity, "best_hours": best_hours, "best_episodes": best_episodes,
        "markets": market_list,
    }


def build_report(csv_path, threshold, depth=None):
    """depth: 可选的实时深度快照 {market: {max_exec_usd, slip_tol_bps, ...}};
    历史报告来自CSV缓存,深度是实时量、每次合并(不进缓存键),供逐市场显示可执行额。"""
    mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else 0
    ckey = (csv_path, round(threshold, 3))
    with _lock:
        c = _cache.get(ckey)
        if c and c["mtime"] == mtime and (time.time() - c["at"]) < 10:
            data = c["data"]
        else:
            data = _compute(csv_path, threshold)
            _cache[ckey] = {"mtime": mtime, "at": time.time(), "data": data}
    if depth:
        for m in data.get("markets", []):
            m["depth"] = depth.get(m["market"])
    # 合并 focus 标志(聚焦主流币市场,薄meme降权显示)
    try:
        from .markets import load_markets
        fmap = {mm.key: mm.focus for mm in load_markets()}
        for m in data.get("markets", []):
            m["focus"] = fmap.get(m["market"], False)
    except Exception:  # noqa: BLE001
        pass
    return data

