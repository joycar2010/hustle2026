"""DEX_LAB API(V6.2 §MIX-V62-DEXLAB-PACK-01)——D-lab 独立域唯一服务,跑在 crossarb-testbox(172.31.16.200)。

隔离铁律(§8.1,不变):
- 本机与生产 A/B/C(10.0 VPC)非同 VPC、零生产凭证、零客户 PII、零 dcm Redis/PG DSN;
- 本服务只监听 127.0.0.1:8700,经本机 nginx /lab-api/ 暴露(X-Lab-Token 鉴权);
- 生产侧(mix-backend)单向拉取;本服务永远不可能向生产写入任何东西;
- 允许的命令只有:scan_start/scan_stop/replay/shadow_start/shadow_stop/annotate/report/
  canary_proposal/verdict。**不存在生产下单命令**。

V6.2 升级(本文件 v0.2):
- 三状态拆开:project.stage(阶段) / run.state(轮次) / verdict(判决)——SHADOW 从判决枚举移除;
- 判决新枚举:KEEP_MEASURING/ADVANCE_REVIEW/KILL/GRADUATE_PROPOSAL/INSUFFICIENT_EVIDENCE/RETEST_APPROVED;
  旧 KEEP/SHADOW 入参兼容映射为 KEEP_MEASURING,历史行保留 legacy_verdict;
- typed 证据闸(§7):EVIDENCE_POLICY 按产品列必需证据类型;证据未齐 → KEEP_MEASURING/ADVANCE_REVIEW/
  GRADUATE_PROPOSAL 一律 409 LAB_VERDICT_GATE_FAILED(KILL/INSUFFICIENT_EVIDENCE/RETEST_APPROVED 永远放行);
- RUNNING 轮次在场 → 禁止发布判决(先停轮次;KILL 例外=自动停轮);
- research_outbox v2:artifact_type/supersedes_id/schema_version;
- §15 一次性迁移:无证据的历史 KEEP/SHADOW 判决 → SUPERSEDED+LAB_VERDICT_RETRACTED(D3 撤回原因=
  EVIDENCE_SCOPE_MISMATCH_AND_CONTRADICTORY_REPORT,并单独登记 RETEST_APPROVED,不覆盖历史 KILL);
- GET /projects/{pid}/lifecycle:六阶段真状态(COMPLETED/CURRENT/AVAILABLE/LOCKED/FAILED/NOT_APPLICABLE)
  +blocking_reasons+completion_condition+next_action——前端阶段条从静态装饰变可导航。
"""
from __future__ import annotations
import os
import json
import time
import hashlib
import sqlite3
import logging
import lab_spine as _spine
import lab_schema as _schema   # 第二代严谨表代码自有 DDL

from fastapi import FastAPI, Request, HTTPException

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dexlab")

DB = os.path.expanduser("~/dexlab/dexlab.db")
XV_DB = os.path.expanduser("~/xv/xv.db")
TOKEN = os.getenv("DEXLAB_TOKEN", "")

app = FastAPI(title="DEX_LAB API", version="0.2.0")

_ALLOWED = {"scan_start", "scan_stop", "replay", "shadow_start", "shadow_stop",
            "annotate", "report", "canary_proposal", "verdict"}

# ── V6.2 判决状态模型(§4.1):SHADOW 是阶段不是判决 ─────────────────────────
_VERDICTS = {"KEEP_MEASURING", "ADVANCE_REVIEW", "KILL", "GRADUATE_PROPOSAL",
             "INSUFFICIENT_EVIDENCE", "RETEST_APPROVED"}
_LEGACY_VERDICT_MAP = {"KEEP": "KEEP_MEASURING", "SHADOW": "KEEP_MEASURING",
                       "KILL": "KILL", "GRADUATE_PROPOSAL": "GRADUATE_PROPOSAL"}
# 证据闸不拦的"安全方向"判决(停止研究/承认证据不足/登记重测意向)
_SAFE_VERDICTS = {"KILL", "INSUFFICIENT_EVIDENCE", "RETEST_APPROVED"}

# ── typed 证据政策(§7 裁剪版:按类型覆盖,不按条数投票;代码内字典=单人规模的 policy 表) ──
EVIDENCE_POLICY = {
    "D1": ["CONTRACT_IDENTITY", "EXCHANGE_RATE", "REDEEM_STATUS", "TARGET_QUOTE"],
    "D2": ["CONTRACT_IDENTITY", "MATURITY_ONCHAIN", "REDEMPTION_MODEL", "TARGET_QUOTE"],
    "D3": ["CEX_DEPOSIT_OPEN", "CHAIN_CONTRACT_MAPPING", "TRANSFER_TIMING", "HEDGE_DEPTH"],
    "D4": ["FIXED_RATE_LOCK", "TERM_MATCH", "CAPACITY", "COLLATERAL_COST"],
    "R1": [],   # 哨兵只测量,无晋级路径
}
EVIDENCE_TYPE_CN = {
    "CONTRACT_IDENTITY": "合约身份", "EXCHANGE_RATE": "链上兑换率", "REDEEM_STATUS": "赎回状态",
    "TARGET_QUOTE": "目标金额真实报价", "MATURITY_ONCHAIN": "链上到期", "REDEMPTION_MODEL": "兑付模型",
    "CEX_DEPOSIT_OPEN": "CEX充值开放", "CHAIN_CONTRACT_MAPPING": "链/合约映射",
    "TRANSFER_TIMING": "到账时间分布", "HEDGE_DEPTH": "对冲深度",
    "FIXED_RATE_LOCK": "可锁定固定利率", "TERM_MATCH": "期限匹配", "CAPACITY": "真实额度",
    "COLLATERAL_COST": "抵押与清算成本",
}

