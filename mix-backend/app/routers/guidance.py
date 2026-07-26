"""V6.2 R3+ 操作引导技术契约(§5/§8)——GuidanceCue 投影 + 内容注册表 + 进度/事件审计。

四表(§16):guidance_template / strategy_playbook(见 playbooks.py 表化) /
          operator_guidance_progress / operator_guidance_event。
铁律:
- Cue 是**展示投影**,不是第二工作流权威;事实来自 control_snapshot/drift/automation。
- 文案=版本化模板随 git 发布(ensure_seed 幂等,copy_version 升版才覆盖);不接 CMS/LLM 实时改。
- 去疲劳服务端强制(§5.2):同 cue_id 只 auto_expand 一次(SHOWN 事件判定);
  页面同时最多 1 个 auto_expand;新状态(state_sig 变)才生成新 cue_id 重新提示;
  风险级(L3+)可确认不可永久关闭——ack 只压当前 cue_id,状态变化自然复活。
- primary_action_ref 只允许深链 route(mix/ 前缀),引导层不拼订单参数。
"""
import hashlib
import json
import logging
import time

from fastapi import APIRouter, Body, Depends, HTTPException

from ..deps import require_viewer
from .. import datasources as ds

log = logging.getLogger("mix.guidance")
router = APIRouter(tags=["v6-guidance"])

_DDL = """
CREATE TABLE IF NOT EXISTS guidance_template(
  template_id text PRIMARY KEY,
  scope_type text NOT NULL,
  severity text NOT NULL,
  surface text NOT NULL,
  title text NOT NULL,
  plain_summary text,
  why_now text,
  operator_action_text text,
  completion_text text,
  primary_action_ref text,
  copy_version int NOT NULL DEFAULT 1,
  curriculum_version int NOT NULL DEFAULT 1,
  enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS operator_guidance_progress(
  operator_id text NOT NULL,
  scope text NOT NULL,
  curriculum_version int NOT NULL,
  completed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(operator_id, scope, curriculum_version)
);
CREATE TABLE IF NOT EXISTS operator_guidance_event(
  id bigserial PRIMARY KEY,
  operator_id text NOT NULL,
  cue_id text NOT NULL,
  template_id text,
  scope_type text,
  scope_id text,
  action text NOT NULL,
  severity text,
  copy_version int,
  generation bigint,
  snooze_until timestamptz,
  device text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_oge_op_cue ON operator_guidance_event(operator_id, cue_id, action);
"""

# 文案注册表种子(§5.3 风格;改文案=升 copy_version+部署,可审计)
_TEMPLATES = [
    ("TODAY_TOUR", "TRAINING", "L1", "COACH_MARK", "今日工作首次引导",
     "带你认识一遍今日工作页:状态条、流程条、工作列表和抽屉。",
     "你是第一次进入(或流程有重大版本变化)。",
     "跟着聚光框走完 4 步即可。", "走完全部步骤。", "mix/today", 1, 1),
    ("WORKITEM_P0", "WORK_ITEM", "L3", "FLOATING_RAIL", "需要处理:{symbol} {stage}",
     "{what}", "P0/异常事项不处理会持续累积风险。",
     "{next_action}", "{completion}", "mix/today", 1, 1),
    ("PENDING_APPROVAL", "WORK_ITEM", "L1", "FLOATING_RAIL", "有 {n} 项等待你的审批/研判",
     "机会或计划已通过系统闸,停在等待人工确认。",
     "不确认不会有任何自动动作;超时会自动过期。",
     "逐项打开确认或拒绝。", "队列清零。", "mix/today", 1, 1),
    ("RELEASE_DRIFT_P0", "INCIDENT", "L3", "FLOATING_RAIL", "发布漂移:生产代码偏离基线",
     "关键后端文件与 release 基线不一致(P0 级 {n} 处)。",
     "漂移的代码=灾备不可重建+行为不可解释。",
     "确认是否有人直改服务器;正当热修则回灌 git 并刷新基线。",
     "漂移检查回到 CLEAN。", "mix/today", 1, 1),
    ("AUTOPILOT_STALE", "AUTOMATION", "L2", "FLOATING_RAIL", "相位自动环 ARMED 但近 3 小时无留痕",
     "自动回路声称武装,但观测源近 3 小时没有任何轮次记录。",
     "正常无动作和服务故障必须区分——现在无法证明它活着。",
     "打开自动回路详情核对 timer 与日志;必要时上 B 机查 unit。",
     "出现新轮次留痕或确认为计划内停机。", "mix/today", 1, 1),
]

_seeded = False


