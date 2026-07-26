"""V6.2 R2 自动回路统一监督面(MIX-V6.2-OPEX-AUTO-PATCH-03 §7)——只读。

- AutomationLoopRegistry:mix_main.automation_loop_registry,种子=R0 审计实测清单(2026-07-26)。
- 本路由**零控制能力**:无暂停/恢复/提额端点(R4 走统一 typed command),只做登记+投影+证据透出。
- 证据分级如实标注:Redis dcm:phase:auto:log 为 TEMP_OBSERVATION(临时观测源,
  非审计权威——正式链路 cycle→decision→Intent→Saga→RECON→Ledger 由 B 侧 outbox 补,R2 后续)。
"""
import json
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer
from .. import datasources as ds

log = logging.getLogger("mix.automation")
router = APIRouter(tags=["v6-automation"])

_DDL = """
CREATE TABLE IF NOT EXISTS automation_loop_registry(
  loop_id text PRIMARY KEY,
  display_name text NOT NULL,
  machine text NOT NULL,
  unit_name text,
  product_code text,
  principal_kind text NOT NULL,   -- AUTO_WRITER/EXECUTOR/BOOKKEEPER/PROPOSER/OBSERVER/MANUAL_EXECUTOR
  risk_class text NOT NULL,       -- NEW_RISK/REDUCE_ONLY/STATE_REPAIR/READ_ONLY
  runtime_stage text NOT NULL,    -- ARMED/SHADOW/MEASURE/MANUAL/ACTIVE
  schedule text,
  chain_note text,                -- 执行链证据(R0 审计结论)
  evidence_source text,           -- 现有可观测源
  evidence_grade text NOT NULL DEFAULT 'TEMP_OBSERVATION',
  registered_by text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
"""

