"""V6.2 N4 训练模式(§八):新操作员用生产同款页面+回放数据完成六课目,
通过后才获得新增风险类命令权限;减险类命令永远不受训练门禁约束。

- training_certification{operator, version, scope, passed_at}:带版本与范围,非永久布尔;
- 现有操作员由 seed 预发认证(祖父条款)——门禁只拦"未来的新人",不锁现役;
- 课目判定=确定性状态机(动作序列匹配),不用 LLM;
- 训练快照=合成场景,整站横幅由前端按 /training/session 状态渲染;
- 训练命令走本路由,不经 /operator/commands,零生产影响。
"""
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from ..deps import require_viewer, _resolve, _jwt_decode
from .. import datasources as ds

log = logging.getLogger("mix.training")
router = APIRouter(tags=["v6-training"])

CERT_VERSION = "v6.2-1"
CERT_SCOPE = "RISK_ADDING"   # 认证解锁范围:新增风险类命令

_DDL = """CREATE TABLE IF NOT EXISTS training_certification (
    operator TEXT NOT NULL,
    version TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'RISK_ADDING',
    passed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (operator, version, scope));
CREATE TABLE IF NOT EXISTS training_session (
    id BIGSERIAL PRIMARY KEY,
    operator TEXT NOT NULL,
    course TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'IN_PROGRESS'
        CHECK (state IN ('IN_PROGRESS','PASSED','FAILED')),
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ)"""

# ── 六课目(§八):场景快照 + 期望动作序列(状态机判定) ─────────────────────
COURSES = {
    "巡检": {
        "title": "状态巡检", "order": 1,
        "brief": "看懂状态条与流程条:确认当前允许操作、找到最高优先级任务",
        "scenario": {"top_alert": None, "counts": {"candidates": 2, "holding": 1, "abnormal": 0}},
        "expect": ["ack_status"],
        "expect_cn": ["点击『我已确认系统状态』"],
    },
    "候选审批": {
        "title": "候选审批", "order": 2,
        "brief": "把一个正期望候选送入工作台(试算不下单),理解 DRY_RUN→冷却→二次认证链",
        "scenario": {"candidate": {"symbol": "DEMOUSDT", "ev": 18.4, "route": "bybit↔binance"}},
        "expect": ["send_to_workbench"],
        "expect_cn": ["对 DEMOUSDT 点『送入工作台』"],
    },
    "补对冲": {
        "title": "部分成交补对冲", "order": 3,
        "brief": "识别单腿风险:已卖出800/对冲600,立即补齐200",
        "scenario": {"position": {"symbol": "DEMOUSDT", "sold": 800, "hedged": 600}},
        "expect": ["complete_hedge"],
        "expect_cn": ["点『完成对冲』补齐缺口200"],
    },
    "买回还币": {
        "title": "买回还币", "order": 4,
        "brief": "C3.S 退出序:先买回现货,再还币,顺序不可反",
        "scenario": {"position": {"symbol": "DEMOUSDT", "borrowed": 3000, "bought_back": 3000}},
        "expect": ["buy_back", "repay"],
        "expect_cn": ["先点『买回』", "再点『还币』"],
    },
    "平台限制": {
        "title": "平台限制处置", "order": 5,
        "brief": "某平台被限制:确认事件,对该平台冻结新增(减险),不碰存量仓位",
        "scenario": {"incident": {"venue": "demoex", "mode": "NO_NEW_RISK", "title": "提现连败"}},
        "expect": ["ack_incident", "freeze_venue"],
        "expect_cn": ["先点『确认事件』", "再点『冻结该平台新增』"],
    },
    "人工双永续研判": {
        "title": "C2.P 人工双永续研判", "order": 7,
        "brief": "四步研判(阶段/依据/风险/结论)→生成人工计划:研判只产结论,计划走 DRY_RUN 审批链",
        "scenario": {"candidate": {"symbol": "DEMOUSDT", "funding_gap": 0.42,
                                   "route": "bitget(空)↔binance(多)"}},
        "expect": ["open_research", "complete_research", "create_manual_plan"],
        "expect_cn": ["打开研判工作区", "完成四步研判(结论=准备人工计划)", "生成人工计划(DRY_RUN,不下单)"],
    },
    "收工核账": {
        "title": "收工核账", "order": 6,
        "brief": "三问收工:我有多少钱/钱从哪来/账是否对上——确认恒等式通过",
        "scenario": {"ledger": {"identity_ok": True, "unmapped": 0}},
        "expect": ["confirm_recon"],
        "expect_cn": ["点『确认账目核对通过』"],
    },
}


async def _pool():
    p = await ds.pg_main()
    if p is None:
        raise HTTPException(503, "mix_main 不可达")
    await p.execute(_DDL)
    return p


async def require_trainee(
        x_op_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None)) -> dict:
    """训练鉴权:operator 令牌 或 任意 mix 用户 JWT——训练目标人群恰是『还不是
    操作员的新人』,且训练命令走独立路由零生产影响;认证按登录身份签发。"""
    # ⚠前端 http6 把登录令牌(可能是 JWT)统一放 X-Op-Token 头——
    # 该头必须与 require_viewer 的 _resolve_any 同语义:先试 operator 表,再试 JWT 解码。
    # (2026-07-16 事故:此处只走 _resolve 导致用户 JWT 401 弹登录门;
    #  且当时用 Bearer 头自测=与前端真实行为不一致的假阳性验证)
    who = await _resolve(x_op_token) or _jwt_decode(x_op_token)
    if who:
        return who
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    juser = _jwt_decode(bearer)
    if juser:
        return juser
    raise HTTPException(401, "需要登录(操作员令牌或用户账号均可参加训练)")