# ── 信号口径(§6.1:一个 net_bps 不能代表全部) ─────────────────────────────
SIGNAL_KIND = {"D1": "RAW_DISCOUNT", "D2": "IMPLIED_YIELD_SPREAD",
               "D4": "VARIABLE_RATE_MONITOR", "R1": "FUNDING_GAP_SAMPLE"}
KIND_NOTE = {
    "D1": "原始折/溢价信号(LST比价未对 exchange rate 校正);可执行净收益待计算",
    "D2": "隐含收益率差(年化,非本笔套利利润);到期毛折价/净收益待 PT 价格与兑付模型",
    "D3": "无扫描器;历史 KILL_CURRENT_COST 在案,重测须先登记 RETEST_APPROVED",
    "D4": "浮动利率观察差(年化,非固定期限锁定利差);不产生 D4 晋级判决",
    "R1": "跨所资金费差样本(xv 采样库,真数据)",
}

_DDL = """
CREATE TABLE IF NOT EXISTS lab_project(
  project_id TEXT PRIMARY KEY, product TEXT, title TEXT, stage TEXT DEFAULT 'IDEA',
  chain_protocol TEXT DEFAULT '', budget_usdt REAL DEFAULT 0, note TEXT DEFAULT '',
  created_at INTEGER, updated_at INTEGER);
CREATE TABLE IF NOT EXISTS lab_run(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, kind TEXT, params TEXT DEFAULT '{}',
  state TEXT DEFAULT 'RUNNING', samples INTEGER DEFAULT 0, result_bps REAL,
  started_at INTEGER, ended_at INTEGER, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS lab_signal(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, ts INTEGER, payload TEXT);
CREATE TABLE IF NOT EXISTS lab_cost_model(
  project_id TEXT PRIMARY KEY, model TEXT DEFAULT '{}', updated_at INTEGER);
CREATE TABLE IF NOT EXISTS lab_evidence(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, run_id INTEGER, kind TEXT,
  title TEXT, body TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS lab_budget(
  project_id TEXT PRIMARY KEY, granted_usdt REAL DEFAULT 0, used_usdt REAL DEFAULT 0,
  wallet TEXT DEFAULT '', updated_at INTEGER);
CREATE TABLE IF NOT EXISTS lab_wallet_snapshot(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wallet TEXT, equity_usdt REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS research_outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, title TEXT, summary TEXT,
  severity TEXT DEFAULT 'info', created_at INTEGER, consumed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS lab_command_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, command TEXT, params TEXT, actor TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS lab_meta(key TEXT PRIMARY KEY, value TEXT);
"""

_SEED = [
    ("R1", "R1", "市场效率哨兵(跨所资金费差,xv 真数据)", "MEASURE", "CEX五所+HL"),
    ("D1", "D1", "可赎回稳定币/LST/ERC-4626 折价", "IDEA", "ETH L1/L2"),
    ("D2", "D2", "PT/收益凭证固定到期折价", "IDEA", "Pendle 等"),
    ("D3", "D3", "DEX买入-CEX对冲-充值卖出结算", "KILL_CANDIDATE", "多链"),
    ("D4", "D4", "同币种固定期限借贷利差", "IDEA", "Aave/Morpho"),
]


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")   # scanner 写 + API 读并发
    c.execute("PRAGMA busy_timeout=8000")  # 扫描器短事务写入时等待而非立即 locked
    return c


