#!/usr/bin/env python3
"""aster_probe —— VENUE.ASTER_PERP_V3 场所准入只读探针(PACK-01 LP5,VENUE_ADMISSION)。

只读打 Aster 公开 fapi(Binance-fork 结构),采准入证据:合约universe/资金费可得性/
深度充足性/API时延与可靠性。绝不下单、绝不持仓、绝不写生产配置——纯研究测量。
证据落 dexlab.db venue_admission_evidence,供准入闸(G1-G5)判定与LAB主体状态推进。

用法:
  python3 aster_probe.py discover   # 一次性摸清universe+资金费+深度(打印,不入库)
  python3 aster_probe.py capture    # 采一轮证据+G1-G5闸判定入库
  python3 aster_probe.py show       # 打印最近几轮证据
"""
import hashlib
import json
import sqlite3
import sys
import time
import urllib.request

BASE = "https://fapi.asterdex.com"
DB = "dexlab.db"
SUBJECT_ID = "subj-618bd71344f4ef4d"
REVISION_ID = "rev-e3816e52aa577ec9"

# G2 深度篮子(主流+场所自身代币)。准入判定只认这些"干净"USDT永续。
DEPTH_BASKET = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ASTERUSDT", "BNBUSDT"]
# 已知计价资产白名单(USDT为主;USD1/U为exotic标记用)
CLEAN_QUOTE = "USDT"


def _get(path, timeout=8):
    t0 = time.time()
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "dexlab-aster-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    return data, round((time.time() - t0) * 1000, 1)


def _depth_one(sym):
    dep, dl = _get(f"/fapi/v1/depth?symbol={sym}&limit=20")
    bids, asks = dep.get("bids", []), dep.get("asks", [])
    if not (bids and asks):
        return None
    bid, ask = float(bids[0][0]), float(asks[0][0])
    spr = (ask - bid) / ((ask + bid) / 2) * 1e4
    bidn = sum(float(p) * float(q) for p, q in bids)
    askn = sum(float(p) * float(q) for p, q in asks)
    return {"lat_ms": dl, "spread_bps": round(spr, 2),
            "bid20_usd": round(bidn, 0), "ask20_usd": round(askn, 0)}


def _gather():
    """采一轮原始测量。返回 measurement dict + 端点时延表。"""
    lat = {}
    ex, lat["exchangeInfo"] = _get("/fapi/v1/exchangeInfo")
    syms = ex.get("symbols", [])
    trading = [s for s in syms if s.get("status") == "TRADING"]
    quotes = {}
    for s in syms:
        quotes[s.get("quoteAsset")] = quotes.get(s.get("quoteAsset"), 0) + 1
    usdt_perp = [s for s in trading
                 if s.get("quoteAsset") == CLEAN_QUOTE and s.get("contractType") == "PERPETUAL"]
    # exotic:非USDT计价 或 明显代币化股票前缀
    exotic = [s["symbol"] for s in trading
              if s.get("quoteAsset") != CLEAN_QUOTE
              or any(t in s["symbol"] for t in ("SHIELD", "AMZN", "TRUTH", "SBET"))]

    pidx, lat["premiumIndex"] = _get("/fapi/v1/premiumIndex")
    if isinstance(pidx, dict):
        pidx = [pidx]
    funded = [x for x in pidx
              if x.get("lastFundingRate") not in (None, "", "0", "0.00000000")]
    # 资金费结算间隔:从 nextFundingTime 众数推(小时)
    intervals = {}
    for x in pidx[:200]:
        nf = x.get("nextFundingTime")
        if nf:
            # 距下次结算(ms)→小时,取整到常见值
            h = round((int(nf) - int(time.time() * 1000)) / 3600000)
            intervals[h] = intervals.get(h, 0) + 1

    # 深度篮子
    depth = {}
    for sym in DEPTH_BASKET:
        try:
            d = _depth_one(sym)
            if d:
                depth[sym] = d
                lat[f"depth:{sym}"] = d["lat_ms"]
        except Exception as e:  # noqa: BLE001
            depth[sym] = {"error": str(e)}

    # 24h成交量
    tk, lat["ticker24hr"] = _get("/fapi/v1/ticker/24hr")
    if isinstance(tk, dict):
        tk = [tk]
    vols = sorted(((float(x.get("quoteVolume", 0) or 0), x.get("symbol")) for x in tk),
                  reverse=True)
    vol_total = sum(v for v, _ in vols)
    vol_top = [{"symbol": s, "quote_vol_usd": round(v, 0)} for v, s in vols[:10]]

    return {
        "instrument_total": len(syms),
        "instrument_trading": len(trading),
        "usdt_perp": len(usdt_perp),
        "quote_dist": quotes,
        "exotic_count": len(exotic),
        "exotic_sample": exotic[:15],
        "funding_symbols": len(pidx),
        "funding_nonzero": len(funded),
        "funding_interval_hist": intervals,
        "depth_basket": depth,
        "vol_24h_total_usd": round(vol_total, 0),
        "vol_top10": vol_top,
    }, lat