async def ensure_seed():
    """祖父条款:现役 operators 表全员预发认证——门禁只拦未来的新人,不锁现役。"""
    pool = await ds.pg_main()
    if pool is None:
        return
    await pool.execute(_DDL)
    src = await ds.pg()
    if src is None:
        return
    try:
        for r in await src.fetch("SELECT name FROM operators WHERE enabled"):
            await pool.execute(
                "INSERT INTO training_certification(operator, version, scope, granted_by) "
                "VALUES($1,$2,$3,'seed-grandfather') ON CONFLICT DO NOTHING",
                r["name"], CERT_VERSION, CERT_SCOPE)
    except Exception as e:  # noqa: BLE001
        log.warning("training seed: %s", e)


async def is_certified(operator: str) -> bool:
    """供 /operator/commands 门禁调用:当前版本+RISK_ADDING 范围。"""
    try:
        pool = await ds.pg_main()
        if pool is None:
            return True   # 库不可达 fail-open 于训练门禁(风险闸另有 fail-closed,不叠加锁死)
        row = await pool.fetchrow(
            "SELECT 1 FROM training_certification WHERE operator=$1 AND version=$2 AND scope=$3",
            operator, CERT_VERSION, CERT_SCOPE)
        return bool(row)
    except Exception:  # noqa: BLE001
        return True


@router.get("/training/courses")
async def training_courses(who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT course, state, steps, started_at::text, ended_at::text FROM training_session "
        "WHERE operator=$1 ORDER BY id", who["operator"])
    prog = {}
    for r in rows:
        prog[r["course"]] = {"state": r["state"],
                             "steps": (json.loads(r["steps"]) if isinstance(r["steps"], str) else r["steps"])}
    cert = await is_certified(who["operator"])
    out = []
    for key, c in sorted(COURSES.items(), key=lambda kv: kv[1]["order"]):
        p = prog.get(key) or {}
        out.append({"course": key, "title": c["title"], "order": c["order"], "brief": c["brief"],
                    "expect_cn": c["expect_cn"], "state": p.get("state") or "NOT_STARTED",
                    "steps_done": len(p.get("steps") or [])})
    passed = sum(1 for o in out if o["state"] == "PASSED")
    return {"courses": out, "passed": passed, "total": len(out),
            "certified": cert, "cert_version": CERT_VERSION,
            "note": "全部课目通过自动签发认证;认证只解锁新增风险类命令,减险类永远可用"}


@router.post("/training/{course}/start")
async def training_start(course: str, who=Depends(require_trainee)):
    c = COURSES.get(course)
    if not c:
        raise HTTPException(404, "课目不存在")
    pool = await _pool()
    await pool.execute(
        "UPDATE training_session SET state='FAILED', ended_at=now() "
        "WHERE operator=$1 AND course=$2 AND state='IN_PROGRESS'", who["operator"], course)
    await pool.execute(
        "INSERT INTO training_session(operator, course) VALUES($1,$2)", who["operator"], course)
    return {"started": course, "scenario": c["scenario"], "brief": c["brief"],
            "expect_cn": c["expect_cn"],
            "banner": "训练模式 · 回放数据 · 不产生真实订单"}


@router.post("/training/{course}/action")
async def training_action(course: str, body: dict, who=Depends(require_trainee)):
    """课目动作:确定性状态机判定——动作必须按 expect 顺序;错序=如实提示不判过。"""
    c = COURSES.get(course)
    if not c:
        raise HTTPException(404, "课目不存在")
    act = str(body.get("action") or "")
    pool = await _pool()
    row = await pool.fetchrow(
        "SELECT id, steps FROM training_session WHERE operator=$1 AND course=$2 AND state='IN_PROGRESS' "
        "ORDER BY id DESC LIMIT 1", who["operator"], course)
    if not row:
        raise HTTPException(409, "课目未开始:先点开始训练")
    steps = json.loads(row["steps"]) if isinstance(row["steps"], str) else (row["steps"] or [])
    expect = c["expect"]
    idx = len(steps)
    if idx >= len(expect):
        return {"state": "PASSED", "note": "课目已完成"}
    if act != expect[idx]:
        return {"state": "IN_PROGRESS", "wrong": True,
                "hint": f"顺序不对:下一步应是「{c['expect_cn'][idx]}」(第{idx+1}步)"}
    steps.append(act)
    done = len(steps) >= len(expect)
    await pool.execute(
        "UPDATE training_session SET steps=$2::jsonb, state=$3, ended_at=(CASE WHEN $3='PASSED' THEN now() END) "
        "WHERE id=$1", row["id"], json.dumps(steps), "PASSED" if done else "IN_PROGRESS")
    cert_granted = False
    if done:
        passed = await pool.fetchval(
            "SELECT count(DISTINCT course) FROM training_session WHERE operator=$1 AND state='PASSED'",
            who["operator"])
        if int(passed) >= len(COURSES):
            await pool.execute(
                "INSERT INTO training_certification(operator, version, scope, granted_by) "
                "VALUES($1,$2,$3,'course-completion') ON CONFLICT DO NOTHING",
                who["operator"], CERT_VERSION, CERT_SCOPE)
            cert_granted = True
    return {"state": "PASSED" if done else "IN_PROGRESS",
            "step": idx + 1, "of": len(expect),
            "next": (None if done else c["expect_cn"][len(steps)]),
            "cert_granted": cert_granted,
            "note": ("✓ 课目通过" + (";六课目全部完成,已签发认证,生产新增风险命令已解锁" if cert_granted else "")
                     if done else f"✓ 第{idx+1}步正确")}
