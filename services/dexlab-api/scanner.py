"""dexlab-scanner(D-lab):D1/D2/D4 扫描器 worker——LAB 从『登记壳』变『真实验』的本体。

- 只读公开数据源(DefiLlama/Pendle 公共 API),无 key、无签名、零下单能力;
- 消费 lab_run(state=RUNNING, kind=MEASURE) 决定扫哪些项目——UI『开始扫描』登记的轮次
  在这里真正被执行;停止扫描(state=DONE)即停;
- 产出:lab_signal 逐样本(payload=逐标的折价/利差 bps)+ lab_run.samples/result_bps 累计
  + lab_cost_model(静态成本假设,判定净值用);
- result_bps = 扣成本后中位数机会(负=无套利空间,如实记录);
- 失败逐项目隔离:一个数据源挂了只影响该项目该轮,err 记进 run.note。

D1 可赎回稳定币/LST 折价:市场价 vs 赎回参考价(LST/ETH 比价、稳定币/1)。
D2 PT 固定到期折价:Pendle impliedApy vs underlyingApy(固定收益贴水)。
D4 同币种借贷利差:DefiLlama yields,同资产跨协议(aave/morpho/compound)存借差。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dexlab-scanner")

DB = "/home/ec2-user/dexlab/dexlab.db"
INTERVAL = 300   # 5min:公开源限频友好;折价/利差变化以小时计

# 成本模型(静态假设,进 lab_cost_model 供判定;后续可按实测更新)
COST_MODEL = {
    "D1": {"round_trip_bps": 25, "note": "DEX swap 5 + gas 5 + 赎回等待资金成本 10 + 滑点 5"},
    "D2": {"round_trip_bps": 40, "note": "Pendle swap 15 + gas 5 + 持有到期资金成本 20"},
    "D4": {"round_trip_bps": 10, "note": "存借各一次 gas + 利率漂移缓冲"},
}


def _get(url: str, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "dexlab-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── D1:LST/可赎回稳定币折价(DefiLlama prices,免key) ─────────────────────
_D1_SET = {
    # llama coin id → (名称, 参考资产 llama id, 类型)
    "coingecko:staked-ether": ("stETH", "coingecko:ethereum", "LST"),
    "coingecko:rocket-pool-eth": ("rETH", "coingecko:ethereum", "LST-带息(折价须对比exchangeRate,此处记比价)"),
    "coingecko:wrapped-beacon-eth": ("wBETH", "coingecko:ethereum", "LST-带息"),
    "coingecko:ethena-usde": ("USDe", None, "yield-stable"),
    "coingecko:first-digital-usd": ("FDUSD", None, "stable"),
    "coingecko:paypal-usd": ("PYUSD", None, "stable"),
}


def scan_d1() -> list[dict]:
    ids = list(_D1_SET) + ["coingecko:ethereum"]
    data = _get("https://coins.llama.fi/prices/current/" + ",".join(ids))
    px = {k: v.get("price") for k, v in (data.get("coins") or {}).items()}
    eth = px.get("coingecko:ethereum")
    out = []
    for cid, (name, ref, kind) in _D1_SET.items():
        p = px.get(cid)
        if p is None:
            continue
        if ref:   # LST:对 ETH 比价偏离(带息 LST 比价>1 正常,折价看负偏离)
            if not eth:
                continue
            ratio = p / eth
            disc_bps = round((1 - ratio) * 10000, 1)
        else:     # 稳定币:对 1 美元偏离
            disc_bps = round((1 - p) * 10000, 1)
        out.append({"asset": name, "kind": kind, "price": p, "discount_bps": disc_bps})
    return out


# ── D2:Pendle PT 固定收益贴水(公共 API) ─────────────────────────────────
def scan_d2() -> list[dict]:
    # Pendle v2 公共 markets(以太坊主网 chainId=1);取活跃市场 impliedApy vs underlyingApy
    data = _get("https://api-v2.pendle.finance/core/v1/1/markets?limit=20&is_active=true")
    out = []
    for m in (data.get("results") or [])[:20]:
        try:
            imp = float(m.get("impliedApy") or 0) * 100
            und = float((m.get("underlyingApy") or 0)) * 100
            name = ((m.get("pt") or {}).get("symbol")) or m.get("symbol") or "?"
            # 固定收益溢价=implied-underlying(百分点);正=买PT锁固定收益优于浮动
            out.append({"asset": name, "implied_apy_pct": round(imp, 3),
                        "underlying_apy_pct": round(und, 3),
                        "spread_bps": round((imp - und) * 100, 1),
                        "expiry": m.get("expiry")})
        except Exception:  # noqa: BLE001
            continue
    return out


# ── D4:同币种跨协议借贷利差(DefiLlama yields,免key) ─────────────────────
def scan_d4() -> list[dict]:
    data = _get("https://yields.llama.fi/pools")
    rows = data.get("data") or []
    keep = [r for r in rows
            if r.get("chain") == "Ethereum"
            and r.get("project") in ("aave-v3", "morpho-blue", "compound-v3", "spark")
            and r.get("symbol") in ("USDC", "USDT", "DAI", "WETH")
            and (r.get("tvlUsd") or 0) > 5_000_000]
    by_sym: dict[str, list] = {}
    for r in keep:
        by_sym.setdefault(r["symbol"], []).append(r)
    out = []
    for sym, ps in by_sym.items():
        if len(ps) < 2:
            continue
        best = max(ps, key=lambda x: x.get("apyBase") or 0)
        worst = min(ps, key=lambda x: x.get("apyBase") or 0)
        out.append({"asset": sym,
                    "best": f"{best['project']} {round(best.get('apyBase') or 0, 2)}%",
                    "worst": f"{worst['project']} {round(worst.get('apyBase') or 0, 2)}%",
                    "spread_bps": round(((best.get("apyBase") or 0) - (worst.get("apyBase") or 0)) * 100, 1),
                    "pools": len(ps)})
    return out


_SCANNERS = {"D1": scan_d1, "D2": scan_d2, "D4": scan_d4}


def loop_once(c: sqlite3.Connection):
    now = int(time.time())
    runs = list(c.execute(
        "SELECT run_id, project_id FROM lab_run WHERE state='RUNNING' AND kind='MEASURE'"))
    for run_id, pid in runs:
        fn = _SCANNERS.get(pid)
        if fn is None:
            continue   # R1 由 xv 采样器负责,其余项目无扫描器=如实不动
        try:
            sigs = fn()
            if not sigs:
                raise RuntimeError("empty result")
            cost = COST_MODEL.get(pid, {}).get("round_trip_bps", 0)
            # 机会口径:D1 取『折价』正向(折价>0 才是买入赎回机会);D2/D4 取 spread
            vals = [s.get("discount_bps", s.get("spread_bps", 0)) for s in sigs]
            med = round(statistics.median(vals), 1)
            best = round(max(vals), 1)
            net_best = round(best - cost, 1)
            # V6.2 §6.1:raw_signal 与 economic_net_result 拆开——粗成本常数只作参考,
            # 不得再把 best-cost 标成『净最优』;可执行净收益=待计算(需目标金额真实报价)
            kind = {"D1": "RAW_DISCOUNT", "D2": "IMPLIED_YIELD_SPREAD",
                    "D4": "VARIABLE_RATE_MONITOR"}.get(pid, "RAW_SIGNAL")
            c.execute("INSERT INTO lab_signal(project_id, ts, payload) VALUES(?,?,?)",
                      (pid, now, json.dumps({"signal_kind": kind, "signals": sigs,
                                             "median_bps": med, "best_bps": best,
                                             "cost_bps": cost, "net_best_bps": net_best,
                                             "net_state": "PENDING_CALCULATION"}, ensure_ascii=False)))
            c.execute("UPDATE lab_run SET samples=samples+?, result_bps=?, note=? WHERE run_id=?",
                      (len(sigs), best,
                       f"初步信号最优={best}bps 中位={med}(参考成本{cost}bps;可执行净收益待计算)", run_id))
            c.execute("INSERT INTO lab_cost_model(project_id, model, updated_at) VALUES(?,?,?) "
                      "ON CONFLICT(project_id) DO UPDATE SET model=excluded.model, updated_at=excluded.updated_at",
                      (pid, json.dumps(COST_MODEL.get(pid, {}), ensure_ascii=False), now))
            c.execute("UPDATE lab_project SET stage='MEASURE', updated_at=? WHERE project_id=?", (now, pid))
            log.info("%s: %d signals, net_best=%.1fbps", pid, len(sigs), net_best)
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE lab_run SET note=? WHERE run_id=?", (f"ERR:{repr(e)[:120]}", run_id))
            log.warning("%s scan failed: %r", pid, e)
    c.commit()


def main():
    log.info("dexlab-scanner up interval=%ss scanners=%s", INTERVAL, list(_SCANNERS))
    while True:
        try:
            c = sqlite3.connect(DB)
            loop_once(c)
            c.close()
        except Exception:  # noqa: BLE001
            log.exception("scan round crashed (continuing)")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
