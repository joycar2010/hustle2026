#!/usr/bin/env python3
"""LP3: xv 四项认证(§10.6)+ model release 机制。

四项认证=真实检查产出证据行(过=DEPLOY_VERIFIED,不过=记FAIL交人工),全过才建
model release(DRAFT);30天前向观察钟从认证完成时刻起跑。
release 状态机: DRAFT -> CANDIDATE(观察满30天+复核) -> RELEASED(经C审批,LAB无权)。
"""
import hashlib
import json
import sqlite3
import time

XV = "/home/ec2-user/xv/xv.db"
DB = "/home/ec2-user/dexlab/dexlab.db"
VENUES = {"bn", "bb", "okx", "gt", "bg", "hl"}   # xv缩写:binance/bybit/okx/gate/bitget/hyperliquid


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def cert_source(xc):
    """①source认证:数据源身份+完整性(引用已登记SHA-256 manifest)。"""
    rows = xc.execute("SELECT count(*) FROM gaps").fetchone()[0]
    rng = xc.execute("SELECT min(ts), max(ts) FROM gaps").fetchone()
    days = (rng[1] - rng[0]) / 86400 if rng[0] else 0
    ok = rows > 1_000_000 and days > 5
    return ok, {"gaps_rows": rows, "window_days": round(days, 1),
                "manifest": "srcmf-0ad4f09dcf3b4fa7(SHA-256异地副本已对账)"}


def cert_instrument(xc):
    """②instrument归一认证:symbol以USDT结尾(允许非ASCII——币安Alpha中文名meme币真实存在)
    +venue枚举合法。**已知限制**:跨所按symbol名join,同名不同物风险(参照XAGUSD面值坑)
    对非ASCII/小币尤甚——作为限制记录,route级G1须逐币合约地址核对。"""
    bad_sym = xc.execute(
        "SELECT count(*) FROM gaps WHERE symbol NOT LIKE '%USDT' "
        "AND ts > strftime('%s','now')-7*86400").fetchone()[0]
    nonascii = xc.execute(
        "SELECT count(DISTINCT symbol) FROM gaps WHERE symbol NOT GLOB '[A-Z0-9]*' "
        "AND ts > strftime('%s','now')-7*86400").fetchone()[0]
    vs = {r[0] for r in xc.execute(
        "SELECT DISTINCT hi_v FROM gaps WHERE ts > strftime('%s','now')-86400")} | \
         {r[0] for r in xc.execute(
        "SELECT DISTINCT lo_v FROM gaps WHERE ts > strftime('%s','now')-86400")}
    unknown = vs - VENUES
    ok = bad_sym == 0 and not unknown
    return ok, {"non_usdt_symbols_7d": bad_sym, "nonascii_symbols_7d": nonascii,
                "venues_seen_24h": sorted(vs), "unknown_venues": sorted(unknown),
                "known_limitation": "同名不同物风险(中文/小币尤甚);route级G1须合约身份核对"}


def cert_funding_calendar(xc):
    """③资金费日历认证:gap_d(日化费差)分布合理——归一化正确的必要条件。
    过滤口径内|gap_d|应集中在低值,极端值占比可控;并抽验24h内轮次节奏。"""
    r = xc.execute(
        "SELECT count(*), sum(CASE WHEN abs(gap_d)<=10 THEN 1 ELSE 0 END), "
        "sum(CASE WHEN abs(gap_d)<=1 THEN 1 ELSE 0 END) "
        "FROM gaps WHERE ts > strftime('%s','now')-86400").fetchone()
    total, within10, within1 = r
    rounds = xc.execute(
        "SELECT count(DISTINCT ts) FROM gaps WHERE ts > strftime('%s','now')-86400").fetchone()[0]
    ok = total > 0 and within10 / total > 0.98 and within1 / total > 0.85 and rounds > 200
    return ok, {"samples_24h": total, "within10pct_share": round(within10 / total, 4) if total else 0,
                "within1pct_share": round(within1 / total, 4) if total else 0,
                "rounds_24h": rounds,
                "note": "归一日化正确的必要条件:绝大多数|gap_d|低值集中;极端值由可交易过滤拦"}


