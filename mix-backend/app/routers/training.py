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
    ended_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS training_course_publication (
    course TEXT PRIMARY KEY,
    published BOOLEAN NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_by TEXT NOT NULL DEFAULT '')"""


def _default_published(course: str) -> bool:
    """默认发布态:非 draft 课=默认已发布(现役 6/7 课);draft=True 的新人课默认隐藏。"""
    c = COURSES.get(course) or {}
    return not c.get("draft")


async def _published_set(pool) -> set:
    """当前已发布课目集合=默认发布态,叠加 training_course_publication 显式覆盖。
    现役课无覆盖行→保持默认已发布;新人 draft 课经 publish 端点插行才转已发布。"""
    pub = {k for k in COURSES if _default_published(k)}
    try:
        for r in await pool.fetch("SELECT course, published FROM training_course_publication"):
            if r["course"] not in COURSES:
                continue
            if r["published"]:
                pub.add(r["course"])
            else:
                pub.discard(r["course"])
    except Exception as e:  # noqa: BLE001
        log.warning("training publication read: %s", e)
    return pub

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
    # ── 新人入职轨(DRAFT/草稿:draft=True 默认隐藏,不进操作台课目列表、
    #    不改现役认证阈值;SUPER_ADMIN 经 /training/courses/{course}/publish 逐课激活。
    #    激活前端场景卡为未来步骤,当前隐藏不渲染) ──────────────────────────
    "新人-系统总览": {
        "title": "新人 · 系统总览", "order": 101, "draft": True, "track": "新人入职",
        "brief": "先认识后动手:状态条 / 三面墙(风控·策略·执行) / 今日工作台各看什么",
        "scenario": {"overview": {"walls": ["风控", "策略", "执行"], "workbench": "今日"}},
        "expect": ["ack_overview"],
        "expect_cn": ["确认已读懂系统总览(状态条+三面墙+工作台)"],
    },
    "新人-角色与边界": {
        "title": "新人 · 角色与边界", "order": 102, "draft": True, "track": "新人入职",
        "brief": "VIEWER<OPERATOR<SUPER_ADMIN;减险动作(撤单/减仓/还币/压停)永远可用,新增风险类命令须认证",
        "scenario": {"roles": ["VIEWER", "OPERATOR", "SUPER_ADMIN"],
                     "always_allowed": ["撤单", "减仓", "还币", "压停自动控制"]},
        "expect": ["ack_roles"],
        "expect_cn": ["确认理解角色分级与『减险恒可用 / 增险需认证』边界"],
    },
    "新人-武装纪律": {
        "title": "新人 · 武装纪律(双钥匙)", "order": 103, "draft": True, "track": "新人入职",
        "brief": "真钱自动控制=双钥匙:主控闸(control:enabled)+子闸(resume:authorized);链路=键入命令→Passkey→生成→双钥匙确认;绝不单方武装,须用户盯盘放行",
        "scenario": {"chain": ["键入命令", "Passkey", "生成", "双钥匙确认"],
                     "master_gate": "dcm:v6:automation:control:enabled",
                     "resume_gate": "dcm:v6:automation:resume:authorized"},
        "expect": ["ack_arming_chain"],
        "expect_cn": ["确认理解武装双钥匙链路(命令→Passkey→生成→双钥匙;须盯盘放行)"],
    },
    "新人-应急压停演练": {
        "title": "新人 · 应急压停演练", "order": 104, "draft": True, "track": "新人入职",
        "brief": "压停(pause)属减险、手机可发、无需盯盘;演练一次对自动控制回路执行压停",
        "scenario": {"loop": "phase-autopilot", "risk_class": "REDUCE_RISK", "mobile_allowed": True},
        "expect": ["ack_pause_scene", "do_pause"],
        "expect_cn": ["确认演练场景(自动控制回路需压停)", "执行『压停自动控制』(减险,不需盯盘放行)"],
    },
    "新人-证据分级": {
        "title": "新人 · 证据分级", "order": 105, "draft": True, "track": "新人入职",
        "brief": "事实分级:AUDIT_TABLE(持久事实表)高于 TEMP_OBSERVATION(临时观测);对外汇报按最高可得证据,不夸大",
        "scenario": {"grades": ["AUDIT_TABLE", "TEMP_OBSERVATION"]},
        "expect": ["ack_evidence"],
        "expect_cn": ["确认理解证据分级(AUDIT_TABLE > TEMP_OBSERVATION,按最高可得证据汇报)"],
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
    pub = await _published_set(pool)   # 仅已发布课目进操作台;draft 新人课隐藏
    out = []
    for key, c in sorted(COURSES.items(), key=lambda kv: kv[1]["order"]):
        if key not in pub:
            continue
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
    if course not in await _published_set(pool):
        raise HTTPException(409, "该课目未发布(草稿):需 SUPER_ADMIN 先激活方可练习")
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
        pub = await _published_set(pool)   # 认证阈值=已发布课数(现役=7,不受 draft 新人课影响)
        rows_passed = await pool.fetch(
            "SELECT DISTINCT course FROM training_session WHERE operator=$1 AND state='PASSED'",
            who["operator"])
        passed = sum(1 for r in rows_passed if r["course"] in pub)
        if int(passed) >= len(pub):
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


# ── 课程治理:管理端目录预览 + 逐课发布/下架(SUPER_ADMIN) ───────────────────
from ..deps import require_admin  # noqa: E402


@router.get("/training/courses/catalog")
async def training_catalog(admin=Depends(require_admin)):
    """全量课目目录(含 draft 草稿),供管理端预览与激活;标注默认态/当前发布态/所属轨。
    只读,不影响操作台课目列表。"""
    pool = await _pool()
    pub = await _published_set(pool)
    ov = {}
    try:
        for r in await pool.fetch(
                "SELECT course, published, changed_at::text, changed_by "
                "FROM training_course_publication"):
            ov[r["course"]] = {"published": r["published"],
                               "changed_at": r["changed_at"], "changed_by": r["changed_by"]}
    except Exception as e:  # noqa: BLE001
        log.warning("catalog overrides: %s", e)
    items = []
    for key, c in sorted(COURSES.items(), key=lambda kv: kv[1]["order"]):
        items.append({
            "course": key, "title": c["title"], "order": c["order"],
            "track": c.get("track") or "现役六课", "brief": c["brief"],
            "expect_cn": c["expect_cn"], "steps": len(c["expect"]),
            "is_draft_default": bool(c.get("draft")),
            "default_published": _default_published(key),
            "published": key in pub,
            "override": ov.get(key),
        })
    published_n = sum(1 for it in items if it["published"])
    return {"courses": items, "total": len(items), "published": published_n,
            "cert_threshold": published_n,
            "note": "认证阈值=当前已发布课目数;发布 draft 新人课将同步抬高新操作员的认证门槛,"
                    "现役操作员持祖父认证不受影响。激活前请确认前端已有对应场景卡。"}


@router.post("/training/courses/{course}/publish")
async def training_publish(course: str, body: dict, admin=Depends(require_admin)):
    """逐课发布/下架:写 training_course_publication 覆盖行。发布 draft 新人课=激活;
    下架=移出操作台课目列表。此动作改变新操作员的认证门槛,故需 SUPER_ADMIN。"""
    if course not in COURSES:
        raise HTTPException(404, "课目不存在")
    if "published" not in body:
        raise HTTPException(400, "缺少 published 布尔字段")
    published = bool(body["published"])
    pool = await _pool()
    await pool.execute(
        "INSERT INTO training_course_publication(course, published, changed_by) VALUES($1,$2,$3) "
        "ON CONFLICT (course) DO UPDATE SET published=EXCLUDED.published, "
        "changed_at=now(), changed_by=EXCLUDED.changed_by",
        course, published, admin.get("admin") or admin.get("operator") or "")
    pub = await _published_set(pool)
    return {"course": course, "published": course in pub,
            "published_total": len(pub), "cert_threshold": len(pub),
            "note": ("已激活:该课目进入操作台课目列表,新操作员认证门槛+1"
                     if published else "已下架:该课目移出操作台课目列表")}
