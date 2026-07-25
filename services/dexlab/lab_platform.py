#!/usr/bin/env python3
"""lab_platform —— V6.2 Research LAB 平台化 LP0 收敛(PACK-01 §4/§13,2026-07-25 开工)。

原则(承包§13.1"复用而非第二套权威"):
  - 全部加法迁移(CREATE IF NOT EXISTS / ALTER ADD COLUMN),不动现有 18+5 表;
  - 现有 lab_project/lab_run/lab_evidence 保留为运行面,本模块建**治理面**:
    Subject/Revision/六轴状态/gate_profile/watch policy/source registry;
  - 迁入态一律 REPORTED_ 前缀(§10.1),证据一律 LEGACY_IMPORTED(§7.2);
  - VENUE admission 只给 VENUE_ADMISSION kind(§4.6);禁止序数比较语义入库。

用法:
  python3 lab_platform.py ensure    # 建表+版本戳(幂等)
  python3 lab_platform.py seed      # 注册五主体+ASTER+source+gate policy+legacy证据(幂等)
  python3 lab_platform.py list      # 主体全景
"""
import hashlib
import json
import os
import sqlite3
import sys
import time

DB = os.path.expanduser("~/dexlab/dexlab.db")
SCHEMA_V3_FLAG = "mig_v62_platform_lp0"

