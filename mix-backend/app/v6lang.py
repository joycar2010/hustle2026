"""V6.1 §3/§6 三件地基:能力注册表 + 术语字典 + DataValueState 缺值契约。

铁律:
- 页面不再按未来规划虚构功能:PLANNED 产品不得出现空白可编辑表单;
- 前端不得自行猜测按钮是否可用——effective_actions 由服务端六元交集计算:
    capability ∩ role ∩ risk_policy ∩ workflow_stage ∩ device ∩ maintenance
- 默认页面只返回业务标签/原因/建议,专家详情才返回原始代码;
- 禁止把未知值写成 0 或裸 N/A:所有财务/风险字段带 {value,state,as_of,source_status}。
"""
import time
import logging

from . import datasources as ds

log = logging.getLogger("mix.v6lang")

_DDL = """CREATE TABLE IF NOT EXISTS presentation_dictionary (
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    explain TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS product_capability_registry (
    product_code TEXT PRIMARY KEY,
    capability TEXT NOT NULL CHECK (capability IN
        ('ACTIVE_WRITE','ACTIVE_READ','SHADOW','PLANNED','BLOCKED','DEPRECATED')),
    note TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""

# ── 术语字典种子(§6.1 八条 + 高频扩展;可经 API 增补,版本化) ──────────────
_DICT_SEED = [
    # (code, label, explain, category)
    ("NO_NEW_RISK", "暂停开新仓", "只禁止新增风险,已有仓位的减仓/平仓/还币不受影响", "risk_mode"),
    ("REDUCE_ONLY", "只允许减仓和还币", "该范围内不能加仓,只能往安全方向操作", "risk_mode"),
    ("EXIT_ONLY", "只允许清仓退出", "比只减仓更严格:目标是把该范围仓位全部退出", "risk_mode"),
    ("QUARANTINED", "资金/交易访问受限", "平台侧账户被限制,资金可能暂时取不出来", "risk_mode"),
    ("FROZEN", "已冻结", "该范围完全冻结,等待人工处置", "risk_mode"),
    ("WATCH", "观察中", "出现弱信号,系统加强监控但未限制交易", "risk_mode"),
    ("RECOVERY_WATCH", "恢复观察期", "刚从限制中恢复,额度按阶梯逐步放开", "risk_mode"),
    ("NORMAL", "正常", "无限制", "risk_mode"),
    ("STALE", "数据更新延迟", "超过安全时限没有新数据,系统自动禁止新增风险", "risk_mode"),
    ("RECON", "账目核对", "系统声称的仓位/账目与交易所实际逐笔比对", "ledger"),
    ("NAV bridge", "净值恒等式检查", "自动检查『净值变化-出入金』是否等于各收益类目之和,账记错会在这里暴露", "ledger"),
    ("UNMAPPED", "尚未归类的账目", "出现了系统不认识的账单类型,需要人工归类", "ledger"),
    ("DRY_RUN", "仅试算,不会下单", "把开仓意图完整走一遍校验和审批,但不触碰真金", "workflow"),
    ("Credential Epoch", "凭证版本", "API密钥换过一次版本号就加一,防止旧密钥被误用", "account"),
    ("p95", "较慢情况下的耗时", "100次里第95慢的那次耗时,反映最差体验", "stat"),
    ("p50", "一般情况下的耗时", "中位数耗时", "stat"),
    ("SHADOW", "影子验证", "系统完整跑决策但不下单,用于验证逻辑", "runtime"),
    ("CANARY", "小额试点", "用极小真金验证全链路", "runtime"),
    ("ARMED", "真实下单", "该策略会用真金执行", "runtime"),
    ("CLOSE_ONLY", "只出不进", "只管理存量仓位直到全部退出", "runtime"),
    ("Saga", "多腿执行流程", "把一次开仓/平仓拆成多步,任一步失败自动回滚", "workflow"),
    ("Intent", "交易意图", "一次『想开/想平』的完整登记,审批通过才可能变成订单", "workflow"),
    ("writer_lease", "写入控制权", "同一策略范围同时只有一个入口能下指令", "workflow"),
    ("owner_key", "组合归属键", "标记这组仓位归哪个策略管,防止两个引擎抢同一个币", "workflow"),
    ("ADL", "交易所强制减仓队列", "盈利仓位可能被交易所自动减掉一部分", "risk"),
    ("funding", "资金费", "永续合约多空双方定期互付的费用,是本系统主要收入来源", "econ"),
    ("basis", "期现价差", "现货与合约之间的价格差", "econ"),
    ("bps", "万分之一", "1bps=0.01%;『+21bps/日』即每天约万分之21的收益率", "econ"),
    ("notional", "持仓名义金额", "仓位规模按当前价折算的美元值,不是利润", "econ"),
    ("haircut", "受限资产折价", "被限制的平台上的钱按风险打折计入净值", "risk"),
    ("trapped", "暂时取不出的资金", "因平台限制暂时无法转出的权益", "risk"),
    ("VENUE_POLICY", "平台条款状态", "该平台的服务条款风险评级(未复核=先按观察处理)", "risk"),
    ("OVERRIDE", "人工指令", "操作员手动下发的风险限制或解除", "risk"),
    ("Incident", "风险事件", "系统侦测到的异常,按严重度分级(P0最高)", "risk"),
    ("PENDING_APPROVAL", "待审批", "冷却期已过,等待操作员二次认证批准", "workflow"),
    ("COOLDOWN", "冷却期", "提案创建后的强制等待时间,防止冲动操作", "workflow"),
]

# ── 能力注册表种子(§3 当前初始状态) ─────────────────────────────────────
_CAP_SEED = [
    ("C1", "ACTIVE_READ", "期现收费:统一内核持有管理中,开仓回路未建"),
    ("C2", "ACTIVE_WRITE", "跨所费差:统一工作台受控(候选→DRY_RUN→审批)"),
    ("C3.S", "ACTIVE_WRITE", "借币点差:迁移中,写经coin桥代理,受统一工作台控制"),
    ("C3.R", "ACTIVE_READ", "借贷利差:引擎shadow,只读"),
    ("C4", "PLANNED", "期现交割:尚未启用,不出现可编辑表单"),
    ("C5", "PLANNED", "永续交割:尚未启用"),
    ("C6", "PLANNED", "交割配对:尚未启用"),
    ("O1", "PLANNED", "现金流优化:数据层已建,执行回路未启用"),
    ("R1", "SHADOW", "市场效率哨兵:仅LAB"),
    ("D1", "SHADOW", "折价套利:仅LAB"),
    ("D2", "SHADOW", "固定到期折价:仅LAB"),
    ("D3", "BLOCKED", "CrossArb已证伪,KILL"),
    ("D4", "SHADOW", "固定期限利差:仅LAB"),
    ("LEGACY_C3S", "DEPRECATED", "旧C3.S坑位页:只读对比,新流程稳定后淘汰"),
]

_cache: dict = {"dict": None, "caps": None, "ts": 0}


async def ensure_seed():
    pool = await ds.pg_main()
    if pool is None:
        return
    await pool.execute(_DDL)
    for code, label, explain, cat in _DICT_SEED:
        await pool.execute(
            "INSERT INTO presentation_dictionary(code,label,explain,category) VALUES($1,$2,$3,$4) "
            "ON CONFLICT (code) DO NOTHING", code, label, explain, cat)
    for pc, cap, note in _CAP_SEED:
        await pool.execute(
            "INSERT INTO product_capability_registry(product_code,capability,note) VALUES($1,$2,$3) "
            "ON CONFLICT (product_code) DO NOTHING", pc, cap, note)


async def dictionary() -> dict:
    """{code:{label,explain,category}} 60s 进程缓存。"""
    if _cache["dict"] is not None and time.monotonic() - _cache["ts"] < 60:
        return _cache["dict"]
    pool = await ds.pg_main()
    out = {}
    if pool is not None:
        try:
            await pool.execute(_DDL)
            for r in await pool.fetch("SELECT code,label,explain,category FROM presentation_dictionary"):
                out[r["code"]] = {"label": r["label"], "explain": r["explain"], "category": r["category"]}
        except Exception as e:  # noqa: BLE001
            log.warning("dictionary: %s", e)
    _cache.update(dict=out, ts=time.monotonic())
    return out


async def capabilities() -> dict:
    """{product_code: capability} 60s 缓存;C2.H/C2.C 归并 C2。"""
    if _cache["caps"] is not None and time.monotonic() - _cache["ts"] < 60:
        return _cache["caps"]
    pool = await ds.pg_main()
    out = {}
    if pool is not None:
        try:
            await pool.execute(_DDL)
            for r in await pool.fetch("SELECT product_code,capability FROM product_capability_registry"):
                out[r["product_code"]] = r["capability"]
        except Exception as e:  # noqa: BLE001
            log.warning("capabilities: %s", e)
    _cache["caps"] = out
    return out


def cap_of(caps: dict, strategy_code: str) -> str:
    """C2.H/C2.P/C2.C→C2;未登记=PLANNED(fail-closed:未知能力不可写)。"""
    sc = str(strategy_code or "")
    if sc in caps:
        return caps[sc]
    root = sc.split(".")[0]
    return caps.get(root, "PLANNED")


# ── DataValueState(§6.2):禁止未知值写成 0 或裸 N/A ─────────────────────
def dv(value, state: str | None = None, as_of: str | None = None, source: str = "",
       reason: str = "") -> dict:
    """九态(V6.2 PATCH-01 §4.2 MetricValueEnvelope=同一权威,不建第二套):
    PRESENT/ZERO/NOT_APPLICABLE/NOT_CONNECTED/NOT_YET_AVAILABLE/WAITING_INPUT/STALE/UNDER_REVIEW/ERROR。
    reason=机器可读原因码(如 OI_SOURCE_NOT_CONNECTED/AICOIN_MAPPING_MISSING),禁止裸 N/A。"""
    if state is None:
        if value is None:
            state = "NOT_CONNECTED"
        elif isinstance(value, (int, float)) and abs(float(value)) < 1e-12:
            state = "ZERO"
        else:
            state = "PRESENT"
    out = {"value": value, "state": state, "as_of": as_of, "source_status": source}
    if reason:
        out["reason"] = reason
    return out


# ── effective_actions(§3 六元交集) ───────────────────────────────────────
def _act(code, label, kind="normal", wired=True, reason=""):
    return {"code": code, "label": label, "kind": kind, "wired": wired, "reason": reason}


def effective_actions(item: dict, caps: dict, can_open: bool, risk_capability: str,
                      maintenance_active: bool) -> tuple[list, str]:
    """按 能力∩风险∩阶段∩维护 算基础动作集;角色/设备过滤在路由层叠加。
    返回 (allowed_actions, blocking_reason)。wired=false=Pencil画了但当前只能禁用展示。"""
    stage = item.get("workflow_stage")
    sc = item.get("strategy_code") or ""
    cap = cap_of(caps, sc)
    acts: list = []
    block = ""
    risk_bad = item.get("risk_status", {}).get("level") not in (None, "NORMAL", "WATCH", "RECOVERY_WATCH")

    if cap in ("PLANNED", "BLOCKED"):
        return [_act("view", "查看", wired=True)], f"能力未启用({cap})"
    if cap == "DEPRECATED":
        return [_act("view", "只读查看", wired=True)], "旧入口只读,已进入淘汰流程"

    if stage == "DISCOVERED":
        ev = item.get("expected_net_return")
        ev_neg = ev is not None and float(ev) <= 0   # 风险调整后净期望≤0=仅观察,不给开仓入口
        openable = (can_open and not maintenance_active and not risk_bad
                    and cap == "ACTIVE_WRITE" and not ev_neg)
        if not openable:
            block = ("风险快照过期/受限,暂停新增" if not can_open else
                     "维护排空中,禁止新增" if maintenance_active else
                     f"腿平台受限:{item.get('risk_status', {}).get('reason', '')}" if risk_bad else
                     "风险调整后净期望为负,仅供观察(转正自动放开)" if ev_neg else
                     f"该产品当前{cap},不可开新仓")
        acts = [
            _act("opportunity_to_workbench", "送入工作台(试算不下单)", "primary", wired=openable, reason=block),
            _act("opportunity_watch", "加入观察"),
            _act("opportunity_ignore", "忽略"),
            _act("view_basis", "查看依据"),
        ]
    elif stage == "RESEARCH":
        # C2.P 人工研判(PATCH-01 §3):研判只产结论,不产订单;生成计划=新增风险类
        openable = (can_open and not maintenance_active and not risk_bad and cap == "ACTIVE_WRITE")
        if not openable:
            block = ("风险快照过期/受限,暂停新增" if not can_open else
                     "维护排空中,禁止新增" if maintenance_active else
                     f"腿平台受限:{item.get('risk_status', {}).get('reason', '')}" if risk_bad else
                     f"该产品当前{cap},不可生成计划")
        done = str(item.get("research_status") or "") == "COMPLETED"
        prep = str(item.get("research_decision") or "") == "PREPARE_PLAN"
        acts = [
            _act("open_research", "打开研判", "primary" if not (done and prep) else "normal"),
            _act("create_manual_plan", "生成人工计划(DRY_RUN)", "primary" if (done and prep) else "normal",
                 wired=(openable and done and prep),
                 reason=(block or ("" if (done and prep) else
                                   "先完成研判(阶段/依据/风险/结论)" if not done else
                                   "研判结论=继续观察;生成计划需结论为『准备计划』"))),
            _act("workitem_ack", "确认知悉"),
        ]
    elif stage == "REVIEW":
        # 只有真实提案(position_intent_id=dryrun:N)才发审批动作;opener送入工作台的REVIEW项
        # 没有提案,下一步=研判→生成计划(否则"二次认证批准"按钮指向不存在的提案=断头路)
        if str(item.get("position_intent_id") or "").startswith("dryrun:"):
            acts = [_act("proposal_approve", "二次认证批准", "primary"),
                    _act("proposal_reject", "驳回", "danger")]
        else:
            acts = [_act("open_research", "打开研判(试算前置)", "primary"),
                    _act("create_manual_plan", "生成计划(DRY_RUN)", "normal",
                         wired=False, reason="先完成研判,结论=『准备计划』后自动放开"),
                    _act("opportunity_ignore", "忽略", "danger")]
    elif stage == "RESERVED":
        acts = [_act("view", "查看(已批准·试算终态,不下单)")]
    elif stage in ("EXECUTING", "HOLDING"):
        if item.get("automation_mode") == "AUTO":
            acts.append(_act("workitem_takeover", "人工接管(冻结自动新增)"))
        acts.append(_act("close_preview", "平仓预演(前后风险对比)"))
        if sc == "C3.S":
            acts += [_act("c3_partial_repay", "部分还币"),
                     _act("c3_force_close", "平仓买回", "danger")]
        acts.append(_act("workitem_ack", "确认知悉"))
    elif stage == "EXITING":
        acts = [_act("close_preview", "退出进度与预演")]
        if sc == "C3.S":
            acts.append(_act("c3_partial_repay", "还币", "primary"))
        acts.append(_act("workitem_ack", "确认知悉"))
    elif stage == "RECONCILING":
        acts = [_act("goto_risk_center", "进风险中心修复", "danger"),
                _act("workitem_ack", "确认知悉")]
    else:
        acts = [_act("view", "查看")]
    return acts, block


MOBILE_ACT_WHITELIST = {"opportunity_watch", "opportunity_ignore", "workitem_ack",
                        "close_preview", "c3_partial_repay", "view", "view_basis",
                        "goto_risk_center", "pause_new_risk"}

# 新增风险类动作(still_allowed 反选集;训练门禁/禁用三行式共用)
RISK_ADDING_ACTS = {"opportunity_to_workbench", "proposal_dry_run", "create_manual_plan"}


# ── WorkItem v2.2 状态机叙述器(V6.2 §4):what_happened/system_did/
#    completion_condition/next_trigger 由确定性模板生成——AI 只许解释,不许决定 ──
def narrate(item: dict, acts: list) -> dict:
    """按 source×stage 生成四段运营叙述 + still_allowed。绝不编造数字:
    只引用工作项已有事实字段;信息不足时写『见详情』而不是猜。"""
    src = item.get("source")
    stage = item.get("workflow_stage")
    sc = item.get("strategy_code") or ""
    sym = item.get("symbol") or ""
    ev = item.get("expected_net_return")
    pnl = item.get("confirmed_pnl")
    detail = item.get("stage_detail") or ""
    ddl = item.get("next_deadline")
    auto = item.get("automation_mode")
    risk = item.get("risk_status") or {}

    what, did, done_when, trigger = "", "", "", ""
    if stage == "DISCOVERED":
        evs = f"风调后期望 {ev:+.1f}bps/日" if ev is not None else "期望待算"
        what = f"顾问扫描出候选:{sym}({item.get('route') or sc}),{evs}"
        did = "已过净期望闸+资格矩阵校验" + (";期望含平台风险扣减(RiskCharge)" if risk.get("level") not in (None, "NORMAL") else "")
        if ev is not None and ev <= 0:
            done_when = "风调后期望转正后可送入工作台"
            trigger = "费差回摆或平台限制解除→自动放开按钮"
        else:
            done_when = "送入工作台并完成审批链"
            trigger = "点击送入→DRY_RUN 冷却→二次认证"
    elif stage == "RESEARCH":
        rs = item.get("research_status") or "PENDING"
        what = f"{sc or '人工'} 人工研判:{sym} {detail or ('研判完成,可生成计划' if rs == 'COMPLETED' else '待完成研判')}"
        did = "已登记研判案件;AiCoin 仅作证据参考,官方快照是开仓硬闸唯一数据源"
        done_when = ("生成人工计划并进入 DRY_RUN 审批链" if rs == "COMPLETED"
                     else "完成四步研判(阶段/依据/风险/结论)")
        trigger = "研判结论=准备计划 → 生成计划按钮放开"
    elif stage == "REVIEW":
        if str(item.get("position_intent_id") or "").startswith("dryrun:"):
            what = f"提案已创建({detail}),经济快照已锁定"
            did = "冷却期防冲动;到期自动转待审批"
            done_when = "二次认证批准或驳回"
            trigger = "冷却到期自动进入待审批"
        else:
            what = f"候选已送入工作台({detail}),尚未生成提案"
            did = "登记操作员意向;费差/风险持续跟踪中"
            done_when = "完成研判并生成计划(DRY_RUN)"
            trigger = "研判结论=准备计划 → 提案进入冷却/审批链"
    elif stage == "RESERVED":
        what = "提案已批准(试算终态,未下真单)"
        did = "记录人工意图;真实下单须专场放行(armed)"
        done_when = "armed 专场放行后进入执行"
        trigger = "等待专场授权"
    elif stage in ("EXECUTING", "HOLDING"):
        pnls = f",已确认 {pnl:+.1f}U" if pnl is not None else ""
        what = f"{detail or '持有中'}{pnls}"
        did = ("引擎自动管理中(异常自动转人工)" if auto == "AUTO"
               else "内核按已批准配置持有,关键步骤需确认")
        done_when = ("买回+还币+账本确认" if sc == "C3.S" else "退出条件触发或人工平仓确认后两腿平净")
        trigger = f"{ddl} 资金费结算" if ddl and ":" in str(ddl) else (ddl or "见组合详情")
    elif stage == "EXITING":
        what = f"退出进行中:{detail}"
        did = "限价单收敛中,系统按容差追单"
        done_when = ("还币完成+账本确认" if sc == "C3.S" else "两腿平净+账本确认")
        trigger = ddl or "成交即推进"
    elif stage == "RECONCILING":
        what = f"异常:{detail}"
        did = "已冻结该范围新增;修复路径已就绪"
        done_when = "差异归零且账目核对通过"
        trigger = "修复完成自动关闭;超时升级人工"
    else:
        what = detail or "已完成"
        did = "账本已确认"
        done_when = "无需操作"
        trigger = "—"

    still = [a["label"] for a in acts
             if a.get("wired") and a["code"] not in RISK_ADDING_ACTS and a["code"] != "view"]
    return {"what_happened": what, "system_did": did,
            "completion_condition": done_when, "next_trigger": trigger,
            "still_allowed": still}


def filter_actions_for_device(acts: list, mobile: bool) -> list:
    """§8.3 手机白名单:不在白名单的动作直接不出现(不是禁用,是不渲染)。"""
    if not mobile:
        return acts
    return [a for a in acts if a["code"] in MOBILE_ACT_WHITELIST]