async def _ensure(pool):
    global _seeded
    if _seeded:
        return
    async with pool.acquire() as con:
        await con.execute(_DDL)
        for t in _TEMPLATES:
            # copy_version 升版才覆盖旧文案(同版不动,允许 DB 端 enabled 开关持久生效)
            await con.execute(
                """INSERT INTO guidance_template(template_id,scope_type,severity,surface,title,
                     plain_summary,why_now,operator_action_text,completion_text,primary_action_ref,
                     copy_version,curriculum_version)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   ON CONFLICT (template_id) DO UPDATE SET
                     scope_type=EXCLUDED.scope_type, severity=EXCLUDED.severity,
                     surface=EXCLUDED.surface, title=EXCLUDED.title,
                     plain_summary=EXCLUDED.plain_summary, why_now=EXCLUDED.why_now,
                     operator_action_text=EXCLUDED.operator_action_text,
                     completion_text=EXCLUDED.completion_text,
                     primary_action_ref=EXCLUDED.primary_action_ref,
                     copy_version=EXCLUDED.copy_version,
                     curriculum_version=EXCLUDED.curriculum_version, updated_at=now()
                   WHERE guidance_template.copy_version < EXCLUDED.copy_version
                      OR guidance_template.curriculum_version < EXCLUDED.curriculum_version""",
                *t)
    _seeded = True


def _sig(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _fill(text: str, ctx: dict) -> str:
    out = text or ""
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v if v is not None else "—"))
    return out