DDL_V3 = """
CREATE TABLE IF NOT EXISTS research_subject (
    subject_id TEXT PRIMARY KEY,
    subject_code TEXT UNIQUE NOT NULL,
    subject_kind TEXT NOT NULL CHECK(subject_kind IN
        ('STRATEGY_HYPOTHESIS','MARKET_SENTINEL','SIGNAL_MODEL','VENUE_ADMISSION',
         'PRODUCT_RESEARCH','EXECUTION_CAPABILITY')),
    display_name TEXT,
    target_product_code TEXT,
    source_owner TEXT,
    current_revision_id TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS research_subject_revision (
    revision_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    hypothesis_text TEXT,
    payoff_or_signal_model TEXT,
    measurement_scope TEXT,
    instrument_scope_hash TEXT,
    notional_ladder_hash TEXT,
    code_commit TEXT,
    config_hash TEXT,
    cost_model_version TEXT,
    gate_profile_id TEXT,
    gate_profile_version INTEGER,
    supersedes_revision_id TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(subject_id, revision_no)
);
CREATE TABLE IF NOT EXISTS research_subject_state (
    subject_id TEXT PRIMARY KEY,
    research_stage TEXT NOT NULL DEFAULT 'IDEA' CHECK(research_stage IN
        ('IDEA','MEASURE','REPLAY','SHADOW','CANARY','REVIEW')),
    project_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(project_status IN
        ('ACTIVE','PAUSED','CLOSED','ARCHIVED')),
    research_disposition TEXT NOT NULL DEFAULT 'NOT_EVALUATED' CHECK(research_disposition IN
        ('NOT_EVALUATED','KEEP_RESEARCH','ADVANCE_REVIEW','CLOSE_CURRENT_ASSUMPTION',
         'GRADUATION_PROPOSED','SUPERSEDED')),
    economic_verdict TEXT NOT NULL DEFAULT 'UNKNOWN',
    promotion_eligibility TEXT NOT NULL DEFAULT 'RESEARCH_ONLY' CHECK(promotion_eligibility IN
        ('RESEARCH_ONLY','PRODUCTION_SHADOW_ELIGIBLE','CANARY_REVIEW_ELIGIBLE','BLOCKED','EXPIRED')),
    watch_mode TEXT NOT NULL DEFAULT 'OFF' CHECK(watch_mode IN
        ('OFF','PASSIVE_SENTINEL','THRESHOLD_WATCH')),
    reported_legacy_label TEXT,
    updated_at INTEGER DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS research_subject_dependency (
    subject_revision_id TEXT NOT NULL,
    depends_on_revision_id TEXT NOT NULL,
    dependency_kind TEXT,
    required_gate_codes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    PRIMARY KEY(subject_revision_id, depends_on_revision_id)
);
CREATE TABLE IF NOT EXISTS lab_source_system (
    source_system_id TEXT PRIMARY KEY,
    legacy_name TEXT,
    source_type TEXT CHECK(source_type IN ('SERVICE','SQLITE','CSV','API','CHAIN')),
    host_alias TEXT,
    code_commit TEXT,
    schema_version TEXT,
    last_seen_at INTEGER,
    verification_state TEXT DEFAULT 'REPORTED'
);
CREATE TABLE IF NOT EXISTS lab_source_manifest (
    manifest_id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL,
    source_schema_version TEXT,
    source_kind TEXT,
    snapshot_method TEXT,
    object_uri TEXT NOT NULL,
    object_version TEXT,
    content_sha256 TEXT NOT NULL,
    schema_hash TEXT,
    row_count INTEGER,
    min_event_at INTEGER,
    max_event_at INTEGER,
    timezone TEXT DEFAULT 'UTC',
    null_profile TEXT,
    source_commit TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS etl_watermark (
    source_manifest_id TEXT NOT NULL,
    source_partition TEXT NOT NULL DEFAULT '',
    last_source_key TEXT,
    backfill_completed_at INTEGER,
    live_handoff_at INTEGER,
    normalizer_version TEXT,
    PRIMARY KEY(source_manifest_id, source_partition)
);
CREATE TABLE IF NOT EXISTS lab_gate_policy (
    profile_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    subject_kind TEXT,
    gate_code TEXT NOT NULL CHECK(gate_code IN ('G1','G2','G3','G4','G5')),
    applicability TEXT DEFAULT 'REQUIRED',
    required_evidence_types TEXT,
    evaluator_module TEXT,
    evaluator_version TEXT,
    threshold_policy TEXT,
    ttl_seconds INTEGER,
    policy_origin TEXT DEFAULT 'LEGACY_IMPORTED',
    verification_state TEXT DEFAULT 'UNVERIFIED',
    created_at INTEGER DEFAULT (strftime('%s','now')),
    PRIMARY KEY(profile_id, version, gate_code)
);
CREATE TABLE IF NOT EXISTS lab_watch_policy (
    watch_policy_id TEXT PRIMARY KEY,
    subject_revision_id TEXT NOT NULL,
    watch_mode TEXT NOT NULL DEFAULT 'THRESHOLD_WATCH',
    metric_rules TEXT NOT NULL,
    minimum_sources INTEGER DEFAULT 1,
    minimum_duration_sec INTEGER DEFAULT 3600,
    hysteresis_pct REAL DEFAULT 10.0,
    cooldown_sec INTEGER DEFAULT 604800,
    freshness_limit_sec INTEGER DEFAULT 3600,
    policy_version INTEGER DEFAULT 1,
    enabled INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS lab_reopen_candidate (
    candidate_id TEXT PRIMARY KEY,
    subject_revision_id TEXT NOT NULL,
    watch_policy_id TEXT,
    triggered_at INTEGER,
    metric_snapshot TEXT,
    status TEXT DEFAULT 'PENDING_REVIEW' CHECK(status IN
        ('PENDING_REVIEW','REVIEWED_NO_ACTION','REVIEWED_NEW_REVISION','EXPIRED')),
    reviewed_by TEXT,
    reviewed_at INTEGER
);
CREATE TABLE IF NOT EXISTS lab_legacy_evidence (
    evidence_id TEXT PRIMARY KEY,
    subject_revision_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_assurance TEXT NOT NULL DEFAULT 'LEGACY_IMPORTED' CHECK(evidence_assurance IN
        ('LEGACY_IMPORTED','HASH_VERIFIED','DOCUMENT_VERIFIED','SOURCE_REPRODUCED',
         'DEPLOY_VERIFIED','MAINNET_FACT_VERIFIED','MONEY_VERIFIED')),
    scope TEXT,
    source_manifest_id TEXT,
    payload TEXT,
    content_hash TEXT,
    observed_from INTEGER,
    observed_to INTEGER,
    produced_at INTEGER DEFAULT (strftime('%s','now')),
    expires_at INTEGER,
    contradicts_evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_subj_rev ON research_subject_revision(subject_id, revision_no);
CREATE INDEX IF NOT EXISTS idx_legacy_ev ON lab_legacy_evidence(subject_revision_id);
"""


def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def ensure(conn=None):
    own = conn is None
    c = conn or _db()
    c.executescript(DDL_V3)
    c.execute("INSERT OR IGNORE INTO lab_meta(key, value) VALUES(?, ?)",
              (SCHEMA_V3_FLAG, str(int(time.time()))))
    cur = c.execute("PRAGMA user_version").fetchone()[0]
    if cur < 3:
        c.execute("PRAGMA user_version=3")
    c.commit()
    if own:
        c.close()
    print("ensure: v3 平台治理面 11 表就绪(加法,零动现有表)")


