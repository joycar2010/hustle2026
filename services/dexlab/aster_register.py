#!/usr/bin/env python3
"""LP5 ASTER 准入轨注册:G1-G5闸策略 + watch策略 + 状态推进 IDEA→MEASURE。

加法/幂等:闸策略INSERT OR IGNORE(profile_id唯一);状态UPDATE只推进本主体。
只写LAB治理面,绝不碰生产配置。
"""
import json
import sqlite3
import time

DB = "dexlab.db"
SUBJECT_ID = "subj-618bd71344f4ef4d"
REVISION_ID = "rev-e3816e52aa577ec9"
NOW = int(time.time())

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

# ---- 0. 打印当前六轴 ----
print("=== state列 ===")
scols = [r[1] for r in c.execute("PRAGMA table_info(research_subject_state)")]
print(scols)
cur = c.execute("SELECT * FROM research_subject_state WHERE subject_id=?",
                (SUBJECT_ID,)).fetchone()
print("=== 推进前 ===", dict(cur) if cur else None)

# ---- 1. G1-G5 准入闸策略 ----
GATES = [
    ("G1_INSTRUMENT_IDENTITY", "合约身份可解析:清洁USDT永续足量,exotic(代币化股票/异计价)标记特护",
     ["VENUE_INSTRUMENT_UNIVERSE"], {"usdt_perp_min": 50, "trading_min": 50}),
    ("G2_LIQUIDITY_DEPTH", "目标下单量深度充足:主流篮子spread<=5bps且bid20>=$100k",
     ["VENUE_DEPTH_SAMPLE"], {"spread_bps_max": 5, "bid20_usd_min": 100000, "basket_min": 3}),
    ("G3_FUNDING_MECHANISM", "资金费机制活跃可采carry:非零funding>=100+结算间隔可确定",
     ["VENUE_FUNDING_SNAPSHOT"], {"funding_nonzero_min": 100}),
    ("G4_API_RELIABILITY", "API时延/在线/限频达标:单轮全端点<500ms+多轮uptime聚合",
     ["VENUE_API_LATENCY"], {"lat_ms_max": 500, "sustained_rounds_min": 30}),
    ("G5_CUSTODY_WITHDRAWAL", "托管/提现健康:链上永续DEX托管模型+提现充值可用性(需鉴权/链上验证)",
     ["VENUE_CUSTODY_ASSESSMENT"], {"manual_required": True}),
]
for code, appl, evtypes, thr in GATES:
    pid = f"gp-aster-{code.split('_')[0].lower()}"
    c.execute("""INSERT OR IGNORE INTO lab_gate_policy
        (profile_id,version,subject_kind,gate_code,applicability,required_evidence_types,
         evaluator_module,evaluator_version,threshold_policy,ttl_seconds,policy_origin,
         verification_state,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (pid, 1, "VENUE_ADMISSION", code, appl,
               json.dumps(evtypes, ensure_ascii=False),
               "aster_probe" if code != "G5_CUSTODY_WITHDRAWAL" else "manual",
               "v1", json.dumps(thr, ensure_ascii=False),
               86400, "LAB_AUTHORED",
               "AUTOMATED_READONLY" if code != "G5_CUSTODY_WITHDRAWAL" else "MANUAL_PENDING",
               NOW))
print(f"闸策略注册: {len(GATES)}条(INSERT OR IGNORE)")

# ---- 2. watch策略:MEASURE轨持续采集(只读公开API,资源微,启用) ----
wcols = [r[1] for r in c.execute("PRAGMA table_info(lab_watch_policy)")]
wpid = "wp-aster-admission-v1"
c.execute("""INSERT OR IGNORE INTO lab_watch_policy
    (watch_policy_id,subject_revision_id,watch_mode,metric_rules,minimum_sources,
     minimum_duration_sec,hysteresis_pct,cooldown_sec,freshness_limit_sec,
     policy_version,enabled,created_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (wpid, REVISION_ID, "MEASURE",
           json.dumps({"capture_interval_sec": 3600,
                       "promotion_needs_rounds": 30,
                       "gates": ["G1", "G2", "G3", "G4"],
                       "note": "只读公开fapi采样;G5需人工;晋级需30轮持续全PASS"},
                      ensure_ascii=False),
           1, 30 * 3600, 0.0, 0, 7200, 1, 1, NOW))
print("watch策略注册: wp-aster-admission-v1 (MEASURE,enabled=1,只读公开API)")

# ---- 3. 状态推进 IDEA→MEASURE ----
def col(name):
    return name if name in scols else None

sets, vals = [], []
def setcol(name, value):
    if name in scols:
        sets.append(f"{name}=?")
        vals.append(value)

setcol("research_stage", "MEASURE")
setcol("watch_mode", "PASSIVE_SENTINEL")  # CHECK: OFF/PASSIVE_SENTINEL/THRESHOLD_WATCH
setcol("reported_legacy_label", "MEASURE/ADMISSION_EVIDENCE_COLLECTING")
# updated_at 若有
for tcol in ("updated_at", "modified_at", "last_updated"):
    if tcol in scols:
        setcol(tcol, NOW)
        break
if sets:
    vals.append(SUBJECT_ID)
    c.execute(f"UPDATE research_subject_state SET {','.join(sets)} WHERE subject_id=?", vals)

c.commit()
after = c.execute("SELECT * FROM research_subject_state WHERE subject_id=?",
                  (SUBJECT_ID,)).fetchone()
print("=== 推进后 ===", dict(after) if after else None)
c.close()
