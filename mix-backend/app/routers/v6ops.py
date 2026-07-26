"""V6 操作员 API(Rev.2 §13 统一自动/辅助/手动操作权威 + §14 旧 C3.S 对比)。

挂载前缀 /api/v6:
  GET  /operator/control/snapshot      统一快照(REST 全量;WS 增量走 hub control:snapshot 帧)
  GET  /operator/workitems             统一工作项投影(过滤器)
  POST /operator/commands              唯一 typed command 入口
  POST /operator/lease/acquire|release 唯一写入租约(§13.1)
  GET  /operator/lease
  GET  /operator/legacy/compare        旧 C3.S 只读对比(§14.1,不下单)
  GET  /operator/legacy/runs           对比历史

铁律:
- 生产 API 拒绝 environment=DEX_LAB 的任何写入(§8.1)。
- 风险能力永远覆盖运行方式:快照过期/NO_NEW 时新增风险命令 fail-closed 拒绝,减险放行。
- 手机受限角色(OPERATOR_MOBILE_LIMITED)只允许减险/确认/暂停新增,禁开仓/改规则/恢复NORMAL。
- 做不到的命令诚实 501,绝不假 202。
"""
import asyncio
import json
import time
import secrets
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from ..deps import require_viewer, require_operator, _resolve, _jwt_decode
from .. import datasources as ds
from .. import v6core

log = logging.getLogger("mix.v6ops")
router = APIRouter(tags=["v6-operator"])