# ── 种子:五个legacy主体 + ASTER + D1-D4挂靠 ─────────────────────────────────
SUBJECTS = [
    # (code, kind, display, product, source_owner, stage, status, disposition,
    #  economic, promotion, watch, reported_label, hypothesis)
    ("R1.CEX_DEX_LATENCY_CROSSARB", "STRATEGY_HYPOTHESIS", "CEX-DEX延迟穿越套利", "R1", "dc",
     "REVIEW", "CLOSED", "CLOSE_CURRENT_ASSUMPTION", "REPORTED_KILL_CURRENT_COST",
     "BLOCKED", "THRESHOLD_WATCH", "REPORTED_KILL_CURRENT_COST",
     "DEX买入+CEX合约对冲吃延迟价差;证伪:成本线38bps在专业玩家钉宽之外(P1真金canary+五方向统一证伪)"),
    ("R1.DEX_DEX_ATOMIC_BSC", "STRATEGY_HYPOTHESIS", "BSC链内DEX-DEX原子套利", "R1", "dd",
     "REVIEW", "CLOSED", "CLOSE_CURRENT_ASSUMPTION", "REPORTED_KILL_CURRENT_COST",
     "BLOCKED", "OFF", "REPORTED_KILL_CURRENT_COST",
     "同链池间原子价差;证伪:死池污染中位数假阳性+CAKE路径594次模拟失败(REPORTED待复核)"),
    ("R1.CEX_DEX_GAP_SURVIVAL", "MARKET_SENTINEL", "CEX-DEX价差存活标尺", "R1", "dd",
     "REVIEW", "CLOSED", "CLOSE_CURRENT_ASSUMPTION", "REPORTED_KILL_CURRENT_COST",
     "BLOCKED", "THRESHOLD_WATCH", "REPORTED_KILL_CURRENT_COST",
     "去锚EWMA后净肉厚存活窗口;结论:去锚后仅0.4-2.4bps(REPORTED),不够成本线"),
    ("C9.BINANCE_PUT_CALL_PARITY", "STRATEGY_HYPOTHESIS", "币安期权平价偏离", "C9", "op",
     "REVIEW", "CLOSED", "CLOSE_CURRENT_ASSUMPTION", "REPORTED_KILL_CURRENT_COST",
     "BLOCKED", "OFF", "REPORTED_KILL_CURRENT_COST",
     "Put-Call平价偏离套利;证伪:四腿费用16.5bps>>偏离1.5bps;**仅关闭本假设,不代表C9整体**"),
    ("C2H.CROSS_VENUE_FUNDING_DISCOVERY", "SIGNAL_MODEL", "五所资金费差发现模型", "C2.H", "xv",
     "MEASURE", "ACTIVE", "KEEP_RESEARCH", "UNKNOWN",
     "RESEARCH_ONLY", "OFF", "REPORTED_FORWARD_SHADOW",
     "五所最优对资金费差扫描+可交易过滤;7天报告:gap>=0.5%/d占2.74%(508币),已定位C2选对/容量情报源;"
     "四项认证(source/instrument/funding calendar/depth)完成前不得映射正式SHADOW"),
    ("VENUE.ASTER_PERP_V3", "VENUE_ADMISSION", "ASTER永续V3场所准入", "C2候选Venue", "aster",
     "IDEA", "ACTIVE", "NOT_EVALUATED", "UNKNOWN",
     "RESEARCH_ONLY", "OFF", "IDEA/NOT_REGISTERED",
     "ASTER Perp V3作为C2候选场所;公共只读采集不需签名;主网Agent只在B(LP5批次)"),
]

SOURCES = [
    ("src-dc", "dc/crossarb-p1", "SERVICE", "dex-canary机(已退役)", "REPORTED"),
    ("src-dd-atomic", "dd/dexarb-shadow", "SERVICE", "13.230.29.158", "REPORTED"),
    ("src-dd-gap", "dd/crossarb-p0", "SERVICE", "13.230.29.158", "REPORTED"),
    ("src-op", "op/options-probe", "SERVICE", "op站(已KILL)", "REPORTED"),
    ("src-xv", "xv/sampler+shadow", "SQLITE", "13.230.29.158:~/xv/xv.db", "DEPLOY_VERIFIED"),
]