def _eval_gates(m, lat):
    """G1-G5 场所准入闸判定(单轮快照;晋级需多轮持续,此处只给本轮裁决)。"""
    g = {}
    # G1 合约身份:清洁USDT永续足量;exotic(代币化股票/异计价)如实标记
    g1_ok = m["instrument_trading"] >= 50 and m["usdt_perp"] >= 50
    g["G1_INSTRUMENT_IDENTITY"] = {
        "verdict": "PASS" if g1_ok else "FAIL",
        "usdt_perp": m["usdt_perp"], "trading": m["instrument_trading"],
        "exotic_flagged": m["exotic_count"],
        "note": "币安fork结构;含代币化股票(SHIELD*/异计价)已标exotic需身份特护",
    }
    # G2 流动性深度:篮子主流spread<=5bps且bid20>=$100k
    basket_ok = []
    for sym, d in m["depth_basket"].items():
        if "error" in d:
            continue
        basket_ok.append(d["spread_bps"] <= 5 and d["bid20_usd"] >= 100000)
    g2_ok = len(basket_ok) >= 3 and all(basket_ok)
    g["G2_LIQUIDITY_DEPTH"] = {
        "verdict": "PASS" if g2_ok else "PARTIAL",
        "basket_checked": len(basket_ok), "basket_pass": sum(basket_ok),
        "threshold": "spread<=5bps & bid20>=$100k",
    }
    # G3 资金费机制:非零funding>=100=机制活跃(carry可采)
    g3_ok = m["funding_nonzero"] >= 100
    top_iv = max(m["funding_interval_hist"].items(), key=lambda kv: kv[1])[0] \
        if m["funding_interval_hist"] else None
    g["G3_FUNDING_MECHANISM"] = {
        "verdict": "PASS" if g3_ok else "FAIL",
        "funding_nonzero": m["funding_nonzero"], "funding_symbols": m["funding_symbols"],
        "settlement_interval_h_est": top_iv,
        "note": "间隔为nextFundingTime众数估;精确间隔需多轮或fundingRate史确认",
    }
    # G4 API可靠性:本轮所有端点<500ms(持续性需N轮聚合)
    slow = {k: v for k, v in lat.items() if v >= 500}
    g4_ok = len(slow) == 0
    g["G4_API_RELIABILITY"] = {
        "verdict": "PASS" if g4_ok else "DEGRADED",
        "endpoints": len(lat), "max_lat_ms": max(lat.values()) if lat else None,
        "slow": slow, "note": "单轮时延闸;uptime/限频需多轮持续采样",
    }
    # G5 托管/提现:Aster=链上永续DEX,托管=on-chain,提现健康需鉴权探针
    g["G5_CUSTODY_WITHDRAWAL"] = {
        "verdict": "NOT_EVALUATED",
        "note": "链上永续DEX托管模型;提现/充值健康需鉴权或链上验证,本只读探针无法测,诚实留空",
    }
    passed = sum(1 for v in g.values() if v["verdict"] == "PASS")
    g["_summary"] = {"passed": passed, "of_automatable": 4,
                     "overall": "MEASURE_IN_PROGRESS",
                     "note": "单轮快照;准入晋级需持续多轮+G5人工评估"}
    return g


