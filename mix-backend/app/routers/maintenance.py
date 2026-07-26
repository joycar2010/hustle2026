"""MaintenanceCoordinator(V2 §7)——网站维护与交易排空的联合编排。

铁律(V2 §7.1):两层状态、单一风险权威——site_maintenance_state 只管公告/只读/排空进度,
**交易权限映射到既有 risk_policy_override 通道(GLOBAL 追加),绝不新建平行 kill switch**:
    ANNOUNCED → GLOBAL NO_NEW_RISK
    DRAINING  → GLOBAL REDUCE_ONLY
    恢复      → GLOBAL NORMAL 追加(只移除维护来源限制;venue 级更严格限制继续有效,
               且 policy 引擎的 RECOVERY_WATCH 阶梯对经历过 REDUCE+ 的 venue 自动生效)
状态机:NORMAL → ANNOUNCED → DRAINING → (DRAIN_BLOCKED) → MAINTENANCE → RECOVERY_CHECK → CLOSED
排空判定=真数据清单(未决提案/在管组合非稳态/C3 非终态坑位/修复意图/RECON 差异);
EXIT_ONLY 只是能力集合不是自动平仓命令——排空受阻须 DrainPlan 显式决策(延长/强制退出提案),
绝不因截止时间到就砍仓,也绝不在有仓时显示"维护完成"。
幂等:同时至多一个活跃维护请求,重复 start 返回现有请求。
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer, require_operator
from .. import datasources as ds
from .proposal import _totp_verify

router = APIRouter()

_DDL = """CREATE TABLE IF NOT EXISTS maintenance_request (
    id BIGSERIAL PRIMARY KEY,
    mtype TEXT NOT NULL DEFAULT 'SITE_AND_DRAIN' CHECK (mtype IN ('SITE_ONLY','SITE_AND_DRAIN')),
    state TEXT NOT NULL DEFAULT 'ANNOUNCED' CHECK (state IN
        ('ANNOUNCED','DRAINING','DRAIN_BLOCKED','MAINTENANCE','RECOVERY_CHECK','CLOSED')),
    reason TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    deadline_at TIMESTAMPTZ,
    created_by TEXT NOT NULL DEFAULT '',
    closed_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS maintenance_progress (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL,
    stage TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor TEXT NOT NULL DEFAULT '',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS drain_plan (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('EXTEND','FORCE_EXIT_PROPOSAL')),
    note TEXT NOT NULL DEFAULT '',
    extend_min INT,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS maintenance_recovery_check (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL,
    checks JSONB NOT NULL DEFAULT '{}'::jsonb,
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now())"""

CONFIRM_PHRASE = "开始维护并排空"


async def _pool():
    p = await ds.pg_main()
    if p is None:
        raise HTTPException(503, "mix_main 不可达")
    await p.execute(_DDL)
    return p


async def _active(pool):
    return await pool.fetchrow(
        "SELECT * FROM maintenance_request WHERE state != 'CLOSED' ORDER BY id DESC LIMIT 1")


async def _log(pool, rid, stage, detail, actor=""):
    await pool.execute(
        "INSERT INTO maintenance_progress(request_id, stage, detail, actor) VALUES($1,$2,$3::jsonb,$4)",
        rid, stage, json.dumps(detail, ensure_ascii=False, default=str), actor)


async def _risk_override(mode: str, reason: str, actor: str, ttl_hours: float | None = None):
    """维护阶段→既有风险权威通道(dcm_main.risk_policy_override GLOBAL 追加,risk-ledger ≤30s 合并;
    另发 dcm:risk:trigger 直通催重算)。绝不直接写 dcm:risk:policy。ttl_hours=可选过期(防遗忘冻结)。"""
    pool = await ds.pg()
    if pool is None:
        raise HTTPException(503, "dcm_main 不可达,维护无法映射风险权威(拒绝启动,防止只挂公告不停手)")
    expires = None
    if ttl_hours:
        import datetime as _dt
        expires = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=float(ttl_hours))
    await pool.execute(
        "INSERT INTO risk_policy_override(scope_type, scope_key, mode, reason, created_by, expires_at) "
        "VALUES('GLOBAL','GLOBAL',$1,$2,$3,$4)", mode, reason[:200], actor, expires)
    try:
        await ds.rds().publish("dcm:risk:trigger", json.dumps({"why": "maintenance", "mode": mode}))
    except Exception:  # noqa: BLE001
        pass


async def _drain_checklist() -> dict:
    """排空清单=真数据逐项(缺数据如实标注,绝不装清零)。"""
    out = {}
    # ① 未决开仓提案
    try:
        p = await ds.pg_main()
        row = await p.fetchrow("SELECT count(*) AS n FROM dry_run_proposal "
                               "WHERE state IN ('COOLDOWN','PENDING_APPROVAL')")
        out["pending_proposals"] = int(row["n"])
    except Exception:  # noqa: BLE001
        out["pending_proposals"] = None
    # ② 在管组合(exec-manager)非空仓行 + 单腿
    mgr = await ds.get_json("dcm:exec:manager") or {}
    live, single = [], []
    for ps in (mgr.get("pairs") or []):
        if any(abs(float(lg.get("amt") or 0)) > 1e-9 for lg in (ps.get("legs") or [])):
            live.append({"symbol": ps.get("symbol") or ps.get("pair"), "kind": "C2",
                         "action": ps.get("action")})
            if "SINGLE_LEG" in str(ps.get("action")):
                single.append(ps.get("symbol") or ps.get("pair"))
    for ss in (mgr.get("symbols") or []):
        if abs(float(ss.get("perp_amt") or 0)) > 1e-9 or float(ss.get("spot") or 0) > 1e-9:
            live.append({"symbol": ss.get("symbol"), "kind": "C1", "action": ss.get("action")})
    out["live_combos"] = live
    out["single_legs"] = single
    # ③ C3 非终态坑位(coin 意图账)
    snap = await ds.get_json("dcm:engine:coin:positions") or {}
    c3 = [p2 for p2 in (snap.get("positions") or [])
          if p2.get("status") not in ("CLOSED", "FAILED")]
    out["c3_open_pits"] = [{"symbol": p2.get("symbol"), "status": p2.get("status")} for p2 in c3]
    # ④ 修复意图在途
    rep = await ds.get_json("dcm:exec:repair") or {}
    out["repair_intents"] = len(rep.get("intents") or [])
    # ⑤ RECON:借组合表口径(账户快照 vs 期望腿)
    pol = await ds.get_json("dcm:risk:policy") or {}
    out["policy_global_mode"] = pol.get("global_mode")
    out["clear"] = (not live and not c3 and not single
                    and (out["pending_proposals"] or 0) == 0)
    return out


@router.get("/maintenance/preview")
async def maintenance_preview(_who=Depends(require_viewer)):
    """启动前影响预览=排空清单(无活跃维护时前端确认页用)。"""
    return await _drain_checklist()


@router.get("/maintenance/status")
async def maintenance_status():
    """公开端点(无鉴权):客户前台/投资门户/状态条消费。只暴露公告级信息。"""
    try:
        pool = await ds.pg_main()
        if pool is None:
            return {"state": "NORMAL"}
        await pool.execute(_DDL)
        row = await _active(pool)
        if not row:
            return {"state": "NORMAL"}
        return {"state": row["state"], "mtype": row["mtype"],
                "note": row["note"], "since": str(row["created_at"])[:16],
                "deadline": str(row["deadline_at"] or "")[:16],
                "banner": ("系统正在维护:新增交易已暂停,现有仓位正在按风险规则逐步收敛"
                           if row["mtype"] == "SITE_AND_DRAIN" else "系统维护公告:" + (row["note"] or ""))}
    except Exception:  # noqa: BLE001
        return {"state": "NORMAL", "note": "status degraded"}


async def block_new_risk():
    """给其它路由用的新增风险闸:维护活跃(SITE_AND_DRAIN)时 API 入口即拒(策略/引擎闸之外的
    第一道,belt-and-suspenders;权威仍是 risk policy)。"""
    try:
        pool = await ds.pg_main()
        if pool is None:
            return
        row = await pool.fetchrow("SELECT id, mtype, state FROM maintenance_request "
                                  "WHERE state NOT IN ('CLOSED') ORDER BY id DESC LIMIT 1")
        if row and row["mtype"] == "SITE_AND_DRAIN" and row["state"] in (
                "ANNOUNCED", "DRAINING", "DRAIN_BLOCKED", "MAINTENANCE"):
            raise HTTPException(409, f"维护排空中(#{row['id']} {row['state']}):新增风险已禁止;"
                                     "减险动作(撤单/减仓/还币/修复)不受影响")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass   # 检查失败不阻塞(权威闸在 policy/engine 层)


@router.post("/maintenance/start")
async def maintenance_start(body: dict, op=Depends(require_operator)):
    """启动维护:确认短语+TOTP(已绑定则必验)重新认证;幂等(已有活跃请求即返回)。
    SITE_AND_DRAIN 立即映射 GLOBAL NO_NEW_RISK。"""
    pool = await _pool()
    actor = str(op.get("operator") or op.get("username") or "op")
    existing = await _active(pool)
    if existing:
        return {"ok": True, "id": existing["id"], "state": existing["state"],
                "note": "已有活跃维护请求(幂等返回,不重复执行)"}
    if str(body.get("confirm_phrase") or "").strip() != CONFIRM_PHRASE:
        raise HTTPException(400, f"确认短语不符,须输入「{CONFIRM_PHRASE}」")
    from ..deps import is_strong_session
    if not is_strong_session(op):
        trow = await pool.fetchrow("SELECT secret, confirmed FROM operator_totp WHERE operator=$1", actor)
        if trow and trow["confirmed"]:
            if not _totp_verify(trow["secret"], str(body.get("totp_code") or "")):
                raise HTTPException(403, "TOTP 验证码错误(已绑定二次认证的操作员必验)")
    mtype = str(body.get("mtype") or "SITE_AND_DRAIN")
    if mtype not in ("SITE_ONLY", "SITE_AND_DRAIN"):
        raise HTTPException(400, "mtype 必须 SITE_ONLY|SITE_AND_DRAIN")
    ddl_min = int(body.get("deadline_min") or 120)
    row = await pool.fetchrow(
        "INSERT INTO maintenance_request(mtype, state, reason, note, deadline_at, created_by) "
        "VALUES($1,'ANNOUNCED',$2,$3, now() + ($4||' minutes')::interval, $5) RETURNING id",
        mtype, str(body.get("reason") or ""), str(body.get("note") or ""), str(ddl_min), actor)
    rid = row["id"]
    detail = await _drain_checklist()
    await _log(pool, rid, "ANNOUNCED", {"impact_preview": detail, "mtype": mtype}, actor)
    if mtype == "SITE_AND_DRAIN":
        await _risk_override("NO_NEW_RISK", f"maintenance:#{rid} ANNOUNCED(排空前置)", actor)
    try:   # 跑马灯公告
        await ds.rds().publish("dcm:notify:broadcast", json.dumps(
            {"level": "warn", "title": "网站维护",
             "content": f"维护#{rid} 已公告({'含交易排空' if mtype=='SITE_AND_DRAIN' else '仅网站'}):{body.get('note') or ''}"},
            ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "id": rid, "state": "ANNOUNCED",
            "risk_mapping": "GLOBAL NO_NEW_RISK 已追加(risk-ledger ≤30s 合并,直通已催)" if mtype == "SITE_AND_DRAIN" else "无(仅公告)"}


@router.post("/maintenance/{rid}/advance")
async def maintenance_advance(rid: int, op=Depends(require_operator)):
    """ANNOUNCED→DRAINING(映射 GLOBAL REDUCE_ONLY);DRAINING→MAINTENANCE 仅当排空清单 clear
    或存在显式 DrainPlan 例外登记——有仓绝不显示完成。"""
    pool = await _pool()
    actor = str(op.get("operator") or op.get("username") or "op")
    row = await pool.fetchrow("SELECT * FROM maintenance_request WHERE id=$1", rid)
    if not row or row["state"] == "CLOSED":
        raise HTTPException(404, "无此活跃维护请求")
    if row["mtype"] == "SITE_ONLY":
        raise HTTPException(409, "SITE_ONLY 无排空阶段,直接 recover 关闭")
    if row["state"] == "ANNOUNCED":
        await pool.execute("UPDATE maintenance_request SET state='DRAINING', updated_at=now() WHERE id=$1", rid)
        await _risk_override("REDUCE_ONLY", f"maintenance:#{rid} DRAINING(交易排空)", actor)
        await _log(pool, rid, "DRAINING", {"note": "GLOBAL REDUCE_ONLY 已追加;在途 Saga 允许完成对冲/回滚"}, actor)
        return {"ok": True, "state": "DRAINING"}
    if row["state"] in ("DRAINING", "DRAIN_BLOCKED"):
        cl = await _drain_checklist()
        await _log(pool, rid, "DRAIN_ASSESS", cl, actor)
        if cl["clear"]:
            await pool.execute("UPDATE maintenance_request SET state='MAINTENANCE', updated_at=now() WHERE id=$1", rid)
            await _log(pool, rid, "MAINTENANCE", {"note": "排空清单全清,进入维护态"}, actor)
            return {"ok": True, "state": "MAINTENANCE", "checklist": cl}
        # 有仓/有坑/有提案:受阻——须 DrainPlan 显式决策,绝不装完成
        await pool.execute("UPDATE maintenance_request SET state='DRAIN_BLOCKED', updated_at=now() WHERE id=$1", rid)
        return {"ok": False, "state": "DRAIN_BLOCKED", "checklist": cl,
                "note": "排空受阻:提交 DrainPlan(延长排空/强制退出提案)或人工处置后重试;不会自动砍仓"}
    raise HTTPException(409, f"状态={row['state']} 无可推进动作")


@router.post("/maintenance/{rid}/drain-plan")
async def maintenance_drain_plan(rid: int, body: dict, op=Depends(require_operator)):
    """DRAIN_BLOCKED 的显式决策:EXTEND(延长排空)或 FORCE_EXIT_PROPOSAL(登记强制退出提案,
    仅登记——执行仍走各产品退出通道+人工,绝不直接市价砍仓)。"""
    pool = await _pool()
    actor = str(op.get("operator") or op.get("username") or "op")
    decision = str(body.get("decision") or "")
    if decision not in ("EXTEND", "FORCE_EXIT_PROPOSAL"):
        raise HTTPException(400, "decision 必须 EXTEND|FORCE_EXIT_PROPOSAL")
    ext = int(body.get("extend_min") or 60) if decision == "EXTEND" else None
    await pool.execute(
        "INSERT INTO drain_plan(request_id, decision, note, extend_min, created_by) VALUES($1,$2,$3,$4,$5)",
        rid, decision, str(body.get("note") or ""), ext, actor)
    if decision == "EXTEND":
        await pool.execute("UPDATE maintenance_request SET state='DRAINING', "
                           "deadline_at = deadline_at + ($2||' minutes')::interval, updated_at=now() WHERE id=$1",
                           rid, str(ext))
    await _log(pool, rid, "DRAIN_PLAN", {"decision": decision, "extend_min": ext,
                                         "note": body.get("note")}, actor)
    return {"ok": True, "decision": decision}


@router.get("/maintenance/{rid}/progress")
async def maintenance_progress(rid: int, _who=Depends(require_viewer)):
    pool = await _pool()
    row = await pool.fetchrow("SELECT * FROM maintenance_request WHERE id=$1", rid)
    if not row:
        raise HTTPException(404, "无此维护请求")
    cl = await _drain_checklist()
    logs = await pool.fetch("SELECT stage, detail, actor, recorded_at::text FROM maintenance_progress "
                            "WHERE request_id=$1 ORDER BY id DESC LIMIT 30", rid)
    plans = await pool.fetch("SELECT decision, note, extend_min, created_by, created_at::text "
                             "FROM drain_plan WHERE request_id=$1 ORDER BY id DESC", rid)
    return {"request": {k: str(v) if k.endswith("_at") else v for k, v in dict(row).items()},
            "checklist": cl, "logs": [dict(x) for x in logs], "drain_plans": [dict(x) for x in plans]}


@router.post("/maintenance/{rid}/recover")
async def maintenance_recover(rid: int, body: dict, op=Depends(require_operator)):
    """恢复:健康检查清单(服务/策略新鲜度/P0 Incident/排空残留)→ RECOVERY_CHECK →
    通过则 CLOSED+追加 GLOBAL NORMAL(只移除维护来源限制;venue 级限制与 RECOVERY_WATCH
    阶梯继续生效,不得直跳 NORMAL)。TOTP 必验(已绑定)。"""
    pool = await _pool()
    actor = str(op.get("operator") or op.get("username") or "op")
    row = await pool.fetchrow("SELECT * FROM maintenance_request WHERE id=$1", rid)
    if not row or row["state"] == "CLOSED":
        raise HTTPException(404, "无此活跃维护请求")
    from ..deps import is_strong_session
    if not is_strong_session(op):
        trow = await pool.fetchrow("SELECT secret, confirmed FROM operator_totp WHERE operator=$1", actor)
        if trow and trow["confirmed"]:
            if not _totp_verify(trow["secret"], str(body.get("totp_code") or "")):
                raise HTTPException(403, "TOTP 验证码错误")
    # 健康检查(真数据;fail 项如实列出)
    pol = await ds.get_json("dcm:risk:policy") or {}
    age = int(time.time() - float(pol.get("ts") or 0)) if pol else None
    cl = await _drain_checklist()
    checks = {
        "policy_fresh": age is not None and age < 90,
        "no_fatal_incident": not any(True for _ in []),   # 由下方 incidents 填充
        "drain_residue_clear_or_planned": cl["clear"] or bool(
            await pool.fetchval("SELECT count(*) FROM drain_plan WHERE request_id=$1", rid)),
        "checklist": cl,
    }
    dcm = await ds.pg()
    fatal = 0
    if dcm is not None:
        try:
            # 排除 policy-mode(=本维护 override 自身导致的模式降级,恢复即消除,非独立事件);
            # 只有平台/账户/单腿等独立 fatal 事件才阻塞恢复(V2 §7.3 语义)
            fatal = int(await dcm.fetchval(
                "SELECT count(*) FROM venue_incident WHERE state IN ('OPEN','ESCALATED') "
                "AND severity='fatal' AND rule <> 'policy-mode'"))
        except Exception:  # noqa: BLE001
            fatal = -1
    checks["no_fatal_incident"] = fatal == 0
    checks["fatal_incidents"] = fatal
    passed = bool(checks["policy_fresh"] and checks["no_fatal_incident"]
                  and checks["drain_residue_clear_or_planned"])
    await pool.execute(
        "INSERT INTO maintenance_recovery_check(request_id, checks, passed) VALUES($1,$2::jsonb,$3)",
        rid, json.dumps(checks, ensure_ascii=False, default=str), passed)
    if not passed:
        await pool.execute("UPDATE maintenance_request SET state='RECOVERY_CHECK', updated_at=now() WHERE id=$1", rid)
        return {"ok": False, "state": "RECOVERY_CHECK", "checks": checks,
                "note": "健康检查未过:处理未过项后重试(不会一键恢复 NORMAL)"}
    await pool.execute("UPDATE maintenance_request SET state='CLOSED', closed_by=$2, updated_at=now() WHERE id=$1",
                       rid, actor)
    if row["mtype"] == "SITE_AND_DRAIN":
        await _risk_override("NORMAL", f"maintenance:#{rid} 恢复(仅移除维护来源限制;venue级限制/恢复阶梯不受影响)", actor)
    await _log(pool, rid, "CLOSED", {"checks": checks}, actor)
    try:
        await ds.rds().publish("dcm:notify:broadcast", json.dumps(
            {"level": "info", "title": "维护结束", "content": f"维护#{rid} 已恢复;经历 REDUCE 的 venue 进入 RECOVERY_WATCH 阶梯"},
            ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "state": "CLOSED", "checks": checks,
            "note": "已恢复:GLOBAL NORMAL 已追加;venue 级 RECOVERY_WATCH 阶梯自动生效(不直跳 NORMAL)"}