# R0 审计实测清单(2026-07-26):新增自动 writer 必须先入此册(§7.1)
_SEED = [
    ("phase-autopilot", "相位自动开平仓", "B", "dcm-phase-autopilot.timer", "C1,C2.C",
     "AUTO_WRITER", "NEW_RISK", "ARMED", "每10分钟",
     "开=rpush dcm:exec:fastlane:req(C四闸预审→B runner 机器闸+Intent工厂+Saga);平=manager target=close;直接下单调用=0(R0逐行审计)",
     "redis:dcm:phase:auto:log", "TEMP_OBSERVATION"),
    ("exec-autopilot", "L0 自动开仓层", "B", "dcm-exec-autopilot.service", "C2",
     "AUTO_WRITER", "NEW_RISK", "ARMED", "常驻循环",
     "单笔30U/日预算100U(2026-07-25用户授权);经 fastlane 统一链", "journald", "TEMP_OBSERVATION"),
    ("exec-opener", "机会开仓器", "B", "dcm-exec-opener.service", "C2",
     "AUTO_WRITER", "NEW_RISK", "ARMED", "常驻循环",
     "深度硬闸+三配额+冷却(Redis热配);Saga执行;direct_order=0", "journald", "TEMP_OBSERVATION"),
    ("exec-runner", "fastlane 执行器", "B", "dcm-exec-runner.service", "多产品",
     "EXECUTOR", "NEW_RISK", "ARMED", "队列消费",
     "OpenPairIntent→save_intent→saga关联→open_pair;平仓减险方向不设深度/额度闸", "redis:dcm:exec:fastlane:res:*", "TEMP_OBSERVATION"),
    ("exec-manager", "持仓收敛管理器", "B", "dcm-exec-manager.service", "多产品",
     "AUTO_WRITER", "REDUCE_ONLY", "ARMED", "常驻循环",
     "close_pair→SagaExecutor→MultiVenue(复用六所place,不造第二条下单路)", "journald", "TEMP_OBSERVATION"),
    ("exec-recon", "对账自动修复", "B", "dcm-exec-recon.service", "多产品",
     "BOOKKEEPER", "STATE_REPAIR", "ARMED", "常驻循环",
     "armed 仅 ORPHAN_CLAIM(DCM_RECON_AUTO_FIX 白名单);reaper 默认 shadow(DCM_REAP_ENFORCE 才真收)", "pg:recon_fixes", "AUDIT_TABLE"),
    ("exec-repair", "风险修复意图层", "B", "dcm-exec-repair.service", "多产品",
     "PROPOSER", "READ_ONLY", "SHADOW", "常驻循环",
     "绝不下单;构造意图+manager patch 提案", "journald", "TEMP_OBSERVATION"),
    ("c3s-autopilot", "C3.S 影子自主环", "C", "mix-backend 内嵌任务", "C3.S",
     "PROPOSER", "READ_ONLY", "SHADOW", "每20秒",
     "代码级零 emit(不 import c3s_writer);E闸+借币承重闸", "pg:c3s_autopilot_cycle", "AUDIT_TABLE"),
    ("c4-exec-cli", "C4/C5 期现交割执行器", "B", "人工 CLI(无 unit)", "C4,C5",
     "MANUAL_EXECUTOR", "NEW_RISK", "MANUAL", "按需人工",
     "⚠直接下单;两钥匙(env DCM_C4_ARMED+redis dcm:c4:exec:armed)五闸 fail-closed;独立于 Intent/Saga=R1 候补收编项", "pg:c4_position", "AUDIT_TABLE"),
    ("c6-calendar-probe", "C6 日历价差探针", "C", "dcm-c6-calendar.timer", "C6",
     "OBSERVER", "READ_ONLY", "MEASURE", "每小时:23",
     "纯公共行情零密钥零下单", "pg:c6_calendar_samples", "AUDIT_TABLE"),
    ("carry-advisor", "carry 选对顾问", "C", "dcm-carry-advisor.service", "C2",
     "OBSERVER", "READ_ONLY", "ACTIVE", "常驻循环",
     "rule-based best-pair 扫描;只出 watchlist 不执行", "redis", "TEMP_OBSERVATION"),
    ("fund-scheduler", "资金水线调度", "C", "dcm-fund-scheduler.service", "资金面",
     "PROPOSER", "READ_ONLY", "ACTIVE", "常驻循环",
     "waterline proposals,no execution", "pg", "TEMP_OBSERVATION"),
    ("llm-advisor", "LLM 只读复核层", "C", "dcm-llm-advisor.service", "多产品",
     "OBSERVER", "READ_ONLY", "ACTIVE", "常驻循环",
     "never touches money path", "journald", "TEMP_OBSERVATION"),
    ("release-drift", "发布漂移检测", "C", "mix-release-drift.timer", "基础设施",
     "OBSERVER", "READ_ONLY", "ACTIVE", "每小时:41",
     "活体 vs manifest 基线(P0=后端代码/P1=dist/OPS=配置)", "file:/data/mix/release/drift_status.json", "AUDIT_TABLE"),
]

_seeded = False


async def _ensure(pool):
    global _seeded
    if _seeded:
        return
    async with pool.acquire() as con:
        await con.execute(_DDL)
        for row in _SEED:
            await con.execute(
                """INSERT INTO automation_loop_registry(loop_id,display_name,machine,unit_name,
                     product_code,principal_kind,risk_class,runtime_stage,schedule,chain_note,
                     evidence_source,evidence_grade,registered_by)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'r0_audit_20260726')
                   ON CONFLICT (loop_id) DO NOTHING""", *row)
    _seeded = True


async def _phase_log(limit=8):
    r = ds.rds()
    if r is None:
        return None
    try:
        raw = await r.lrange("dcm:phase:auto:log", 0, limit - 1)
        out = []
        for x in raw:
            try:
                out.append(json.loads(x))
            except Exception:
                out.append({"raw": x})
        return out
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)[:120]}]


def _drift_status():
    try:
        with open("/data/mix/release/drift_status.json") as f:
            return json.load(f)
    except Exception:
        return None