def _cols(c, table: str) -> set:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _migrate(c):
    """幂等迁移:表结构升级 + §15 一次性数据修正(版本化撤回,不删历史)。"""
    now = int(time.time())
    # 1) lab_verdict 重建(旧 CHECK 含 SHADOW → 新枚举+status/legacy 列)
    sql = (c.execute("SELECT sql FROM sqlite_master WHERE name='lab_verdict'").fetchone() or [""])[0] or ""
    if "'SHADOW'" in sql:
        old = [dict(r) for r in c.execute("SELECT * FROM lab_verdict ORDER BY id")]
        c.execute("ALTER TABLE lab_verdict RENAME TO lab_verdict_legacy_v01")
        c.execute("""CREATE TABLE lab_verdict(
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT,
          verdict TEXT CHECK(verdict IN ('KEEP_MEASURING','ADVANCE_REVIEW','KILL',
            'GRADUATE_PROPOSAL','INSUFFICIENT_EVIDENCE','RETEST_APPROVED')),
          reason TEXT, actor TEXT DEFAULT '', created_at INTEGER,
          status TEXT DEFAULT 'ACTIVE', supersede_reason TEXT DEFAULT '',
          legacy_verdict TEXT DEFAULT '', evidence_snapshot TEXT DEFAULT '')""")
        for r in old:
            nv = _LEGACY_VERDICT_MAP.get(r["verdict"], "KEEP_MEASURING")
            c.execute("INSERT INTO lab_verdict(id,project_id,verdict,reason,actor,created_at,"
                      "status,legacy_verdict) VALUES(?,?,?,?,?,?,?,?)",
                      (r["id"], r["project_id"], nv, r["reason"], r["actor"], r["created_at"],
                       "ACTIVE", r["verdict"] if r["verdict"] != nv else ""))
        log.info("lab_verdict rebuilt: %d rows migrated (legacy table kept as lab_verdict_legacy_v01)", len(old))
    # 2) research_outbox v2 列
    oc = _cols(c, "research_outbox")
    if "artifact_type" not in oc:
        c.execute("ALTER TABLE research_outbox ADD COLUMN artifact_type TEXT DEFAULT ''")
        c.execute("ALTER TABLE research_outbox ADD COLUMN supersedes_id INTEGER")
        c.execute("ALTER TABLE research_outbox ADD COLUMN schema_version INTEGER DEFAULT 2")
        c.execute("UPDATE research_outbox SET artifact_type=CASE severity "
                  "WHEN 'verdict' THEN 'LAB_VERDICT_PUBLISHED' "
                  "WHEN 'proposal' THEN 'LAB_GRADUATION_PROPOSAL' "
                  "ELSE 'LAB_RUN_PROGRESS' END WHERE artifact_type=''")
    # 3) lab_evidence typed 列
    ec = _cols(c, "lab_evidence")
    if "evidence_type" not in ec:
        c.execute("ALTER TABLE lab_evidence ADD COLUMN evidence_type TEXT DEFAULT ''")
        c.execute("ALTER TABLE lab_evidence ADD COLUMN source TEXT DEFAULT ''")
        c.execute("ALTER TABLE lab_evidence ADD COLUMN observed_at INTEGER")
        c.execute("ALTER TABLE lab_evidence ADD COLUMN expires_at INTEGER")
    # 4) §15 一次性数据修正:无证据的历史 KEEP/SHADOW → SUPERSEDED + 撤回 artifact
    if not c.execute("SELECT 1 FROM lab_meta WHERE key='mig_v62_01'").fetchone():
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM lab_verdict WHERE status='ACTIVE' AND legacy_verdict IN ('KEEP','SHADOW')")]
        d3_retracted = False
        for r in rows:
            pid = r["project_id"]
            req = EVIDENCE_POLICY.get(pid, [])
            have = {x[0] for x in c.execute(
                "SELECT DISTINCT evidence_type FROM lab_evidence WHERE project_id=? AND evidence_type!=''", (pid,))}
            if req and not set(req).issubset(have):
                reason = ("EVIDENCE_SCOPE_MISMATCH_AND_CONTRADICTORY_REPORT" if pid == "D3"
                          else "LEGACY_VERDICT_WITHOUT_EVIDENCE")
                c.execute("UPDATE lab_verdict SET status='SUPERSEDED', supersede_reason=? WHERE id=?",
                          (reason, r["id"]))
                c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
                          "artifact_type,supersedes_id,schema_version) VALUES(?,?,?,?,?,?,?,2)",
                          (pid, f"{pid} 判决撤回:{r['legacy_verdict']}(#{r['id']})",
                           f"V6.2迁移:该判决发布时必需证据 0/{len(req)},且与既有证据结论冲突;"
                           f"已版本化撤回(原因={reason}),历史行保留可审计。", "verdict", now,
                           "LAB_VERDICT_RETRACTED", r["id"]))
                if pid == "D3":
                    d3_retracted = True
        if d3_retracted:
            # 原 KEEP 提交者的真实意图=重新观察 → 单独登记 RETEST_APPROVED,绝不覆盖历史 KILL
            c.execute("INSERT INTO lab_verdict(project_id,verdict,reason,actor,created_at,status) "
                      "VALUES('D3','RETEST_APPROVED',"
                      "'原KEEP撤回;重测意向单独登记——只表示允许重新采样,不覆盖历史KILL_CURRENT_COST','migration',?, 'ACTIVE')", (now,))
            c.execute("UPDATE lab_project SET stage='MEASURE', note='RETEST_REQUIRED:历史KILL在案,重测已获准', "
                      "updated_at=? WHERE project_id='D3'", (now,))
        c.execute("INSERT INTO lab_meta(key,value) VALUES('mig_v62_01',?)", (str(now),))
        log.info("mig_v62_01 done: %d legacy verdicts checked, D3 retracted=%s", len(rows), d3_retracted)