# legacy 阈值 → 版本化 gate policy(policy_origin=LEGACY_IMPORTED,§6.5)
GATE_POLICIES = [
    ("gp-crossarb-legacy", 1, "STRATEGY_HYPOTHESIS", "G2",
     json.dumps({"net_edge_min_bps": 25, "note": "CrossArb旧经济闸"}), None),
    ("gp-crossarb-legacy", 1, "STRATEGY_HYPOTHESIS", "G3",
     json.dumps({"quote_stale_ms_max": 1500, "px_gap_pct_max": 2.0}), None),
    ("gp-op-legacy", 1, "STRATEGY_HYPOTHESIS", "G2",
     json.dumps({"total_fee_bps": 16.5, "note": "op四腿费用墙"}), None),
    ("gp-xv-legacy", 1, "SIGNAL_MODEL", "G3",
     json.dumps({"capture_rate_min_pct": 50, "gap_abs_max_pct_d": 10.0,
                 "note": "捕获率属G3/G4非G2经济证明(§6.5)"}), 86400 * 7),
    ("gp-xv-legacy", 1, "SIGNAL_MODEL", "G2",
     json.dumps({"note": "G2须实际资金费+费用+滑点+basis退出净现金流,legacy无此口径=待建"}), 86400 * 7),
]

EVIDENCE = [
    ("R1.CEX_DEX_LATENCY_CROSSARB", "ECONOMIC_KILL_MEMO",
     "五方向统一证伪:成本线38bps在专业玩家钉宽外;假阳性根因=死池污染中位数/锚定币折价;"
     "P1真金canary全链路通+对抗式复核修11真金bug(2026-06,crossarb-infeasibility-verdict)",
     "scope:公共RPC+币安合约对冲;当时VIP0费率;≤500U名义"),
    ("R1.DEX_DEX_ATOMIC_BSC", "SIMULATION_FAILURE_LOG",
     "BSC CAKE路径594次原子模拟失败(REPORTED未复核);死池巨幅偏差非机会",
     "scope:BSC主网;PancakeSwap系池"),
    ("R1.CEX_DEX_GAP_SURVIVAL", "SENTINEL_SUMMARY",
     "EWMA去锚后净偏离仅0.4-2.4bps(REPORTED);幸存者偏差备注在案",
     "scope:dd轮询采样;CEX-DEX对"),
    ("C9.BINANCE_PUT_CALL_PARITY", "ECONOMIC_KILL_MEMO",
     "op站只读探针实测:四腿总费用16.5bps>>平价偏离1.5bps(crossarb-options-probe-deploy);"
     "仅证伪本假设,Long Box/Conversion等C9其余假设不受此结论约束",
     "scope:币安期权+现货;当时费率表"),
    ("C2H.CROSS_VENUE_FUNDING_DISCOVERY", "FORWARD_REPORT",
     "7天7.5M清洁样本/759币:gap>=0.5%/d占2.74%时间(508币)/>=1%占0.97%(267币);"
     "TOP12回本0.1-0.3天;cap25深度1.4k-6.7kU;与carry-advisor选对高度重合(2026-07-25离线复算)",
     "scope:币安/Bybit/OKX/Gate/Bitget五所;可交易过滤后"),
]