def capture():
    m, lat = _gather()
    gates = _eval_gates(m, lat)
    now = int(time.time())
    body = {"subject_id": SUBJECT_ID, "revision_id": REVISION_ID,
            "captured_at": now, "measurement": m, "gates": gates}
    canon = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    ch = hashlib.sha256(canon.encode()).hexdigest()
    eid = "vae-" + ch[:16]

    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS venue_admission_evidence(
        evidence_id TEXT PRIMARY KEY,
        subject_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        venue TEXT NOT NULL,
        captured_at INTEGER NOT NULL,
        instrument_trading INTEGER,
        usdt_perp INTEGER,
        funding_nonzero INTEGER,
        vol_24h_total_usd REAL,
        gates_passed INTEGER,
        measurement_json TEXT NOT NULL,
        gates_json TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        assurance TEXT DEFAULT 'MEASURED_READONLY',
        created_at INTEGER DEFAULT (strftime('%s','now')))""")
    c.execute("""INSERT OR IGNORE INTO venue_admission_evidence
        (evidence_id,subject_id,revision_id,venue,captured_at,instrument_trading,
         usdt_perp,funding_nonzero,vol_24h_total_usd,gates_passed,
         measurement_json,gates_json,content_hash)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (eid, SUBJECT_ID, REVISION_ID, "VENUE.ASTER_PERP_V3", now,
               m["instrument_trading"], m["usdt_perp"], m["funding_nonzero"],
               m["vol_24h_total_usd"], gates["_summary"]["passed"],
               json.dumps(m, ensure_ascii=False), json.dumps(gates, ensure_ascii=False), ch))
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM venue_admission_evidence WHERE subject_id=?",
                  (SUBJECT_ID,)).fetchone()[0]
    c.close()
    print(f"captured {eid} | G1-G5本轮: " +
          " ".join(f"{k.split('_')[0]}={v['verdict']}"
                   for k, v in gates.items() if k.startswith("G")))
    print(f"  合约TRADING={m['instrument_trading']} USDT永续={m['usdt_perp']} "
          f"非零资金费={m['funding_nonzero']} 24h额=${m['vol_24h_total_usd']:,.0f}")
    print(f"  篮子深度: " + " ".join(
        f"{s}({d.get('spread_bps','?')}bps/${d.get('bid20_usd',0):,.0f})"
        for s, d in m["depth_basket"].items() if "error" not in d))
    print(f"  累计证据轮数={n}")


def show():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT evidence_id,captured_at,instrument_trading,usdt_perp,
        funding_nonzero,vol_24h_total_usd,gates_passed FROM venue_admission_evidence
        WHERE subject_id=? ORDER BY captured_at DESC LIMIT 8""", (SUBJECT_ID,)).fetchall()
    for r in rows:
        print(dict(r))
    c.close()


def discover():
    m, lat = _gather()
    print(f"合约总数={m['instrument_total']} TRADING={m['instrument_trading']} "
          f"USDT永续={m['usdt_perp']}")
    print(f"计价分布={m['quote_dist']}")
    print(f"exotic标记={m['exotic_count']} 样例={m['exotic_sample']}")
    print(f"资金费: 条数={m['funding_symbols']} 非零={m['funding_nonzero']} "
          f"间隔直方={m['funding_interval_hist']}")
    print("深度篮子:")
    for s, d in m["depth_basket"].items():
        print(f"  {s}: {d}")
    print(f"24h额=${m['vol_24h_total_usd']:,.0f} top5={m['vol_top10'][:5]}")
    print(f"时延={lat}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "discover"
    {"discover": discover, "capture": capture, "show": show}.get(cmd, discover)()