@router.get("/automation/loops")
async def automation_loops(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可用")
    await _ensure(pool)
    async with pool.acquire() as con:
        rows = [dict(r) for r in await con.fetch(
            "SELECT * FROM automation_loop_registry ORDER BY risk_class, machine, loop_id")]
    for r in rows:
        r["updated_at"] = str(r.get("updated_at"))
    return {"loops": rows, "as_of": int(time.time()),
            "note": "登记册=R0审计实测;evidence_grade=TEMP_OBSERVATION 的源不作审计权威(§7.3)"}


@router.get("/automation/summary")
async def automation_summary(_who=Depends(require_viewer)):
    """今日工作自动状态条:紧凑事实带。所有源不可达时如实降级,绝不编数。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可用")
    await _ensure(pool)
    async with pool.acquire() as con:
        agg = await con.fetch(
            "SELECT risk_class, runtime_stage, count(*) n FROM automation_loop_registry "
            "GROUP BY 1,2 ORDER BY 1,2")
        c3s = None
        try:
            row = await con.fetchrow(
                "SELECT cycle_ts, n_candidates, n_signal, n_v6_open FROM c3s_autopilot_cycle "
                "ORDER BY id DESC LIMIT 1")
            c3s = dict(row) if row else None
            if c3s:
                c3s["cycle_ts"] = str(c3s["cycle_ts"])
        except Exception:
            pass
    armed_key = None
    r = ds.rds()
    if r is not None:
        try:
            armed_key = await r.get("dcm:phase:auto:armed")
        except Exception:
            armed_key = None
    plog = await _phase_log(5)
    last_phase_ts = None
    if plog:
        for e in plog:
            if isinstance(e, dict) and e.get("ts"):
                last_phase_ts = e["ts"]
                break
    c6_last = None
    try:
        dpool = await ds.pg()
        if dpool is not None:
            async with dpool.acquire() as con:
                c6_last = str(await con.fetchval("SELECT max(ts) FROM c6_calendar_samples"))
    except Exception:
        pass
    return {
        "as_of": int(time.time()),
        "counts": [dict(a) for a in agg],
        "phase_autopilot": {
            "armed_redis_key": armed_key,
            "armed_note": "两钥匙:env PHASE_AUTO_ARMED 侧在 B 机 unit(此处不可见);redis 钥匙如左",
            "last_log_ts": last_phase_ts,
            "recent": plog,
            "evidence_grade": "TEMP_OBSERVATION",
        },
        "c3s_autopilot_last_cycle": c3s,
        "c6_probe_last_sample": c6_last,
        "release_drift": _drift_status(),
    }


@router.get("/automation/loops/{loop_id}/timeline")
async def automation_timeline(loop_id: str, limit: int = 50, _who=Depends(require_viewer)):
    limit = max(1, min(200, limit))
    if loop_id == "phase-autopilot":
        return {"loop_id": loop_id, "events": await _phase_log(limit) or [],
                "evidence_grade": "TEMP_OBSERVATION",
                "note": "Redis 日志为临时观测源,证据不完整;正式链路见 §7.3"}
    if loop_id == "c3s-autopilot":
        pool = await ds.pg_main()
        try:
            async with pool.acquire() as con:
                rows = [dict(r) for r in await con.fetch(
                    "SELECT * FROM c3s_autopilot_cycle ORDER BY id DESC LIMIT $1", limit)]
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, "isoformat"):
                        r[k] = str(v)
            return {"loop_id": loop_id, "events": rows, "evidence_grade": "AUDIT_TABLE"}
        except Exception as e:  # noqa: BLE001
            return {"loop_id": loop_id, "events": [], "error": str(e)[:120]}
    if loop_id == "c6-calendar-probe":
        try:
            dpool = await ds.pg()
            async with dpool.acquire() as con:
                rows = [dict(r) for r in await con.fetch(
                    "SELECT ts, venue, coin, sym_near, sym_far, days_between, ann_spread_bps "
                    "FROM c6_calendar_samples ORDER BY ts DESC, abs(ann_spread_bps) DESC LIMIT $1", limit)]
            for r in rows:
                r["ts"] = str(r["ts"])
                for k in ("days_between", "ann_spread_bps"):
                    r[k] = float(r[k])
            return {"loop_id": loop_id, "events": rows, "evidence_grade": "AUDIT_TABLE"}
        except Exception as e:  # noqa: BLE001
            return {"loop_id": loop_id, "events": [], "error": str(e)[:120]}
    return {"loop_id": loop_id, "events": [],
            "note": "该回路暂无 C 侧可读时间线源(B 侧 outbox 事实流为 R2 后续)"}