def seed():
    c = _db()
    now = int(time.time())
    try:
        for sid, name, stype, host, vstate in SOURCES:
            c.execute("INSERT OR IGNORE INTO lab_source_system(source_system_id, legacy_name, "
                      "source_type, host_alias, verification_state, last_seen_at) "
                      "VALUES(?,?,?,?,?,?)", (sid, name, stype, host, vstate, now))
        for (code, kind, disp, prod, owner, stage, status, dispo, econ, promo, watch,
             label, hypo) in SUBJECTS:
            subj_id = f"subj-{_h(code)}"
            rev_id = f"rev-{_h(code + ':1')}"
            c.execute("INSERT OR IGNORE INTO research_subject(subject_id, subject_code, "
                      "subject_kind, display_name, target_product_code, source_owner, "
                      "current_revision_id) VALUES(?,?,?,?,?,?,?)",
                      (subj_id, code, kind, disp, prod, owner, rev_id))
            c.execute("INSERT OR IGNORE INTO research_subject_revision(revision_id, subject_id, "
                      "revision_no, hypothesis_text, gate_profile_id, gate_profile_version) "
                      "VALUES(?,?,1,?,?,1)",
                      (rev_id, subj_id, hypo,
                       {"dc": "gp-crossarb-legacy", "op": "gp-op-legacy",
                        "xv": "gp-xv-legacy"}.get(owner)))
            c.execute("INSERT OR IGNORE INTO research_subject_state(subject_id, research_stage, "
                      "project_status, research_disposition, economic_verdict, "
                      "promotion_eligibility, watch_mode, reported_legacy_label) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (subj_id, stage, status, dispo, econ, promo, watch, label))
        for pid, ver, kind, gate, thr, ttl in GATE_POLICIES:
            c.execute("INSERT OR IGNORE INTO lab_gate_policy(profile_id, version, subject_kind, "
                      "gate_code, threshold_policy, ttl_seconds) VALUES(?,?,?,?,?,?)",
                      (pid, ver, kind, gate, thr, ttl))
        for code, etype, payload, scope in EVIDENCE:
            rev_id = f"rev-{_h(code + ':1')}"
            eid = f"lev-{_h(code + ':' + etype)}"
            c.execute("INSERT OR IGNORE INTO lab_legacy_evidence(evidence_id, "
                      "subject_revision_id, evidence_type, evidence_assurance, scope, payload, "
                      "content_hash) VALUES(?,?,?,'LEGACY_IMPORTED',?,?,?)",
                      (eid, rev_id, etype, scope, payload, _h(payload)))
        # CrossArb watch policy(THRESHOLD_WATCH,§8.3复合条件,enabled=0待资源批准)
        rev_dc = f"rev-{_h('R1.CEX_DEX_LATENCY_CROSSARB:1')}"
        c.execute("INSERT OR IGNORE INTO lab_watch_policy(watch_policy_id, subject_revision_id, "
                  "watch_mode, metric_rules, enabled) VALUES(?,?,?,?,0)",
                  (f"wp-{_h(rev_dc)}", rev_dc, "THRESHOLD_WATCH", json.dumps({
                      "rules": [
                          {"metric_id": "conservative_executable_edge_bps", "operator": ">",
                           "threshold": "approved_safety_hurdle", "window": "24h",
                           "min_consecutive": 3},
                          {"metric_id": "p10_window_lifetime_ms", "operator": ">",
                           "threshold": "p99_e2e_latency_ms", "window": "24h", "min_consecutive": 3},
                          {"metric_id": "executable_capacity_usdt", "operator": ">=",
                           "threshold": "target_size_usdt", "window": "24h", "min_consecutive": 3}],
                      "combine": "AND",
                      "note": "§8.3:VIP只影响CEX腿成本,不得单独触发重测"})))
        # ASTER 依赖图(§4.3)
        rev_aster = f"rev-{_h('VENUE.ASTER_PERP_V3:1')}"
        rev_xv = f"rev-{_h('C2H.CROSS_VENUE_FUNDING_DISCOVERY:1')}"
        c.execute("INSERT OR IGNORE INTO research_subject_dependency(subject_revision_id, "
                  "depends_on_revision_id, dependency_kind, required_gate_codes) VALUES(?,?,?,?)",
                  (rev_aster, rev_xv, "SIGNAL_MODEL_RELEASE", json.dumps(["G2", "G3"])))
        c.commit()
        print("seed: 6主体+5source+5证据(LEGACY_IMPORTED)+gate policy+watch policy(enabled=0)+依赖图 幂等落库")
    finally:
        c.close()


def list_all():
    c = _db()
    try:
        for r in c.execute(
                "SELECT s.subject_code, s.subject_kind, st.research_stage, st.project_status, "
                "st.economic_verdict, st.promotion_eligibility, st.watch_mode, "
                "st.reported_legacy_label FROM research_subject s "
                "JOIN research_subject_state st ON st.subject_id=s.subject_id"):
            print(f"{r['subject_code']:38} {r['subject_kind']:20} {r['research_stage']:8} "
                  f"{r['project_status']:8} {r['economic_verdict']:28} "
                  f"{r['promotion_eligibility']:14} watch={r['watch_mode']}")
        n = c.execute("SELECT count(*) FROM lab_legacy_evidence").fetchone()[0]
        print(f"legacy evidence rows: {n}")
    finally:
        c.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "ensure":
        ensure()
    elif cmd == "seed":
        ensure()
        seed()
    else:
        list_all()