async def _compose_cues(pool) -> list[dict]:
    """从既有事实源组装候选 cue(零新权威):control_snapshot + drift + automation 观测。"""
    cues = []
    tmap = {}
    async with pool.acquire() as con:
        for r in await con.fetch("SELECT * FROM guidance_template WHERE enabled"):
            tmap[r["template_id"]] = dict(r)

    snap = None
    r = ds.rds()
    if r is not None:
        try:
            raw = await r.get("mix:v6:control_snapshot")
            snap = json.loads(raw) if raw else None
        except Exception:
            snap = None
    gen = (snap or {}).get("generation") or 0
    items = (snap or {}).get("work_items") or []

    def mk(tid, scope_id, ctx, state_sig, deadline=None):
        t = tmap.get(tid)
        if not t:
            return
        cue_id = f"{tid}:{scope_id}:cv{t['copy_version']}:{state_sig}"
        cues.append({
            "cue_id": cue_id, "template_id": tid, "scope_type": t["scope_type"],
            "scope_id": scope_id, "severity": t["severity"], "surface": t["surface"],
            "title": _fill(t["title"], ctx), "plain_summary": _fill(t["plain_summary"], ctx),
            "why_now": _fill(t["why_now"], ctx),
            "operator_action_text": _fill(t["operator_action_text"], ctx),
            "completion_text": _fill(t["completion_text"], ctx),
            "primary_action_ref": t["primary_action_ref"],
            "copy_version": t["copy_version"], "generation": gen,
            "deadline": deadline,
        })

    # 1) 工作项 P0/异常(最多 1 条,取最重)
    p0 = next((w for w in items if (w.get("severity") == "P0"
                or w.get("workflow_stage") == "ABNORMAL" or w.get("blocking_reason"))), None)
    if p0:
        mk("WORKITEM_P0", p0.get("work_item_id") or p0.get("symbol") or "wi",
           {"symbol": p0.get("symbol"), "stage": p0.get("stage_detail") or p0.get("workflow_stage"),
            "what": p0.get("what_happened"), "next_action": p0.get("next_action"),
            "completion": p0.get("completion_condition")},
           _sig(p0.get("work_item_id"), p0.get("workflow_stage"), p0.get("stage_detail")),
           p0.get("next_deadline"))

    # 2) 待审批/待研判聚合(L1)
    n_pend = sum(1 for w in items if w.get("workflow_stage") == "PENDING_APPROVAL"
                 or w.get("research_status") == "PENDING")
    if n_pend:
        mk("PENDING_APPROVAL", "queue", {"n": n_pend}, _sig("pend", n_pend))

    # 3) 发布漂移 P0
    try:
        with open("/data/mix/release/drift_status.json") as f:
            d = json.load(f)
        if d and not d.get("clean") and (d.get("counts") or {}).get("P0"):
            mk("RELEASE_DRIFT_P0", "release", {"n": d["counts"]["P0"]},
               _sig("drift", d.get("checked_at"), d["counts"]["P0"]))
    except Exception:
        pass

    # 4) 相位环 ARMED 但观测停更
    if r is not None:
        try:
            armed = await r.get("dcm:phase:auto:armed")
            if str(armed) == "1":
                raw = await r.lrange("dcm:phase:auto:log", 0, 0)
                stale = True
                if raw:
                    e = json.loads(raw[0])
                    ts = e.get("ts") or 0
                    stale = (time.time() - float(ts)) > 3 * 3600
                if stale:
                    mk("AUTOPILOT_STALE", "phase-autopilot", {},
                       _sig("apstale", int(time.time() // (3 * 3600))))
        except Exception:
            pass
    return cues


_SEV_RANK = {"L4": 4, "L3": 3, "L2": 2, "L1": 1, "L0": 0}


@router.get("/guidance/active")
async def guidance_active(who=Depends(require_viewer)):
    """当前 cue 列表(服务端去疲劳):auto_expand 至多 1 条且同 cue_id 一生只 auto 一次。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可用")
    await _ensure(pool)
    op = str(who.get("operator") or "op")
    cues = await _compose_cues(pool)
    if not cues:
        return {"cues": [], "as_of": int(time.time())}
    ids = [c["cue_id"] for c in cues]
    async with pool.acquire() as con:
        ev = await con.fetch(
            """SELECT cue_id, action, snooze_until FROM operator_guidance_event
               WHERE operator_id=$1 AND cue_id = ANY($2::text[])""", op, ids)
    acked = {e["cue_id"] for e in ev if e["action"] == "ACK"}
    shown = {e["cue_id"] for e in ev if e["action"] == "SHOWN"}
    now = time.time()
    snoozed = {e["cue_id"] for e in ev if e["action"] == "SNOOZE" and e["snooze_until"]
               and e["snooze_until"].timestamp() > now}
    vis = [c for c in cues if c["cue_id"] not in acked and c["cue_id"] not in snoozed]
    vis.sort(key=lambda c: -_SEV_RANK.get(c["severity"], 0))
    auto_done = False
    for c in vis:
        c["auto_expand"] = False
        if (not auto_done and c["cue_id"] not in shown
                and _SEV_RANK.get(c["severity"], 0) >= 2):
            c["auto_expand"] = True
            auto_done = True
    # 首次交付记 SHOWN(auto_expand 判定依据;非 auto 的不记,滚动可见不算打扰)
    new_shown = [c for c in vis if c["auto_expand"]]
    if new_shown:
        async with pool.acquire() as con:
            for c in new_shown:
                await con.execute(
                    """INSERT INTO operator_guidance_event(operator_id,cue_id,template_id,scope_type,
                         scope_id,action,severity,copy_version,generation)
                       VALUES($1,$2,$3,$4,$5,'SHOWN',$6,$7,$8)""",
                    op, c["cue_id"], c["template_id"], c["scope_type"], c["scope_id"],
                    c["severity"], c["copy_version"], c["generation"])
    return {"cues": vis, "suppressed_ack": len(acked), "as_of": int(time.time())}


@router.post("/guidance/{cue_id}/ack")
async def guidance_ack(cue_id: str, body: dict = Body(default={}), who=Depends(require_viewer)):
    pool = await ds.pg_main()
    await _ensure(pool)
    op = str(who.get("operator") or "op")
    async with pool.acquire() as con:
        await con.execute(
            "INSERT INTO operator_guidance_event(operator_id,cue_id,action,device) "
            "VALUES($1,$2,'ACK',$3)", op, cue_id, str(body.get("device") or ""))
    return {"ok": True, "note": "风险级 cue 状态变化后会以新 cue_id 复活,不存在永久关闭"}


@router.post("/guidance/{cue_id}/snooze")
async def guidance_snooze(cue_id: str, body: dict = Body(default={}), who=Depends(require_viewer)):
    minutes = max(5, min(24 * 60, int(body.get("minutes") or 60)))
    pool = await ds.pg_main()
    await _ensure(pool)
    op = str(who.get("operator") or "op")
    async with pool.acquire() as con:
        await con.execute(
            "INSERT INTO operator_guidance_event(operator_id,cue_id,action,snooze_until,device) "
            "VALUES($1,$2,'SNOOZE', now() + ($3||' minutes')::interval, $4)",
            op, cue_id, str(minutes), str(body.get("device") or ""))
    return {"ok": True, "snoozed_minutes": minutes}


@router.get("/guidance/progress")
async def guidance_progress(who=Depends(require_viewer)):
    pool = await ds.pg_main()
    await _ensure(pool)
    op = str(who.get("operator") or "op")
    async with pool.acquire() as con:
        rows = [dict(r) for r in await con.fetch(
            "SELECT scope, curriculum_version, completed_at FROM operator_guidance_progress "
            "WHERE operator_id=$1", op)]
        cur = {r["template_id"]: r["curriculum_version"] for r in await con.fetch(
            "SELECT template_id, curriculum_version FROM guidance_template WHERE surface='COACH_MARK' AND enabled")}
    for r in rows:
        r["completed_at"] = str(r["completed_at"])
    return {"operator": op, "completed": rows, "curricula": cur}


@router.post("/guidance/progress/complete")
async def guidance_progress_complete(body: dict = Body(...), who=Depends(require_viewer)):
    scope = str(body.get("scope") or "")
    ver = int(body.get("curriculum_version") or 1)
    if not scope:
        raise HTTPException(400, "scope 必填")
    pool = await ds.pg_main()
    await _ensure(pool)
    op = str(who.get("operator") or "op")
    async with pool.acquire() as con:
        await con.execute(
            """INSERT INTO operator_guidance_progress(operator_id,scope,curriculum_version)
               VALUES($1,$2,$3) ON CONFLICT DO NOTHING""", op, scope, ver)
        await con.execute(
            "INSERT INTO operator_guidance_event(operator_id,cue_id,action) VALUES($1,$2,'COMPLETE')",
            op, f"{scope}:v{ver}")
    return {"ok": True}