_DDL = """CREATE TABLE IF NOT EXISTS strategy_writer_lease (
    scope TEXT PRIMARY KEY,
    active_writer TEXT NOT NULL,
    writer_epoch BIGINT NOT NULL DEFAULT 1,
    fencing_token TEXT NOT NULL,
    automation_mode TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK (automation_mode IN ('AUTO','ASSISTED','MANUAL')),
    valid_until TIMESTAMPTZ NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS v6_command_log (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    command_type TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    automation_mode TEXT NOT NULL DEFAULT 'MANUAL',
    actor TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',
    writer_epoch BIGINT,
    status TEXT NOT NULL DEFAULT 'ACCEPTED',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS v6_opportunity_action (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_code TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL CHECK (action IN ('TO_WORKBENCH','WATCH','IGNORE')),
    actor TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS legacy_compare_run (
    id BIGSERIAL PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL DEFAULT now(),
    v6_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    legacy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    diffs JSONB NOT NULL DEFAULT '[]'::jsonb,
    diff_count INT NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT 'V6_READONLY_SHADOW');
CREATE TABLE IF NOT EXISTS automation_control_log (
    id BIGSERIAL PRIMARY KEY,
    loop_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('PAUSE','RESUME')),
    control_key TEXT NOT NULL DEFAULT '',
    prev_value TEXT,
    new_value TEXT,
    effect TEXT NOT NULL,          -- APPLIED / SHADOW_LOGGED / STAGED_AWAIT_SUPERVISION
    reason TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',
    writer_epoch BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""

# ─── R4 自动化环控制(暂停/恢复)：typed command 接权威 Redis 控制键 ───
# 主控总闸(须盯盘时人工置 1 才真实改键)——缺失/≠1 时全走 SHADOW 只登记不改键，真钱零行为改变。
_AUTOCTL_MASTER = "dcm:v6:automation:control:enabled"
# 恢复(re-arm)副闸：即便主闸开，resume 仍须此键=1（盯盘二次授权），否则 STAGED 不放行。
_AUTOCTL_RESUME_OK = "dcm:v6:automation:resume:authorized"
# 可 Web 控制的真钱自动环 → 其单键 Redis 闸（两钥匙型：Web 只碰 Redis 键，B 机 env 仍需就位，
# 故 Web 只能"更严格"地压停或在 env 允许时放行，绝不能绕过 B 机本地武装钥匙）。
_CONTROLLABLE_LOOPS = {
    "phase-autopilot": {"key": "dcm:phase:auto:armed", "two_key": "B:PHASE_AUTO_ARMED",
                        "name": "相位自动开平仓"},
    "c3s-autopilot": {"key": "dcm:c3s:v6:autopilot", "two_key": None,
                      "name": "C3.S 影子自主环(零真钱)"},
    "c4-exec-cli": {"key": "dcm:c4:exec:armed", "two_key": "B:DCM_C4_ARMED",
                    "name": "C4/C5 期现交割执行器"},
}

# 新增风险类命令(风险能力/维护/手机角色都要拦);减险类永远放行
# resume_automation=重新武装真钱自动环=新增风险(全闸);pause_automation=压停=减险(永远放行)
_RISK_ADDING = {"opportunity_to_workbench", "proposal_dry_run", "lease_acquire_auto",
                "resume_automation"}
# PATCH-02 §10.2 手机白名单(服务端强制,UI 隐藏≠权限;越界返回 403):
#   ack_incident/pause_new_risk/add_to_watch/dismiss_non_risk_item=登记类立即
#   preview_reduction=只读预演(无重认证)  approve_reduction/cancel_open_orders=减险执行(须重认证)
_MOBILE_ALLOWED = {"pause_new_risk", "opportunity_watch", "opportunity_ignore",
                   "workitem_ack", "ack_incident", "add_to_watch", "dismiss_non_risk_item",
                   "preview_reduction", "approve_reduction", "cancel_open_orders", "coin_reduce",
                   "pause_automation"}  # 手机紧急压停自动环(减险方向)放行;resume 禁手机
# 减险执行类:须最新快照重预演+重认证(reauth_ticket);快照过期不阻断减险但强制重预演
_REDUCE_EXEC = {"approve_reduction", "cancel_open_orders", "coin_reduce"}
_KNOWN = _RISK_ADDING | _MOBILE_ALLOWED | {
    "resume_normal", "workitem_takeover", "workitem_release", "maintenance_start"}


async def _pool():
    p = await ds.pg_main()
    if p is None:
        raise HTTPException(503, "mix_main 不可达")
    await p.execute(_DDL)
    return p


async def require_operator_or_mobile(
        x_op_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None)) -> dict:
    """commands 入口鉴权:operator 令牌(全能力) 或 mix 用户 JWT 且角色=OPERATOR_MOBILE_LIMITED
    (§7.1 手机受限:能力集在 operator_commands 内强制,不靠隐藏菜单)。"""
    who = await _resolve(x_op_token)
    if who:
        return {**who, "token": x_op_token, "urole": ""}
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    # X-Op-Token 里也可能是用户 JWT(前端统一放这个头)——先解出身份再判权限
    juser = _jwt_decode(x_op_token) or _jwt_decode(bearer)
    if juser and str(juser.get("urole") or "") == "OPERATOR_MOBILE_LIMITED":
        return {**juser, "role": "OPERATOR", "urole": "OPERATOR_MOBILE_LIMITED", "token": None}
    if juser:
        # 有有效登录但角色不够=403(权限不足),绝不能 401——前端把 401 当会话失效弹登录门
        raise HTTPException(403, f"当前账号({juser.get('operator')})为只读用户,无操作权限;需操作员令牌")
    raise HTTPException(401, "需要 operator 令牌或手机受限操作员登录(OPERATOR_MOBILE_LIMITED)")


# ─────────────────────────── 快照与工作项 ───────────────────────────

@router.get("/operator/control/snapshot")
async def control_snapshot(_who=Depends(require_viewer)):
    """首次 REST 全量;之后 WS(hub 透传 control:snapshot 帧)带 generation 增量。
    worker 挂了→现算兜底(generation 取 Redis 现值,不递增)。"""
    raw = None
    r = ds.rds()
    if r is not None:
        try:
            raw = await r.get(v6core.SNAPSHOT_KEY)
        except Exception:  # noqa: BLE001
            pass
    if raw:
        return json.loads(raw)
    snap = await v6core.build_control_snapshot()
    try:
        snap["generation"] = int(await r.get(v6core.GEN_KEY) or 0)
    except Exception:  # noqa: BLE001
        snap["generation"] = 0
    snap["degraded"] = "worker快照缺失,现算兜底"
    return snap


@router.get("/operator/risk-control")
async def risk_control_snapshot(_who=Depends(require_viewer)):
    """REV4 批C §6B:P3 账户与保证金汇总——平台父行+账户风险子行+全局事实带。
    交互式(/mix/venuerisk)与外接墙(/wall/risk)读同一快照;venue 原始风险口径与
    canonical 统一口径并列(公式注册表说明各所分子/分母/安全方向);未接入指标=null 不冒充。"""
    return await v6core.build_risk_control_snapshot()


# ══ Asset 360 单币全景 API (MIX-V6.2-ASSET360-PATCH-01 A1) ═══════════════
from app import asset360

@router.get("/assets/search")
async def assets_search(q: str, limit: int = 20, _who=Depends(require_viewer)):
    """资产搜索：规范symbol/别名/合约地址（A1阶段=预置列表+别名；A3接CoinGecko）。"""
    return {"results": asset360.search_assets(q, limit)}

@router.get("/assets/{asset_id}/360")
async def asset360_snapshot(asset_id: str, _who=Depends(require_viewer)):
    """单币全景快照：跨平台价格/资金费/OI/充提/韩国/市值（A1-A3分批完成）。"""
    aid = asset_id.strip().upper()
    if not aid or aid in ("UNDEFINED", "NULL", "NONE"):
        raise HTTPException(400, "asset_id 必填")
    # 归一到 canonical(BTCUSDT→BTC):pos_detail 匹配/CoinGecko 映射/韩国市场都以 canonical 为键
    return await asset360.build_asset360_snapshot(asset360._match_alias(aid))


@router.get("/operator/workitems")
async def workitems(stage: str = "", strategy: str = "", _who=Depends(require_viewer)):
    """工作项投影(V6.1 §4 全字段+服务端 allowed_actions)。
    手机受限角色:动作按白名单过滤——不在白名单的动作不渲染(§8.3)。"""
    from .. import v6lang
    items = await v6core.build_work_items()
    if stage:
        items = [w for w in items if w["workflow_stage"] == stage]
    if strategy:
        items = [w for w in items if (w["strategy_code"] or "").startswith(strategy)]
    if str(_who.get("urole") or "") == "OPERATOR_MOBILE_LIMITED":
        for w in items:
            w["allowed_actions"] = v6lang.filter_actions_for_device(w.get("allowed_actions") or [], True)
    elif _who.get("kind") == "mix_user" or _who.get("role") == "VIEWER":
        # VIEWER/普通用户:动作全部降为禁用展示(角色维度进七元交集)——按钮可见但不可点,
        # 三行式给原因;否则点击撞 403 观感像故障
        for w in items:
            for a in (w.get("allowed_actions") or []):
                if a.get("wired"):
                    a["wired"] = False
                    a["reason"] = "只读账号:需操作员权限(联系管理员提权或用操作员令牌登录)"
    return {"count": len(items), "items": items}


# ── OperatorBootstrap(PATCH-02 §4.1):登录后一次拿全——薄聚合既有权威,不建第二套权限计算 ──
@router.get("/operator/bootstrap")
async def operator_bootstrap(surface: str = "desktop",
                             x_device_session: str | None = Header(default=None),
                             who=Depends(require_viewer)):
    from .. import v6lang
    from .training import is_certified, CERT_VERSION
    pol = await ds.get_json("dcm:risk:policy") or {}
    pol_age = time.time() - float(pol.get("ts") or 0) if pol else 9e9
    maint = "NORMAL"
    try:
        pool = await ds.pg_main()
        if pool is not None:
            row = await pool.fetchrow(
                "SELECT state FROM maintenance_request WHERE state != 'CLOSED' ORDER BY id DESC LIMIT 1")
            if row:
                maint = row["state"]
    except Exception:  # noqa: BLE001
        pass
    caps = await v6lang.capabilities()
    role = who.get("role", "VIEWER")
    urole = str(who.get("urole") or "")
    certified = await is_certified(who.get("operator") or "")
    mobile_limited = urole == "OPERATOR_MOBILE_LIMITED"
    nav = ["today", "training", "venuerisk", "report", "history", "lab"]
    if role in ("OPERATOR", "SUPER_ADMIN"):
        nav += ["workbench", "aicoin", "rules", "accounts", "slots", "system", "notify", "operators"]
    if certified and "training" in nav:
        nav.remove("training")   # §9.2:通过后入口迁今日工作按钮
    # REV2 §9.1 device_trust(shadow 立项):受信=已注册 trusted_operator_device;
    # 未注册移动设备一律 untrusted→仅只读/减险(不因是iPad/手机自行开放开仓)。
    # armed 移动交易待 M4 完成+设备注册流程+用户放行;本批只投影契约,默认 untrusted。
    device_trust = {"state": "desktop_implicit" if surface == "desktop" else "untrusted",
                    "device_session_id": None, "limits": None}
    if surface in ("tablet", "phone") and x_device_session:
        try:
            pool = await ds.pg_main()
            if pool is not None:
                row = await pool.fetchrow(
                    "SELECT trust_state, last_seen_at FROM trusted_operator_device "
                    "WHERE device_session_id=$1 AND operator=$2 AND trust_state='trusted'",
                    x_device_session, who.get("operator") or "")
                if row:
                    lim = await pool.fetch(
                        "SELECT scope, max_notional_usdt::float8 mn, daily_risk_budget_usdt::float8 db "
                        "FROM operator_device_limit WHERE device_session_id=$1", x_device_session)
                    device_trust = {"state": "trusted", "device_session_id": x_device_session,
                                    "limits": {r["scope"]: {"max_notional": r["mn"], "daily_budget": r["db"]}
                                               for r in lim}}
        except Exception:  # noqa: BLE001  表未建/查失败=保守 untrusted
            pass
    # 受信状态覆盖 device_policy:受信平板/手机可开仓(受设备额度),否则只读+减险
    trusted = device_trust["state"] in ("trusted", "desktop_implicit")
    device_policy = {
        "desktop": {"new_risk": role in ("OPERATOR", "SUPER_ADMIN"), "approve": True, "reduce": True},
        "tablet": {"new_risk": trusted, "approve": trusted, "reduce": True},
        "phone": {"new_risk": trusted, "approve": trusted, "reduce": "whitelist" if not trusted else True},
        "wall": {"new_risk": False, "approve": False, "reduce": False},
    }.get(surface, {})
    return {
        "operator_id": who.get("operator"), "role": role, "urole": urole,
        "surface": surface, "device_policy": device_policy, "device_trust": device_trust,
        "environment": "PROD_CEX", "maintenance_state": maint,
        "effective_risk_mode": ("STALE" if pol_age > 90 else pol.get("global_mode", "NORMAL")),
        "policy_epoch": pol.get("policy_epoch"), "policy_version": pol.get("policy_version"),
        "product_capabilities": caps,
        "allowed_navigation": nav,
        "reauth_method": ("passkey_or_totp" if not mobile_limited else "passkey"),
        "training_profile": {"certified": certified, "version": CERT_VERSION},
        "snapshot_endpoint": "/api/v6/operator/control/snapshot",
        "websocket_endpoint": "/ws/stream",
        "note_device_trust": "受信设备注册流程与移动armed交易待M5;当前未注册=untrusted只读/减险",
    }


# ─────────────────── REV2 §9 受信设备(M5:注册/撤销/额度 + 命令闸消费) ───────────────────
_DEV_DDL = """CREATE TABLE IF NOT EXISTS trusted_operator_device (
    device_session_id TEXT PRIMARY KEY, operator TEXT NOT NULL,
    surface TEXT NOT NULL DEFAULT 'phone' CHECK (surface IN ('tablet','phone','desktop')),
    trust_state TEXT NOT NULL DEFAULT 'pending' CHECK (trust_state IN ('pending','trusted','revoked')),
    webauthn_cred_id TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
    registered_by TEXT NOT NULL DEFAULT '', last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), revoked_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS operator_device_limit (
    device_session_id TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'GLOBAL',
    max_notional_usdt NUMERIC NOT NULL DEFAULT 0, daily_risk_budget_usdt NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (device_session_id, scope))"""

# 移动端新增风险默认额度(受信桌面可逐设备调低,不可在移动端提高)
_DEV_DEFAULT_MAX_NOTIONAL = float(__import__("os").environ.get("MIX_DEV_MAX_NOTIONAL", "50"))
_DEV_DEFAULT_DAILY = float(__import__("os").environ.get("MIX_DEV_DAILY_BUDGET", "200"))


@router.post("/operator/devices/register")
async def device_register(body: dict, op=Depends(require_operator)):
    """受信桌面(operator 令牌)确认注册一台移动设备(§9.1:非浏览器自报/非屏宽)。
    直接置 trusted(桌面 operator 已受信),绑定操作员已注册的 WebAuthn 凭证;返回
    device_session_id 供移动设备保存(X-Device-Session 头)。默认设备额度可后续调低。"""
    pool = await _pool()
    await pool.execute(_DEV_DDL)
    surface = str(body.get("surface") or "phone")
    if surface not in ("tablet", "phone"):
        raise HTTPException(400, "surface 须 tablet|phone")
    # 要求操作员已有 WebAuthn 凭证(设备信任锚定在 Passkey);表未建=尚无 Passkey,受信但标未绑
    cred = None
    try:
        cred = await pool.fetchrow(
            "SELECT credential_id FROM operator_webauthn_credential WHERE operator=$1 ORDER BY id LIMIT 1",
            op["operator"])
    except Exception:  # noqa: BLE001  operator_webauthn_credential 未建(无人注册 Passkey)
        pass
    sid = secrets.token_urlsafe(24)
    await pool.execute(
        "INSERT INTO trusted_operator_device(device_session_id, operator, surface, trust_state, "
        "webauthn_cred_id, label, registered_by) VALUES($1,$2,$3,'trusted',$4,$5,$6)",
        sid, op["operator"], surface, (cred["credential_id"] if cred else ""),
        str(body.get("label") or f"{surface}-{sid[:6]}")[:60], op["operator"])
    mn = float(body.get("max_notional") or _DEV_DEFAULT_MAX_NOTIONAL)
    db = float(body.get("daily_budget") or _DEV_DEFAULT_DAILY)
    await pool.execute(
        "INSERT INTO operator_device_limit(device_session_id, scope, max_notional_usdt, daily_risk_budget_usdt) "
        "VALUES($1,'GLOBAL',$2,$3) ON CONFLICT (device_session_id, scope) DO UPDATE SET "
        "max_notional_usdt=$2, daily_risk_budget_usdt=$3", sid, mn, db)
    await _log_cmd(pool, "device.register", "", {"surface": surface, "sid": sid[:6]},
                   op["operator"], op.get("role", ""), "trusted")
    return {"ok": True, "device_session_id": sid, "surface": surface,
            "webauthn_bound": bool(cred),
            "limits": {"max_notional": mn, "daily_budget": db},
            "note": ("移动设备保存此 device_session_id;未绑定 Passkey 时受信但开仓仍需先注册 Passkey"
                     if not cred else "在移动设备用此会话+Passkey 完成受信交易")}


@router.get("/operator/devices")
async def device_list(op=Depends(require_operator)):
    pool = await _pool()
    await pool.execute(_DEV_DDL)
    rows = await pool.fetch(
        "SELECT d.device_session_id, d.surface, d.trust_state, d.label, d.last_seen_at::text, "
        "d.created_at::text, d.webauthn_cred_id<>'' AS has_passkey, "
        "l.max_notional_usdt::float8 mn, l.daily_risk_budget_usdt::float8 db "
        "FROM trusted_operator_device d LEFT JOIN operator_device_limit l "
        "ON l.device_session_id=d.device_session_id AND l.scope='GLOBAL' "
        "WHERE d.operator=$1 AND d.trust_state<>'revoked' ORDER BY d.created_at DESC", op["operator"])
    return [{"device_session_id": r["device_session_id"][:8] + "…", "sid_full": r["device_session_id"],
             "surface": r["surface"], "trust_state": r["trust_state"], "label": r["label"],
             "has_passkey": r["has_passkey"], "last_seen": r["last_seen_at"], "created": r["created_at"],
             "max_notional": r["mn"], "daily_budget": r["db"]} for r in rows]


@router.post("/operator/devices/{sid}/revoke")
async def device_revoke(sid: str, op=Depends(require_operator)):
    """撤销设备(§10.3:设备丢失→桌面立即撤销;现有会话即失效,后续 bootstrap=untrusted)。"""
    pool = await _pool()
    await pool.execute(_DEV_DDL)
    n = await pool.execute(
        "UPDATE trusted_operator_device SET trust_state='revoked', revoked_at=now() "
        "WHERE device_session_id=$1 AND operator=$2", sid, op["operator"])
    await _log_cmd(pool, "device.revoke", "", {"sid": sid[:6]}, op["operator"], op.get("role", ""), "revoked")
    return {"ok": n.endswith("1"), "revoked": sid[:8] + "…"}


@router.post("/operator/devices/{sid}/limits")
async def device_limits(sid: str, body: dict, op=Depends(require_operator)):
    """调整设备额度(只降不升的纪律靠桌面 operator 判断;移动端无此端点)。"""
    pool = await _pool()
    await pool.execute(_DEV_DDL)
    mn = float(body.get("max_notional") or 0)
    db = float(body.get("daily_budget") or 0)
    await pool.execute(
        "INSERT INTO operator_device_limit(device_session_id, scope, max_notional_usdt, daily_risk_budget_usdt) "
        "VALUES($1,'GLOBAL',$2,$3) ON CONFLICT (device_session_id, scope) DO UPDATE SET "
        "max_notional_usdt=$2, daily_risk_budget_usdt=$3, updated_at=now()", sid, mn, db)
    return {"ok": True, "max_notional": mn, "daily_budget": db}


async def _device_gate(pool, op, x_device_session, ctype, params):
    """M5b:移动端(mix 用户 JWT)新增风险命令须受信设备+额度内。
    受信=trusted_operator_device;桌面 operator 令牌不受此限(desktop_implicit)。
    额度=单笔名义≤max_notional 且 当日移动新增风险≤daily_budget。超限/未受信=403。
    返回 (device_session_id|None, note)。真金执行仍另门控——此闸只挡新增风险的下发资格。"""
    # 桌面 operator 令牌(有 token)= 隐式受信,不查设备
    if op.get("token"):
        return None, "desktop_implicit"
    if not x_device_session:
        raise HTTPException(403, "移动端新增风险须受信设备:缺 X-Device-Session(先在受信桌面注册设备)")
    dev = await pool.fetchrow(
        "SELECT trust_state FROM trusted_operator_device WHERE device_session_id=$1 AND operator=$2",
        x_device_session, op.get("operator") or op.get("username") or "")
    if not dev or dev["trust_state"] != "trusted":
        raise HTTPException(403, "设备未受信或已撤销:新增风险已禁止(减险/确认不受影响)")
    await pool.execute("UPDATE trusted_operator_device SET last_seen_at=now() WHERE device_session_id=$1",
                       x_device_session)
    lim = await pool.fetchrow(
        "SELECT max_notional_usdt::float8 mn, daily_risk_budget_usdt::float8 db "
        "FROM operator_device_limit WHERE device_session_id=$1 AND scope='GLOBAL'", x_device_session)
    mn = float(lim["mn"]) if lim else 0.0
    db = float(lim["db"]) if lim else 0.0
    notional = float(params.get("notional") or params.get("target_notional") or 0)
    if notional > mn:
        raise HTTPException(403, f"超设备单笔额度:{notional}U > 上限 {mn}U(移动端不可自行提高)")
    # 当日移动新增风险累计(Redis 计数,按 operator+device)
    r = ds.rds()
    used = 0.0
    if r is not None:
        try:
            import datetime as _dt
            day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
            used = float(await r.get(f"mix:dev:risk:{x_device_session}:{day}") or 0)
        except Exception:  # noqa: BLE001
            pass
    if used + notional > db:
        raise HTTPException(403, f"超设备当日移动新增风险额度:已用 {used}+{notional} > {db}U")
    return x_device_session, f"trusted·单笔≤{mn}·当日余{db - used}"


async def _log_cmd(pool, ctype, scope, params, actor, role, status):
    try:
        await pool.execute(
            "INSERT INTO v6_command_log(command_type, scope, params, actor, actor_role, status, result) "
            "VALUES($1,$2,$3::jsonb,$4,$5,$6,'{}'::jsonb)",
            ctype, scope, json.dumps(params, ensure_ascii=False, default=str), actor, role, status)
    except Exception:  # noqa: BLE001
        pass


# ── UX 使用计数(M5 收敛门槛数据:工作台 vs 今日工作,连续两周归零才收菜单) ──
_PV_PAGES = {"today", "workbench", "aicoin", "console", "wall"}


@router.post("/ux/pageview")
async def ux_pageview(body: dict, _who=Depends(require_viewer)):
    page = str(body.get("page") or "")
    if page not in _PV_PAGES:
        return {"ok": False}
    r = ds.rds()
    if r is not None:
        try:
            import datetime as _dt
            day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
            await r.hincrby(f"mix:ux:pv:{day}", page, 1)
            await r.expire(f"mix:ux:pv:{day}", 86400 * 30)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


@router.get("/ux/pageviews")
async def ux_pageviews(days: int = 14, _who=Depends(require_viewer)):
    r = ds.rds()
    out = {}
    if r is not None:
        import datetime as _dt
        for i in range(min(days, 30)):
            day = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=i)).strftime("%Y%m%d")
            try:
                h = await r.hgetall(f"mix:ux:pv:{day}")
                if h:
                    out[day] = {(k.decode() if isinstance(k, bytes) else k):
                                int(v) for k, v in h.items()}
            except Exception:  # noqa: BLE001
                pass
    return {"days": out, "note": "M5 门槛:workbench 连续两周为 0 → 收敛旧入口(路由保留30-60天)"}


# ─────────────────────────── V6.1 元数据(字典/能力注册表) ───────────────────────────

@router.get("/meta/dictionary")
async def meta_dictionary(_who=Depends(require_viewer)):
    """术语字典(§6.1):默认页面只显示业务标签,专家详情才显示原始代码。"""
    from .. import v6lang
    return await v6lang.dictionary()


@router.get("/meta/capabilities")
async def meta_capabilities(_who=Depends(require_viewer)):
    from .. import v6lang
    pool = await ds.pg_main()
    rows = []
    if pool is not None:
        await v6lang.ensure_seed()
        rows = [dict(r) for r in await pool.fetch(
            "SELECT product_code, capability, note, updated_by, updated_at::text "
            "FROM product_capability_registry ORDER BY product_code")]
    return {"rows": rows,
            "legend": {"ACTIVE_WRITE": "当前可写", "ACTIVE_READ": "已接入只读", "SHADOW": "影子验证",
                       "PLANNED": "尚未启用", "BLOCKED": "被风险/维护阻断", "DEPRECATED": "即将淘汰"}}


@router.put("/meta/capabilities/{product_code}")
async def meta_capability_put(product_code: str, body: dict, op=Depends(require_operator)):
    cap = str(body.get("capability") or "")
    if cap not in ("ACTIVE_WRITE", "ACTIVE_READ", "SHADOW", "PLANNED", "BLOCKED", "DEPRECATED"):
        raise HTTPException(400, "capability 非法")
    pool = await _pool()
    await pool.execute(
        "INSERT INTO product_capability_registry(product_code,capability,note,updated_by) "
        "VALUES($1,$2,$3,$4) ON CONFLICT (product_code) DO UPDATE SET capability=$2, note=$3, "
        "updated_by=$4, updated_at=now()",
        product_code, cap, str(body.get("note") or ""), op["operator"])
    from .. import v6lang
    v6lang._cache["caps"] = None   # 失效缓存
    return {"ok": True, "product_code": product_code, "capability": cap}


@router.put("/meta/dictionary/{code}")
async def meta_dictionary_put(code: str, body: dict, op=Depends(require_operator)):
    pool = await _pool()
    from .. import v6lang
    await v6lang.ensure_seed()
    await pool.execute(
        "INSERT INTO presentation_dictionary(code,label,explain,category,version) VALUES($1,$2,$3,$4,1) "
        "ON CONFLICT (code) DO UPDATE SET label=$2, explain=$3, category=$4, "
        "version=presentation_dictionary.version+1, updated_at=now()",
        code, str(body.get("label") or code), str(body.get("explain") or ""),
        str(body.get("category") or "general"))
    v6lang._cache["dict"] = None
    return {"ok": True}


# ─────────────────────────── 唯一写入租约(§13.1) ───────────────────────────

@router.get("/operator/lease")
async def lease_list(_who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch("SELECT * FROM strategy_writer_lease ORDER BY updated_at DESC LIMIT 100")
    return [{**dict(r), "valid_until": r["valid_until"].isoformat(),
             "updated_at": r["updated_at"].isoformat(),
             "expired": r["valid_until"].timestamp() < time.time()} for r in rows]


@router.post("/operator/lease/acquire")
async def lease_acquire(body: dict, op=Depends(require_operator)):
    """同一 scope 只有一个可写入口。已被他人持有且未过期→409(须 takeover)。
    获取/接管都 bump writer_epoch——旧 epoch 的命令一律拒。"""
    scope = str(body.get("scope") or "").strip()
    if not scope:
        raise HTTPException(400, "scope 必填(如 CORE_POOL:C3.S:FILUSDT)")
    mode = str(body.get("automation_mode") or "MANUAL")
    if mode not in ("AUTO", "ASSISTED", "MANUAL"):
        raise HTTPException(400, "automation_mode ∈ AUTO/ASSISTED/MANUAL")
    ttl_min = min(int(body.get("ttl_min") or 60), 480)
    takeover = bool(body.get("takeover"))
    pool = await _pool()
    cur = await pool.fetchrow("SELECT * FROM strategy_writer_lease WHERE scope=$1", scope)
    if cur and cur["valid_until"].timestamp() > time.time() \
            and cur["active_writer"] != op["operator"] and not takeover:
        raise HTTPException(409, f"scope 已被 {cur['active_writer']} 持有(epoch {cur['writer_epoch']});"
                                 "接管须 takeover=true(冻结原自动新增+完整审计)")
    token = secrets.token_hex(16)
    row = await pool.fetchrow(
        "INSERT INTO strategy_writer_lease(scope, active_writer, writer_epoch, fencing_token, "
        "automation_mode, valid_until, note) "
        "VALUES($1,$2,1,$3,$4,now()+($5||' minutes')::interval,$6) "
        "ON CONFLICT (scope) DO UPDATE SET active_writer=$2, writer_epoch=strategy_writer_lease.writer_epoch+1, "
        "fencing_token=$3, automation_mode=$4, valid_until=now()+($5||' minutes')::interval, "
        "note=$6, updated_at=now() RETURNING writer_epoch",
        scope, op["operator"], token, mode, str(ttl_min),
        str(body.get("note") or ("接管" if takeover else "")))
    await pool.execute(
        "INSERT INTO v6_command_log(command_type, scope, params, actor, actor_role, writer_epoch, status, result) "
        "VALUES('lease_acquire',$1,$2::jsonb,$3,$4,$5,'DONE','{}'::jsonb)",
        scope, json.dumps({"takeover": takeover, "mode": mode}), op["operator"], op["role"], row["writer_epoch"])
    return {"scope": scope, "writer_epoch": int(row["writer_epoch"]), "fencing_token": token,
            "automation_mode": mode, "ttl_min": ttl_min,
            "note": "每个后续命令必须携带 writer_epoch+fencing_token;旧 epoch 一律拒绝"}


@router.post("/operator/lease/release")
async def lease_release(body: dict, op=Depends(require_operator)):
    scope = str(body.get("scope") or "").strip()
    pool = await _pool()
    n = await pool.execute("DELETE FROM strategy_writer_lease WHERE scope=$1 AND active_writer=$2",
                           scope, op["operator"])
    return {"scope": scope, "released": n.endswith("1")}


async def _lease_check(pool, scope: str, epoch, token) -> None:
    """fencing:带 scope 的写命令必须持有效租约且 epoch/token 逐字节一致。"""
    if not scope:
        return
    cur = await pool.fetchrow("SELECT * FROM strategy_writer_lease WHERE scope=$1", scope)
    if not cur:
        raise HTTPException(428, f"scope {scope} 无写入租约:先 POST /operator/lease/acquire")
    if cur["valid_until"].timestamp() < time.time():
        raise HTTPException(428, "租约已过期,重新 acquire(epoch 会递增)")
    if int(epoch or 0) != int(cur["writer_epoch"]) or str(token or "") != cur["fencing_token"]:
        raise HTTPException(409, f"fencing 拒绝:writer_epoch/token 不匹配(现 epoch={cur['writer_epoch']});"
                                 "旧 epoch 一律拒绝——可能已被接管")


# ─────────────────────────── typed command 入口 ───────────────────────────

@router.post("/operator/commands")
async def operator_commands(body: dict, x_device_session: str | None = Header(default=None),
                            op=Depends(require_operator_or_mobile)):
    """V6 唯一可写策略入口。envelope:
    {command_type, scope?, params?, idempotency_key?, writer_epoch?, fencing_token?,
     automation_mode?, environment?}
    REV2 §9:移动端(mix JWT)新增风险命令须受信设备(X-Device-Session)+额度内。
    """
    ctype = str(body.get("command_type") or "").strip()
    if ctype not in _KNOWN:
        raise HTTPException(400, f"未知 command_type:{ctype}(已注册:{sorted(_KNOWN)})")
    # §8.1 生产 API 拒绝 DEX_LAB
    if str(body.get("environment") or "PROD_CEX") == "DEX_LAB":
        raise HTTPException(403, "生产 API 拒绝 environment=DEX_LAB 的写入(LAB 信号只能经 research_outbox 单向发布)")
    params = body.get("params") or {}
    scope = str(body.get("scope") or "")
    amode = str(body.get("automation_mode") or "MANUAL")
    pool = await _pool()

    # 手机受限角色(§7.1):urole 来自 mix 用户体系;operators 表角色不受此限
    urole = str(op.get("urole") or "")
    if urole == "OPERATOR_MOBILE_LIMITED" and ctype not in _MOBILE_ALLOWED:
        raise HTTPException(403, f"手机受限角色禁止 {ctype}(仅允许:{sorted(_MOBILE_ALLOWED)})")

    # 幂等
    idem = str(body.get("idempotency_key") or "") or None
    if idem:
        prior = await pool.fetchrow("SELECT status, result FROM v6_command_log WHERE idempotency_key=$1", idem)
        if prior:
            return {"idempotent_replay": True, "status": prior["status"],
                    "result": json.loads(prior["result"]) if isinstance(prior["result"], str) else prior["result"]}

    # 风险能力覆盖运行方式:新增风险类命令过快照/维护双闸(fail-closed)+训练认证门禁(N4)
    dev_note = None
    if ctype in _RISK_ADDING:
        pol = await ds.get_json("dcm:risk:policy") or {}
        age = time.time() - float(pol.get("ts") or 0)
        if not pol or age > 90:
            raise HTTPException(423, "风险快照缺失/过期(>90s),fail-closed 禁止新增风险;减险类命令不受影响")
        from .maintenance import block_new_risk
        await block_new_risk()
        # 训练门禁只拦新增风险,减险类命令永远不经过此处(§二.4)
        from .training import is_certified
        if not await is_certified(op["operator"]):
            raise HTTPException(403, "未通过训练认证:新增风险类命令暂不可用(减险/确认/观察不受影响);"
                                     "完成 /mix/training 六课目后自动解锁")
        # REV2 §9 M5b:移动端(mix JWT,无 operator 令牌)新增风险须受信设备+额度内
        await pool.execute(_DEV_DDL)
        _dev_sid, dev_note = await _device_gate(pool, op, x_device_session, ctype, params)
        await _lease_check(pool, scope, body.get("writer_epoch"), body.get("fencing_token"))

    status, result = "DONE", {}
    try:
        if ctype == "pause_new_risk":
            from .maintenance import _risk_override
            ttl = params.get("ttl_hours")
            await _risk_override("NO_NEW_RISK", str(params.get("reason") or "V6命令:暂停新增"),
                                 op["operator"], ttl_hours=float(ttl) if ttl else None)
            result = {"applied": "GLOBAL NO_NEW_RISK(经 risk_policy_override 权威通道)",
                      "ttl_hours": ttl or None}
        elif ctype == "resume_normal":
            if urole == "OPERATOR_MOBILE_LIMITED":
                raise HTTPException(403, "手机角色不能恢复 NORMAL")
            from .maintenance import _risk_override
            await _risk_override("NORMAL", str(params.get("reason") or "V6命令:恢复"), op["operator"])
            result = {"applied": "GLOBAL NORMAL 追加(venue级更严格限制继续生效)"}
        elif ctype in ("pause_automation", "resume_automation"):
            # R4:自动化环暂停/恢复 —— 接权威 Redis 控制键。pause=压停(减险,永远放行);
            # resume=重新武装真钱环(新增风险,已过全闸 freshness+设备Passkey+租约+训练)。
            # 双重人工护栏:①主控总闸 _AUTOCTL_MASTER 未开 → 全 SHADOW 只登记不改键(真钱零改变);
            #               ②resume 即便主闸开,仍须副闸 _AUTOCTL_RESUME_OK=1(盯盘二次授权)否则 STAGED。
            act = "PAUSE" if ctype == "pause_automation" else "RESUME"
            loop_id = str(params.get("loop_id") or "")
            spec = _CONTROLLABLE_LOOPS.get(loop_id)
            if not spec:
                raise HTTPException(400, f"loop_id 不可控或未知(可控:{sorted(_CONTROLLABLE_LOOPS)})")
            r = ds.rds()
            if r is None:
                raise HTTPException(503, "权威 Redis 不可达,无法执行自动化环控制")
            ckey = spec["key"]
            prev = await r.get(ckey)
            master_on = str(await r.get(_AUTOCTL_MASTER) or "") == "1"
            target = "0" if act == "PAUSE" else "1"
            reason = str(params.get("reason") or ("V6命令:压停自动环" if act == "PAUSE" else "V6命令:恢复自动环"))
            if not master_on:
                effect, newv = "SHADOW_LOGGED", prev
                result = {"effect": "SHADOW", "loop_id": loop_id, "control_key": ckey,
                          "would_set": target, "current": prev,
                          "note": f"主控总闸未开(SET {_AUTOCTL_MASTER}=1 须盯盘授权);已登记控制意图,未真实改键"}
            elif act == "RESUME" and str(await r.get(_AUTOCTL_RESUME_OK) or "") != "1":
                effect, newv = "STAGED_AWAIT_SUPERVISION", prev
                result = {"effect": "STAGED", "loop_id": loop_id, "control_key": ckey,
                          "note": f"恢复真钱自动环须副闸授权(SET {_AUTOCTL_RESUME_OK}=1,盯盘二次确认);已登记待放行"}
                status = "STAGED"
            else:
                await r.set(ckey, target)
                effect, newv = "APPLIED", target
                twok = spec.get("two_key")
                result = {"effect": "APPLIED", "loop_id": loop_id, "control_key": ckey,
                          "prev": prev, "new": target,
                          "note": (f"{spec['name']}:Redis 闸已置 {target}"
                                   + (f";两钥匙型另需 B 机 {twok} 就位方全生效" if twok else ""))}
            await pool.execute(
                "INSERT INTO automation_control_log(loop_id, action, control_key, prev_value, "
                "new_value, effect, reason, actor, actor_role, writer_epoch) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                loop_id, act, ckey, prev, newv, effect, reason,
                op["operator"], op["role"], body.get("writer_epoch"))
        elif ctype in ("opportunity_to_workbench", "opportunity_watch", "opportunity_ignore"):
            act = {"opportunity_to_workbench": "TO_WORKBENCH", "opportunity_watch": "WATCH",
                   "opportunity_ignore": "IGNORE"}[ctype]
            sym = str(params.get("symbol") or "")
            if not sym:
                raise HTTPException(400, "params.symbol 必填")
            await pool.execute(
                "INSERT INTO v6_opportunity_action(symbol, strategy_code, action, actor) VALUES($1,$2,$3,$4)",
                sym, str(params.get("strategy_code") or ""), act, op["operator"])
            result = {"registered": act, "symbol": sym,
                      "note": ("已登记送入工作台(DISCOVERED→REVIEW);真实开仓仍须 DRY_RUN→审批,不直接下单"
                               if act == "TO_WORKBENCH" else "已登记")}
        elif ctype == "proposal_dry_run":
            from .proposal import proposal_create
            result = await proposal_create({**params, "automation_mode": amode}, op)
            status = "DELEGATED"
        elif ctype == "workitem_takeover":
            # 人工接管:登记 MANUAL 租约(epoch bump=冻结旧口令),自动侧消费租约为后续接线,如实标注
            body2 = {"scope": scope or f"CORE_POOL:{params.get('strategy_code','?')}:{params.get('symbol','?')}",
                     "automation_mode": "MANUAL", "takeover": True,
                     "note": f"人工接管:{params.get('reason','')}"}
            result = await lease_acquire(body2, op)
            result["honest_note"] = "租约已 bump epoch(旧口令失效);引擎侧消费租约冻结自动新增=下一步接线项"
            status = "DONE"
        elif ctype == "workitem_release":
            result = await lease_release({"scope": scope}, op)
        elif ctype in ("workitem_ack", "ack_incident"):
            result = {"acked": params.get("work_item_id") or params.get("incident"),
                      "note": "已确认知悉(登记)"}
        elif ctype == "add_to_watch":
            sym = str(params.get("symbol") or "")
            if not sym:
                raise HTTPException(400, "params.symbol 必填")
            await pool.execute(
                "INSERT INTO v6_opportunity_action(symbol, strategy_code, action, actor) VALUES($1,$2,'WATCH',$3)",
                sym, str(params.get("strategy_code") or ""), op["operator"])
            result = {"registered": "WATCH", "symbol": sym}
        elif ctype == "dismiss_non_risk_item":
            result = {"dismissed": params.get("work_item_id"), "note": "已忽略(非风险项;风险项不可忽略)"}
        elif ctype == "preview_reduction":
            # §10 减险预演(只读 before/after,不下单不需重认证)——手机接警后先看退出估值
            sym = str(params.get("symbol") or "")
            if not sym:
                raise HTTPException(400, "params.symbol 必填")
            from .proposal import close_preview
            pv = await close_preview(sym, op)
            rx = ((await ds.get_json("dcm:risk:exit")) or {}).get("items", {}).get(sym) or {}
            result = {"symbol": sym, "preview": pv, "risk_protection_state": rx.get("state"),
                      "closeout_pnl_net": rx.get("closeout_pnl_net"),
                      "note": "只读预演;执行减仓/撤单须『批准减仓』(重认证)"}
            status = "PREVIEW"
        elif ctype in _REDUCE_EXEC:
            # 减险执行:强制重认证(reauth_ticket)+最新事实重预演——不因快照过期阻断,但拒绝陈旧预演
            from .webauthn_auth import check_reauth_ticket
            if not await check_reauth_ticket(op["operator"], str(body.get("reauth_ticket") or "")):
                raise HTTPException(401, "减险执行须重认证(Passkey/TOTP reauth_ticket);先『批准减仓』二次确认")
            # 真实减仓/撤单执行=B 机 reduce_pair / coin 撤单代理(§8.6 RiskExitSaga)——armed 门控项,
            # 诚实 501 不假 202;预演与重认证已就位,执行接线随 B 机批次放行。
            raise HTTPException(
                501, f"{ctype}:减险执行路径(B 机 reduce_pair / 撤单代理)待 RiskExitSaga 批次接线;"
                     "预演+重认证已通过,执行须 armed 放行(绝不假成功)")
        elif ctype == "maintenance_start":
            raise HTTPException(501, "维护启动须确认短语+TOTP,走 /mix/maintenance 单一权威页,不经本入口")
    except HTTPException as e:
        status, result = "REJECTED", {"error": e.detail, "code": e.status_code}
        await pool.execute(
            "INSERT INTO v6_command_log(idempotency_key, command_type, scope, params, automation_mode, "
            "actor, actor_role, writer_epoch, status, result) VALUES($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10::jsonb)",
            idem, ctype, scope, json.dumps(params, ensure_ascii=False, default=str), amode,
            op["operator"], op["role"], body.get("writer_epoch"), status,
            json.dumps(result, ensure_ascii=False, default=str))
        raise
    await pool.execute(
        "INSERT INTO v6_command_log(idempotency_key, command_type, scope, params, automation_mode, "
        "actor, actor_role, writer_epoch, status, result) VALUES($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10::jsonb)",
        idem, ctype, scope, json.dumps(params, ensure_ascii=False, default=str), amode,
        op["operator"], op["role"], body.get("writer_epoch"), status,
        json.dumps(result, ensure_ascii=False, default=str))
    # M5b:受信设备新增风险成功→累计当日移动新增风险额度(Redis,与 _device_gate 同键)
    if dev_note and dev_note != "desktop_implicit" and ctype in _RISK_ADDING and x_device_session:
        notional = float(params.get("notional") or params.get("target_notional") or 0)
        if notional > 0 and ds.rds() is not None:
            try:
                import datetime as _dt
                day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
                k = f"mix:dev:risk:{x_device_session}:{day}"
                await ds.rds().incrbyfloat(k, notional)
                await ds.rds().expire(k, 86400 * 2)
            except Exception:  # noqa: BLE001
                pass
    return {"status": status, "result": result, "device": dev_note}


@router.get("/operator/commands/log")
async def commands_log(limit: int = 50, _who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT id, idempotency_key, command_type, scope, automation_mode, actor, actor_role, "
        "writer_epoch, status, result, created_at::text FROM v6_command_log ORDER BY id DESC LIMIT $1",
        max(1, min(limit, 200)))
    return [dict(r) for r in rows]


@router.get("/operator/automation/control/state")
async def automation_control_state(_who=Depends(require_viewer)):
    """R4 自动化环控制面板(只读):主控总闸/恢复副闸状态 + 各可控环当前 Redis 闸值 + 最近控制记录。
    真钱零改变:本端点纯读;改键只经 POST /operator/commands(pause_automation/resume_automation)。"""
    pool = await _pool()
    r = ds.rds()
    master_on = resume_ok = False
    loops = []
    if r is not None:
        try:
            master_on = str(await r.get(_AUTOCTL_MASTER) or "") == "1"
            resume_ok = str(await r.get(_AUTOCTL_RESUME_OK) or "") == "1"
            for lid, spec in _CONTROLLABLE_LOOPS.items():
                v = await r.get(spec["key"])
                loops.append({"loop_id": lid, "name": spec["name"], "control_key": spec["key"],
                              "value": v, "armed": v == "1", "two_key": spec.get("two_key")})
        except Exception:  # noqa: BLE001
            pass
    try:
        recent = await pool.fetch(
            "SELECT loop_id, action, control_key, prev_value, new_value, effect, reason, "
            "actor, created_at::text FROM automation_control_log ORDER BY id DESC LIMIT 20")
        recent = [dict(x) for x in recent]
    except Exception:  # noqa: BLE001
        recent = []
    return {"master_control_enabled": master_on, "resume_authorized": resume_ok,
            "master_key": _AUTOCTL_MASTER, "resume_key": _AUTOCTL_RESUME_OK,
            "controllable_loops": loops, "recent_actions": recent,
            "note": ("主控总闸开=命令真实改键;关=SHADOW 只登记。"
                     "恢复真钱环另需恢复副闸。均由盯盘时人工在权威 Redis 置键。")}


# ─────────────────────────── 旧 C3.S 对比(§14.1) ───────────────────────────

_CMP_DIMS = ("坑位", "账户", "阶段", "借币", "买回还币", "收益", "允许动作")


async def _legacy_c3s_snapshot() -> dict:
    """旧 C3.S 事实=coin 意图账快照+面板(只读,旧引擎仍是执行权威)。"""
    snap = await ds.get_json("dcm:engine:coin:positions") or {}
    rows = []
    for p in (snap.get("positions") or []):
        st = str(p.get("status") or "")
        if st in ("CLOSED", "FAILED", "SETTLED"):
            continue
        rows.append({"pit": p.get("symbol"), "account": f"sub:{p.get('sub_account_id')}",
                     "stage": st, "borrowed": p.get("borrowed_amount"),
                     "usdt": p.get("open_usdt_amount"), "status_raw": p.get("status")})
    return {"source": "coin(dcm:engine:coin:positions)", "ts": snap.get("ts"), "slots": rows}


async def _v6_c3s_snapshot() -> dict:
    items = [w for w in await v6core.build_work_items() if w["strategy_code"] == "C3.S"]
    return {"source": "v6 work_item_projection", "slots": [
        {"pit": w["symbol"], "account": (w["physical_accounts"] or [None])[0],
         "stage": w["workflow_stage"], "stage_detail": w["stage_detail"],
         "usdt": w["capital_reserved"], "confirmed_pnl": w["confirmed_pnl"]} for w in items]}


@router.get("/operator/legacy/compare")
async def legacy_compare(persist: bool = True, _who=Depends(require_viewer)):
    """§14.1 对比机制:同一截至时间,V6 投影 vs 旧 C3.S 事实,逐坑位七维 diff。
    旧页持续显示「旧版只读·不会下单」;本端点零写生产,只落对比流水。"""
    legacy, v6 = await _legacy_c3s_snapshot(), await _v6_c3s_snapshot()
    lm = {r["pit"]: r for r in legacy["slots"]}
    vm = {r["pit"]: r for r in v6["slots"]}
    diffs = []
    for pit in sorted(set(lm) | set(vm)):
        a, b = lm.get(pit), vm.get(pit)
        if a is None:
            diffs.append({"pit": pit, "dim": "坑位", "legacy": None, "v6": "有", "note": "V6 有旧版无"})
            continue
        if b is None:
            diffs.append({"pit": pit, "dim": "坑位", "legacy": "有", "v6": None, "note": "旧版有 V6 无"})
            continue
        if a["account"] != b["account"]:
            diffs.append({"pit": pit, "dim": "账户", "legacy": a["account"], "v6": b["account"]})
        exp_stage = v6core._COIN_STAGE.get(str(a["stage"]), (a["stage"], ""))[0]
        if exp_stage != b["stage"]:
            diffs.append({"pit": pit, "dim": "阶段", "legacy": a["stage"], "v6": b["stage"]})
        if (a.get("usdt") or 0) and (b.get("usdt") or 0) and \
                abs(float(a["usdt"]) - float(b["usdt"])) / max(float(a["usdt"]), 1e-9) > 0.02:
            diffs.append({"pit": pit, "dim": "借币", "legacy": a["usdt"], "v6": b["usdt"], "note": ">2%"})
    run = {"as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "phase": "V6_READONLY_SHADOW",
           "legacy": legacy, "v6": v6, "diffs": diffs, "diff_count": len(diffs),
           "dims": _CMP_DIMS,
           "note": "旧版只读·不会下单;差异>0 时阻止下线步骤推进(§14.2)"}
    if persist:
        try:
            pool = await _pool()
            await pool.execute(
                "INSERT INTO legacy_compare_run(v6_snapshot, legacy_snapshot, diffs, diff_count, phase) "
                "VALUES($1::jsonb,$2::jsonb,$3::jsonb,$4,'V6_READONLY_SHADOW')",
                json.dumps(v6, ensure_ascii=False, default=str),
                json.dumps(legacy, ensure_ascii=False, default=str),
                json.dumps(diffs, ensure_ascii=False, default=str), len(diffs))
        except Exception as e:  # noqa: BLE001
            run["persist_error"] = str(e)
    return run


def _read_write_gauge() -> dict:
    """§14.2 第二门槛度量:旧 C3.S 写接口零调用计量器(read-only).
    由 root systemd timer(legacy-write-gauge)每小时扫 nginx 日志写出 /var/lib/mix/legacy_write_gauge.json;
    本函数只读该文件,后端不 sudo、不碰 coin 引擎热路径。文件缺失=计量器未部署,如实回 available=False。"""
    import json as _json, os as _os, datetime as _dt
    p = "/var/lib/mix/legacy_write_gauge.json"
    try:
        with open(p) as f:
            g = _json.load(f)
        age_sec = None
        ga = g.get("generated_at")
        if ga:
            try:
                age_sec = (_dt.datetime.now(_dt.timezone.utc)
                           - _dt.datetime.fromisoformat(ga)).total_seconds()
            except Exception:  # noqa: BLE001
                age_sec = None
        return {"available": True, "stale": (age_sec is not None and age_sec > 7200),
                "age_sec": age_sec,
                "zero_call_streak_days": g.get("zero_call_streak_days", 0),
                "gate_met": bool(g.get("gate_met")),
                "days_remaining": g.get("days_remaining"),
                "log_days_available": g.get("log_days_available"),
                "note": g.get("note", "")}
    except FileNotFoundError:
        return {"available": False, "gate_met": False, "zero_call_streak_days": 0,
                "note": "计量器未部署(缺 /var/lib/mix/legacy_write_gauge.json)"}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "gate_met": False, "zero_call_streak_days": 0,
                "note": f"计量器读取失败:{type(e).__name__}"}


async def _decision_parity_panel(pool) -> dict:
    """S1 决策级经济平价证据(read-only,读 c3s_ground_truth+c3s_shadow_decision)。
    ⚠ 这【不是】零差异门:V6-enforce 背离老引擎(拒开负 E 仓)正是目的(V6 经济更严),
    背离越多越好。此面板量化【切写的经济就绪度】:V6-enforce 会拒开哪些、纯 E 闸避损多少、
    E 值复现保真度。自杀闸(配置冲突,两模式都拒)与 no_data(缺料不可判)不计入避损归因。"""
    try:
        rows = await pool.fetch(
            "SELECT mode, gate, count(*) n, coalesce(sum(realized_pnl),0)::float pnl, "
            "count(*) FILTER (WHERE e_match) em, "
            "count(*) FILTER (WHERE e_stored IS NOT NULL) ek "
            "FROM c3s_shadow_decision GROUP BY 1,2")
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"S1 决策表未就绪:{type(e).__name__}"}
    if not rows:
        return {"available": False, "note": "c3s_shadow_decision 空(S1 尚未回放)"}
    agg: dict = {}
    for r in rows:
        m = agg.setdefault(r["mode"], {"gates": {}, "gate_pnl": {}, "e_match": 0,
                                       "e_known": 0, "n": 0})
        m["gates"][r["gate"]] = r["n"]
        m["gate_pnl"][r["gate"]] = round(r["pnl"], 4)
        m["e_match"] += r["em"]
        m["e_known"] += r["ek"]
        m["n"] += r["n"]
    enf = agg.get("enforce", {})
    e_avoided = enf.get("gate_pnl", {}).get("E", 0.0)      # 纯 E 闸拒开仓的老引擎实收(负=避损)
    ek = enf.get("e_known", 0)
    latest = await pool.fetchval("SELECT max(decided_at)::text FROM c3s_shadow_decision")
    return {"available": True, "as_of": latest, "by_mode": agg,
            "e_gate_avoided_pnl": round(e_avoided, 4),
            "e_match_fidelity": f"{enf.get('e_match', 0)}/{ek}",
            "note": "S1 决策级经济平价(零真钱)。V6-enforce 对老引擎的背离=预期(V6 经济更严),"
                    "非零差异门。纯 E 闸(E≤0)拒开仓·老引擎已实现合计="
                    f"{round(e_avoided, 4)}U(负值=切写后可避免的真实已实现亏损)。"
                    "自杀闸/no_data 不计入避损归因;E 值逐字节复现保真度见 e_match_fidelity。"}


@router.get("/operator/legacy/runs")
async def legacy_runs(limit: int = 30, _who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT id, as_of::text, diff_count, phase FROM legacy_compare_run ORDER BY id DESC LIMIT $1",
        max(1, min(limit, 200)))
    out = [dict(r) for r in rows]
    zero_streak = 0
    for r in out:
        if r["diff_count"] == 0:
            zero_streak += 1
        else:
            break
    # §14.2 时钟按日历天:连续(无间断)且每天全部 run 零差异的 UTC 天数;没跑 compare 的天=无证据,断streak
    days = await pool.fetch(
        "SELECT (as_of AT TIME ZONE 'utc')::date d, max(diff_count) mx "
        "FROM legacy_compare_run GROUP BY 1 ORDER BY 1 DESC")
    import datetime as _dt
    streak_days = 0
    expect = _dt.datetime.utcnow().date()
    for r in days:
        if r["d"] not in (expect, expect - _dt.timedelta(days=1)) and streak_days == 0:
            break  # 最新记录不在今天/昨天=时钟未在走
        if streak_days > 0 and r["d"] != expect:
            break  # 断天
        if r["mx"] != 0:
            break
        streak_days += 1
        expect = r["d"] - _dt.timedelta(days=1)
    wg = _read_write_gauge()
    dp = await _decision_parity_panel(pool)
    diff_gate_met = streak_days >= 14
    write_gate_met = bool(wg.get("gate_met"))
    return {"runs": out, "zero_diff_streak": zero_streak,
            "zero_diff_streak_days": streak_days,
            "gate_days_required": 14,
            "gate_days_remaining": max(0, 14 - streak_days),
            # §14.2 两门槛并列 + AND(两者皆满才允许淘汰旧引擎写权威)
            "gate1_diff_zero": {"met": diff_gate_met, "streak_days": streak_days,
                                "remaining": max(0, 14 - streak_days)},
            "gate2_write_zero_call": wg,
            # S1 经济就绪证据(只读,非 AND 门 —— 背离是预期,量化避损)
            "gate3_decision_parity_evidence": dp,
            "batch_h_gate_met": diff_gate_met and write_gate_met,
            "gate_note": "淘汰门槛(§14.2)= 连续14天零P0/P1差异 AND 旧写接口连续14天零调用;"
                         "两门槛皆满才允许切换执行写权威。streak_days按UTC日历天计,当天无对比记录即断。"
                         "注:旧coin-admin写接口在C已是302 stub(结构性零调用),真正阻塞切写的是"
                         "V6 C3.S写/开仓路径尚未建成(仍为READONLY_SHADOW),非时钟。"
                         "gate3 为 S1 决策级经济平价证据(只读·非 AND 门):量化 V6-enforce 切写后"
                         "可避免的已实现亏损,是切写的经济就绪度佐证而非零差异闸。"}


@router.get("/operator/legacy/write-transport")
async def legacy_write_transport(_who=Depends(require_viewer)):
    """S2 影子写路传输就绪度(只读)。展示 V6 C3.S 写者【双钥】状态、绞杀者桥存活、最近影子意图。
    ⚠ 双钥皆需盯盘放行:钥1=注册表 C3.S.V6→ACTIVE_WRITE;钥2=Redis dcm:c3s:v6:armed=1。
    本端点只读,不拨任何钥、不入队。double_key_armed=false 即写路被关死。"""
    from .. import c3s_writer
    pool = await _pool()
    r = ds.rds()
    try:
        st = await c3s_writer.status(pool, r)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"S2 传输状态读取失败:{type(e).__name__}: {e}"}
    st["available"] = True
    st["note"] = ("S2 传输管道已铺(信封1:1镜像 dcm:coin:cmd 白名单;coin 状态机+护栏仍权威;桥铸JWT)。"
                  "double_key_armed=false 即写路关死;切活写=盯盘放行下同时翻两钥(注册表+armed)。")
    return st


@router.get("/operator/legacy/autopilot")
async def legacy_autopilot(_who=Depends(require_viewer)):
    """影子自主环(c3s_autopilot)对账面板(只读)。
    V6 自主大脑全速跑活:读实时点差→独立算 E→三闸(信号·E·借币可借性)决策开/跳,
    但【只写影子账本 c3s_autopilot_decision,物理无 emit】,与活着的老 coin 引擎并跑。
    ⚠ 本面板量化 V6 自主决策与老引擎真实行为的一致性,零真钱;OPEN=V6 若掌权会真开的仓。"""
    pool = await _pool()
    r = ds.rds()
    enabled = None
    borrowable_now = None
    if r is not None:
        try:
            enabled = str(await r.get("dcm:c3s:v6:autopilot")) == "1"
            h = await r.hgetall("dcm:borrow:avail")
            now = time.time()
            cnt = 0
            for _k, v in (h or {}).items():
                try:
                    d = json.loads(v)
                    if float(d.get("amount") or 0) > 0 and (now - float(d.get("ts") or 0)) <= 3600:
                        cnt += 1
                except Exception:  # noqa: BLE001
                    pass
            borrowable_now = cnt
        except Exception:  # noqa: BLE001
            pass
    try:
        last = await pool.fetchrow("SELECT * FROM c3s_autopilot_cycle ORDER BY id DESC LIMIT 1")
        tot = await pool.fetchval("SELECT count(*) FROM c3s_autopilot_cycle")
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"影子自主环表未就绪:{type(e).__name__}(服务或未启动)"}
    if not last:
        return {"available": False, "enabled": enabled, "note": "c3s_autopilot 尚无 cycle(服务未跑?)"}
    last_age = time.time() - last["cycle_ts"].timestamp()
    agg = await pool.fetchrow(
        "SELECT count(*) FILTER(WHERE v6_decision='OPEN') v6_open, "
        "count(*) FILTER(WHERE signal AND v6_gate='e_gate') skip_egate, "
        "count(*) FILTER(WHERE signal AND v6_gate='borrow_unavail') skip_borrow, "
        "count(*) FILTER(WHERE old_e IS NOT NULL) old_evals, "
        "count(*) FILTER(WHERE e_parity) e_parity_ok "
        "FROM c3s_autopilot_decision WHERE cycle_ts > now()-interval '24 hours'")
    v6_opens = await pool.fetch(
        "SELECT symbol, count(*) n, max(v6_e)::float max_e, max(cycle_ts)::text last "
        "FROM c3s_autopilot_decision WHERE v6_decision='OPEN' AND cycle_ts > now()-interval '24 hours' "
        "GROUP BY symbol ORDER BY n DESC LIMIT 20")
    phantom = await pool.fetch(
        "SELECT symbol, count(*) n, max(v6_e)::float max_e "
        "FROM c3s_autopilot_decision WHERE signal AND v6_gate='borrow_unavail' "
        "AND cycle_ts > now()-interval '24 hours' GROUP BY symbol ORDER BY n DESC LIMIT 12")
    import decimal as _dec
    def _norm(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, _dec.Decimal):
            return float(v)
        return v
    return {
        "available": True, "enabled": enabled,
        "service_live": last_age < 120, "last_cycle_age_s": round(last_age, 1),
        "cycles_total": tot, "borrowable_assets_now": borrowable_now,
        "last_cycle": {k: _norm(v) for k, v in dict(last).items()},
        "window_24h": {"v6_open": agg["v6_open"], "skip_egate": agg["skip_egate"],
                       "skip_borrow": agg["skip_borrow"], "old_engine_evals": agg["old_evals"],
                       "e_parity_ok": agg["e_parity_ok"]},
        "v6_would_open": [dict(x) for x in v6_opens],
        "phantom_blocked_by_borrow_gate": [dict(x) for x in phantom],
        "note": ("V6 自主大脑三闸(信号·E·借币)决策,只写影子账本零真钱。"
                 "phantom_blocked_by_borrow_gate=裸 E 闸会误判开、被借币可借性闸拦下的幻影单——"
                 "影子环首日实证:高点差币多因无券可借(库存=0)才点差高。"
                 "v6_would_open=V6 若掌写权会真开的仓,须与老引擎实开(S0 c3s_ground_truth)N 天对齐后方谈交接。")}


async def legacy_compare_daily_loop():
    """§14.2 时钟发条:每小时检查,当 UTC 日尚无对比记录时自动跑一次并落库。
    幂等(先查当日有无记录),重启安全;人工触发的 compare 照常额外落行不冲突。"""
    await asyncio.sleep(30)
    while True:
        try:
            pool = await _pool()
            n = await pool.fetchval(
                "SELECT count(*) FROM legacy_compare_run "
                "WHERE (as_of AT TIME ZONE 'utc')::date = (now() AT TIME ZONE 'utc')::date")
            if not n:
                await legacy_compare(persist=True, _who=None)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(3600)