@app.on_event("startup")
def _init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = db()
    c.executescript(_DDL)
    _schema.ensure_v2(c)          # 孤儿严谨表收编为代码自有(IF NOT EXISTS 对 live 零作用)+ schema_version 版本戳
    now = int(time.time())
    for pid, prod, title, stage, chain in _SEED:
        c.execute("INSERT OR IGNORE INTO lab_project(project_id,product,title,stage,chain_protocol,"
                  "created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (pid, prod, title, stage, chain, now, now))
    # D3 CrossArb 五方向证伪 → 种子判决(历史事实;新枚举下=KILL,口径 KILL_CURRENT_COST)
    if not c.execute("SELECT 1 FROM lab_verdict WHERE project_id='D3' AND verdict='KILL'").fetchone():
        c.execute("INSERT OR IGNORE INTO lab_verdict(id,project_id,verdict,reason,actor,created_at) "
                  "VALUES(1,'D3','KILL','KILL_CURRENT_COST:CrossArb五方向统一证伪:成本线38bps在专业玩家钉宽外;"
                  "假阳性=死池污染/锚定币折价','seed',?)", (now,))
    _migrate(c)
    c.commit()
    c.close()


def _auth(req: Request):
    if not TOKEN or req.headers.get("X-Lab-Token") != TOKEN:
        raise HTTPException(401, "X-Lab-Token 无效")


def _evidence_state(c, pid: str) -> dict:
    """证据闸状态:必需类型 vs 已具备(未过期)类型。"""
    req = EVIDENCE_POLICY.get(pid, [])
    now = int(time.time())
    have = {x[0] for x in c.execute(
        "SELECT DISTINCT evidence_type FROM lab_evidence WHERE project_id=? AND evidence_type!='' "
        "AND (expires_at IS NULL OR expires_at>?)", (pid, now))}
    missing = [t for t in req if t not in have]
    return {"required": req, "present": sorted(have & set(req)), "missing": missing,
            "gate_pass": not missing, "coverage": f"{len(req)-len(missing)}/{len(req)}" if req else "—"}


@app.get("/health")
def health(req: Request):
    _auth(req)
    xv_ok = os.path.exists(XV_DB)
    return {"ok": True, "env": "DEX_LAB", "xv_db": xv_ok, "ts": int(time.time()),
            "version": "0.2.0",
            "isolation": "独立VPC/零生产凭证/单向outbox"}


@app.get("/projects")
def projects(req: Request):
    _auth(req)
    c = db()
    rows = [dict(r) for r in c.execute(
        "SELECT p.*, "
        "(SELECT count(*) FROM lab_run r WHERE r.project_id=p.project_id) AS runs, "
        "(SELECT count(*) FROM lab_run r WHERE r.project_id=p.project_id AND r.state='RUNNING') AS running, "
        "(SELECT coalesce(sum(samples),0) FROM lab_run r WHERE r.project_id=p.project_id) AS samples_total, "
        "(SELECT result_bps FROM lab_run r WHERE r.project_id=p.project_id "
        " AND result_bps IS NOT NULL ORDER BY run_id DESC LIMIT 1) AS latest_result_bps, "
        "(SELECT max(ts) FROM lab_signal s WHERE s.project_id=p.project_id) AS last_signal_ts, "
        "(SELECT count(*) FROM lab_evidence e WHERE e.project_id=p.project_id) AS evidence_total "
        "FROM lab_project p ORDER BY p.project_id")]
    for p in rows:
        pid = p["project_id"]
        ev = _evidence_state(c, pid)
        p["evidence_gate"] = ev
        # 最新有效判决(排除 RETEST_APPROVED——它是重测许可,不是结论)
        v = c.execute("SELECT verdict,reason,created_at,research_disposition,promotion_eligibility,economic_net_bps,blocking_reasons FROM lab_verdict WHERE project_id=? "
                      "AND status='ACTIVE' AND verdict!='RETEST_APPROVED' ORDER BY id DESC LIMIT 1",
                      (pid,)).fetchone()
        p["latest_verdict"] = v["verdict"] if v else None
        p["latest_verdict_reason"] = v["reason"] if v else ""
        p["research_disposition"] = v["research_disposition"] if v else None
        p["promotion_eligibility"] = v["promotion_eligibility"] if v else None
        p["economic_net_bps"] = v["economic_net_bps"] if v else None
        p["blocking_reasons"] = v["blocking_reasons"] if v else None
        rt = c.execute("SELECT created_at FROM lab_verdict WHERE project_id=? AND verdict='RETEST_APPROVED' "
                       "AND status='ACTIVE' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        p["retest_at"] = rt["created_at"] if rt else None
        p["signal_kind"] = SIGNAL_KIND.get(pid)
        p["kind_note"] = KIND_NOTE.get(pid, "")
    c.close()
    return rows


# ── 生命周期(§4.2/§4.3):阶段条从静态装饰变可导航——每个阶段真状态+锁定原因+下一步 ──
_STAGES = ["IDEA", "MEASURE", "REPLAY", "SHADOW", "CANARY", "REVIEW"]
_STAGE_CN = {"IDEA": "想法", "MEASURE": "测量", "REPLAY": "回放", "SHADOW": "影子测试",
             "CANARY": "小额Canary", "REVIEW": "判决"}
_MIN_SAMPLES = 100


@app.get("/projects/{pid}/lifecycle")
def lifecycle(pid: str, req: Request):
    _auth(req)
    c = db()
    p = c.execute("SELECT * FROM lab_project WHERE project_id=?", (pid,)).fetchone()
    if not p:
        c.close()
        raise HTTPException(404, f"项目 {pid} 不存在")
    now = int(time.time())
    ev = _evidence_state(c, pid)
    running = c.execute("SELECT count(*) FROM lab_run WHERE project_id=? AND state='RUNNING'",
                        (pid,)).fetchone()[0]
    samples = c.execute("SELECT coalesce(sum(samples),0) FROM lab_run WHERE project_id=?",
                        (pid,)).fetchone()[0]
    measured = samples > 0
    kill = c.execute("SELECT 1 FROM lab_verdict WHERE project_id=? AND verdict='KILL' AND status='ACTIVE'",
                     (pid,)).fetchone() is not None
    retest = c.execute("SELECT 1 FROM lab_verdict WHERE project_id=? AND verdict='RETEST_APPROVED' "
                       "AND status='ACTIVE'", (pid,)).fetchone() is not None
    sentinel = pid == "R1"   # 哨兵项目:只测量,无晋级路径
    stages = []

    def add(stage, status, blocking=None, cond="", nxt="", data=None):
        stages.append({"stage": stage, "cn": _STAGE_CN[stage], "status": status,
                       "blocking_reasons": blocking or [], "completion_condition": cond,
                       "next_action": nxt, "data": data or {}})

    add("IDEA", "COMPLETED", cond="产品定义/收益来源/失效条件已登记",
        data={"title": p["title"], "chain_protocol": p["chain_protocol"], "note": p["note"]})
    if kill and not retest:
        add("MEASURE", "LOCKED", ["历史 KILL 在案——重测须先登记 RETEST_APPROVED 判决(不覆盖历史 KILL)"],
            "登记重测许可后可重新采样", "verdict:RETEST_APPROVED")
    elif running:
        add("MEASURE", "CURRENT", cond=f"最小样本 ≥{_MIN_SAMPLES}(现 {samples})且信号新鲜",
            nxt="scan_stop", data={"samples": samples, "running_runs": running})
    elif measured:
        add("MEASURE", "COMPLETED", cond=f"已累计 {samples} 样本;可再次 scan_start 补采",
            nxt="scan_start", data={"samples": samples})
    else:
        add("MEASURE", "AVAILABLE", cond=f"开始扫描后由 worker 每5分钟采样;最小样本 ≥{_MIN_SAMPLES}",
            nxt="scan_start")
    rep_running = c.execute("SELECT count(*) FROM lab_run WHERE project_id=? AND kind='REPLAY' "
                            "AND state='RUNNING'", (pid,)).fetchone()[0]
    rep_done = c.execute("SELECT run_id, note, ended_at FROM lab_run WHERE project_id=? AND kind='REPLAY' "
                         "AND state='DONE' ORDER BY run_id DESC LIMIT 1", (pid,)).fetchone()
    if sentinel:
        add("REPLAY", "NOT_APPLICABLE")
    elif rep_running:
        add("REPLAY", "CURRENT", cond="回放执行器将在下一轮(≤5分钟)完成历史重放",
            data={"running": rep_running})
    elif rep_done:
        add("REPLAY", "COMPLETED",
            cond="口径=重放已采样lab_signal历史(非区块重演);结果须人工评审,不自动晋级",
            nxt="replay", data={"latest_run_id": rep_done["run_id"], "latest": rep_done["note"]})
    elif samples >= _MIN_SAMPLES:
        add("REPLAY", "AVAILABLE", cond="重放已采样历史→超成本占比/持续性/瞬时信号率/净p50",
            nxt="replay")
    else:
        add("REPLAY", "LOCKED", [f"测量样本不足({samples}/{_MIN_SAMPLES})——先积累采样再回放"],
            "达到最小样本后可回放", "")
    add("SHADOW", "NOT_APPLICABLE" if sentinel else "LOCKED",
        None if sentinel else ["影子执行器未建(后续批次)", "回放结果须人工评审通过(不自动晋级)"],
        "影子账本+风险预算+权限+退出路径通过", "")
    add("CANARY", "NOT_APPLICABLE" if sentinel else "LOCKED",
        None if sentinel else ["影子未通过", "需 D-canary 独立钱包 + HOUSE_RND + Passkey + 明确预算(人工审批)"],
        "仅 D-canary+HOUSE_RND+Passkey+预算;本页永不直接下单", "")
    add("REVIEW", "AVAILABLE", cond="证据闸通过后方可 保留研究/提交评审/生产化提案;停止研究/证据不足/允许重测 随时可登记",
        nxt="verdict", data={"evidence_gate": ev, "running": running})
    c.close()
    return {"project_id": pid, "project_stage": p["stage"], "stages": stages,
            "evidence_gate": ev, "data_as_of": now}


@app.get("/signals")
def signals(req: Request, project: str = "", limit: int = 50):
    """lab_signal 逐样本(扫描与观察页签数据源)。payload 含逐标的明细+口径标注。"""
    _auth(req)
    c = db()
    limit = max(1, min(limit, 200))
    if project:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM lab_signal WHERE project_id=? ORDER BY id DESC LIMIT ?", (project, limit))]
    else:
        rows = [dict(r) for r in c.execute("SELECT * FROM lab_signal ORDER BY id DESC LIMIT ?", (limit,))]
    for r in rows:
        try:
            r["payload"] = json.loads(r["payload"])
        except Exception:  # noqa: BLE001
            pass
    c.close()
    return rows


def _r1_fresh_summary() -> dict | None:
    """R1=xv 采样器真数据(同机只读):近24h 最优跨所费差样本量与中位数。"""
    if not os.path.exists(XV_DB):
        return None
    try:
        x = sqlite3.connect(f"file:{XV_DB}?mode=ro", uri=True)
        x.row_factory = sqlite3.Row
        tabs = [r[0] for r in x.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        tab = "samples" if "samples" in tabs else (tabs[0] if tabs else None)
        if not tab:
            return None
        n = x.execute(f"SELECT count(*) AS n FROM {tab}").fetchone()["n"]
        cols = [r[1] for r in x.execute(f"PRAGMA table_info({tab})")]
        out = {"table": tab, "total_samples": int(n), "columns": cols[:12]}
        if "ts" in cols:
            r24 = x.execute(f"SELECT count(*) AS n FROM {tab} WHERE ts > strftime('%s','now')-86400").fetchone()
            out["samples_24h"] = int(r24["n"])
        x.close()
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}


@app.get("/runs")
def runs(req: Request, project: str = ""):
    _auth(req)
    c = db()
    q = "SELECT * FROM lab_run" + (" WHERE project_id=?" if project else "") + " ORDER BY run_id DESC LIMIT 100"
    rows = [dict(r) for r in (c.execute(q, (project,)) if project else c.execute(q))]
    c.close()
    return {"runs": rows, "r1_live": _r1_fresh_summary()}


@app.get("/evidence")
def evidence(req: Request, run_id: str = "", project: str = ""):
    _auth(req)
    c = db()
    if run_id:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM lab_evidence WHERE run_id=? ORDER BY id DESC LIMIT 100", (run_id,))]
    elif project:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM lab_evidence WHERE project_id=? ORDER BY id DESC LIMIT 100", (project,))]
    else:
        rows = [dict(r) for r in c.execute("SELECT * FROM lab_evidence ORDER BY id DESC LIMIT 100")]
    c.close()
    return rows


@app.get("/verdicts")
def verdicts(req: Request):
    _auth(req)
    c = db()
    rows = [dict(r) for r in c.execute("SELECT * FROM lab_verdict ORDER BY id DESC LIMIT 100")]
    c.close()
    return rows


@app.get("/outbox")
def outbox(req: Request):
    """research_outbox 单向研究摘要——生产侧只显示「LAB 有新结果」提醒,信号不入可执行列表。"""
    _auth(req)
    c = db()
    rows = [dict(r) for r in c.execute("SELECT * FROM research_outbox ORDER BY id DESC LIMIT 50")]
    c.close()
    return rows


def _compose_report(c, pid: str) -> str:
    """无人工正文时,从项目事实合成报告(阶段/轮次/证据闸/最新判决+口径注)——
    宁可写『尚无测量数据』也不发空正文。"""
    p = c.execute("SELECT * FROM lab_project WHERE project_id=?", (pid,)).fetchone()
    if not p:
        return f"{pid}:项目不存在"
    runs = list(c.execute("SELECT kind,state,samples,result_bps FROM lab_run WHERE project_id=? "
                          "ORDER BY run_id DESC LIMIT 5", (pid,)))
    ev = _evidence_state(c, pid)
    vd = c.execute("SELECT verdict,reason,created_at FROM lab_verdict WHERE project_id=? "
                   "AND status='ACTIVE' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    lines = [f"{p['title']}｜链/协议:{p['chain_protocol'] or '—'}｜当前阶段:{p['stage']}"]
    note = KIND_NOTE.get(pid)
    if note:
        lines.append(f"口径:{note}")
    if pid == "R1":
        live = _r1_fresh_summary() or {}
        lines.append(f"实时采样:总样本 {live.get('total_samples','?')} · 24h {live.get('samples_24h','?')}(xv 采样库)")
    if runs:
        lines.append("最近轮次:" + " / ".join(
            f"{r['kind']}·{r['state']}" + (f"·{r['result_bps']}bps" if r["result_bps"] is not None else "")
            for r in runs))
    else:
        lines.append("尚无测量/回放/影子轮次——项目处于想法阶段,报告仅登记现状")
    lines.append(f"证据闸:{ev['coverage']}" + ("(缺:" + "/".join(
        EVIDENCE_TYPE_CN.get(t, t) for t in ev["missing"]) + ")" if ev["missing"] else ""))
    if vd:
        lines.append(f"最新判决:{vd['verdict']}——{vd['reason']}")
    else:
        lines.append("尚无判决(证据未齐时=待取证)")
    return "\n".join(lines)[:2000]


def _ev_snapshot(c, pid: str) -> str:
    """判决引用的不可变证据快照(id+type+hash)。"""
    rows = [dict(r) for r in c.execute(
        "SELECT id,evidence_type,title,created_at FROM lab_evidence WHERE project_id=? ORDER BY id", (pid,))]
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return json.dumps({"evidence_ids": [r["id"] for r in rows],
                       "snapshot_hash": hashlib.sha1(blob.encode()).hexdigest()[:16]}, ensure_ascii=False)


@app.post("/commands")
async def commands(req: Request):
    _auth(req)
    body = await req.json()
    cmd = str(body.get("command") or "")
    if cmd not in _ALLOWED:
        raise HTTPException(400, f"仅允许 {sorted(_ALLOWED)};不存在生产下单命令")
    pid = str(body.get("project_id") or "")
    actor = str(body.get("actor") or "")[:60]
    now = int(time.time())
    c = db()
    c.execute("INSERT INTO lab_command_log(command,params,actor,created_at) VALUES(?,?,?,?)",
              (cmd, json.dumps(body, ensure_ascii=False), actor, now))
    out = {"accepted": cmd}
    try:
        if cmd in ("scan_start", "replay", "shadow_start"):
            kind = {"scan_start": "MEASURE", "replay": "REPLAY", "shadow_start": "SHADOW"}[cmd]
            # D3 重测闸(§10):历史 KILL 在案且无 RETEST_APPROVED → 拒绝开新轮
            killed = c.execute("SELECT 1 FROM lab_verdict WHERE project_id=? AND verdict='KILL' "
                               "AND status='ACTIVE'", (pid,)).fetchone()
            retest = c.execute("SELECT 1 FROM lab_verdict WHERE project_id=? AND verdict='RETEST_APPROVED' "
                               "AND status='ACTIVE'", (pid,)).fetchone()
            if killed and not retest:
                raise HTTPException(409, {"code": "RETEST_REQUIRED",
                                          "blocking_reasons": ["历史 KILL 在案——先登记 RETEST_APPROVED 判决再重新采样"]})
            run_params = dict(body.get("params") or {})
            try:
                run_params["_plan_id"] = _spine.register_run_plan(c, pid, kind, run_params, now)
            except Exception as _e:  # noqa: BLE001  # 主脊 plan 登记失败绝不挡研究主命令
                log.warning("spine plan register failed pid=%s: %r", pid, _e)
            cur = c.execute("INSERT INTO lab_run(project_id,kind,params,state,started_at) VALUES(?,?,?,?,?)",
                            (pid, kind, json.dumps(run_params, ensure_ascii=False), "RUNNING", now))
            c.execute("UPDATE lab_project SET stage=?, updated_at=? WHERE project_id=?", (kind, now, pid))
            out["run_id"] = cur.lastrowid
        elif cmd in ("scan_stop", "shadow_stop"):
            _stopping = [dict(_rr) for _rr in c.execute(
                "SELECT run_id,project_id,kind,params,started_at FROM lab_run "
                "WHERE project_id=? AND state='RUNNING'", (pid,)).fetchall()]
            c.execute("UPDATE lab_run SET state='DONE', ended_at=? WHERE project_id=? AND state='RUNNING'",
                      (now, pid))
            _mans = []
            for _r in _stopping:
                try:
                    _r["state"] = "DONE"; _r["ended_at"] = now
                    _pl = (json.loads(_r.get("params") or "{}") or {}).get("_plan_id")
                    c.execute("DELETE FROM lab_run_manifests WHERE run_id=?", (_r["run_id"],))
                    _mans.append(_spine.insert_manifest(c, _r, plan_id=_pl, min_ratio=0.80))
                except Exception as _e:  # noqa: BLE001  # manifest 失败不挡停轮
                    log.warning("spine manifest failed run=%s: %r", _r.get("run_id"), _e)
            out["manifests"] = _mans
            c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
                      "artifact_type,schema_version) VALUES(?,?,?,?,?,'LAB_RUN_COMPLETED',2)",
                      (pid, f"{pid} 轮次结束", f"{pid} 运行中轮次已停止;判决只消费已完成轮次。", "info", now))
            out["stopped"] = True
        elif cmd == "annotate":
            # typed 证据登记:evidence_type 属 EVIDENCE_POLICY 词表(annotation=自由标注,不计闸)
            et = str(body.get("evidence_type") or "")
            if et and et not in EVIDENCE_TYPE_CN:
                raise HTTPException(400, f"evidence_type 须属:{sorted(EVIDENCE_TYPE_CN)} 或留空(自由标注)")
            c.execute("INSERT INTO lab_evidence(project_id,run_id,kind,title,body,created_at,"
                      "evidence_type,source,observed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (pid, body.get("run_id"), "annotation" if not et else "typed",
                       str(body.get("title") or "")[:120], str(body.get("body") or "")[:2000], now,
                       et, str(body.get("source") or "")[:120], now))
            if et:
                c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
                          "artifact_type,schema_version) VALUES(?,?,?,?,?,'LAB_EVIDENCE_UPDATED',2)",
                          (pid, f"{pid} 证据更新:{EVIDENCE_TYPE_CN.get(et, et)}",
                           str(body.get("title") or "")[:200], "info", now))
        elif cmd == "report":
            title = f"{pid} 研究摘要"
            summ = str(body.get("summary") or "")[:2000]
            if not summ:
                summ = _compose_report(c, pid)   # 任何项目都合成事实正文,绝不发空壳报告
            c.execute("INSERT INTO research_outbox(project_id,title,summary,created_at,"
                      "artifact_type,schema_version) VALUES(?,?,?,?,'LAB_RUN_PROGRESS',2)",
                      (pid, title, summ, now))
            out["outbox"] = True
        elif cmd == "verdict":
            v_in = str(body.get("verdict") or "")
            v = _LEGACY_VERDICT_MAP.get(v_in, v_in)
            if v not in _VERDICTS:
                raise HTTPException(400, f"verdict ∈ {sorted(_VERDICTS)}(SHADOW 是阶段不是判决)")
            ev = _evidence_state(c, pid)
            running = c.execute("SELECT count(*) FROM lab_run WHERE project_id=? AND state='RUNNING'",
                                (pid,)).fetchone()[0]
            if v not in _SAFE_VERDICTS:
                blocking = []
                if running:
                    blocking.append(f"轮次运行中({running} RUNNING)——判决只消费已完成轮次,先停止扫描")
                if ev["missing"]:
                    blocking.append("必需证据未齐:" + "/".join(
                        EVIDENCE_TYPE_CN.get(t, t) for t in ev["missing"]))
                if v == "GRADUATE_PROPOSAL":
                    stg = c.execute("SELECT stage FROM lab_project WHERE project_id=?", (pid,)).fetchone()
                    if not stg or stg["stage"] not in ("SHADOW", "CANARY"):
                        blocking.append("GRADUATE_PROPOSAL 只能来自 SHADOW/CANARY 完成态(§4.1 不变量)")
                    # LP0 coverage enforce:GRADUATION 要求完整覆盖率证明(DEGRADED/INCOMPLETE 拦)
                    try:
                        _cov_adv = _spine.coverage_advisory(c, pid)
                        if _cov_adv:
                            for _m in _cov_adv:
                                rid = _m.get("run_id", "?")
                                integ = _m.get("integrity_status", "?")
                                cov = float(_m.get("coverage_ratio") or 0)
                                blocking.append(f"覆盖率不足:run#{rid} {integ} ({cov*100:.1f}%<95%)")
                    except Exception as _e:
                        log.warning("coverage advisory failed in GRADUATION gate pid=%s: %r", pid, _e)
                if blocking:
                    raise HTTPException(409, {"code": "LAB_VERDICT_GATE_FAILED",
                                              "missing_evidence_types": ev["missing"],
                                              "blocking_reasons": blocking})
            if v == "KILL" and running:
                # 停止研究隐含停轮(减险方向,永远放行)
                c.execute("UPDATE lab_run SET state='DONE', ended_at=? WHERE project_id=? AND state='RUNNING'",
                          (now, pid))
            c.execute("INSERT INTO lab_verdict(project_id,verdict,reason,actor,created_at,status,"
                      "evidence_snapshot) VALUES(?,?,?,?,?,'ACTIVE',?)",
                      (pid, v, str(body.get("reason") or "")[:500], actor, now, _ev_snapshot(c, pid)))
            try:
                _adv = _spine.coverage_advisory(c, pid)
                if _adv:
                    out["coverage_advisory"] = _adv
                    c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
                              "artifact_type,schema_version) VALUES(?,?,?,?,?,'LAB_COVERAGE_ADVISORY',2)",
                              (pid, f"{pid} 覆盖率顾问(shadow)", json.dumps(_adv, ensure_ascii=False), "warn", now))
            except Exception as _e:  # noqa: BLE001
                log.warning("spine coverage advisory failed pid=%s: %r", pid, _e)
            at = "LAB_GRADUATION_PROPOSAL" if v == "GRADUATE_PROPOSAL" else "LAB_VERDICT_PUBLISHED"
            c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
                      "artifact_type,schema_version) VALUES(?,?,?,?,?,?,2)",
                      (pid, f"{pid} 判决:{v}", str(body.get("reason") or "")[:500], "verdict", now, at))
            out["verdict"] = v
        elif cmd == "canary_proposal":
            c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
                      "artifact_type,schema_version) VALUES(?,?,?,?,?,'LAB_GRADUATION_PROPOSAL',2)",
                      (pid, f"{pid} 受控canary提案(HOUSE_RND,人工审批)",
                       str(body.get("summary") or "")[:1000], "proposal", now))
            out["note"] = "提案只落 outbox;真钱 canary 须 HOUSE_RND 独立钱包+人工审批,本服务无下单能力"
        c.commit()
    finally:
        c.close()
    return out