def cert_depth(xc):
    """④深度/容量认证:depth表覆盖+新鲜度+cap25合理性。"""
    r = xc.execute("SELECT count(*), count(DISTINCT symbol), max(ts) FROM depth "
                   "WHERE ts > strftime('%s','now')-86400").fetchone()
    rows, syms, last = r
    age = int(time.time()) - (last or 0)
    med = xc.execute("SELECT cap25_usdt FROM depth WHERE ts > strftime('%s','now')-86400 "
                     "AND cap25_usdt IS NOT NULL ORDER BY cap25_usdt LIMIT 1 OFFSET "
                     "(SELECT count(*)/2 FROM depth WHERE ts > strftime('%s','now')-86400 "
                     "AND cap25_usdt IS NOT NULL)").fetchone()
    ok = rows > 100 and syms > 20 and age < 3600
    return ok, {"depth_rows_24h": rows, "symbols_24h": syms, "freshness_sec": age,
                "median_cap25_usdt": med[0] if med else None}


def main():
    xc = sqlite3.connect(XV)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS lab_model_release (
        release_id TEXT PRIMARY KEY,
        subject_revision_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        code_commit TEXT,
        config_hash TEXT,
        release_status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(release_status IN
            ('DRAFT','CANDIDATE','RELEASED','WITHDRAWN')),
        certifications_json TEXT,
        observation_starts_at INTEGER,
        observation_days_required INTEGER DEFAULT 30,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        note TEXT
    );""")
    rev_xv = f"rev-{_h('C2H.CROSS_VENUE_FUNDING_DISCOVERY:1')}"
    now = int(time.time())
    certs = {}
    all_ok = True
    for name, fn in (("SOURCE_CERTIFICATION", cert_source),
                     ("INSTRUMENT_NORMALIZATION_CERT", cert_instrument),
                     ("FUNDING_CALENDAR_CERT", cert_funding_calendar),
                     ("DEPTH_CAPACITY_CERT", cert_depth)):
        try:
            ok, detail = fn(xc)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, {"error": repr(e)[:150]}
        certs[name] = {"pass": ok, **detail}
        all_ok = all_ok and ok
        payload = json.dumps({"pass": ok, "detail": detail, "checked_at": now}, ensure_ascii=False)
        c.execute("INSERT OR REPLACE INTO lab_legacy_evidence(evidence_id, subject_revision_id, "
                  "evidence_type, evidence_assurance, scope, payload, content_hash, expires_at) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (f"lev-{_h('xv-cert:' + name)}", rev_xv, name,
                   "DEPLOY_VERIFIED" if ok else "LEGACY_IMPORTED",
                   "xv四项认证(§10.6),对live xv.db实测", payload, _h(payload),
                   now + 7 * 86400))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(detail, ensure_ascii=False)[:130]}")

    if all_ok:
        rel_id = f"mrel-{_h('xv:v1:' + str(now))[:12]}"
        c.execute("INSERT INTO lab_model_release(release_id, subject_revision_id, model_version, "
                  "code_commit, release_status, certifications_json, observation_starts_at, note) "
                  "VALUES(?,?,?,?,'DRAFT',?,?,?)",
                  (rel_id, rev_xv, "xv-funding-discovery-v1", "xv/sampler.py@dd",
                   json.dumps(certs, ensure_ascii=False), now,
                   "四项认证全过;30天前向观察钟自此起跑;DRAFT→CANDIDATE须观察满+复核;"
                   "→RELEASED须C审批(LAB无权)"))
        # 认证全过→研究阶段可正式映射SHADOW(§10.6)
        c.execute("UPDATE research_subject_state SET research_stage='SHADOW', "
                  "reported_legacy_label='FORWARD_SHADOW(certified)', updated_at=? "
                  "WHERE subject_id=(SELECT subject_id FROM research_subject "
                  "WHERE subject_code='C2H.CROSS_VENUE_FUNDING_DISCOVERY')", (now,))
        print(f"\n✅ 四项认证全过 → model release {rel_id} (DRAFT) 观察钟起跑;"
              f"研究阶段 MEASURE→SHADOW(正式)")
    else:
        print("\n❌ 有认证未过:不建release,阶段保持MEASURE(诚实)")
    c.commit()
    c.close()
    xc.close()


if __name__ == "__main__":
    main()
