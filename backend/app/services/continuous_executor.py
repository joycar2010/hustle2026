"""Continuous Strategy Executor - Automated Trading with Trigger Management"""
import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from uuid import UUID

from app.models.account import Account
from app.services.order_executor_v2 import OrderExecutorV2
from app.services.position_manager import PositionManager, position_manager
from app.services.trigger_manager import TriggerCountManager, CompareOperator
from app.services.market_service import market_data_service
from app.services.strategy_status_pusher import status_pusher
from app.utils.quantity_converter import quantity_converter
from app.core.config import settings


logger = logging.getLogger(__name__)

# ── 共享 httpx 客户端(MT5 bridge health): 消除反复创建AsyncClient触发C层SSL重建阻塞事件循环 ──
# 同 [[testgo-event-loop-ssl-stall]] 根治模式。所有 _connection_down_reason 共用此单例。
import httpx as _httpx_shared
_mt5_health_client: _httpx_shared.AsyncClient | None = None

def _get_mt5_health_client() -> _httpx_shared.AsyncClient:
    global _mt5_health_client
    if _mt5_health_client is None or _mt5_health_client.is_closed:
        _mt5_health_client = _httpx_shared.AsyncClient(timeout=4.0)
    return _mt5_health_client



def _get_pair_config(pair_code: str = "XAU"):
    """Get symbol names and conversion factor from hedging pair config, with fallback"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        pair = hedging_pair_service.get_pair(pair_code)
        if pair:
            return pair.symbol_a.symbol, pair.symbol_b.symbol, pair.conversion_factor
    except Exception:
        pass
    return "XAUUSDT", "XAUUSD+", 100.0


_sl_filter_cache = {"ts": 0.0, "val": None}


def _single_leg_pair_label(pair_code: str) -> str:
    """单腿告警品种中文名(前缀匹配, 多交易对下告警区分品种)。未知→回退pair_code。"""
    pc = (pair_code or "").upper()
    if "XAU" in pc:
        return "黄金"
    if "XAG" in pc:
        return "白银"
    if pc.startswith("CL") or "USO" in pc or "XTI" in pc or "WTI" in pc:
        return "美原油"
    if pc.startswith("BZ") or "UKO" in pc or "XBR" in pc or "BRN" in pc:
        return "布伦特原油"
    if pc.startswith("NG") or "XNG" in pc or "NATGAS" in pc:
        return "天然气"
    return pair_code or "未知品种"


def _load_single_leg_filter():
    """单腿告警噪音过滤阈值（热读 config/single_leg_filter.json，5s 缓存，fail-open 到默认）。
    - min_trade_xau: 本笔 A 腿成交量低于此值视为碎单、直接跳过单腿检测（默认 1.0 XAU = 0.01 手最小步长）。
    - min_gap_xau:   总缺口低于此值不告警（默认 10.0 XAU = 0.1 手），抑制亚手/碎单噪音。
    真单腿（裸敞口 >= min_gap_xau）不受影响；纯过滤“显示侧”噪音，不改下单/对冲路径。"""
    import os as _os, time as _t, json as _j
    _now = _t.time()
    c = _sl_filter_cache
    if c["val"] is not None and (_now - c["ts"]) < 5.0:
        return c["val"]
    val = {"min_trade_xau": 1.0, "min_gap_xau": 10.0, "delta_gap_xau": 16.0,
           "hard_gap_xau": 60.0, "gold_abs_gap_xau": 0.6, "gold_pct_gap": 0.05,
           "enabled": True}
    try:
        _p = _os.path.join(_os.path.dirname(__file__), "..", "..", "config", "single_leg_filter.json")
        with open(_p, "r", encoding="utf-8") as _f:
            data = _j.load(_f)
        if isinstance(data, dict):
            for k in ("min_trade_xau", "min_gap_xau", "delta_gap_xau",
                      "hard_gap_xau", "gold_abs_gap_xau", "gold_pct_gap"):
                if k in data and isinstance(data[k], (int, float)):
                    val[k] = float(data[k])
            if "enabled" in data:
                val["enabled"] = bool(data["enabled"])
    except Exception:
        pass
    c["ts"] = _now
    c["val"] = val
    return val



# ── 黄金净敞口周期对账(2026-07-06) ──────────────────────────────────────────
# 背景: 单腿检测原为纯"成交事件驱动"(Step 8.5 在 exec_result 返回后才spawn),
# 执行器体外形成的持仓变化——孤儿挂单成交(cq002 0706: 25s总超时cancel监控协程
# 但交易所挂单未撤, 20 XAU无人对冲成交)、外部平仓、强平——没有 exec_result,
# 永远不会被看见, 直到下一笔策略成交。本对账器以45s周期独立协程实查两腿带号
# 净持仓, 判定与黄金地板同口径(|币安净+MT5净|>gold_abs_gap_xau 或 >两腿较大
# 净仓×gold_pct_gap), 只读+告警, 永不下单/撤单/停策略。与下单/对冲协程零共享
# 状态, 不在A腿成交→B腿发单链路上, 对成交速度无影响(每对每45s一次轻量查询)。
# 告警复用 _send_single_leg_alert(弹框+飞书+跑马灯), 本地300s冷却; 缺口未消除
# 会持续重报——登出窗口错过的弹框, 登回来后下一轮必再弹。
_RECON_EXECUTORS = {}
_RECON_TASK = None
_RECON_LAST_ALERT = {}
_RECON_INTERVAL_S = 45.0
_RECON_COOLDOWN_S = 300.0


def _recon_ensure_started() -> None:
    """确保全局对账协程在跑。20260707起由 app 启动时调用(原懒启动依赖首个执行器
    注册 — 后端重启后若无策略运行, 对账器永不启动, 与"只盯运行中策略"叠加成
    双重盲区, cq002 停策略+残留挂单成交裸多11 XAU全程零告警即此)。"""
    global _RECON_TASK
    try:
        if _RECON_TASK is None or _RECON_TASK.done():
            _RECON_TASK = asyncio.create_task(_gold_net_recon_loop())
    except Exception:
        pass


def _recon_register(ex) -> None:
    """执行器启动时兜底拉起对账协程(目标清单已改DB全量, 注册表仅留作诊断)。"""
    try:
        _RECON_EXECUTORS[ex.strategy_id] = ex
    except Exception:
        pass
    _recon_ensure_started()


_RECON_TARGETS_CACHE = {"ts": 0.0, "items": []}
_RECON_PENDING = {}  # tkey -> 上次越限时刻(连续两周期确认, 滤在途对冲瞬时敞口)
_RECON_SWEEP_TS = {}  # (account_id,pair) -> 上次孤儿挂单清扫时刻(300s节流)
_RECON_BN_CLIENTS = {}  # account_id -> BinanceFuturesClient(复用, 防SSL上下文反复重建)


async def _recon_targets():
    """对账目标=「用户已绑定A+B账户」的XAU族交易对全量(DB直查, 60s缓存)。
    20260707改: 不再依赖运行中执行器 — 持仓的存在不以策略运行为前提(停策略后的
    残留挂单成交/外部平仓/强平都发生在执行器体外), 对账目标必须以「账户绑定」为
    准而非「策略在跑」。hedge_multiplier≠1 的用户对(放大对冲天然净敞口)跳过。"""
    import time as _t
    c = _RECON_TARGETS_CACHE
    now = _t.time()
    if c["items"] and now - c["ts"] < 60.0:
        return c["items"]
    items = []
    try:
        from sqlalchemy import text as _sqt_t
        from app.core.database import AsyncSessionLocal as _ASL_t
        from types import SimpleNamespace as _NS
        async with _ASL_t() as db:
            rows = (await db.execute(_sqt_t("""
                SELECT upa.user_id::text, upa.pair_code,
                       aa.account_id::text, aa.api_key, aa.api_secret, aa.proxy_config,
                       ab.account_id::text,
                       COALESCE(MAX(COALESCE(sc.hedge_multiplier, 1)), 1) AS hm
                FROM user_pair_accounts upa
                JOIN accounts aa ON aa.account_id = upa.account_a_id
                JOIN accounts ab ON ab.account_id = upa.account_b_id
                LEFT JOIN strategy_configs sc
                       ON sc.user_id = upa.user_id AND sc.pair_code = upa.pair_code
                -- 20260716: 过滤停用账户 — cq987/xy123的旧绑定引用disabled无代理账户,
                -- recon拿死key直连币安每45s撞一次-2015白名单错(纯噪音, 键都认证不过,
                -- 对账零价值)。停用=用户明示弃用, 不进对账目标。
                WHERE aa.is_active = TRUE AND COALESCE(aa.status, 'active') = 'active'
                  AND ab.is_active = TRUE AND COALESCE(ab.status, 'active') = 'active'
                GROUP BY 1,2,3,4,5,6,7
            """))).all()
        for uid, pc, a_id, a_key, a_sec, a_proxy, b_id, hm in rows:
            # 20260707c: 不再按金族过滤 — 净敞口检查在 _recon_two_leg_net 内只对
            # XAU族生效, 但孤儿挂单清扫须覆盖全部品种(NG/油/银的残留挂单同样会
            # 被行情打成交形成单腿)。
            items.append((
                uid, pc,
                _NS(account_id=a_id, api_key=a_key, api_secret=a_sec, proxy_config=a_proxy),
                _NS(account_id=b_id),
                float(hm or 1),
            ))
    except Exception as e:
        logger.warning(f"[GOLD_RECON] targets query failed: {e}")
        return c["items"]  # 查询失败沿用旧目标, 不清空
    c["ts"], c["items"] = now, items
    return items


async def _recon_two_leg_net(pair_code, acc_a, acc_b):
    """实查两腿带号净持仓(XAU单位)。任一侧失败返回None——宁可本轮跳过, 绝不拿0误报。
    20260707: 参数由执行器实例改为账户凭证(DB驱动目标), 币安客户端按account_id
    模块级复用(防60s缓存刷新导致客户端/SSL上下文反复重建)。"""
    sym_a, sym_b, conv = _get_pair_config(pair_code)
    # 20260708: 取消金族限制 — 换算系数已按对全部核正, 净敞口口径对所有品种成立
    if acc_a is None or acc_b is None:
        return None
    _cli = _RECON_BN_CLIENTS.get(acc_a.account_id)
    if _cli is None:
        from app.services.binance_client import BinanceFuturesClient as _BFC_rc
        from app.core.proxy_utils import build_proxy_url as _bpu_rc
        _cli = _BFC_rc(acc_a.api_key, acc_a.api_secret,
                       proxy_url=_bpu_rc(acc_a.proxy_config))
        _RECON_BN_CLIENTS[acc_a.account_id] = _cli
    _pos = await asyncio.wait_for(_cli.get_position_risk(symbol=sym_a), timeout=8.0)
    b_net = sum(float(p.get('positionAmt', 0)) for p in _pos)
    from app.models.mt5_client import MT5Client as _MC_rc
    from app.core.database import AsyncSessionLocal as _ASL_rc
    from sqlalchemy import select as _sel_rc
    import httpx as _hx_rc
    import os as _os_rc
    async with _ASL_rc() as _db:
        _mc = (await _db.execute(
            _sel_rc(_MC_rc)
            .where(_MC_rc.account_id == acc_b.account_id)
            .where(_MC_rc.is_active == True)
            .where(_MC_rc.is_system_service == False)
            .order_by(_MC_rc.priority).limit(1)
        )).scalar_one_or_none()
    if not _mc:
        return None
    _bridge = _mc.bridge_url or f"http://172.31.14.113:{_mc.bridge_service_port}"
    _key = _os_rc.getenv("MT5_API_KEY", "")
    _hdr = {"X-Api-Key": _key} if _key else {}
    async with _hx_rc.AsyncClient(timeout=3.0) as _hc:  # 桥是VPC内网纯http, 无SSL上下文重建之忧
        _r = await _hc.get(f"{_bridge}/mt5/positions", headers=_hdr)
        if _r.status_code != 200:
            return None
        _body = _r.json()
        _pl = _body if isinstance(_body, list) else _body.get("positions", [])
    m_net_lot = sum((1.0 if int(p.get("type", 0)) == 0 else -1.0) * abs(float(p.get("volume", 0)))
                    for p in _pl if p.get("symbol", "") == sym_b)
    return b_net, m_net_lot * conv


def _has_running_executor(uid, pc) -> bool:
    """该用户×对当前是否有运行中执行器(注册表实时判定, 运行中=挂单有主人不清扫)。"""
    for ex in list(_RECON_EXECUTORS.values()):
        try:
            if getattr(ex, 'is_running', False) and str(getattr(ex, 'user_id', '')) == str(uid) \
                    and getattr(ex, 'pair_code', None) == pc:
                return True
        except Exception:
            continue
    return False


async def _sweep_orphan_orders(uid, pc, acc_a):
    """孤儿s-挂单清扫(2026-07-07c, 20260716扩)。形成机制: 执行器仅在"下次下单前"清理
    遗留挂单(Step7.9, 且8s超时会跳过), 停止/崩溃/重启路径零撤单 → 在途maker挂单
    永久残留, 被行情打成交=无人对冲(cq002 7/6两次事故均此机制)。
    两种场景:
    ① 无运行中执行器: A侧存在任何s-策略挂单 → 全撤(原逻辑)。
    ② 运行中执行器(20260716新增): 25s总超时cancel监控协程后挂单无人看管, 而策略
       本身仍在跑/被用户秒重开 → 旧逻辑因running直接跳过, 孤儿单悬14.5min直到手撤
       (0716 06:36事故)。新判据: s-挂单 (a)下单龄>90s(正常maker单生命周期≤~15s)
       且 (b)不在_order_fill_events(无活跃监控协程) → 判悬挂孤儿, 撤掉+单腿告警。
    只撤s-单(m-手动单只能由用户Cancel-All撤, 既有约定); 每账户×对60s节流(原300s,
    悬挂孤儿检出要快); 查询/撤单失败静默, 下轮再试。"""
    import time as _t
    _k = (acc_a.account_id, pc)
    now = _t.time()
    if now - _RECON_SWEEP_TS.get(_k, 0.0) < 60.0:
        return
    _RECON_SWEEP_TS[_k] = now
    _running = _has_running_executor(uid, pc)
    sym_a, _, _ = _get_pair_config(pc)
    if not sym_a:
        return
    _cli = _RECON_BN_CLIENTS.get(acc_a.account_id)
    if _cli is None:
        from app.services.binance_client import BinanceFuturesClient as _BFC_sw
        from app.core.proxy_utils import build_proxy_url as _bpu_sw
        _cli = _BFC_sw(acc_a.api_key, acc_a.api_secret,
                       proxy_url=_bpu_sw(acc_a.proxy_config))
        _RECON_BN_CLIENTS[acc_a.account_id] = _cli
    try:
        open_orders = await asyncio.wait_for(_cli.get_open_orders(symbol=sym_a), timeout=8.0)
    except Exception:
        return
    own = [o for o in (open_orders or []) if str(o.get("clientOrderId", "")).startswith("s-")]
    if _running and own:
        # 场景②: 只清"超龄且无人监控"的悬挂孤儿, 正被监控协程盯着的在途单绝不碰
        try:
            from app.tasks.broadcast_tasks import _order_fill_events as _evt_sw
        except Exception:
            _evt_sw = {}
        _now_ms = _t.time() * 1000.0
        own = [o for o in own
               if (_now_ms - float(o.get("time", _now_ms) or _now_ms)) > 90_000.0
               and o.get("orderId") not in _evt_sw
               and str(o.get("orderId")) not in _evt_sw]
    if not own:
        return
    ok = 0
    for od in own:
        try:
            await asyncio.wait_for(_cli.cancel_order(sym_a, od["orderId"]), timeout=5.0)
            ok += 1
        except Exception:
            pass
    if _running:
        _qty_sw = sum(float(o.get("origQty", 0) or 0) for o in own)
        logger.error(
            f"[GOLD_RECON] 悬挂孤儿挂单清扫(运行中): user={uid} pair={pc} 发现{len(own)}笔超龄(>90s)"
            f"且无监控协程的s-挂单(合计{_qty_sw:g}), 已撤{ok}笔 — 成因通常为25s总超时cancel监控协程, "
            f"若频繁出现请查执行耗时/REST阻塞")
        # 推送告警(复用单腿告警通道, 事件真相是"悬挂孤儿已自动撤", 不是已成交单腿)
        try:
            from types import SimpleNamespace as _NS_sw
            _shim_sw = _NS_sw(user_id=str(uid), pair_code=pc)
            await asyncio.wait_for(ContinuousStrategyExecutor._send_single_leg_alert(_shim_sw,
                strategy_type='reverse_opening',
                exec_result={'single_leg_details': {
                    'binance_filled': 0, 'bybit_filled': 0,
                    'unfilled_qty': round(_qty_sw, 4),
                    'error': f'悬挂孤儿挂单x{len(own)}已自动撤{ok}笔(挂龄>90s无监控协程)',
                    'trigger': 'ORPHAN_ORDER_SWEEP',
                    'verification_method': 'orphan_order_sweep',
                }}), timeout=15.0)
        except Exception as _ae_sw:
            logger.warning(f"[GOLD_RECON] 悬挂孤儿告警发送失败: {_ae_sw}")
    else:
        logger.error(
            f"[GOLD_RECON] 孤儿挂单清扫: user={uid} pair={pc} 无运行中策略但A侧残留{len(own)}笔s-策略挂单, "
            f"已撤{ok}笔 — 残留挂单成交即历史单腿事故根源, 若持续出现请检查策略停止流程")


_REPAIRED_ORDERS = {}   # order_id -> ts, 补腿幂等闸(触发源唯一=本进程崩溃现场, 进程内即全局)
_REPAIR_TASKS = set()   # 强引用防task被GC(mt5-agent同款坑)


async def _crash_repair_leg(ex, ctx, ladder_idx, strategy_type, binance_account, bybit_account):
    """崩溃自动补腿(20260716)。把崩溃路径从"只告警靠人工"升级为"自动补腿+告警"。
    三道闸保证与手动交易绝缘:
    ① 触发源限定: 只由策略执行协程崩溃现场触发(绝不由净敞口对账触发 —— 净敞口
       混手动仓, 按敞口补会把手动单当缺口);
    ② 对象限定: 补腿量 = ctx里本次策略订单order_id的REST实查成交 - 已对冲量,
       clientOrderId须s-前缀(手动m-单从源头进不了ctx);
    ③ 幂等: 每order_id仅补一次 + 按增量对冲进度扣减, 防双补; 桥单失败回退告警等人工。
    以独立task运行: 不随ladder task被强杀; 每个远程调用独立短超时; 成败都发跟进
    告警(带真实成交数字), 成功文案明示"无需人工"消除人工双补竞态。"""
    import time as _t
    import math as _m
    order_id = ctx.get("order_id")
    if not order_id or not ctx.get("repair_armed"):
        return
    if order_id in _REPAIRED_ORDERS:
        return
    _REPAIRED_ORDERS[order_id] = _t.time()
    if len(_REPAIRED_ORDERS) > 500:
        for _k in list(_REPAIRED_ORDERS)[:250]:
            _REPAIRED_ORDERS.pop(_k, None)
    coid = str(ctx.get("client_order_id") or "")
    if not coid.startswith("s-"):
        # 20260716b 严格身份闸(P0): 空/缺失/非s-一律拒绝自动补腿(只告警等人工)。
        # 身份不明的单宁可人工处理也不自动动仓, 与"手动m-单绝缘"同级铁律。
        logger.error(f"[AUTO_REPAIR] 拒绝补腿: order={order_id} clientOrderId={coid!r} 非s-策略单/身份缺失")
        _REPAIRED_ORDERS.pop(order_id, None)
        try:
            await asyncio.wait_for(ex._send_single_leg_alert(
                strategy_type=strategy_type,
                exec_result={"single_leg_details": {
                    "binance_filled": 0, "bybit_filled": 0, "unfilled_qty": 0,
                    "error": f"[崩溃补腿] 订单{order_id}身份缺失(clientOrderId={coid!r}), 拒绝自动补腿, 请人工核对",
                    "trigger": "AUTO_REPAIR_IDENTITY_REFUSED",
                    "verification_method": "crash_auto_repair",
                }}), timeout=15.0)
        except Exception:
            pass
        return
    hedged = float(ctx.get("hedged_xau", 0) or 0)
    filled = None
    lot = 0.0
    # 20260716b 有限重试+去重时点修正(P0): 旧实现幂等标记先占位、单次核查失败
    # 即放弃 → 一次瞬时网络失败让该单永久失去补腿资格。改为核查重试3次(2/4/6s
    # 退避); 全部失败时释放幂等位再请人工 — 此时未做任何补腿动作, 释放是安全的。
    for _try_i in range(3):
        try:
            st = await asyncio.wait_for(
                ex.order_executor.base_executor.check_binance_order_status(
                    binance_account, ctx["symbol"], order_id), timeout=8.0)
            if st and st.get("success"):
                filled = float(st.get("filled_qty", 0) or 0)
                break
        except Exception as _e:
            logger.error(f"[AUTO_REPAIR] REST核查失败(第{_try_i+1}/3次) order={order_id}: {_e!r}")
        if _try_i < 2:
            await asyncio.sleep(2.0 * (_try_i + 1))
    if filled is None:
        _REPAIRED_ORDERS.pop(order_id, None)
        outcome = f"补腿核查3次均失败(REST不可用), 已释放幂等位, 请人工核对 order={order_id}"
    else:
        gap = filled - hedged
        mult = float(ctx.get("hedge_multiplier", 1) or 1)
        try:
            from app.services.order_executor_v2 import _a_to_b as _a2b_rp
            raw_lot = _a2b_rp(gap, ex.pair_code) * mult
        except Exception:
            raw_lot = quantity_converter.xau_to_lot(gap) * mult
        lot = _m.floor(round(raw_lot * 100, 4)) / 100.0
        if gap <= 0 or lot < 0.01:
            logger.warning(f"[AUTO_REPAIR] 无需补腿: order={order_id} filled={filled} hedged={hedged}")
            return
        side = "Buy" if ctx.get("hedge_is_buy") else "Sell"
        close_pos = bool(ctx.get("hedge_close_position"))
        logger.error(f"[AUTO_REPAIR] 崩溃补腿开始: order={order_id} filled={filled} hedged={hedged} "
                     f"→ B侧 {side} {lot} lot ({ctx.get('sym_b')}, close={close_pos})")
        async def _fire_repair():
            return await asyncio.wait_for(
                ex.order_executor.base_executor.place_bybit_order(
                    account=bybit_account, symbol=ctx["sym_b"], side=side,
                    order_type="Market", quantity=str(round(lot, 2)),
                    close_position=close_pos), timeout=20.0)
        # 20260716b 未知≠失败(P0): 桥超时/异常=结果未知(可能已成交), 绝不盲目
        # 重发(防双补), 保留幂等占位并请人工核对; 桥明确回失败(拿到了响应)才
        # 安全重试一次。
        _unknown = False
        try:
            res = await _fire_repair()
        except Exception as _pe:
            res, _unknown = {"success": False, "error": repr(_pe)}, True
        if not _unknown and not res.get("success"):
            logger.warning(f"[AUTO_REPAIR] 桥明确拒单({res.get('error')}), 3s后重试一次 order={order_id}")
            await asyncio.sleep(3.0)
            try:
                res = await _fire_repair()
            except Exception as _pe2:
                res, _unknown = {"success": False, "error": repr(_pe2)}, True
        if _unknown:
            outcome = (f"补腿结果未知(桥无响应): B侧 {side} {lot} lot 可能已成交, "
                       f"已锁定幂等位防重复下单, 请人工核对MT5持仓后处理")
            logger.error(f"[AUTO_REPAIR] 补腿未知 order={order_id}: {outcome}")
        elif res.get("success"):
            outcome = f"已自动补腿 {lot} lot (B侧{side}, ticket={res.get('order_id')}), 无需人工"
            logger.error(f"[AUTO_REPAIR] 补腿成功: order={order_id} {outcome}")
            if 'opening' in strategy_type:
                try:  # 账本同步记账, 前端策略持仓不再漏显本笔(平仓方向账本由对账兜)
                    ex.position_mgr.record_opening(ex.strategy_id, ladder_idx, strategy_type, gap)
                except Exception as _le:
                    logger.warning(f"[AUTO_REPAIR] 账本记录失败(不影响补腿): {_le}")
        else:
            outcome = f"自动补腿失败({res.get('error')}), 请人工补 {lot} lot"
            logger.error(f"[AUTO_REPAIR] 补腿失败: order={order_id} {outcome}")
    try:
        await asyncio.wait_for(ex._send_single_leg_alert(
            strategy_type=strategy_type,
            exec_result={"single_leg_details": {
                "binance_filled": filled if filled is not None else 0,
                "bybit_filled": hedged,
                "unfilled_qty": (filled - hedged) if filled is not None else 0,
                "error": f"[崩溃补腿] {outcome}",
                "trigger": "AUTO_REPAIR",
                "verification_method": "crash_auto_repair",
            }}), timeout=15.0)
    except Exception as _ae:
        logger.warning(f"[AUTO_REPAIR] 跟进告警发送失败: {_ae}")


async def _recon_binance_net(acc_a, sym_a):
    """A腿带号净持仓(A单位)。客户端按account_id模块级复用(防SSL重建)。"""
    _cli = _RECON_BN_CLIENTS.get(acc_a.account_id)
    if _cli is None:
        from app.services.binance_client import BinanceFuturesClient as _BFC_rc2
        from app.core.proxy_utils import build_proxy_url as _bpu_rc2
        _cli = _BFC_rc2(acc_a.api_key, acc_a.api_secret,
                        proxy_url=_bpu_rc2(acc_a.proxy_config))
        _RECON_BN_CLIENTS[acc_a.account_id] = _cli
    _pos = await asyncio.wait_for(_cli.get_position_risk(symbol=sym_a), timeout=8.0)
    return sum(float(p.get('positionAmt', 0)) for p in _pos)


async def _recon_mt5_net_units(acc_b, sym_b, conv):
    """B腿带号净持仓(折A单位)。桥查询失败返回None(绝不拿0误报)。"""
    from app.models.mt5_client import MT5Client as _MC_rc2
    from app.core.database import AsyncSessionLocal as _ASL_rc2
    from sqlalchemy import select as _sel_rc2
    import httpx as _hx_rc2
    import os as _os_rc2
    async with _ASL_rc2() as _db:
        _mc = (await _db.execute(
            _sel_rc2(_MC_rc2)
            .where(_MC_rc2.account_id == acc_b.account_id)
            .where(_MC_rc2.is_active == True)
            .where(_MC_rc2.is_system_service == False)
            .order_by(_MC_rc2.priority).limit(1)
        )).scalar_one_or_none()
    if not _mc:
        return None
    _bridge = _mc.bridge_url or f"http://172.31.14.113:{_mc.bridge_service_port}"
    _key = _os_rc2.getenv("MT5_API_KEY", "")
    _hdr = {"X-Api-Key": _key} if _key else {}
    async with _hx_rc2.AsyncClient(timeout=3.0) as _hc:
        _r = await _hc.get(f"{_bridge}/mt5/positions", headers=_hdr)
        if _r.status_code != 200:
            return None
        _body = _r.json()
        _pl = _body if isinstance(_body, list) else _body.get("positions", [])
    m_net_lot = sum((1.0 if int(p.get("type", 0)) == 0 else -1.0) * abs(float(p.get("volume", 0)))
                    for p in _pl if p.get("symbol", "") == sym_b)
    return m_net_lot * float(conv or 0)


async def _sibling_binance_net(uid, pair_code, sym_b):
    """20260708 共享B品种组口径: 同用户其它共享同一MT5品种(等conv)交易对的A腿净合计。
    供成交后Phase2并入, 防把姊妹对(ICXAU↔PAXG共用XAUUSD)的对冲腿当成本对裸敞口。
    复用 _recon_targets 缓存的账户凭证与客户端。"""
    _sa_self, _sb_self, _cv_self = _get_pair_config(pair_code)
    total = 0.0
    targets = await _recon_targets()
    seen = set()
    for t_uid, t_pc, t_acc_a, t_acc_b, t_hm in targets:
        if str(t_uid) != str(uid) or t_pc == pair_code:
            continue
        t_sa, t_sb, t_cv = _get_pair_config(t_pc)
        if t_sb != sym_b or not t_sa:
            continue
        if abs(float(t_cv or 0) - float(_cv_self or 0)) > 1e-9:
            continue  # conv不一致无法合并(周期对账会对该组警示)
        k = (t_acc_a.account_id, t_sa)
        if k in seen:
            continue
        seen.add(k)
        total += await _recon_binance_net(t_acc_a, t_sa)
    return total


async def _gold_net_recon_loop():
    """45s周期黄金净敞口对账。只读+告警, 永不干预交易。"""
    logger.info("[GOLD_RECON] periodic net-exposure reconciler started")
    while True:
        try:
            await asyncio.sleep(_RECON_INTERVAL_S)
            flt = _load_single_leg_filter()
            if not flt.get("enabled", True):
                continue
            gold_abs = float(flt.get("gold_abs_gap_xau", 0.6))
            gold_pct = float(flt.get("gold_pct_gap", 0.05))
            targets = await _recon_targets()
            # ── 20260708 共享B品种组合口径 ──────────────────────────────────
            # 同一(用户,对冲账户,MT5品种)可被多个交易对共享(ICXAU/PAXG共用IC XAUUSD),
            # 按对分账会把共享对冲腿双重计入 → 交叉误报并诱导用户拆掉健康对冲
            # (0708实证: PAXG成交→"ICXAU单腿"误报→用户平共享腿→PAXG真裸奔→乒乓)。
            # 组口径: 组净敞口 = Σ成员对A腿净 + 共享MT5净×conv(组内conv必须一致,
            # 不一致跳过并警示); 告警标签=成员对拼接, 冷却/两周期确认按组键。
            _groups = {}
            _seen_member = set()
            for uid, pc, acc_a, acc_b, hmult in targets:
                if hmult != 1.0:
                    continue  # 放大对冲模式天然净敞口, 不适用
                _mk = (str(uid), acc_a.account_id, acc_b.account_id, pc)
                if _mk in _seen_member:
                    continue
                _seen_member.add(_mk)
                _sa_g, _sb_g, _cv_g = _get_pair_config(pc)
                if not _sa_g or not _sb_g:
                    continue
                _groups.setdefault((str(uid), acc_b.account_id, _sb_g), []).append(
                    (pc, acc_a, acc_b, _sa_g, float(_cv_g or 0)))
            _seen_grp_acc = set()
            for (_uid_g, _accb_id, _sb_g), _members in _groups.items():
                # 共享账户去重(关联用户绑同套账户): 同(B账户,B品种,A账户集)只查/报一次
                _acc_sig = (_accb_id, _sb_g, tuple(sorted({m[1].account_id for m in _members})))
                if _acc_sig in _seen_grp_acc:
                    continue
                _seen_grp_acc.add(_acc_sig)
                # 孤儿挂单清扫(全品种, 300s节流, 只撤s-单) — 与净敞口检查互相独立
                for _pc_m, _acc_a_m, _accb_m, _sa_m, _cv_m in _members:
                    try:
                        await _sweep_orphan_orders(_uid_g, _pc_m, _acc_a_m)
                    except Exception:
                        pass
                _convs = {round(m[4], 9) for m in _members}
                if len(_convs) != 1 or 0.0 in _convs:
                    logger.warning(
                        f"[GOLD_RECON] 组内换算系数不一致或为0, 跳过组 {_sb_g}: "
                        f"{[(m[0], m[4]) for m in _members]}")
                    continue
                _conv_grp = _members[0][4]
                uid = _uid_g
                pc = "+".join(sorted(m[0] for m in _members))  # 告警标签(多成员拼接)
                tkey = f"{_uid_g}:{_accb_id}:{_sb_g}"
                # A腿净: 组内按(A账户,A品种)去重求和; 任一查询失败整组跳过(绝不拿0误报)
                b_net = 0.0
                _a_ok = True
                _seen_asym = set()
                for _pc_m, _acc_a_m, _accb_m, _sa_m, _cv_m in _members:
                    _ak = (_acc_a_m.account_id, _sa_m)
                    if _ak in _seen_asym:
                        continue
                    _seen_asym.add(_ak)
                    try:
                        b_net += await _recon_binance_net(_acc_a_m, _sa_m)
                    except Exception:
                        _a_ok = False
                        break
                if not _a_ok:
                    continue
                try:
                    m_net_xau = await _recon_mt5_net_units(_members[0][2], _sb_g, _conv_grp)
                except Exception:
                    continue
                if m_net_xau is None:
                    continue
                net = b_net + m_net_xau
                base = max(abs(b_net), abs(m_net_xau))
                # 金族沿用配置阈值(0.6/5%), 其它绝对地板=conv×0.01; 族别按共享B品种判
                _is_gold_rc = 'XAU' in _sb_g.upper()
                _abs_thr = gold_abs if _is_gold_rc else max(_conv_grp * 0.01, 1e-9)
                trig = None
                if _abs_thr > 0 and abs(net) > _abs_thr:
                    trig = 'GOLD_RECON_ABS' if _is_gold_rc else 'RECON_ABS'
                elif gold_pct > 0 and base > 0 and abs(net) > base * gold_pct:
                    trig = 'GOLD_RECON_PCT' if _is_gold_rc else 'RECON_PCT'
                if not trig:
                    _RECON_PENDING.pop(tkey, None)
                    continue
                _now = asyncio.get_event_loop().time()
                # 瞬时抑制(20260707b): A腿成交→B腿taker相隔1~2s, 单周期采样会把在途
                # 对冲抓成越限(cq001实证: 采样恰逢开仓半程报+10, 下一笔B腿即对平)。
                # 连续两个周期(≈90s)都越限才告警 — 真实站立缺口必然连续越限,
                # 代价仅为45s检出延迟; 在途瞬时敞口下周期已对平自动消失。
                _prev_pend = _RECON_PENDING.get(tkey, 0.0)
                _RECON_PENDING[tkey] = _now
                if _now - _prev_pend > _RECON_INTERVAL_S * 3:
                    continue  # 首次越限(或距上次越限过久): 挂起待下周期复核
                if _now - _RECON_LAST_ALERT.get(tkey, 0.0) < _RECON_COOLDOWN_S:
                    continue
                _RECON_LAST_ALERT[tkey] = _now
                logger.error(
                    f"[GOLD_RECON] 净敞口越限({trig}): user={uid} pair={pc} "
                    f"净敞口={net:+.4f} XAU (币安净={b_net:+.4f}, MT5净={m_net_xau:+.4f}; "
                    f"abs阈={gold_abs}, pct阈={gold_pct:.0%})"
                )
                # shim复用执行器告警方法(该方法仅读self.user_id/self.pair_code);
                # 方向标签按净敞口符号取语境, 文案主体是两腿实盘/净敞口数字
                from types import SimpleNamespace as _NS_a
                _shim = _NS_a(user_id=str(uid), pair_code=pc)
                _st = 'forward_opening' if net >= 0 else 'reverse_opening'
                try:
                    await asyncio.wait_for(ContinuousStrategyExecutor._send_single_leg_alert(_shim,
                        strategy_type=_st,
                        exec_result={'single_leg_details': {
                            'binance_filled': 0, 'bybit_filled': 0,
                            'unfilled_qty': round(net, 4),
                            'position_gap': round(abs(net), 4),
                            'post_binance': round(b_net, 4),
                            'post_bybit': round(m_net_xau, 4),
                            'net_exposure': round(net, 4),
                            'trigger': trig,
                            'verification_method': 'gold_periodic_recon',
                        }}), timeout=15.0)
                except Exception as _ae:
                    logger.warning(f"[GOLD_RECON] alert send failed: {_ae}")
        except asyncio.CancelledError:
            raise
        except Exception as _le:
            logger.warning(f"[GOLD_RECON] loop error: {_le}")


@dataclass
class LadderConfig:
    """Ladder configuration for tiered execution"""
    enabled: bool
    opening_spread: float
    closing_spread: float
    total_qty: float
    opening_trigger_count: int
    closing_trigger_count: int


class ContinuousStrategyExecutor:
    """
    Orchestrates continuous strategy execution with:
    - Trigger count management
    - Ladder configuration support
    - Position limit enforcement
    - Automatic re-execution until conditions no longer met
    """

    def __init__(
        self,
        strategy_id: int,
        pair_code: str = "XAU",
        order_executor: OrderExecutorV2 = None,
        position_mgr: Optional[PositionManager] = None,
        hedge_multiplier: float = 1.0,
        trigger_check_interval: float = 0.5,  # 500ms default (increased to reduce API calls and avoid frequent order cancellations)
        api_spam_prevention_delay: float = 3.0,  # Default 3 seconds to prevent API spam
        delayed_single_leg_check_delay: float = 10.0,  # Default 10 seconds for first single-leg check
        delayed_single_leg_second_check_delay: float = 1.0  # Default 1 second for second single-leg check
    ):
        """
        Initialize continuous executor.

        Args:
            strategy_id: Unique strategy identifier
            order_executor: Order execution engine
            position_mgr: Position manager (uses global if not provided)
            trigger_check_interval: Interval between trigger checks in seconds (default 0.5 = 500ms)
            api_spam_prevention_delay: Delay after order execution to prevent API spam (default 3.0 seconds)
            delayed_single_leg_check_delay: Delay before first single-leg verification (default 10.0 seconds)
            delayed_single_leg_second_check_delay: Delay before second single-leg verification (default 1.0 seconds)
        """
        self.strategy_id = strategy_id
        self.pair_code = pair_code
        self.order_executor = order_executor
        self.position_mgr = position_mgr or position_manager
        self.hedge_multiplier = hedge_multiplier
        self.trigger_check_interval = max(trigger_check_interval, 0.3)  # floor 300ms to prevent API rate limit
        self.api_spam_prevention_delay = api_spam_prevention_delay
        self.delayed_single_leg_check_delay = delayed_single_leg_check_delay
        self.delayed_single_leg_second_check_delay = delayed_single_leg_second_check_delay

        # Execution state
        self.is_running = False
        self.stop_requested = False  # Graceful stop: wait for safe exit point before stopping
        self.stop_reason = None  # 'market_close' 表示因 MT5 临近休市自动停，其余为 None
        self.current_ladder_index = 0
        self.trigger_mgr: Optional[TriggerCountManager] = None
        self.user_id: Optional[str] = None
        self._active_key: Optional[str] = None
        # 优化: 停止信号事件 — 收到停止时立即唤醒空闲 sleep
        self._stop_event = asyncio.Event()
        self._binance_account = None
        # 心跳看门狗(20260617): 每轮循环更新; 看门狗监控, 长时间不更新=挂死->cancel+自恢复(方案B)
        self._last_heartbeat = None  # set on loop entry; monotonic seconds
        # 平仓过度平仓修复(20260622): fstream WS黑洞期持仓WS缓存陈旧,平仓循环若读陈旧值会死锁顶部
        # 阶梯、用错条件过度平下一阶梯。① 每平成一笔→置位, 下一轮强制 force_fresh 直取REST真值(绕双缓存,
        # 仅成交后取一次, 不打爆REST); ② 记录平仓前持仓, 若刷新后仍未下降=feed严重滞后→本轮不平等刷新。
        self._force_fresh_pos_next = False
        self._closing_pos_before = None  # 上一笔平仓前的真实持仓, 用于过度平仓护栏

    async def _init_redis(self):
        if not hasattr(self, '_redis') or self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    def _make_active_key(self, strategy_type: str) -> str:
        direction = 'reverse' if 'reverse' in strategy_type else 'forward'
        action = 'opening' if 'opening' in strategy_type else 'closing'
        return f"strategy_active:{self.user_id}:{direction}_{action}"

    async def _write_proc_heartbeat(self):
        """P2: 把进程运行态写入 Redis 心跳哈希 strategy_proc:{user}:{dir}_{act}(ex=90s)。
        这是给 admin 策略进程监控的【跨进程/抗重启】真相源——内存注册表重启即丢、未来多 worker
        会分裂,而 Redis 哈希过期=进程死,语义天然。非致命:任何异常静默跳过,绝不影响交易循环。"""
        try:
            if not (self._redis and self._active_key):
                return
            import time as _pt, json as _pj
            pk = self._active_key.replace("strategy_active:", "strategy_proc:")
            tm = getattr(self, "trigger_mgr", None)
            ladders = getattr(self, "ladders", None)
            mapping = {
                "user_id": str(self.user_id or ""),
                "pair_code": str(self.pair_code or ""),
                "current_ladder_index": int(getattr(self, "current_ladder_index", 0) or 0),
                "total_ladders": int(len(ladders)) if isinstance(ladders, (list, tuple)) else 0,
                "trigger_count": int(getattr(tm, "count", 0) or 0) if tm is not None else 0,
                "hedge_multiplier": float(getattr(self, "hedge_multiplier", 1.0) or 1.0),
                "is_running": "1" if getattr(self, "is_running", False) else "0",
                "stop_requested": "1" if getattr(self, "stop_requested", False) else "0",
                "stop_reason": str(getattr(self, "stop_reason", "") or ""),
                "hb_ts": str(int(_pt.time())),
            }
            await self._redis.hset(pk, mapping=mapping)
            await self._redis.expire(pk, 90)
        except Exception:
            pass

    async def _is_peer_running(self, strategy_type: str) -> bool:
        try:
            direction = 'reverse' if 'reverse' in strategy_type else 'forward'
            if 'opening' in strategy_type:
                peer_key = f"strategy_active:{self.user_id}:{direction}_closing"
            else:
                peer_key = f"strategy_active:{self.user_id}:{direction}_opening"
            return bool(await self._redis.exists(peer_key))
        except Exception:
            return False

    # ----- MT5 first-trade preflight check -----
    # When MT5 broker reopens (weekend/daily break), QUOTE feed comes back 3-5 min
    # BEFORE the TRADE engine accepts orders. During that window, the strategy
    # sees a valid spread and fires Binance (24/7) which fills, then MT5 rejects
    # with retcode=10018 -> single leg.
    #
    # Fix: query MT5 symbol_info.trade_mode (must == 4 / TRADE_FULL) on the FIRST
    # trade after a >2h idle gap. Subsequent trades short-circuit on the cache.
    _mt5_trade_mode_verified_at: dict = {}
    _mt5_last_full: dict = {}   # (bridge,sym)->bool 上次探测是否FULL, 检测复开市(非FULL→FULL)
    _mt5_reopen_at: dict = {}   # (bridge,sym)->ts 检测到复开市时刻, 供复开市预热(与日级/周末口径一致)
    MT5_PREFLIGHT_TTL_S: float = 10.0  # 30s→10s(20260611): 更频繁复探券商XAU实时可交易状态, 精确抓取节假日/盘中分时段休市(品种特定/与时区无关)

    async def _ensure_mt5_trade_mode(self, bybit_account, sym_b: str, pair_code: str = None) -> bool:
        """Pre-trade gate: only the FIRST trade after >2h idle actually probes
        MT5 trade_mode. Subsequent trades short-circuit on cached verification."""
        import time as _t, os, httpx
        from app.services.order_executor_v2 import _get_trading_bridge_url

        try:
            bridge_url = _get_trading_bridge_url(str(bybit_account.account_id))
        except Exception as e:
            logger.warning(f"[MT5_PREFLIGHT] bridge resolve failed: {e} - refusing trade")
            return False

        key = (bridge_url, sym_b)
        now = _t.time()
        last_ok = ContinuousStrategyExecutor._mt5_trade_mode_verified_at.get(key)
        if last_ok is not None and (now - last_ok) < self.MT5_PREFLIGHT_TTL_S:
            return True

        api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))
        headers = {"X-Api-Key": api_key} if api_key else {}
        try:
            c = _get_mt5_health_client()
            r = await c.get(f"{bridge_url}/mt5/symbol_info/{sym_b}", headers=headers)
            if r.status_code != 200:
                logger.warning(f"[MT5_PREFLIGHT] {sym_b}@{bridge_url} http={r.status_code} - refusing first trade")
                return False
            info = r.json()
            tmode_raw = info.get("trade_mode")
            if tmode_raw is None:
                # 去乐观放行(20260611): 无法确认 trade_mode==FULL 不臆测可交易, 本轮 defer(下轮重试)。
                # 仅 4 按钮套利执行经此预检; 紧急手动交易不受影响。当前各桥均回 trade_mode, 不影响正常交易。
                logger.warning(f"[MT5_PREFLIGHT] {sym_b}@{bridge_url} no trade_mode field - 无法确认可交易, deferring(去乐观放行)")
                ContinuousStrategyExecutor._mt5_last_full[key] = False
                return False
            tmode = int(tmode_raw)
            if tmode == 4:
                # 复开市检测: 上次非FULL → 本次FULL = 复开市
                if ContinuousStrategyExecutor._mt5_last_full.get(key) is False:
                    ContinuousStrategyExecutor._mt5_reopen_at[key] = now
                    # MT5 临时停市熔断解冻(20260620): 仅在 trade_mode 真正经历"非FULL→FULL"跃迁
                    # (=真正的正常开市)时解冻。【关键】绝不能在"trade_mode==FULL"就解冻——因为
                    # 盘中临时停市期间 trade_mode 全程撒谎报 FULL(实测106次全FULL), 那样会10s内
                    # 立即误解冻使熔断形同虚设。停市期 trade_mode 恒FULL不跃迁→冻结正确保持到下一次
                    # 正常日级开市(届时经历真实的非FULL→FULL)才解冻, 与复开市预热同一锚点。
                    try:
                        from app.services.mt5_market_freeze import is_frozen as _frz_q, clear as _frz_clear
                        _aid = str(getattr(bybit_account, "account_id", "") or "")
                        if _aid and _frz_q(_aid):
                            _frz_clear(_aid, reason="复开市(trade_mode 非FULL→FULL跃迁)")
                    except Exception:
                        pass
                ContinuousStrategyExecutor._mt5_last_full[key] = True
                # 复开市预热: 节假日/分时段复开市同样走预热(与日级/周末一致: XAU/BXAU 1min, ICXAU 2min)
                _ro = ContinuousStrategyExecutor._mt5_reopen_at.get(key)
                if _ro is not None and pair_code:
                    try:
                        from app.utils.trading_time import open_warmup_minutes as _owm
                        _warm_s = float(_owm(pair_code)) * 60.0
                    except Exception:
                        _warm_s = 0.0
                    if _warm_s > 0 and (now - _ro) < _warm_s:
                        if (now - _ro) < 2.0:
                            logger.info(f"[MT5_PREFLIGHT] {sym_b}({pair_code}) 复开市, 预热 {int(_warm_s)}s defer(与日级/周末一致)")
                        return False
                ContinuousStrategyExecutor._mt5_trade_mode_verified_at[key] = now
                logger.info(f"[MT5_PREFLIGHT] OK {sym_b}@{bridge_url} trade_mode=FULL verified, next probe in {int(self.MT5_PREFLIGHT_TTL_S)}s unless idle")
                return True
            mode_name = {0:"DISABLED",1:"LONGONLY",2:"SHORTONLY",3:"CLOSEONLY",4:"FULL"}.get(tmode, str(tmode))
            logger.warning(f"[MT5_PREFLIGHT] BLOCK {sym_b}@{bridge_url} trade_mode={mode_name} ({tmode}) - MT5 broker not fully open yet; deferring iter")
            ContinuousStrategyExecutor._mt5_last_full[key] = False
            return False
        except Exception as e:
            logger.warning(f"[MT5_PREFLIGHT] {sym_b}@{bridge_url} probe error: {e} - refusing first trade (safe default)")
            return False

    def _mt5_preflight_refresh(self, bybit_account, sym_b: str) -> None:
        """Touch verified-at timestamp on every successful round-trip so cache
        stays warm during active trading; only goes cold during real idle."""
        # 20260611 no-op: 不再每笔成功就焐热缓存(否则活跃交易中永不复探, 会掩盖盘中分时段休市)。
        # 改由 _ensure_mt5_trade_mode 按 MT5_PREFLIGHT_TTL_S(10s) 定期复探, 精确抓取节假日/突发休市。
        return

    async def execute_reverse_opening_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        opening_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute reverse opening with continuous execution.

        Flow:
        1. For each enabled ladder:
           a. Loop until ladder total_qty reached:
              - Check trigger count accumulated
              - Validate spread still meets threshold
              - Check position limits
              - Execute single trade
              - Update position
              - Immediately check if can continue
           b. Move to next ladder

        Args:
            binance_account: Binance account for SHORT positions
            bybit_account: Bybit account for LONG positions
            ladders: List of ladder configurations
            opening_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting reverse opening continuous execution for strategy {self.strategy_id}")

        self.is_running = True
        self.stop_requested = False
        self.stop_reason = None
        try:
            self._stop_event.clear()
        except Exception:
            pass
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        _recon_register(self)  # 黄金净敞口周期对账注册(独立协程, 不碰下单/对冲路径)  # stored for position snapshot
        await self._init_redis()
        self._active_key = self._make_active_key('reverse_opening')

        try:
            await self._redis.set(self._active_key, "1", ex=3600)
            return await self._execute_continuous_v2(
                strategy_type='reverse_opening',
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                order_qty_limit=opening_m_coin,
            )
        except asyncio.CancelledError:
            logger.warning(f"Task cancelled for strategy {self.strategy_id} (reverse_opening)")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('reverse_opening')
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception(f"Error in reverse opening continuous: {e}")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('reverse_opening')
                except Exception:
                    pass
            return {'success': False, 'error': str(e)}
        finally:
            if getattr(self, '_active_key', None):
                try:
                    import redis.asyncio as _aioredis
                    _r = _aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                    await _r.delete(self._active_key)
                    await _r.aclose()
                except Exception:
                    pass
            self.is_running = False

    async def _execute_ladder(
        self,
        ladder_idx: int,
        ladder: LadderConfig,
        strategy_type: str,
        binance_account: Account,
        bybit_account: Account,
        order_qty_limit: float,
        opening_ceiling: float = None,
        mapper=None
    ) -> Dict:
        """
        Execute single ladder with continuous execution.

        Args:
            ladder_idx: Ladder index
            ladder: Ladder configuration
            strategy_type: 'reverse_opening', 'reverse_closing', 'forward_opening', 'forward_closing'
            binance_account: Binance account
            bybit_account: Bybit account
            order_qty_limit: Max quantity per order

        Returns:
            Execution result
        """
        # Initialize trigger manager for this ladder
        trigger_key = f"{self.strategy_id}_{strategy_type}_ladder_{ladder_idx}"
        self.trigger_mgr = TriggerCountManager(self.strategy_id, trigger_key)

        # Determine if opening or closing
        is_opening = 'opening' in strategy_type
        spread_threshold = ladder.opening_spread if is_opening else ladder.closing_spread
        trigger_count_required = ladder.opening_trigger_count if is_opening else ladder.closing_trigger_count
        # Opening: spread >= threshold (large spread, good for opening)
        # Closing: spread <= threshold (small/negative spread, good for closing)
        compare_op = CompareOperator.GREATER_EQUAL if is_opening else CompareOperator.LESS_EQUAL

        logger.info(f"Starting ladder {ladder_idx} [{strategy_type}] loop: total_qty={ladder.total_qty}, threshold={spread_threshold}, triggers_required={trigger_count_required}")

        consecutive_no_fills = 0  # Track consecutive Binance timeouts/cancels without any fill
        MAX_CONSECUTIVE_NO_FILLS = 5  # After 5 consecutive no-fills, stop the ladder
        unhedged_binance_xau = 0.0  # Accumulated Binance fills not yet hedged (below 0.01 Lot)
        MIN_HEDGE_LOT = 0.01         # ICMarkets minimum lot size
        loop_count = 0
        current_position = 0  # initialise so the post-loop debug block always has a value
        # ── 阶梯重判退出: 防"锁死在次优阶梯"(如平仓死等下层阈值, 而不去平已满足条件的上层阶梯) ──
        import time as _t_re
        _last_reeval = _t_re.time()
        _REEVAL_INTERVAL_S = 12.0
        # ── 内层收盘闸节流: minutes_to_mt5_close() 含文件I/O, 每≈5s 查一次即可(硬停粒度足够) ──
        _last_closegate = float('-inf')
        _CLOSEGATE_INTERVAL_S = 5.0
        # ── 开仓持仓上限硬约束：入口读一次权威真实持仓(force_fresh REST)作封顶基线 ──
        # 免疫 WS 冷启/陈旧导致 remaining 多算 → 开仓冲破上限(实盘已观测 1→3)。
        base_pos = None
        if is_opening and opening_ceiling is not None and self._opening_ceiling_guard_enabled():
            try:
                _bp = await self._get_live_position(binance_account, strategy_type, force_fresh=True)
                if _bp is not None and _bp >= 0:
                    base_pos = _bp
                    logger.info(f"[ladder={ladder_idx}] 持仓上限基线 base_pos={base_pos:.4f} ceiling={opening_ceiling}")
                else:
                    logger.warning(f"[ladder={ladder_idx}] base_pos 读取失败(force_fresh)，回退内存计数封顶")
            except Exception as _bpe:
                logger.warning(f"[ladder={ladder_idx}] base_pos 读取异常: {_bpe}，回退内存计数封顶")
        while self.is_running and not self.stop_requested:
            loop_count += 1
            import time as _hb_t; self._last_heartbeat = _hb_t.monotonic()  # 心跳

            # ── 内层 MT5 收盘自动停闸(根因修复 2026-06-23) ──────────────────────
            # 收盘软/硬停闸原本只在外层 V2 主循环; 一旦本内层 ladder 持有 active 阶梯,
            # 控制权会 captive 在此反复挂撤 maker, 跨越收盘软停(15min)/硬停(5min)两个时刻
            # 都回不到外层闸 → 自动停不掉(实测平仓按钮到硬停时刻仍未停)。此处下沉同一判据,
            # 节流≈5s 一查(含文件I/O), 触发即 set stop_requested 退出, 与外层语义一致:
            #   硬停(<=5min): 无条件停; 软停(<=15min): 仅"启动时>15min"(收盘前一直在跑的)才停,
            #   手动重启(启动时已在窗口内)不软停、继续跑到硬停。打 market_close 标走隔日恢复。
            _ng = _hb_t.monotonic()
            if (_ng - _last_closegate) >= _CLOSEGATE_INTERVAL_S:
                _last_closegate = _ng
                try:
                    from app.utils.trading_time import (
                        minutes_to_mt5_close as _mins_to_close_i,
                        SOFT_STOP_BUFFER_MIN as _SOFT_MIN_i,
                        HARD_STOP_BUFFER_MIN as _HARD_MIN_i,
                    )
                    _mins_i = _mins_to_close_i()
                except Exception:
                    _mins_i = None
                if _mins_i is not None:
                    _sm_i = getattr(self, "_start_mins_to_close", None)
                    _do_stop = False
                    if _mins_i <= _HARD_MIN_i:
                        logger.info(f"[ladder={ladder_idx}][MT5收盘] 距收盘 {_mins_i:.1f} 分钟 <= {_HARD_MIN_i}，内层硬停 {strategy_type}")
                        _do_stop = True
                    # 20260708: 豁免线+2分钟宽限 — 0708事故: 用户软停后20:44:36重启,
                    # 距收盘15.4min比15min豁免线早24秒, 被判'非手动重启'36秒击杀。
                    elif _mins_i <= _SOFT_MIN_i and (_sm_i is not None and _sm_i > _SOFT_MIN_i + 2.0):
                        logger.info(f"[ladder={ladder_idx}][MT5收盘] 距收盘 {_mins_i:.1f} 分钟 <= {_SOFT_MIN_i}，内层软停 {strategy_type}（启动时={_sm_i:.1f}分钟）")
                        _do_stop = True
                    if _do_stop:
                        self.stop_reason = 'market_close'
                        await self._mark_resume_pending(strategy_type)
                        self.stop_requested = True
                        break
                # 根因1修复(2026-07-04): 节假日提前休市时 minutes_to_mt5_close()=None, 上方倒计时闸
                # 被跳过; 若本内层 ladder 此刻 captive(持 active 阶梯), 外层休市闸也跑不到 → 永远停不掉。
                # 此处在同一节流窗口内补一道休市硬闸(与外层同源 is_bybit_trading_hours), 命中休市即
                # 停按钮+mark_resume+break, 走"停按钮+重开自动恢复"语义。
                if not self.stop_requested:
                    try:
                        from app.utils.trading_time import is_bybit_trading_hours as _mkt_i
                        _open_i, _rsn_i = _mkt_i(self.pair_code)
                    except Exception:
                        _open_i, _rsn_i = True, ""
                    if not _open_i:
                        logger.info(f"[ladder={ladder_idx}][MT5休市] 当前休市({_rsn_i})，内层停 {strategy_type}（停按钮+开市自动恢复）")
                        self.stop_reason = 'market_close'
                        await self._mark_resume_pending(strategy_type)
                        self.stop_requested = True
                        break

            # ── 阶梯重判: 每~12s 重读持仓+点差, 并"重读最新DB配置重建mapper"(捕捉运行中改的总手数); 若最优阶梯已变为另一个阶梯, 或开仓时本阶梯按新总手数已满 → 退出本阶梯交还V2主循环重选 ──
            # 修两类锁死: ①平仓死等下层阈值不去平上层(如锁阶梯2不平阶梯3); ②开仓运行中把本阶梯总手数改小后, _execute_ladder 仍按旧total死等开下一手、进不了下一阶梯。
            if mapper is not None and (_t_re.time() - _last_reeval >= _REEVAL_INTERVAL_S):
                _last_reeval = _t_re.time()
                try:
                    _re_pos = await asyncio.wait_for(self._get_live_position(binance_account, strategy_type), timeout=8.0)
                    if _re_pos is not None and _re_pos >= 0:
                        _re_spread = await self._get_current_spread(strategy_type)
                        # 重读最新DB配置重建 mapper(捕捉运行中改的总手数); 失败则退用启动时 mapper
                        _eval_mapper = mapper
                        _f_ladders = None
                        try:
                            _fresh = await asyncio.wait_for(self._reload_strategy_config(strategy_type), timeout=4.0)
                            if _fresh:
                                from app.services.ladder_range_mapper import LadderRangeMapper as _LRM
                                _f_ladders, _ = _fresh
                                _eval_mapper = _LRM(_f_ladders)
                        except Exception:
                            pass
                        _re_active = (_eval_mapper.get_active_ladder_for_opening(_re_pos, _re_spread) if is_opening
                                      else _eval_mapper.get_active_ladder_for_closing(_re_pos, _re_spread))
                        _switch = (_re_active is not None and _re_active.index != ladder_idx)
                        # 开仓: 本阶梯按新配置的累计上限已 <= 当前持仓 → 本阶梯已满(防按旧total继续超开/空转)
                        _cur_full = False
                        if is_opening and _f_ladders is not None and ladder_idx < len(_f_ladders):
                            try:
                                _cur_new_total = float(_f_ladders[ladder_idx].total_qty or 0)
                                if _re_pos >= _cur_new_total - 1e-6:
                                    _cur_full = True
                            except Exception:
                                pass
                        if _switch or _cur_full:
                            logger.info(f"[ladder={ladder_idx}] 阶梯重判: pos={_re_pos:.2f} spread={_re_spread:.3f} 新最优={_re_active.index if _re_active else None} 本阶梯满={_cur_full} ({strategy_type}) → 退出本阶梯交还主循环重选")
                            break
                        # ── 同阶梯阈值热刷新(根因修复2026-06-24): 本阶梯仍在跑(未切换/未满)时,
                        #    若DB里本阶梯的开/平差值或触发数已改 → 即时刷新入口捕获的 spread_threshold/触发数,
                        #    修"captive 在内层挂单时改阈值保存却仍按旧阈值成交"(与外层热重载只重建mapper互补)。
                        elif _f_ladders is not None and 0 <= ladder_idx < len(_f_ladders):
                            try:
                                _cur_ld = _f_ladders[ladder_idx]
                                _new_thr = float(_cur_ld.opening_spread if is_opening else _cur_ld.closing_spread)
                                _new_tcr = int(_cur_ld.opening_trigger_count if is_opening else _cur_ld.closing_trigger_count)
                                if _new_thr != spread_threshold or _new_tcr != trigger_count_required:
                                    logger.info(f"[ladder={ladder_idx}] 阈值热刷新: 点差阈值 {spread_threshold}->{_new_thr}, 触发数 {trigger_count_required}->{_new_tcr} ({strategy_type})")
                                    spread_threshold = _new_thr
                                    trigger_count_required = _new_tcr
                            except Exception:
                                pass
                except Exception as _ree:
                    logger.debug(f"[ladder={ladder_idx}] 阶梯重判 skipped: {_ree}")

            # Step 1: Check position
            # Get memory position (how much we've opened/closed so far)
            position_info = self.position_mgr.get_position(
                self.strategy_id,
                ladder_idx,
                strategy_type
            )
            current_position = position_info['current_position']

            # Log every 100 iterations (50s at 0.5s interval) to avoid log spam
            if loop_count % 100 == 1:
                logger.info(f"[ladder={ladder_idx}] iter={loop_count} pos={current_position}/{ladder.total_qty} triggers={self.trigger_mgr.count}/{trigger_count_required}")

            # Step 2: Check if ladder complete
            if current_position >= ladder.total_qty:
                logger.info(f"Ladder {ladder_idx} complete: {current_position}/{ladder.total_qty}")
                break

            # Step 3: Check trigger count
            trigger_ready = self.trigger_mgr.is_ready(trigger_count_required)

            if not trigger_ready:
                # Accumulate triggers
                try:
                    current_spread = await self._get_current_spread(strategy_type)
                except Exception as e:
                    logger.warning(f"[ladder={ladder_idx}] Failed to get spread for trigger check: {e}")
                    await asyncio.sleep(self.trigger_check_interval)
                    continue

                triggered = await self.trigger_mgr.check_and_increment(
                    current_spread,
                    spread_threshold,
                    compare_op,
                    required_count=trigger_count_required,  # enables express mode for extreme spreads
                )

                if triggered:
                    logger.debug(f"[ladder={ladder_idx}] trigger {self.trigger_mgr.count}/{trigger_count_required} spread={current_spread:.3f} threshold={spread_threshold}")
                    await self._push_trigger_progress(
                        ladder_idx,
                        self.trigger_mgr.count,
                        trigger_count_required,
                        strategy_type,
                        current_spread=current_spread,
                        threshold=spread_threshold,
                        express=getattr(self.trigger_mgr, "last_was_express", False),
                    )

                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 4: Re-check spread after trigger count is satisfied
            # If spread no longer meets threshold, reset triggers and wait again
            try:
                current_spread = await self._get_current_spread(strategy_type)
            except Exception as e:
                logger.warning(f"[ladder={ladder_idx}] Failed to get spread for re-check: {e}")
                await asyncio.sleep(self.trigger_check_interval)
                continue

            spread_ok = (
                (compare_op == CompareOperator.GREATER_EQUAL and current_spread >= spread_threshold) or
                (compare_op == CompareOperator.LESS_EQUAL and current_spread <= spread_threshold)
            )

            if not spread_ok:
                # Spread no longer satisfies condition — reset trigger count and wait
                logger.info(f"[ladder={ladder_idx}] Spread condition lapsed (spread={current_spread:.3f} threshold={spread_threshold}), resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)
                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 5: Calculate order quantity
            is_closing = strategy_type in ('reverse_closing', 'forward_closing')
            try:
                remaining = ladder.total_qty - current_position
                order_qty = min(order_qty_limit, remaining)
                # ── 开仓持仓上限硬约束：以 base_pos + 本轮实际成交 为权威持仓,按 ceiling 钳制 ──
                if (not is_closing) and opening_ceiling is not None and base_pos is not None:
                    effective_pos = base_pos + current_position
                    ceiling_remaining = opening_ceiling - effective_pos
                    if ceiling_remaining <= 1e-9:
                        logger.info(f"[ladder={ladder_idx}] 已达持仓上限 {effective_pos:.2f}/{opening_ceiling}，停止开仓")
                        break
                    order_qty = min(order_qty, ceiling_remaining)
                logger.info(f"[ladder={ladder_idx}] Order qty: {order_qty}, remaining: {remaining}, limit: {order_qty_limit}")
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Exception calculating order_qty: {e}")
                break

            # Step 6: Check position limits
            try:
                result = self.position_mgr.check_can_open(
                    self.strategy_id,
                    ladder_idx,
                    strategy_type,
                    order_qty,
                    ladder.total_qty
                )

                can_open = result['can_open']
                reason = result.get('reason', '')

                if not can_open:
                    logger.warning(f"[ladder={ladder_idx}] Cannot open: {reason}")
                    break
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Exception in check_can_open: {e}")
                break

            # Step 7: Get current prices
            try:
                sym_a, sym_b, _ = _get_pair_config(self.pair_code)
                market_data = await market_data_service.get_current_spread(
                    binance_symbol=sym_a,
                    bybit_symbol=sym_b,
                )
                binance_price = self._get_binance_price(market_data, strategy_type)
                bybit_price = self._get_bybit_price(market_data, strategy_type)
                logger.info(f"[ladder={ladder_idx}] Prices — Binance={binance_price}, Bybit={bybit_price}")
            except Exception as e:
                logger.error(f"[ladder={ladder_idx}] Failed to get market data: {e}")
                await asyncio.sleep(self.trigger_check_interval)
                continue

            # Step 7.5: Snapshot positions before execution.
            # 20260619(方案B): 改为后台 create_task 非阻塞 —— 此快照的结果当前不被任何逻辑消费
            # (_delayed_single_leg_check 的 Phase2 自行实查绝对持仓, 不读 pre_snapshot), 唯一有用
            # 产物是 [SNAPSHOT] Pre-execution 诊断日志。原先 await 白占 A 侧挂单前 ~100ms(中位102ms,
            # p99 643ms)。改为 create_task 后, A 侧挂单零快照延迟(含 express 极速触发), 日志照常打,
            # 单腿防线不动(仍由成交后异步 Phase2 实盘总量对账兜底)。pre_snapshot 传空, 该参数已无消费方。
            pre_snapshot = {}
            try:
                asyncio.create_task(self._snapshot_positions(binance_account, bybit_account))
            except RuntimeError:
                pass  # 无运行中事件循环(极少见), 跳过快照日志, 不影响交易

            # ── Inject accumulated unhedged qty for B-side sizing ──────────────
            # If previous iterations had Binance fills too small for B-side (< 0.01 Lot),
            # we carry the deficit here and add it to the current order's B-side target.
            # This is passed via executor state so order_executor can use it.
            self._unhedged_binance_xau = unhedged_binance_xau

            # Step 7.9: Cancel any lingering open orders on A-side before placing new one
            # Prevents order accumulation on the exchange when previous cancels failed
            # 防挂死(20260617): 整段加 wait_for(8s) 兜底——这是清理性动作(撤遗留挂单),
            # 不是核心交易步骤;若代理/交易所REST在get_open_orders/cancel_order上卡住
            # (实测SOCKS5代理C层阻塞可绕过aiohttp内部12s超时),宁可跳过清理继续往下
            # 走Step8正常下单,也不能让整个策略循环卡死(实测100%卡死点正是这里)。
            async def _step79_cancel_lingering():
                sym_a, _, _ = _get_pair_config(self.pair_code)
                from app.core.proxy_utils import build_proxy_url
                if binance_account.platform_id == 1:
                    from app.services.binance_client import BinanceFuturesClient
                    _cancel_client = BinanceFuturesClient(
                        binance_account.api_key, binance_account.api_secret,
                        proxy_url=build_proxy_url(binance_account.proxy_config)
                    )
                    try:
                        open_orders = await _cancel_client.get_open_orders(symbol=sym_a)
                        # SAFETY: only cancel orders this strategy itself placed.
                        # Manual emergency orders carry clientOrderId prefix "m-" and MUST
                        # survive — they may only be cancelled via the explicit Cancel-All
                        # button. Strategy orders carry prefix "s-".
                        own = [o for o in (open_orders or []) if str(o.get("clientOrderId", "")).startswith("s-")]
                        kept = (len(open_orders) - len(own)) if open_orders else 0
                        for od in own:
                            try:
                                await _cancel_client.cancel_order(sym_a, od["orderId"])
                            except Exception as _ce:
                                logger.debug(f"[ladder={ladder_idx}] cancel one lingering failed: {_ce}")
                        if own or kept:
                            logger.warning(
                                f"[ladder={ladder_idx}] Pre-order cleanup: cancelled {len(own)} OWN strategy orders, "
                                f"kept {kept} non-strategy (e.g. manual emergency) orders on {sym_a}"
                            )
                    finally:
                        await _cancel_client.close()
                elif binance_account.platform_id == 2:
                    from app.services.bybit_client import BybitV5Client
                    _cancel_client = BybitV5Client(
                        api_key=binance_account.api_key, api_secret=binance_account.api_secret,
                        proxy_url=build_proxy_url(binance_account.proxy_config),
                    )
                    try:
                        # SAFETY: mirror Binance behavior — only cancel orders carrying
                        # the strategy "s-" clientOrderId / orderLinkId prefix. Manual
                        # emergency orders use "m-" and must be preserved.
                        bb_open = await _cancel_client.get_open_orders(category='linear', symbol=sym_a)
                        bb_list = (bb_open or {}).get('list', []) if isinstance(bb_open, dict) else (bb_open or [])
                        bb_own = [o for o in bb_list if str(o.get('orderLinkId', '') or o.get('clientOrderId', '')).startswith('s-')]
                        bb_kept = max(0, len(bb_list) - len(bb_own))
                        for od in bb_own:
                            try:
                                _oid = od.get('orderId') or od.get('order_id')
                                if _oid:
                                    await _cancel_client.cancel_order(category='linear', symbol=sym_a, order_id=_oid)
                            except Exception as _ce:
                                logger.debug(f"[ladder={ladder_idx}] Bybit cancel one failed: {_ce}")
                        if bb_own or bb_kept:
                            logger.warning(
                                f"[ladder={ladder_idx}] Pre-order Bybit cleanup: cancelled {len(bb_own)} OWN, "
                                f"kept {bb_kept} non-strategy (manual) orders on {sym_a}"
                            )
                    finally:
                        await _cancel_client.close()
            try:
                await asyncio.wait_for(_step79_cancel_lingering(), timeout=8.0)
            except asyncio.TimeoutError:
                logger.warning(f"[ladder={ladder_idx}] Pre-order cleanup timeout(8s,可能代理/REST阻塞) - 跳过清理直接下单")
            except Exception as e:
                logger.warning(f"[ladder={ladder_idx}] Failed to cancel lingering orders: {e}")

            # Step 7.5: MT5 first-trade preflight (probes only after >2h idle).
            # Active trading short-circuits this via cached verified-at (<1us).
            _sym_a_pf, _sym_b_pf, _ = _get_pair_config(self.pair_code)
            # preflight 先跑(即使冻结中也跑): 它每~10s 探 trade_mode, 在"非FULL→FULL"复开市
            # 瞬间会调 mt5_market_freeze.clear() 解冻 —— 这是冻结的主解冻通道, 故必须放在冻结闸
            # 之前, 否则冻结期 preflight 被跳过, 复开市检测永不触发, 只能死等 6h 兜底。
            _preflight_ok = await self._ensure_mt5_trade_mode(bybit_account, _sym_b_pf, self.pair_code)

            # ── MT5 临时停市熔断闸(20260620): B侧曾回 retcode=10018(市场关闭) → 冻结下单。 ──
            # 10018 是 order_send 真实回执, 不撒谎(trade_mode/trade_allowed/tick 在停市期均会误导)。
            # 冻结期只等待不下A单, 杜绝停市期持续制造单腿; 解冻锚定下一次正常开市(preflight 复开市
            # 检测调 clear)+6h时间兜底+重启清空。只停下单, 绝不自动补存量单腿(交解冻后实时对账+
            # 告警, 由用户决定)。放在 preflight 之后, 确保复开市 clear 通道始终可达。
            try:
                from app.services.mt5_market_freeze import is_frozen as _mt5_frozen, frozen_age as _frz_age
                if _mt5_frozen(str(bybit_account.account_id)):
                    if scan_count % 20 == 1:
                        _age = _frz_age(str(bybit_account.account_id)) or 0
                        logger.warning(
                            f"[ladder={ladder_idx}] MT5临时停市冻结中({_age/60:.0f}min) - 暂停下单, "
                            f"等正常开市自动解冻 ({strategy_type})"
                        )
                    await self._sleep_or_stop(self.api_spam_prevention_delay)
                    continue
            except Exception:
                pass

            if not _preflight_ok:
                logger.warning(
                    f"[ladder={ladder_idx}] MT5 preflight refused - deferring iter "
                    f"(no A-side order placed; will retry next trigger cycle)"
                )
                await self._sleep_or_stop(self.api_spam_prevention_delay)
                continue

            # Step 7.95: 挂单前【单向】二次确认(20260622)。触发达成处取价 → 真正挂单之间会隔
            # 清挂单/preflight 等延迟(开盘 REST 拥堵实测可达 8s),期间点差可能已朝【不利】方向漂移,
            # 导致用陈旧决策挂单、在已不达标的点差上成交(本次 06:09/06:13 两笔即此因)。
            # 用 WS 实时点差(零 REST,与触发轮询同源)复核:仅当点差朝【不利】方向越过撤单容差才
            # 放弃本轮、重置触发重来;【有利方向(点差更优)照常下单成交】。正常行情下决策→挂单为
            # 亚秒级,此复核几乎恒通过,不影响成交效率;只在出现陈旧间隔时拦掉劣质成交。
            try:
                _pre_tol = float(getattr(self.order_executor, 'spread_cancel_tolerance', 0.29) or 0.29)
            except Exception:
                _pre_tol = 0.29
            try:
                _pre_spread = await asyncio.wait_for(self._get_current_spread(strategy_type), timeout=5.0)
            except Exception:
                _pre_spread = None
            if _pre_spread is not None:
                _pre_ok = (
                    (compare_op == CompareOperator.GREATER_EQUAL and _pre_spread >= spread_threshold - _pre_tol) or
                    (compare_op == CompareOperator.LESS_EQUAL and _pre_spread <= spread_threshold + _pre_tol)
                )
                if not _pre_ok:
                    logger.info(
                        f"[ladder={ladder_idx}] 挂单前二次确认: 点差朝不利方向越容差 "
                        f"(spread={_pre_spread:.3f} threshold={spread_threshold} tol={_pre_tol}) - 放弃本轮重新触发"
                    )
                    self.trigger_mgr.reset()
                    await self._push_trigger_reset(ladder_idx, strategy_type)
                    await asyncio.sleep(self.trigger_check_interval)
                    continue

            # 根因2修复(2026-07-04): 下单最后一跳前二次复查。Step7.95 二次确认含数秒 REST/WS 等待,
            # 手动停/休市停信号在此间隙到达时, 原代码仍会把这笔 maker 挂出去(实测按停后 2~8s 仍冒
            # 委托单, 靠 active-cancel/下单监控6s超时事后撤)。此处前移到事前拦截: 停止已请求或已休市
            # → 放弃本轮不挂单, 交还外层干净退出, 从源头消除"按停后仍挂单"的竞态窗口。
            if self.stop_requested or not self.is_running:
                logger.info(f"[ladder={ladder_idx}] 下单前复查: 停止已请求, 放弃本轮不挂单 {strategy_type}")
                break
            try:
                from app.utils.trading_time import is_bybit_trading_hours as _mkt_pre
                _pre_open, _pre_rsn = _mkt_pre(self.pair_code)
            except Exception:
                _pre_open, _pre_rsn = True, ""
            if not _pre_open:
                logger.info(f"[ladder={ladder_idx}] 下单前复查: 已休市({_pre_rsn}), 放弃本轮不挂单 {strategy_type}")
                self.stop_reason = 'market_close'
                await self._mark_resume_pending(strategy_type)
                self.stop_requested = True
                break

            # Step 8: Execute order
            logger.info(f"[ladder={ladder_idx}] Executing {strategy_type}: {order_qty} units")
            # ── 容量护栏(feature b): 在途开仓单期间, 若热重载把本阶梯累计上限降到 < 已开+在途 → 撤在途s-单并结束本阶梯 ──
            _cap_stop = asyncio.Event()
            _cap_guard_task = None
            if is_opening:
                self._cap_cancel = False
                _pos_before_cap = (base_pos if base_pos is not None else 0.0) + current_position
                _cap_guard_task = asyncio.create_task(self._capacity_reduce_guard(
                    strategy_type, binance_account, ladder_idx, _pos_before_cap, order_qty, _cap_stop))
            try:
                # 防挂死(20260616): 给整条下单/对冲执行加 25s 总超时兜底。
                # 正常一次 forward/reverse 执行 <5s; 25s 留单腿重试余量。
                # 超时抛 asyncio.TimeoutError → 被下方 except Exception 接住 →
                # 走 HALT 分支干净退出本阶梯循环(而非无限挂死拖垮全部策略)。
                # 退出后由重启自恢复/下次触发周期带新配置重新评估。
                # 20260716: 截止时刻(exec_deadline)传入执行链 — 下单前预算护栏
                # (order_executor_v2._budget_guard_result): 剩余预算不足一轮监控
                # 就不再挂单干净返回, 避免"下单数秒后被本总超时cancel成孤儿挂单"。
                _exec_deadline = asyncio.get_event_loop().time() + 25.0
                # 20260716 崩溃补腿上下文: 执行链把本次策略订单的身份/对冲进度写进来,
                # 崩溃时独立补腿task按它补齐B腿(只认自己的order_id, 与手动单绝缘)
                _inflight_ctx = {}
                exec_result = await asyncio.wait_for(
                    self._execute_order(
                        strategy_type,
                        binance_account,
                        bybit_account,
                        order_qty,
                        binance_price,
                        bybit_price,
                        spread_threshold,
                        exec_deadline=_exec_deadline,
                        inflight=_inflight_ctx,
                    ),
                    timeout=25.0,
                )
            except BaseException as e:
                # 20260706: Exception→BaseException — HB看门狗强杀/停机发出的 CancelledError
                # 也要走安全网(先告警后撤单), 否则在途挂单成孤儿且零提醒(cq002 0706 01:37
                # 事故: 25s总超时cancel监控协程但币安挂单未撤→20 XAU无人对冲成交)。
                # 处理完毕后 CancelledError 原样回抛, 保证强杀/停机最终落地。
                if isinstance(e, GeneratorExit):
                    raise
                logger.error(f"[ladder={ladder_idx}] CRITICAL: Exception executing order: {e!r}", exc_info=True)
                # SAFETY重排(20260706): ①先告警 — 分离task发送(走Redis纯内存不依赖代理),
                # 即使本任务随后被强制cancel也带不走它。旧顺序先清理后告警:
                # get_open_orders无超时卡死在阻塞代理上61s→看门狗强杀(CancelledError越过
                # except Exception)→告警代码永远没执行→单腿零提醒。
                try:
                    asyncio.create_task(self._send_single_leg_alert(
                        strategy_type=strategy_type,
                        exec_result={"single_leg_details": {
                            "binance_filled": order_qty, "bybit_filled": 0,
                            "unfilled_qty": order_qty,
                            "error": f"execution exception: {e!r}"
                        }}
                    ))
                except Exception:
                    pass
                # ①b 崩溃自动补腿(20260716): 独立task核查本次策略订单终态, 已成交未对冲
                # 则按缺口自动补B腿(三道闸见 _crash_repair_leg), 补完发带真实数字的跟进告警。
                # 独立task不随本ladder task被强杀; 手动m-单与净敞口对账均不在其视野内。
                try:
                    _rp_task = asyncio.create_task(_crash_repair_leg(
                        self, dict(_inflight_ctx), ladder_idx, strategy_type,
                        binance_account, bybit_account))
                    _REPAIR_TASKS.add(_rp_task)
                    _rp_task.add_done_callback(_REPAIR_TASKS.discard)
                except Exception:
                    pass
                # ②再清理: 撤掉本策略在途挂单防孤儿成交。每个远程调用独立短超时(不再
                # 裸奔在阻塞代理上); 若本任务正在被cancel, 首个await即抛CancelledError→
                # 跳过清理回抛(孤儿风险由45s周期对账 GOLD_RECON 兜底)。
                try:
                    sym_a_err, _, _ = _get_pair_config(self.pair_code)
                    from app.core.proxy_utils import build_proxy_url as _bpu_err
                    if binance_account.platform_id == 1:
                        from app.services.binance_client import BinanceFuturesClient as _BFC_err
                        _err_client = _BFC_err(binance_account.api_key, binance_account.api_secret,
                                               proxy_url=_bpu_err(binance_account.proxy_config))
                        _err_open = await asyncio.wait_for(
                            _err_client.get_open_orders(symbol=sym_a_err), timeout=8.0)
                        # POST-CRASH SAFETY: even in panic cleanup, do NOT cancel manual
                        # emergency orders ("m-"). User considers them sacred — only
                        # explicit Cancel-All button may remove them.
                        if _err_open:
                            _err_own = [o for o in _err_open if str(o.get("clientOrderId", "")).startswith("s-")]
                            _err_kept = len(_err_open) - len(_err_own)
                            for _eo in _err_own:
                                try:
                                    await asyncio.wait_for(
                                        _err_client.cancel_order(sym_a_err, _eo["orderId"]), timeout=5.0)
                                except Exception:
                                    pass
                            logger.warning(
                                f"[ladder={ladder_idx}] Post-crash cleanup: cancelled {len(_err_own)} OWN strategy orders, "
                                f"kept {_err_kept} manual orders"
                            )
                        await asyncio.wait_for(_err_client.close(), timeout=3.0)
                except BaseException as _cleanup_err:
                    logger.error(f"[ladder={ladder_idx}] Crash cleanup failed: {_cleanup_err!r}")
                    if isinstance(_cleanup_err, asyncio.CancelledError):
                        raise
                if isinstance(e, asyncio.CancelledError):
                    raise
                logger.error(f"[ladder={ladder_idx}] HALTING ladder loop after execution exception to prevent cascading single-leg")
                return {
                    "success": False,
                    "error": f"Execution exception: {e}",
                    "halted_after_crash": True,
                }
            finally:
                _cap_stop.set()
                if _cap_guard_task is not None:
                    _cap_guard_task.cancel()
                    try:
                        await _cap_guard_task
                    except Exception:
                        pass

            # ── 容量护栏触发: 在途开仓单已撤(本阶梯新累计上限 < 已开+在途) → 记录已成交部分后干净结束本阶梯 ──
            if is_opening and getattr(self, '_cap_cancel', False):
                self._cap_cancel = False
                _cap_bf = exec_result.get('binance_filled_qty', 0) if isinstance(exec_result, dict) else 0
                if _cap_bf and _cap_bf > 0:
                    self.position_mgr.record_opening(self.strategy_id, ladder_idx, strategy_type, _cap_bf)
                    asyncio.create_task(self._delayed_single_leg_check(
                        strategy_type=strategy_type, exec_result=exec_result,
                        binance_account=binance_account, bybit_account=bybit_account, pre_snapshot=pre_snapshot))
                logger.warning(f"[ladder={ladder_idx}] 容量护栏: {getattr(self, '_cap_cancel_reason', '')} → 结束本阶梯(V2主循环将按新配置重判)")
                break

            logger.info(f"[ladder={ladder_idx}] Result — success={exec_result.get('success')}, binance_filled={exec_result.get('binance_filled_qty')}, bybit_filled={exec_result.get('bybit_filled_qty')}")

            # Step 8.3: Immediately notify frontend to restore button when LADDER target is reached
            # 仅在本次成交使 current_position 达到/超过 total_qty 时才发送 button restore 通知。
            # 否则会在多批次场景（如 total_qty=2, m_coin=1）第一批次就错误地恢复按钮，
            # 导致用户看到按钮恢复后策略仍在继续交易第二批次。
            _binance_filled_now = exec_result.get('binance_filled_qty', 0)

            # Step 8.5: Schedule single-leg check if Binance had any fill
            # Non-blocking: uses asyncio.create_task so it never interrupts the main execution loop
            binance_filled_qty = exec_result.get('binance_filled_qty', 0)
            if binance_filled_qty and binance_filled_qty > 0:
                asyncio.create_task(self._delayed_single_leg_check(
                    strategy_type=strategy_type,
                    exec_result=exec_result,
                    binance_account=binance_account,
                    bybit_account=bybit_account,
                    pre_snapshot=pre_snapshot
                ))

            # ── P1 FIX: Immediate B-side retry when single-leg detected ──
            # 风险2修复: 原先手写 for 3x sleep(1s)+place_bybit_order(裸调) 绕开了
            # _execute_bybit_market_buy/sell 内部的重试/10014-收缩/retcode校验等护栏。
            # 改为直接调用统一执行通道: 一次调用即含内部 max_retries(=3) 退避重试。
            # Only when hedge_multiplier==1.0 (standard mode, not amplified hedge)
            if (exec_result.get('is_single_leg') and self.hedge_multiplier == 1.0
                    and exec_result.get('binance_filled_qty', 0) > 0
                    and exec_result.get('bybit_filled_qty', 0) == 0):
                _retry_binance_filled = exec_result['binance_filled_qty']
                sym_a_r, sym_b_r, conv_r = _get_pair_config(self.pair_code)
                _retry_b_qty = quantity_converter.xau_to_lot(_retry_binance_filled)
                # Determine B-side direction
                if strategy_type in ('reverse_opening', 'forward_closing'):
                    _retry_side = "Buy"
                    _retry_close = strategy_type == 'forward_closing'
                else:
                    _retry_side = "Sell"
                    _retry_close = strategy_type == 'reverse_closing'
                logger.warning(
                    f"[SINGLE_LEG_RETRY] B-side=0 with A-side={_retry_binance_filled}, "
                    f"统一走 _execute_bybit_market 内部重试通道 ({_retry_side} {_retry_b_qty} lot {sym_b_r})"
                )
                try:
                    _retry_fn = (self.order_executor.base_executor._execute_bybit_market_buy
                                 if _retry_side == "Buy"
                                 else self.order_executor.base_executor._execute_bybit_market_sell)
                    _retry_ret = await _retry_fn(
                        bybit_account, sym_b_r, _retry_b_qty, close_position=_retry_close,
                    )
                    _retry_filled = (_retry_ret.get('filled_qty', 0) if isinstance(_retry_ret, dict)
                                     else (_retry_ret or 0))
                    if _retry_filled and _retry_filled > 0:
                        logger.warning(f"[SINGLE_LEG_RETRY] B-side SUCCESS via 统一重试通道: filled={_retry_filled}")
                        exec_result['bybit_filled_qty'] = _retry_filled
                        exec_result['is_single_leg'] = False
                        exec_result['success'] = True
                        exec_result['single_leg_retried'] = True
                        if isinstance(_retry_ret, dict) and _retry_ret.get('avg_price'):
                            exec_result['bybit_avg_price'] = _retry_ret['avg_price']
                        if isinstance(_retry_ret, dict) and _retry_ret.get('ticket'):
                            exec_result['bybit_ticket'] = _retry_ret['ticket']
                    else:
                        logger.error(f"[SINGLE_LEG_RETRY] B-side 统一重试通道仍未成交")
                except Exception as _retry_e:
                    logger.error(f"[SINGLE_LEG_RETRY] B-side 统一重试通道异常: {_retry_e}")

            # On successful round-trip, keep preflight cache warm.
            if exec_result.get('success'):
                _sym_a_rf, _sym_b_rf, _ = _get_pair_config(self.pair_code)
                self._mt5_preflight_refresh(bybit_account, _sym_b_rf)

            if not exec_result['success']:
                # ── 资金/保证金达上限: 良性暂缓开仓(不报错/不告警/不停策略/按钮不复位), 待平仓释放保证金后自动继续 ──
                _bres0 = exec_result.get('binance_result') or {}
                _ec0 = str(_bres0.get('error_code'))
                _bf0 = exec_result.get('binance_filled_qty', 0) or 0
                if is_opening and _bf0 == 0 and (
                    exec_result.get('margin_precheck_failed')
                    or (_bres0.get('terminal_error') and _ec0 in ('-2019', '-2018', '-4051'))
                ):
                    if loop_count % 50 == 1:
                        logger.info(f"[ladder={ladder_idx}] 主账号保证金达上限，暂缓开仓，待平仓释放后自动继续 ({exec_result.get('error')})")
                    self.trigger_mgr.reset()
                    await self._push_trigger_reset(ladder_idx, strategy_type)
                    await self._sleep_or_stop(max(self.api_spam_prevention_delay, 2.0))
                    continue
                # 平空(position_exhausted)为正常态, 由下方 INFO 记录; 其余失败才 ERROR(避免噪音告警)
                if not (exec_result.get('position_exhausted') and not is_opening):
                    logger.error(f"Execution failed: {exec_result.get('error')}")

                # CRITICAL: MT5 position exhausted — no more position to close.
                # Treat as normal completion (not an error) and exit the ladder loop.
                if exec_result.get('position_exhausted') and not is_opening:
                    logger.info(
                        f"[ladder={ladder_idx}] MT5持仓已耗尽 ({exec_result.get('error')})，"
                        f"平仓策略视为完成 pos={current_position}/{ladder.total_qty}"
                    )
                    # FIX: Return position_exhausted flag so V2 outer loop exits the entire strategy.
                    # Without this, V2 loop sees success and re-enters the same ladder, creating
                    # a tight error loop (zombie strategy). MT5 has no positions to close — no
                    # ladder can succeed, so the entire closing strategy must terminate.
                    return {'success': True, 'position_exhausted': True, 'message': 'MT5 positions exhausted'}

                # CRITICAL: Binance API outage detected — stop strategy and send emergency alert
                if exec_result.get('binance_api_error'):
                    logger.error(f"[EMERGENCY] Binance API outage during {strategy_type} execution — stopping strategy immediately")
                    self.is_running = False
                    await self._send_binance_api_emergency_alert(strategy_type, exec_result)
                    return {'success': False, 'error': 'Binance API outage'}

                # CRITICAL: Terminal (non-retryable) Binance error — stop the strategy and notify.
                # Without this guard the loop keeps retrying forever, e.g. -4411 TradFi-Perps
                # agreement, -2015 API key invalid, -4401 account blocked, etc.
                binance_result = exec_result.get('binance_result') or {}
                if binance_result.get('terminal_error'):
                    err_code = binance_result.get('error_code', 'unknown')
                    err_msg = binance_result.get('error', '未知错误')
                    logger.error(
                        f"[TERMINAL] Binance returned non-retryable error (code={err_code}) during "
                        f"{strategy_type} — stopping strategy: {err_msg}"
                    )
                    self.is_running = False
                    try:
                        from app.core.redis_client import redis_client as _rc
                        import json as _json
                        # Human-readable hint for common compliance errors
                        hints = {
                            -4411: 'Binance 要求签署 TradFi-Perps 合约协议。请登录 Binance 网页端 → 合约交易 → 黄金品种，完成协议签署后重试。',
                            -4412: 'Binance 账户类型需要升级，请在网页端完成账户升级。',
                            -4400: 'API 账户无交易权限，请检查 API Key 是否开启了合约交易权限。',
                            -4401: 'Binance 账户合约交易已被冻结，请联系 Binance 客服。',
                            -2015: 'API Key 无效或 IP 未加白名单。',
                        }
                        try:
                            _code_int = int(err_code)
                        except (TypeError, ValueError):
                            _code_int = None
                        hint = hints.get(_code_int, '请检查 Binance 账户状态和 API 权限。')
                        evt = {
                            "user_id": self.user_id or "",
                            "type": "risk_alert",
                            "data": {
                                "alert_type": "binance_terminal_error",
                                "level": "critical",
                                "title": "⛔ Binance 账户异常 — 策略已停止",
                                "message": f"{err_msg}",
                                "popup_config": {
                                    "title": "⛔ Binance 账户异常",
                                    "content": f"错误代码: {err_code}\n{err_msg}\n\n{hint}",
                                    "sound_file": "liquidation.mp3",
                                    "sound_repeat": 3,
                                },
                            },
                        }
                        if self.user_id:
                            await _rc.publish("ws:user_event", _json.dumps(evt))
                        logger.info(f"[TERMINAL] Alert published to ws:user_event for user {self.user_id}")
                    except Exception as _alert_err:
                        logger.warning(f"[TERMINAL] Failed to publish stop alert: {_alert_err}")
                    return {'success': False, 'error': f'Terminal Binance error: {err_code}'}

                # CRITICAL FIX: Even if execution failed, record Binance filled qty to prevent over-trading
                binance_filled = exec_result.get('binance_filled_qty', 0)
                if binance_filled > 0:
                    # Record the filled quantity to position manager
                    self.position_mgr.record_opening(
                        self.strategy_id,
                        ladder_idx,
                        strategy_type,
                        binance_filled
                    )
                    logger.warning(f"Execution failed but Binance filled {binance_filled} XAU - recorded to prevent over-trading")

                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)
                await self._sleep_or_stop(self.api_spam_prevention_delay)
                continue

            # Step 9: Handle three scenarios
            binance_filled = exec_result.get('binance_filled_qty', 0)
            spread_cancelled = exec_result.get('spread_cancelled', False)
            is_partial = binance_filled > 0 and binance_filled < order_qty * 0.95

            # Scenario 1 pre-check: If monitor reports filled=0, verify via REST API
            # The WS-based monitor can miss fills (ORDER_TRADE_UPDATE not received, 
            # or TradFi-Perps orders have delayed WS events). A false-negative here
            # means we leave unfilled Binance orders on the exchange that later fill
            # without a corresponding B-side hedge → single-leg exposure.
            if binance_filled == 0 and exec_result.get('binance_order_id'):
                try:
                    _order_id = exec_result['binance_order_id']
                    _rest_status = await self.order_executor.base_executor.check_binance_order_status(
                        binance_account, sym_a, _order_id
                    )
                    if _rest_status and _rest_status.get('success'):
                        _actual_filled = _rest_status.get('filled_qty', 0)
                        _actual_status = _rest_status.get('status', '')
                        if _actual_filled > 0:
                            logger.warning(
                                f"[ladder={ladder_idx}] REST verify: order {_order_id} actually filled "
                                f"{_actual_filled} (status={_actual_status}), WS monitor missed it! "
                                f"Executing emergency B-side hedge."
                            )
                            binance_filled = _actual_filled
                            exec_result['binance_filled_qty'] = _actual_filled
                            # Emergency B-side hedge: the executor missed it, do it now
                            try:
                                sym_a_h, sym_b_h, conv_h = _get_pair_config(self.pair_code)
                                from app.utils.quantity_converter import quantity_converter as _qc
                                _b_qty = _qc.xau_to_lot(_actual_filled)
                                # Determine B-side direction based on strategy type
                                _is_opening_s = 'opening' in strategy_type
                                if strategy_type in ('forward_opening', 'reverse_closing'):
                                    _b_side = "Sell"
                                    _close_pos = not _is_opening_s  # forward_opening=open short, reverse_closing=close short
                                else:
                                    _b_side = "Buy"
                                    _close_pos = not _is_opening_s
                                logger.warning(f"[EMERGENCY_HEDGE] Placing B-side {_b_side} {_b_qty} lot on {sym_b_h}")
                                _b_result = await self.order_executor.base_executor.place_bybit_order(
                                    account=bybit_account,
                                    symbol=sym_b_h,
                                    side=_b_side,
                                    order_type="Market",
                                    quantity=str(round(_b_qty, 2)),
                                    close_position=_close_pos,
                                )
                                if _b_result.get('success'):
                                    logger.warning(f"[EMERGENCY_HEDGE] B-side hedge SUCCESS: {_b_result.get('order_id')}")
                                    exec_result['bybit_filled_qty'] = _b_qty
                                else:
                                    logger.error(f"[EMERGENCY_HEDGE] B-side hedge FAILED: {_b_result.get('error')}")
                            except Exception as _hedge_err:
                                logger.error(f"[EMERGENCY_HEDGE] B-side hedge exception: {_hedge_err}")
                except Exception as _e:
                    logger.warning(f"[ladder={ladder_idx}] REST verify failed: {_e}")

            # Scenario 1: Binance not filled or spread cancelled
            if binance_filled == 0:
                consecutive_no_fills += 1

                # Safe exit point 1: Binance order cancelled — no single-leg risk
                if self.stop_requested:
                    logger.info(f"[GRACEFUL STOP] Stop requested — exiting after Binance cancel (safe, no single-leg)")
                    self.is_running = False
                    await self._push_stop_confirmed(strategy_type)
                    break

                # Spread chase: if spread still meets threshold, skip trigger re-accumulation
                # and immediately re-hang Maker order (only wait 0.5s for exchange cooldown)
                try:
                    _chase_spread = await self._get_current_spread(strategy_type)
                    _chase_ok = (
                        (compare_op == CompareOperator.GREATER_EQUAL and _chase_spread >= spread_threshold) or
                        (compare_op == CompareOperator.LESS_EQUAL and _chase_spread <= spread_threshold)
                    )
                except Exception:
                    _chase_ok = False

                if _chase_ok and not spread_cancelled:
                    logger.info(
                        f"Scenario 1 [SPREAD CHASE]: no-fill #{consecutive_no_fills} but spread "
                        f"{_chase_spread:.3f} still meets threshold {spread_threshold}, "
                        f"skipping trigger re-accumulation, immediate re-hang"
                    )
                    await asyncio.sleep(0.5)
                    continue

                # Spread no longer favorable — full reset + backoff
                logger.info(f"Scenario 1: Binance not filled ({consecutive_no_fills}/{MAX_CONSECUTIVE_NO_FILLS}), resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)

                # After too many consecutive no-fills, pause and reset (don't permanently stop)
                if consecutive_no_fills >= MAX_CONSECUTIVE_NO_FILLS:
                    logger.warning(
                        f"[ladder={ladder_idx}] {consecutive_no_fills} consecutive no-fills — "
                        f"pausing {MAX_CONSECUTIVE_NO_FILLS * 2}s then resuming"
                    )
                    consecutive_no_fills = 0
                    await asyncio.sleep(MAX_CONSECUTIVE_NO_FILLS * 2)
                    self.trigger_mgr.reset()
                    continue

                # Progressive backoff: 1s → 2s → 3s → 4s → 5s
                is_opening = strategy_type in ('reverse_opening', 'forward_opening')
                base_wait = (self.order_executor.open_wait_after_cancel_no_trade
                             if is_opening else self.order_executor.close_wait_after_cancel_no_trade)
                wait_time = base_wait * consecutive_no_fills
                logger.info(f"Waiting {wait_time}s after cancel ({'spread' if spread_cancelled else 'timeout'}, no-fill #{consecutive_no_fills})")
                await asyncio.sleep(wait_time)
                continue

            # Scenario 1b: Partial fill after cancel
            if is_partial:
                is_opening = strategy_type in ('reverse_opening', 'forward_opening')
                wait_time = (self.order_executor.open_wait_after_cancel_part
                             if is_opening else self.order_executor.close_wait_after_cancel_part)
                logger.info(f"Partial fill {binance_filled}/{order_qty}, waiting {wait_time}s before continuing")

            # Step 10: Record position
            # Use Binance filled qty as the position basis (Binance is primary leg).
            # Bybit MT5 fill may lag or return 0 due to sync delay — using min() would
            # cause position to never accumulate and the loop to never terminate.
            binance_filled_xau = exec_result.get('binance_filled_qty', 0)
            bybit_filled_lot = exec_result.get('bybit_filled_qty', 0)
            bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_lot)
            filled_qty = binance_filled_xau  # primary leg determines position progress

            # For both opening and closing, use record_opening (additive) to track
            # how many lots have been executed toward the ladder's total_qty target.
            # record_closing uses subtraction and requires current_position > 0,
            # which would prevent the completion check (current_position >= total_qty) from ever triggering.
            self.position_mgr.record_opening(
                self.strategy_id,
                ladder_idx,
                strategy_type,
                filled_qty
            )

            consecutive_no_fills = 0  # Reset on successful fill

            # ── Unhedged accumulator: handle B-side below-min-lot skips ─────────
            # When a partial Binance fill is too small to meet 0.01 Lot minimum,
            # order_executor returns b_side_skipped_below_min=True. Accumulate
            # the skipped XAU here and retry B-side on the next iteration.
            if exec_result.get('b_side_skipped_below_min') and binance_filled_xau > 0:
                unhedged_binance_xau += binance_filled_xau
                logger.warning(
                    f"[HEDGE_ACCUM] B-side skipped (< {MIN_HEDGE_LOT} Lot), "
                    f"accumulated unhedged={unhedged_binance_xau:.4f} XAU"
                )
            elif binance_filled_xau > 0 and bybit_filled_lot > 0:
                # Successful dual-side fill — reset accumulator
                if unhedged_binance_xau > 0:
                    logger.info(f"[HEDGE_ACCUM] Cleared accumulator after successful B-side fill")
                unhedged_binance_xau = 0.0
            elif unhedged_binance_xau > 0 and exec_result.get('bybit_filled_qty', 0) > 0:
                unhedged_binance_xau = 0.0

            logger.info(f"Position updated: {'+'if is_opening else '-'}{filled_qty}")

            # 实得价差(方向化: reverse=主-对冲, forward=对冲-主) — 与历史"价差"列同口径,
            # 供 平均点差/账本/spread_at_execution 推送 统一使用;缺均价时回退触发点差。
            _rl_bap = exec_result.get('binance_avg_price') or 0
            _rl_bbp = exec_result.get('bybit_avg_price') or 0
            if _rl_bap and _rl_bbp:
                _realized_spread = round(float((_rl_bap - _rl_bbp) if 'reverse' in strategy_type else (_rl_bbp - _rl_bap)), 4)
            else:
                _realized_spread = current_spread

            # Step 11: Push status updates
            asyncio.create_task(self._push_position_change(ladder_idx, filled_qty, position_info, ladder.total_qty))
            await self._push_order_executed(ladder_idx, exec_result, _realized_spread)

            # Step 11.5: 记录 strategy 成交元数据 (threshold/spread) 到 Redis 供历史查询补全
            try:
                binance_order_id = exec_result.get('binance_order_id')
                if binance_order_id:
                    from app.core.redis_client import redis_client as _rc_meta
                    import json as _json_meta
                    meta = {
                        'threshold': spread_threshold,
                        'strategy_type': strategy_type,
                        'pair_code': self.pair_code,
                        'trigger_spread': current_spread,
                    }
                    await _rc_meta.client.setex(
                        f'strategy_trade_meta:{binance_order_id}',
                        30 * 86400,
                        _json_meta.dumps(meta),
                    )
            except Exception as _e_meta:
                logger.warning(f"[META] Redis write failed for order {exec_result.get('binance_order_id')}: {_e_meta}")

            # Step 11.55: 维护"在仓开仓明细账本"(Redis FIFO) — 供前端权威平均入场点差 + 逐笔明细回灌
            # 开仓 RPUSH 一条;平仓按 FIFO 从队首消费。纯记账,异常不影响交易。
            try:
                if self.user_id and binance_filled_xau and binance_filled_xau > 0:
                    from app.core.redis_client import redis_client as _rc_led
                    import json as _json_led, time as _time_led
                    _dir = 'reverse' if 'reverse' in strategy_type else 'forward'
                    _ledger_key = f"pos_open_ledger:{self.user_id}:{self.pair_code}:{_dir}"
                    _LED_TTL = 30 * 86400
                    if is_opening:
                        _entry = _json_led.dumps({
                            "q": round(float(binance_filled_xau), 6),
                            "m": round(float(exec_result.get('bybit_filled_qty', 0) or 0), 6),
                            "s": _realized_spread if _realized_spread is not None else 0.0,
                            "ladder": ladder_idx,
                            "ts": int(_time_led.time() * 1000),
                            "oid": exec_result.get('binance_order_id'),
                        })
                        await _rc_led.client.rpush(_ledger_key, _entry)
                        await _rc_led.client.expire(_ledger_key, _LED_TTL)
                    else:
                        _rows = await _rc_led.client.lrange(_ledger_key, 0, -1)
                        _remain = float(binance_filled_xau)
                        _new = []
                        _done = False
                        for _raw in (_rows or []):
                            if _done:
                                _new.append(_raw); continue
                            try:
                                _e = _json_led.loads(_raw)
                            except Exception:
                                continue
                            _q = float(_e.get('q') or 0)
                            if _remain >= _q - 1e-9:
                                _remain -= _q
                            elif _remain > 1e-9:
                                _e['q'] = round(_q - _remain, 6); _remain = 0.0
                                _new.append(_json_led.dumps(_e)); _done = True
                            else:
                                _new.append(_raw); _done = True
                        _pipe = _rc_led.client.pipeline(transaction=True)
                        _pipe.delete(_ledger_key)
                        if _new:
                            _pipe.rpush(_ledger_key, *_new)
                            _pipe.expire(_ledger_key, _LED_TTL)
                        await _pipe.execute()
            except Exception as _e_led:
                logger.debug(f"[POS_LEDGER] update skipped: {_e_led}")

            # Step 11.6: 滑点保护检查 (双边成交后)
            # 风险1修复: B侧均价桥接不返回(恒0) → 有ticket时异步回填deals均价后再检查
            try:
                _b_filled = exec_result.get('binance_filled_qty', 0)
                _bb_filled = exec_result.get('bybit_filled_qty', 0)
                _bap = exec_result.get('binance_avg_price', 0) or 0
                _bbp = exec_result.get('bybit_avg_price', 0) or 0
                if _b_filled > 0 and _bb_filled > 0 and _bap > 0 and self.user_id:
                    if _bbp > 0:
                        # B侧均价已知 → 同步即时检查(原有路径)
                        actual_spread = round(float((_bap - _bbp) if 'reverse' in strategy_type else (_bbp - _bap)), 4)
                        slippage_val = actual_spread - (spread_threshold or 0)
                        from app.services.slippage_guard import record_and_check as _slip_check
                        await _slip_check(
                            user_id=self.user_id,
                            pair_code=self.pair_code,
                            strategy_type=strategy_type,
                            spread_threshold=spread_threshold,
                            actual_spread=actual_spread,
                            slippage=slippage_val,
                            binance_order_id=binance_order_id,
                            binance_avg_price=_bap,
                            bybit_avg_price=_bbp,
                        )
                    else:
                        # B侧均价缺失(桥接只返回ticket, avg_price=0) →
                        # 非阻塞异步回填: 用 deals 历史查均价后补调滑点检查。
                        # create_task 立即返回, 不占用当前执行周期时间(Step 12立即继续)。
                        _bybit_ticket_for_slip = exec_result.get('bybit_ticket')
                        if _bybit_ticket_for_slip and bybit_account:
                            _slip_ctx = {
                                'user_id': str(self.user_id), 'pair_code': self.pair_code,
                                'strategy_type': strategy_type,
                                'spread_threshold': spread_threshold or 0,
                                'bap': _bap, 'binance_order_id': binance_order_id,
                                'ticket': int(_bybit_ticket_for_slip),
                                'account': bybit_account, 'symbol': sym_b,
                                'is_reverse': 'reverse' in strategy_type,
                            }
                            async def _backfill_and_slip(_ctx=_slip_ctx):
                                try:
                                    from app.services.order_executor_v2 import _get_mt5_client_for_account as _gmc
                                    from app.services.slippage_guard import record_and_check as _sc
                                    _mt5 = _gmc(_ctx['account'])
                                    _deals = None
                                    for _da in range(3):
                                        if hasattr(_mt5, 'get_deals_by_ticket_async'):
                                            _deals = await _mt5.get_deals_by_ticket_async(_ctx['ticket'])
                                        else:
                                            _deals = _mt5.get_deals_by_ticket(_ctx['ticket'])
                                        if _deals:
                                            break
                                        await asyncio.sleep(1.0)
                                    if not _deals:
                                        logger.warning(f"[SLIPPAGE_ASYNC] ticket={_ctx['ticket']} deals空, 跳过滑点检查")
                                        return
                                    _tv = sum(float(d.get('volume', 0)) for d in _deals)
                                    _tc = sum(float(d.get('price', 0)) * float(d.get('volume', 0)) for d in _deals)
                                    _bbp_f = (_tc / _tv) if _tv > 0 else 0.0
                                    if _bbp_f <= 0:
                                        logger.warning(f"[SLIPPAGE_ASYNC] ticket={_ctx['ticket']} 均价=0, 跳过")
                                        return
                                    _asp = round(float((_ctx['bap'] - _bbp_f) if _ctx['is_reverse'] else (_bbp_f - _ctx['bap'])), 4)
                                    _slip = _asp - _ctx['spread_threshold']
                                    await _sc(
                                        user_id=_ctx['user_id'], pair_code=_ctx['pair_code'],
                                        strategy_type=_ctx['strategy_type'],
                                        spread_threshold=_ctx['spread_threshold'],
                                        actual_spread=_asp, slippage=_slip,
                                        binance_order_id=_ctx['binance_order_id'],
                                        binance_avg_price=_ctx['bap'], bybit_avg_price=_bbp_f,
                                    )
                                    logger.info(f"[SLIPPAGE_ASYNC] ticket={_ctx['ticket']} 回填均价={_bbp_f:.4f} 点差={_asp:.4f} 滑点={_slip:.4f}")
                                except Exception as _bfe:
                                    logger.warning(f"[SLIPPAGE_ASYNC] 回填异常: {_bfe}")
                            asyncio.create_task(_backfill_and_slip())
                            logger.debug(f"[SLIPPAGE_ASYNC] ticket={_bybit_ticket_for_slip} 异步均价回填已提交")
            except Exception as _e_slip:
                logger.warning(f"[SLIPPAGE] check failed: {_e_slip}")

            # Step 12: Reset triggers after successful execution
            # CRITICAL FIX: Always reset triggers after order execution to allow next cycle to accumulate fresh triggers
            # This prevents the issue where trigger count remains high and blocks subsequent executions
            logger.info(f"[ladder={ladder_idx}] Filled {binance_filled}/{order_qty}, resetting triggers. New pos: {current_position + filled_qty}/{ladder.total_qty}")
            self.trigger_mgr.reset()
            await self._push_trigger_reset(ladder_idx, strategy_type)

            # Safe exit point 2: Both legs filled — no single-leg risk
            if self.stop_requested:
                logger.info(f"[GRACEFUL STOP] Stop requested — exiting after dual-leg fill (safe, binance={binance_filled} bybit={exec_result.get('bybit_filled_qty', 0)})")
                self.is_running = False
                await self._push_stop_confirmed(strategy_type)
                break

            # ── 目标达成立即退出，不等待 api_spam_prevention_delay ──────────────────
            # 若本次成交已填满当前梯度的总量，直接 break 进入下一梯度或退出，
            # 无需再等 api_spam_prevention_delay（3s），避免双边成交后按钮复原延迟。
            new_position = current_position + filled_qty
            _ceiling_done = (
                (not is_closing) and opening_ceiling is not None and base_pos is not None
                and (base_pos + new_position) >= opening_ceiling - 1e-9
            )
            if new_position >= ladder.total_qty or _ceiling_done:
                logger.info(
                    f"[ladder={ladder_idx}] 目标已达成 ({new_position:.4f}/{ladder.total_qty})，"
                    f"跳过 api_spam_prevention_delay，立即退出"
                )
                break

            # Small delay to prevent API spam (configurable via api_spam_prevention_delay)
            # 仅在目标未完成、需要继续触发时等待，防止频繁 API 调用
            logger.info(f"Waiting {self.api_spam_prevention_delay} seconds to prevent API spam")
            await self._sleep_or_stop(self.api_spam_prevention_delay)

        logger.info(f"[ladder={ladder_idx}] Loop exited after {loop_count} iterations. pos={current_position}/{ladder.total_qty} stop_req={self.stop_requested} is_running={self.is_running}")
        return {'success': True}

    async def _reload_strategy_config(self, strategy_type: str):
        """热重载: 回读最新 DB 策略配置, 返回 (List[LadderConfig], order_qty_limit) 或 None。
        字段映射与启动端点一致: openPrice->opening_spread, threshold->closing_spread,
        qtyLimit->total_qty, opening/closing_sync_count->opening/closing_trigger_count,
        opening/closing_m_coin->order_qty_limit。"""
        from app.core.database import AsyncSessionLocal
        from app.models.strategy import StrategyConfig
        from sqlalchemy import select
        from uuid import UUID as _UUID
        _dir = 'reverse' if 'reverse' in strategy_type else 'forward'
        try:
            _uid = self.user_id if isinstance(self.user_id, _UUID) else _UUID(str(self.user_id))
        except Exception:
            _uid = self.user_id
        async with AsyncSessionLocal() as _db:
            _res = await _db.execute(
                select(StrategyConfig).where(
                    StrategyConfig.user_id == _uid,
                    StrategyConfig.strategy_type == _dir,
                    StrategyConfig.pair_code == self.pair_code,
                ).order_by(StrategyConfig.create_time.desc())
            )
            _cfg = _res.scalars().first()
        if not _cfg or not _cfg.ladders:
            return None
        _otc = int(_cfg.opening_sync_count or 1)
        _ctc = int(_cfg.closing_sync_count or 1)
        _lds = []
        for _ld in _cfg.ladders:
            try:
                _lds.append(LadderConfig(
                    enabled=bool(_ld.get('enabled', True)),
                    opening_spread=float(_ld.get('openPrice', 0) or 0),
                    closing_spread=float(_ld.get('threshold', 0) or 0),
                    total_qty=float(_ld.get('qtyLimit', 0) or 0),
                    opening_trigger_count=_otc,
                    closing_trigger_count=_ctc,
                ))
            except Exception:
                continue
        if not _lds:
            return None
        _mc = _cfg.opening_m_coin if 'opening' in strategy_type else _cfg.closing_m_coin
        _oql = float(_mc or 1.0)
        return (_lds, _oql)

    async def _cancel_own_a_side_orders(self, account) -> int:
        """撤掉本策略(clientOrderId 前缀 's-')在 A 侧(sym_a)的挂单, 保留人工应急('m-')单。返回撤单数。
        与 _execute_ladder Step 7.9 同口径(只撤自己的)。"""
        sym_a, _, _ = _get_pair_config(self.pair_code)
        from app.core.proxy_utils import build_proxy_url
        _n = 0
        try:
            if account.platform_id == 1:
                from app.services.binance_client import BinanceFuturesClient
                _c = BinanceFuturesClient(account.api_key, account.api_secret, proxy_url=build_proxy_url(account.proxy_config))
                try:
                    _open = await _c.get_open_orders(symbol=sym_a)
                    _own = [o for o in (_open or []) if str(o.get("clientOrderId", "")).startswith("s-")]
                    for _od in _own:
                        try:
                            await _c.cancel_order(sym_a, _od["orderId"]); _n += 1
                        except Exception:
                            pass
                finally:
                    await _c.close()
            elif account.platform_id == 2:
                from app.services.bybit_client import BybitV5Client
                _c = BybitV5Client(api_key=account.api_key, api_secret=account.api_secret, proxy_url=build_proxy_url(account.proxy_config))
                try:
                    _open = await _c.get_open_orders(category='linear', symbol=sym_a)
                    _list = (_open or {}).get('list', []) if isinstance(_open, dict) else (_open or [])
                    _own = [o for o in _list if str(o.get('orderLinkId', '') or o.get('clientOrderId', '')).startswith('s-')]
                    for _od in _own:
                        try:
                            _oid = _od.get('orderId') or _od.get('order_id')
                            if _oid:
                                await _c.cancel_order(category='linear', symbol=sym_a, order_id=_oid); _n += 1
                        except Exception:
                            pass
                finally:
                    await _c.close()
        except Exception as _e:
            logger.warning(f"[capacity-guard] cancel own A-side orders failed: {_e}")
        return _n

    async def _capacity_reduce_guard(self, strategy_type, account, ladder_idx, pos_before, order_qty, stop_event):
        """Feature(b): 在途开仓单期间, 每~1.5s 只读 DB 策略配置(不打交易所);
        若用户保存把本阶梯累计总手数降到使 (pos_before + order_qty) 超过新上限,
        则撤掉本策略在途 s- 开仓单, 置 self._cap_cancel 让 _execute_ladder 干净结束本阶梯。
        仅作用于开仓; 仅在真实容量缩小时触发; 撤单只撤自己的(保留人工 m-)。"""
        if 'opening' not in strategy_type:
            return
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=1.5)
                    return  # 订单已结束(stop_event 置位), 退出护栏
                except asyncio.TimeoutError:
                    pass
                try:
                    _fresh = await asyncio.wait_for(self._reload_strategy_config(strategy_type), timeout=4.0)
                except Exception:
                    continue
                if not _fresh:
                    continue
                _f_ladders, _ = _fresh
                if ladder_idx < len(_f_ladders):
                    _new_ceiling = float(_f_ladders[ladder_idx].total_qty or 0)
                elif _f_ladders:
                    _new_ceiling = float(_f_ladders[-1].total_qty or 0)
                else:
                    continue
                if pos_before + order_qty > _new_ceiling + 1e-6:
                    _cancelled = await self._cancel_own_a_side_orders(account)
                    self._cap_cancel = True
                    self._cap_cancel_reason = (
                        f"保存即生效·撤在途: 阶梯{ladder_idx}新累计上限={_new_ceiling:.2f} "
                        f"< 已开{pos_before:.2f}+在途{order_qty:.2f}(撤{_cancelled}张s-在途单)")
                    logger.warning(f"[ladder={ladder_idx}] {self._cap_cancel_reason}")
                    stop_event.set()
                    return
        except asyncio.CancelledError:
            return
        except Exception as _e:
            logger.debug(f"[capacity-guard] guard error: {_e}")

    async def _execute_continuous_v2(
        self,
        strategy_type: str,
        binance_account,
        bybit_account,
        ladders,
        order_qty_limit: float,
    ):
        """Position-based continuous execution with dynamic ladder selection.

        Replaces the sequential for-loop through ladders. Runs a SINGLE loop that:
        1. Reads global position
        2. Reads current spread
        3. Uses LadderRangeMapper to determine active ladder + remaining capacity
        4. Calls _execute_ladder() with a synthetic config for the active ladder
        5. Re-evaluates after each ladder completion
        """
        from app.services.ladder_range_mapper import LadderRangeMapper
        # 初始心跳(20260617修): task一进入即设基准, 让看门狗从启动就能精准计时,
        # 覆盖"卡在进while第一轮前/初始化段"的挂死(否则_last_heartbeat恒None只能靠120s宽限)。
        import time as _hb_t0; self._last_heartbeat = _hb_t0.monotonic()
        mapper = LadderRangeMapper(ladders)
        is_opening = 'opening' in strategy_type
        # ── 配置热重载状态: 每 N 秒回读 DB, 变更即重建 mapper/更新 order_qty_limit(保存即生效) ──
        import time as _t_hr
        _hr_last = _t_hr.time()
        _hr_interval = 3.0
        def _hr_sig(_lds, _oql):
            return (round(float(_oql or 0), 6),
                    tuple((bool(l.enabled), round(float(l.opening_spread), 6), round(float(l.closing_spread), 6),
                           round(float(l.total_qty), 6), int(l.opening_trigger_count), int(l.closing_trigger_count))
                          for l in _lds))
        _hr_cur = _hr_sig(ladders, order_qty_limit)

        logger.info(
            f"[V2] Starting position-based execution: strategy={self.strategy_id} "
            f"type={strategy_type} ladders={len(ladders)} capacity={mapper.get_global_capacity()}"
        )

        scan_count = 0
        # 活跃键刷新时钟: 挂钟30s一次(防scan因代理超时拖长后 scan_count%200 触发周期>TTL 键提前过期)
        import time as _hb_t_ak; _active_key_last_set = float('-inf')

        # MT5 收盘自动停：记录启动时距收盘分钟数，用于区分"收盘前一直运行"与"手动重启"
        from app.utils.trading_time import (
            minutes_to_mt5_close as _mins_to_close,
            SOFT_STOP_BUFFER_MIN as _SOFT_MIN,
            HARD_STOP_BUFFER_MIN as _HARD_MIN,
        )
        try:
            _start_mins = _mins_to_close()
        except Exception:
            _start_mins = None
        # 供内层 _execute_ladder 收盘闸沿用同一"启动时距收盘"软停判据(captive 在内层时外层闸跑不到)
        self._start_mins_to_close = _start_mins

        while self.is_running and not self.stop_requested:
            scan_count += 1
            import time as _hb_t2; self._last_heartbeat = _hb_t2.monotonic()  # 心跳

            # ── 配置热重载: 保存策略后无需停止开/平仓即生效 ──
            if _t_hr.time() - _hr_last >= _hr_interval:
                _hr_last = _t_hr.time()
                try:
                    _fresh = await asyncio.wait_for(self._reload_strategy_config(strategy_type), timeout=5.0)
                    if _fresh is not None:
                        _f_ladders, _f_oql = _fresh
                        _f_sig = _hr_sig(_f_ladders, _f_oql)
                        if _f_sig != _hr_cur:
                            mapper = LadderRangeMapper(_f_ladders)
                            order_qty_limit = _f_oql
                            _hr_cur = _f_sig
                            logger.info(f"[V2][热重载] {strategy_type} 配置变更已生效: order_qty_limit={order_qty_limit}, ladders={len(_f_ladders)}")
                except Exception as _hre:
                    logger.debug(f"[V2][热重载] reload skipped: {_hre}")

            # 活跃键刷新: 挂钟30s一次,不依赖scan次数
            # (scan因SOCKS5代理超时最坏24s,200次=4800s>TTL3600s会提前过期导致按钮误熄灭)
            _now_ak = _hb_t_ak.monotonic()
            if self._active_key and (_now_ak - _active_key_last_set >= 30.0):
                try:
                    await self._redis.set(self._active_key, "1", ex=3600)
                    _active_key_last_set = _now_ak
                except Exception:
                    pass
                # P2: 同节奏写进程心跳哈希(跨进程/抗重启真相源, admin 进程监控读它)
                await self._write_proc_heartbeat()

            # ── MT5 收盘自动停检查 ──────────────────────────────────────────
            try:
                _mins = _mins_to_close()
            except Exception:
                _mins = None
            if _mins is not None:
                if _mins <= _HARD_MIN:
                    logger.info(
                        f"[V2][MT5收盘] 距收盘 {_mins:.1f} 分钟 <= {_HARD_MIN}，硬停 {strategy_type}"
                    )
                    self.stop_reason = 'market_close'; await self._mark_resume_pending(strategy_type)
                    self.stop_requested = True
                    break
                elif _mins <= _SOFT_MIN:
                    # 软停：仅当本策略在进入15分钟窗口前就已运行（启动时>15分钟）
                    # 启动时已在窗口内的（手动重启）不软停，继续运行至硬停
                    # 20260708: 豁免线+2分钟宽限(与内层闸一致, 见0708 NG事故)
                    if _start_mins is not None and _start_mins > _SOFT_MIN + 2.0:
                        logger.info(
                            f"[V2][MT5收盘] 距收盘 {_mins:.1f} 分钟 <= {_SOFT_MIN}，软停 {strategy_type}"
                            f"（启动时={_start_mins:.1f}分钟，可手动重启运行至收盘前{_HARD_MIN}分钟）"
                        )
                        self.stop_reason = 'market_close'; await self._mark_resume_pending(strategy_type)
                        self.stop_requested = True
                        break

            # ── MT5 当前休市硬闸: 休市中只等待, 绝不下单(防主腿先成交、对冲跟不上的单腿) ──
            # ── 连接健康闸: 主账号币安WS / 对冲MT5桥 任一掉线 -> 暂停(不开不平)+推送暂停态; 恢复后自动续跑(防掉线期主腿成交、对冲跟不上的单腿) ──
            try:
                _conn_reason = await asyncio.wait_for(
                    self._connection_down_reason(binance_account, bybit_account), timeout=6.0)
            except asyncio.TimeoutError:
                _conn_reason = "连接检测超时(可能SSL阻塞)"
                logger.warning(f"[CONN_GATE] _connection_down_reason timeout 6s ({strategy_type})")
            if _conn_reason:
                if not getattr(self, "_conn_paused", False):
                    self._conn_paused = True
                    await self._push_connection_status(strategy_type, True, _conn_reason)
                    logger.warning(f"[CONN_GATE] {strategy_type} 暂停: {_conn_reason} (连接恢复后自动续跑)")
                await self._sleep_or_stop(2.0)
                continue
            elif getattr(self, "_conn_paused", False):
                self._conn_paused = False
                await self._push_connection_status(strategy_type, False, "连接已恢复")
                logger.info(f"[CONN_GATE] {strategy_type} 连接已恢复, 续跑")

            try:
                from app.utils.trading_time import is_bybit_trading_hours as _is_mkt_open
                _mkt_open, _mkt_reason = _is_mkt_open(self.pair_code)
            except Exception as _mkt_e:
                _mkt_open, _mkt_reason = True, ""  # 判定异常→放行(下游 MT5 预检兜底), 不误锁交易
                if scan_count % 200 == 1:
                    logger.warning(f"[V2][MT5休市] 开/休市判定异常, 暂放行交由 MT5 预检兜底: {_mkt_e}")
            if not _mkt_open:
                # 根因1修复(2026-07-04): 节假日提前休市/日级休市/周末命中时, 原逻辑仅 sleep+continue
                # 干等(按钮不熄、进度照走)。真正能停按钮的收盘倒计时闸(minutes_to_mt5_close)在已休市态
                # 返回 None 被跳过 → 节假日永远停不掉。此处改为: 命中休市即走"停按钮+隔日/重开自动恢复"
                # 语义(与倒计时硬停一致), 由 StrategyResumeMonitor 在开市并过预热后回放同一启动快照。
                logger.info(f"[V2][MT5休市] 当前休市({_mkt_reason}), 停按钮+开市自动恢复 {strategy_type}")
                self.stop_reason = 'market_close'
                await self._mark_resume_pending(strategy_type)
                self.stop_requested = True
                break

            # ── 开市预热闸: 开市后未满本交易对预热分钟数(XAU 1min/ICXAU 2min, 见 config/open_warmup.json), 只等待不下单 ──
            try:
                from app.utils.trading_time import minutes_since_mt5_open as _mins_open, open_warmup_minutes as _warmup_min
                _since_open = _mins_open(self.pair_code)
                _warmup_m = _warmup_min(self.pair_code)
            except Exception:
                _since_open, _warmup_m = None, 0.0
            if _since_open is not None and _warmup_m > 0 and _since_open < _warmup_m:
                if scan_count % 50 == 1:
                    logger.info(f"[V2][开市预热] {self.pair_code} 开市{_since_open:.1f}min < {_warmup_m:.0f}min, 暂不下单 {strategy_type}")
                await self._sleep_or_stop(2.0)
                continue

            # ── 行情背离软暂停：ICMarkets 行情停顿/背离时只暂停下单，恢复后自动继续 ──
            if await self._is_quote_diverged():
                if scan_count % 50 == 1:
                    logger.info(f"[V2][行情背离] 暂停下单（{strategy_type}），待行情恢复")
                await self._sleep_or_stop(0.5)
                continue

            try:
                # 平仓成交后下一轮强制取真实持仓(force_fresh 绕 WS+REST 双缓存, 仅成交后一次)
                _ff_pos = self._force_fresh_pos_next
                self._force_fresh_pos_next = False
                live_pos = await asyncio.wait_for(
                    self._get_live_position(binance_account, strategy_type, force_fresh=_ff_pos), timeout=8.0)
            except Exception as _lpe:
                logger.warning(f"[V2] live_pos 读取超时/失败, 本轮跳过: {_lpe}")
                live_pos = -1.0
            if live_pos < 0:
                await asyncio.sleep(self.trigger_check_interval)
                continue

            # ── 过度平仓护栏: 上一笔平仓后(已 force_fresh)持仓仍未下降=持仓feed严重滞后,
            #    本轮不平、再强制刷新一次, 杜绝"同一顶部阶梯按陈旧持仓反复平、吃掉下一阶梯"。──
            if (not is_opening) and self._closing_pos_before is not None:
                if live_pos >= self._closing_pos_before - 1e-9:
                    if scan_count % 50 == 1:
                        logger.warning(
                            f"[V2] 平仓护栏: 持仓未随上笔平仓下降(live_pos={live_pos:.2f} >= 平仓前={self._closing_pos_before:.2f}), "
                            f"疑似持仓feed滞后, 本轮暂不平、强制刷新")
                    self._closing_pos_before = None
                    self._force_fresh_pos_next = True
                    await self._sleep_or_stop(2.0)
                    continue
                self._closing_pos_before = None  # 已正常下降, 解除护栏

            # 实仓为0自动对账: 清陈旧开仓账本(force_fresh复核, 20s持续+60s节流, 不影响交易)
            try:
                await self._reconcile_ledger_if_flat(binance_account, strategy_type, live_pos)
            except Exception:
                pass

            try:
                current_spread = await asyncio.wait_for(self._get_current_spread(strategy_type), timeout=8.0)
            except Exception as e:
                logger.warning(f"[V2] Failed to get spread: {e}")
                await asyncio.sleep(self.trigger_check_interval)
                continue

            if is_opening:
                active = mapper.get_active_ladder_for_opening(live_pos, current_spread)
            else:
                active = mapper.get_active_ladder_for_closing(live_pos, current_spread)
                # 收尾平仓(20260622修): 原逻辑"残量 < 平仓单位(close_unit)"就整段当 dust 跳过,
                # 会把【可对冲的末尾残量】(如 1.0 = B腿0.01手)永久留仓、平仓进度条卡死。
                # 改为只在残量【凑不齐 B 腿最小手(0.01 Lot)对应的 A 量】时才留 dust;
                # 残量 >= 该最小可对冲量则按残量(<=close_unit)做最小量收尾平掉。
                # 平仓侧 B 腿已 floor 到 0.01 手(order_executor_v2: max(qty,0.01)),故残量>=最小量
                # 收尾平仓 A/B 平衡、不产生单腿(各金对 0.01手=1.0 A量, 即"1手"是安全最小量)。
                if active is not None:
                    try:
                        from app.services.order_executor_v2 import _b_to_a as _b2a
                        _min_closeable = _b2a(0.01, self.pair_code)
                    except Exception:
                        _min_closeable = order_qty_limit  # 回退: 换算不可用时保持原保守行为
                    if not (_min_closeable and _min_closeable > 0):
                        _min_closeable = order_qty_limit
                    if active.remaining_capacity < _min_closeable:
                        if scan_count % 100 == 1:
                            logger.info(
                                f"[V2] Closing dust skipped: remaining={active.remaining_capacity:.4f} "
                                f"< 最小可对冲量={_min_closeable:.4f}(B腿0.01手) (left as dust)"
                            )
                        active = None

            if active is None:
                if scan_count % 100 == 1:
                    logger.debug(f"[V2] No active ladder: live_pos={live_pos:.2f} spread={current_spread:.3f} (idle, polling 2s)")
                await self._sleep_or_stop(2.0)
                continue

            logger.info(
                f"[V2] Active ladder {active.index}: live_pos={live_pos:.2f}, "
                f"spread={current_spread:.3f}, remaining={active.remaining_capacity:.2f}, "
                f"range=[{active.range_lower}, {active.range_upper}]"
            )

            iter_config = LadderConfig(
                enabled=True,
                opening_spread=active.config.opening_spread,
                closing_spread=active.config.closing_spread,
                total_qty=active.remaining_capacity,
                opening_trigger_count=active.config.opening_trigger_count,
                closing_trigger_count=active.config.closing_trigger_count,
            )

            self.current_ladder_index = active.index
            self.position_mgr.reset_ladder(self.strategy_id, active.index)

            # 平仓前记录真实持仓基线(供过度平仓护栏在下一轮校验持仓是否真的下降)
            if not is_opening:
                self._closing_pos_before = live_pos

            result = await self._execute_ladder(
                ladder_idx=active.index,
                ladder=iter_config,
                strategy_type=strategy_type,
                binance_account=binance_account,
                bybit_account=bybit_account,
                order_qty_limit=order_qty_limit,
                opening_ceiling=(active.range_upper if is_opening else None),
                mapper=mapper,
            )

            # 平仓成交后→下一轮强制取真实持仓(防 WS 黑洞陈旧致死锁顶部阶梯过度平)
            if (not is_opening) and result.get('success') and (result.get('binance_filled') or 0) > 0:
                self._force_fresh_pos_next = True
            elif not is_opening:
                # 本轮未成交(无填充)→解除基线, 避免护栏误判后续正常轮
                self._closing_pos_before = None

            if not result['success']:
                logger.error(f"[V2] Ladder {active.index} failed: {result.get('error')}")
                return result

            # FIX: If _execute_ladder signals position_exhausted (MT5 has no more positions
            # to close), exit the entire V2 loop. No closing ladder can run without MT5
            # positions, so re-entering would create a zombie loop. This is the only safe
            # exit path for "B-side dry" cases.
            if result.get('position_exhausted'):
                # 用户期望: 平仓按钮持续运行——仓位平空后不终止任务, 改为空闲待命,
                # 等开仓策略再次建仓后继续自动平仓; 仅手动停/收盘前自动停(stop_requested)才退出。
                # MT5 无仓时 _execute_ladder 持续返回 position_exhausted, 此处只空转(不会尝试单腿平仓), 安全。
                if scan_count % 100 == 1:
                    logger.info(
                        f"[V2] 仓位已平空, 平仓循环转待命, 等待再次建仓 ({strategy_type}) "
                        f"capacity={mapper.get_global_capacity()}"
                    )
                await self._sleep_or_stop(2.0)
                continue

        # 20260708 退出即撤单: 一切温和退出路径(软停/硬停/休市/停按钮/目标达成)统一
        # 先撤本策略A侧在途s-挂单再收尾 — 三次事故同根: 执行器死亡而挂单存活, 被行情
        # 打成交时无人对冲(0706停按钮遗留/0706崩溃强杀/0708软停击杀重启实例)。
        # 崩溃路径由 _execute_ladder 的 BaseException 安全网负责, 此处覆盖温和路径。
        try:
            await asyncio.wait_for(
                self._cancel_own_orders_on_exit(binance_account, strategy_type), timeout=20.0)
        except Exception as _coe:
            logger.warning(f"[V2] exit-cancel own orders failed: {_coe}")
        logger.info(f"[V2] Execution loop ended: is_running={self.is_running} stop_req={self.stop_requested}")
        await self._push_stop_confirmed(strategy_type)
        return {'success': True, 'message': 'Execution completed'}

    async def _cancel_own_orders_on_exit(self, binance_account, strategy_type):
        """退出收尾: 撤掉A侧本策略(s-前缀)在途挂单; m-手动单神圣不动(既有约定)。
        注: 同对另一方向策略若仍在跑, 其在途maker也可能被一并撤掉 — 其监控会读到
        CANCELED(0成交)按"未成交重挂"正常续跑, 仅一次重挂的代价, 换孤儿单绝迹。"""
        if getattr(binance_account, 'platform_id', None) != 1:
            return
        sym_a_x, _, _ = _get_pair_config(self.pair_code)
        from app.services.binance_client import BinanceFuturesClient as _BFC_x
        from app.core.proxy_utils import build_proxy_url as _bpu_x
        _cli = _BFC_x(binance_account.api_key, binance_account.api_secret,
                      proxy_url=_bpu_x(binance_account.proxy_config))
        try:
            _open = await asyncio.wait_for(_cli.get_open_orders(symbol=sym_a_x), timeout=8.0)
            _own = [o for o in (_open or []) if str(o.get("clientOrderId", "")).startswith("s-")]
            _ok = 0
            for _od in _own:
                try:
                    await asyncio.wait_for(_cli.cancel_order(sym_a_x, _od["orderId"]), timeout=5.0)
                    _ok += 1
                except Exception:
                    pass
            if _own:
                logger.warning(
                    f"[V2] 退出撤单({strategy_type}/{self.pair_code}): 撤掉{_ok}/{len(_own)}笔"
                    f"本策略在途挂单(防执行器退出后挂单被成交无人对冲)")
        finally:
            try:
                await asyncio.wait_for(_cli.close(), timeout=3.0)
            except Exception:
                pass

    async def _reconcile_ledger_if_flat(self, binance_account, strategy_type, live_pos):
        # 实仓为0时自动对账: 清空陈旧开仓账本。force_fresh REST 复核防WS瞬时假0; 持续>=20s; 60s节流。
        import time as _t
        if live_pos is None or live_pos > 0.01:
            self._flat_since = None
            return
        _now = _t.time()
        if getattr(self, "_flat_since", None) is None:
            self._flat_since = _now
            return
        if _now - self._flat_since < 20:
            return
        if _now - getattr(self, "_last_ledger_recon_ts", 0.0) < 60:
            return
        self._last_ledger_recon_ts = _now
        try:
            from app.core.redis_client import redis_client as _rc
            _dir = 'reverse' if 'reverse' in strategy_type else 'forward'
            _key = f"pos_open_ledger:{self.user_id}:{self.pair_code}:{_dir}"
            if not await _rc.client.llen(_key):
                return
            _fresh = await self._get_live_position(binance_account, strategy_type, force_fresh=True)
            if _fresh is not None and _fresh <= 0.01:
                await _rc.client.delete(_key)
                logger.info(f"[POS_LEDGER] 实仓为0(fresh={_fresh})自动对账: 已清空陈旧账本 {_key}")
        except Exception as _e:
            logger.debug(f"[POS_LEDGER] reconcile skipped: {_e}")

    async def _mark_resume_pending(self, strategy_type):
        # mark resume-pending on close-gate auto-stop (only running-then-auto-stopped gets marked)
        try:
            from app.services.strategy_resume_service import mark_resume_pending
            await mark_resume_pending(self.user_id, self.pair_code, strategy_type)
        except Exception as _e:
            logger.warning(f'[RESUME] mark pending failed: {_e}')

    async def _is_quote_diverged(self) -> bool:
        """读取行情背离监控写入的 Redis 标记（无 HTTP）。
        新鲜（ts 在 5s 内）且 diverged=True 才暂停；缺失/过期/异常一律放行（fail-open）。"""
        try:
            await self._init_redis()
            raw = await self._redis.get('quote_divergence:state')
            if not raw:
                return False
            import json as _j, time as _t
            st = _j.loads(raw)
            if _t.time() - float(st.get('ts', 0)) > 5.0:
                return False
            return bool(st.get('diverged'))
        except Exception:
            return False

    async def _connection_down_reason(self, binance_account, bybit_account):
        """主账号(币安市场WS)或对冲账号(MT5桥)掉线检测。返回原因str或None。
        零币安REST: 币安读WS内存(connected+报价新鲜), MT5探桥/health(mt5:true,5s缓存)。
        掉线/探测异常一律判掉线(fail-closed, 宁可暂停也不单腿)。"""
        import time as _t_cg
        # 主账号币安: 市场WS 连接 + 报价新鲜(零REST)
        try:
            from app.services.binance_ws_client import binance_ws
            if not binance_ws.connected:
                return "主账号币安连接中断"
            _sa, _sb, _ = _get_pair_config(self.pair_code)
            _q = binance_ws.get_quote(_sa)
            if _q and _q.get("ts") and (_t_cg.time() * 1000 - float(_q.get("ts")) > 30000):
                return "主账号币安行情中断(报价停更)"
        except Exception:
            return "主账号币安连接中断"
        # 对冲账号: MT5桥 /health(mt5:true), 5s缓存防每轮打桥
        try:
            _now = _t_cg.monotonic()
            _cache = getattr(self, "_mt5_health_cache", None)
            if _cache is not None and (_now - _cache[1]) < 5.0:
                if not _cache[0]:
                    return "对冲账号(MT5)连接中断"
            else:
                from app.services.order_executor_v2 import _get_trading_bridge_url
                import httpx as _httpx
                _burl = _get_trading_bridge_url(str(bybit_account.account_id))
                _ok = False
                _hc = _get_mt5_health_client()
                _r = await _hc.get(f"{_burl}/health")
                _ok = (_r.status_code == 200 and bool((_r.json() or {}).get("mt5")))
                self._mt5_health_cache = (_ok, _now)
                if not _ok:
                    return "对冲账号(MT5)连接中断"
        except Exception:
            try:
                self._mt5_health_cache = (False, _t_cg.monotonic())
            except Exception:
                pass
            return "对冲账号(MT5)连接中断"
        return None

    async def _push_connection_status(self, strategy_type, paused, reason):
        """推送连接暂停/恢复给前端(ws:user_event, type=connection_pause)。"""
        try:
            if not self.user_id:
                return
            from app.core.redis_client import redis_client as _rc
            import json as _json
            evt = {
                "user_id": str(self.user_id),
                "type": "connection_pause",
                "data": {"paused": bool(paused), "reason": reason,
                         "pair_code": self.pair_code, "strategy_type": strategy_type},
            }
            await _rc.publish("ws:user_event", _json.dumps(evt, ensure_ascii=False))
        except Exception as _e:
            logger.debug(f"[CONN_GATE] push status failed: {_e}")

    async def _push_stop_confirmed(self, strategy_type: str):
        """Push stop confirmation event after graceful stop completes."""
        if self.user_id:
            action = 'opening' if 'opening' in strategy_type else 'closing'
            logger.info(f"[GRACEFUL STOP] Pushing stop_confirmed for {self.strategy_id} action={action}")
            await status_pusher.push_custom_event(
                self.strategy_id,
                'stop_confirmed',
                {
                    'action': action,
                    'strategy_type': strategy_type,
                    'reason': getattr(self, 'stop_reason', None) or 'graceful_stop'
                },
                self.user_id
            )

            # 防自动重启(20260616): 手动停时循环自清 Redis snapshot+pending,
            # 确保不被 recover_running_after_restart/StrategyResumeMonitor 在服务重启后拉回。
            # 根因=停止端点曾依赖 task_id 查 strategy_id 才清, task_id 失配(前端持旧id/
            # 经RESUME换新id)即漏清→残留snapshot成定时炸弹。此处用 self.strategy_id 精确自清,
            # 无 task_id 查找、无竞态, 覆盖所有手动停路径。
            # market_close 自动停故意 mark_resume_pending(隔日开市恢复), 必须跳过不清。
            if getattr(self, 'stop_reason', None) != 'market_close':
                try:
                    from app.services.strategy_resume_service import clear_on_manual_stop_by_strategy_id
                    await clear_on_manual_stop_by_strategy_id(self.strategy_id)
                except Exception as _clr_e:
                    logger.warning(f"[RESUME] self-clear on stop failed for {self.strategy_id}: {_clr_e}")

    # REST fallback cache for _get_live_position (user_id+pair → (value, timestamp))
    _rest_pos_cache: dict = {}
    _REST_POS_CACHE_TTL = 3.0  # seconds — at most 1 REST call per 3s
    _ocg_cache: bool = True       # 开仓持仓上限开关缓存(默认 ON)
    _ocg_cache_ts: float = 0.0

    def _opening_ceiling_guard_enabled(self) -> bool:
        """开仓持仓上限硬约束开关(热改,3s 缓存,默认 ON)。"""
        import time as _t, json as _j
        _now = _t.time()
        if getattr(ContinuousStrategyExecutor, "_ocg_cache_ts", 0.0) and (_now - ContinuousStrategyExecutor._ocg_cache_ts) < 3.0:
            return ContinuousStrategyExecutor._ocg_cache
        _enabled = True
        try:
            with open("/data/hustle2026/backend/config/opening_ceiling_guard.json", "r", encoding="utf-8") as _f:
                _d = _j.load(_f)
                if isinstance(_d, dict) and "enabled" in _d:
                    _enabled = bool(_d["enabled"])
        except Exception:
            pass
        ContinuousStrategyExecutor._ocg_cache = _enabled
        ContinuousStrategyExecutor._ocg_cache_ts = _now
        return _enabled

    async def _get_live_position(self, binance_account, strategy_type: str, force_fresh: bool = False) -> float:
        """Get Binance position for closing decisions — ZERO REST in normal operation.

        Priority:
        1. WS cache (position_streamer._binance_positions) — updated by ACCOUNT_UPDATE
           in real-time with zero REST calls. This is the primary source.
        2. REST fallback with 3-second min-interval cache — only fires if WS cache
           is empty (e.g. WS disconnected, or just started).

        For reverse: short position size
        For forward: long position size
        """
        sym_a, _, _ = _get_pair_config(self.pair_code)

        # ── 1. WS cache (primary — zero REST) ──────────────────────────────
        try:
            from app.tasks.broadcast_tasks import position_streamer
            user_id = self.user_id or "_default"
            bn_syms = position_streamer._binance_positions.get(user_id, {})
            if sym_a in bn_syms and not force_fresh:
                long_v, short_v = bn_syms[sym_a]
                if 'reverse' in strategy_type:
                    return short_v
                else:
                    return long_v
            # Try _default user (backward compat — single user mode)
            if user_id != "_default" and not force_fresh:
                bn_default = position_streamer._binance_positions.get("_default", {})
                if sym_a in bn_default:
                    long_v, short_v = bn_default[sym_a]
                    if 'reverse' in strategy_type:
                        return short_v
                    else:
                        return long_v
        except Exception as _ws_e:
            logger.debug(f"[V2] WS position cache miss: {_ws_e}")

        # ── 2. REST fallback with 3s cache ──────────────────────────────────
        import time as _time
        cache_key = f"{self.user_id}:{self.pair_code}:{strategy_type}"
        cached = ContinuousStrategyExecutor._rest_pos_cache.get(cache_key)
        now = _time.time()
        if (not force_fresh) and cached and (now - cached[1]) < ContinuousStrategyExecutor._REST_POS_CACHE_TTL:
            return cached[0]

        try:
            if not hasattr(binance_account, 'binance_client'):
                from app.services.binance_client import BinanceFuturesClient
                from app.core.proxy_utils import build_proxy_url
                binance_account.binance_client = BinanceFuturesClient(
                    api_key=binance_account.api_key,
                    api_secret=binance_account.api_secret,
                    proxy_url=build_proxy_url(binance_account.proxy_config),   # 必须走账户socks5代理,否则直连出口IP→币安-2015
                )
            # 防 socks5 代理偶发卡住 → 无超时 await 永久挂死整个 V2 循环(cq002 启动即无反应的根因)。
            # 超时则抛 TimeoutError 走下方 except → 回退陈旧缓存/-1，循环降级继续而非死锁。
            positions = await asyncio.wait_for(
                binance_account.binance_client.get_position_risk(symbol=sym_a),
                timeout=8.0,
            )
            total = 0.0
            for pos in positions:
                amt = float(pos.get('positionAmt', 0))
                if 'reverse' in strategy_type:
                    if amt < 0:
                        total += abs(amt)
                else:
                    if amt > 0:
                        total += amt
            ContinuousStrategyExecutor._rest_pos_cache[cache_key] = (total, now)
            logger.info(f"[V2] REST fallback position query: {sym_a} {strategy_type} = {total} (WS cache was empty)")
            return total
        except Exception as e:
            logger.warning(f"[V2] REST position query failed: {e}")
            if cached:
                return cached[0]  # return stale cache on error
            return -1.0

    async def _get_current_spread(self, strategy_type: str) -> float:
        """Get current spread for strategy type (pair-aware)"""
        sym_a, sym_b, _ = _get_pair_config(self.pair_code)
        market_data = await market_data_service.get_current_spread(
            binance_symbol=sym_a,
            bybit_symbol=sym_b,
        )
        spreads = market_data_service.calculate_spread(
            market_data.binance_quote,
            market_data.bybit_quote
        )

        if strategy_type == 'reverse_opening':
            return spreads.reverse_entry_spread
        elif strategy_type == 'reverse_closing':
            return spreads.reverse_exit_spread
        elif strategy_type == 'forward_opening':
            return spreads.forward_entry_spread
        elif strategy_type == 'forward_closing':
            return spreads.forward_exit_spread
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

    def _check_spread_condition(
        self,
        current_spread: float,
        threshold: float,
        compare_op: CompareOperator
    ) -> bool:
        """Check if spread meets condition"""
        if compare_op == CompareOperator.GREATER_EQUAL:
            return current_spread >= threshold
        elif compare_op == CompareOperator.LESS_EQUAL:
            return current_spread <= threshold
        return False

    def _get_binance_price(self, market_data, strategy_type: str) -> float:
        """Get reference Binance price for strategy type.

        NOTE: The actual order price is NOT used when post_only=True because
        place_binance_order delegates to place_maker_order (priceMatch=QUEUE),
        which sets the price server-side atomically at the current BBO.

        This value is only used for logging (Step 7) and spread calculation.
        Return the natural side price for reference.
        """
        if 'opening' in strategy_type:
            if 'reverse' in strategy_type:
                return market_data.binance_quote.ask_price   # Reverse opening: SELL SHORT
            else:
                return market_data.binance_quote.bid_price   # Forward opening: BUY LONG
        else:
            if 'reverse' in strategy_type:
                return market_data.binance_quote.bid_price   # Reverse closing: BUY SHORT close
            else:
                return market_data.binance_quote.ask_price   # Forward closing: SELL LONG close

    def _get_bybit_price(self, market_data, strategy_type: str) -> float:
        """Get appropriate Bybit price for strategy type (market orders)"""
        if 'opening' in strategy_type:
            if 'reverse' in strategy_type:
                # Reverse opening: Bybit LONG, use ask for market buy
                return market_data.bybit_quote.ask_price
            else:
                # Forward opening: Bybit SHORT, use bid for market sell
                return market_data.bybit_quote.bid_price
        else:
            if 'reverse' in strategy_type:
                # Reverse closing: Bybit SHORT close, use bid for market sell
                return market_data.bybit_quote.bid_price
            else:
                # Forward closing: Bybit LONG close, use ask for market buy
                return market_data.bybit_quote.ask_price

    async def _execute_order(
        self,
        strategy_type: str,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        spread_threshold: float = None,
        exec_deadline: float = None,
        inflight: dict = None,
    ) -> Dict:
        """Execute order based on strategy type"""
        # ── GATEWAY GUARD ──
        try:
            from app.services.trading_gateway import is_trading_allowed
            gw = await is_trading_allowed(
                caller="continuous_executor",
                user_id=self.user_id,
                pair_code=self.pair_code,
            )
            if not gw.allowed:
                logger.warning(f"[GATEWAY] Order blocked: {gw.reason} | {strategy_type} qty={quantity}")
                return {"success": False, "error": f"Trading blocked: {gw.reason}",
                        "binance_filled_qty": 0, "bybit_filled_qty": 0}
        except Exception as _gw_err:
            logger.debug(f"[GATEWAY] check failed (allowing): {_gw_err}")
        if strategy_type == 'reverse_opening':
            return await self.order_executor.execute_reverse_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
                accumulated_unhedged_xau=getattr(self, '_unhedged_binance_xau', 0.0),
                exec_deadline=exec_deadline,
                inflight=inflight,
            )
        elif strategy_type == 'reverse_closing':
            return await self.order_executor.execute_reverse_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
                exec_deadline=exec_deadline,
                inflight=inflight,
            )
        elif strategy_type == 'forward_opening':
            return await self.order_executor.execute_forward_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
                accumulated_unhedged_xau=getattr(self, '_unhedged_binance_xau', 0.0),
                exec_deadline=exec_deadline,
                inflight=inflight,
            )
        elif strategy_type == 'forward_closing':
            return await self.order_executor.execute_forward_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                spread_threshold=spread_threshold,
                pair_code=self.pair_code,
                hedge_multiplier=self.hedge_multiplier,
                exec_deadline=exec_deadline,
                inflight=inflight,
            )
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

    async def _push_trigger_progress(
        self,
        ladder_idx: int,
        current_count: int,
        required_count: int,
        strategy_type: str,
        current_spread: float = None,
        threshold: float = None,
        express: bool = False,
    ):
        """Push trigger progress update via WebSocket"""
        if self.user_id:
            # Extract action from strategy_type (e.g., 'reverse_opening' -> 'opening')
            action = 'opening' if 'opening' in strategy_type else 'closing'
            await status_pusher.push_custom_event(
                self.strategy_id,
                'trigger_progress',
                {
                    'ladder_index': ladder_idx,
                    'current_count': current_count,
                    'required_count': required_count,
                    'progress_percent': (current_count / required_count) * 100,
                    'action': action,
                    'strategy_type': strategy_type,
                    'current_spread': round(current_spread, 3) if current_spread is not None else None,
                    'threshold': threshold,
                    'express': bool(express),
                },
                self.user_id
            )

    async def _push_trigger_reset(self, ladder_idx: int, strategy_type: str):
        """Push trigger reset notification"""
        if self.user_id:
            action = 'opening' if 'opening' in strategy_type else 'closing'
            await status_pusher.push_custom_event(
                self.strategy_id,
                'trigger_reset',
                {
                    'ladder_index': ladder_idx,
                    'action': action,
                    'strategy_type': strategy_type
                },
                self.user_id
            )

    async def _push_position_change(
        self,
        ladder_idx: int,
        filled_qty: float,
        position_info: Dict,
        total_qty: float = 0
    ):
        """Push position change notification and broadcast real-time MT5 position snapshot."""
        if self.user_id:
            await status_pusher.push_position_change(
                self.strategy_id,
                ladder_idx,
                'opening' if position_info['current_position'] > 0 else 'closing',
                filled_qty,
                position_info['current_position'],
                position_info['total_opened'],
                position_info['total_closed'],
                self.user_id,
                total_qty=total_qty
            )

        # Read MT5 + Binance positions directly (bypasses 60s cache) and push to frontend immediately
        try:
            from app.websocket.manager import manager as ws_manager
            from app.services.binance_client import BinanceFuturesClient

            bybit_account = getattr(self, '_bybit_account', None)
            binance_account = getattr(self, '_binance_account', None)

            long_lots = 0.0
            short_lots = 0.0
            binance_long_xau = 0.0
            binance_short_xau = 0.0

            # Bybit: read from MT5 directly
            sym_a, sym_b, conv_factor = _get_pair_config(self.pair_code)
            if bybit_account and hasattr(bybit_account, 'mt5_client') and bybit_account.mt5_client:
                loop = asyncio.get_event_loop()
                positions = await loop.run_in_executor(
                    None,
                    lambda: bybit_account.mt5_client.get_positions(sym_b)
                )
                long_lots = round(sum(p['volume'] for p in positions if p.get('type') == 0), 2)
                short_lots = round(sum(p['volume'] for p in positions if p.get('type') == 1), 2)

            # Binance: read from REST API directly
            if binance_account and binance_account.api_key and binance_account.api_secret:
                try:
                    from app.core.proxy_utils import build_proxy_url
                    _proxy = build_proxy_url(getattr(binance_account, 'proxy_config', None))
                    client = BinanceFuturesClient(binance_account.api_key, binance_account.api_secret, proxy_url=_proxy)
                    pos_data = await client.get_position_risk(sym_a)
                    await client.close()
                    for pos in pos_data:
                        amt = float(pos.get("positionAmt", 0))
                        if amt > 0:
                            binance_long_xau = round(amt, 3)
                        elif amt < 0:
                            binance_short_xau = round(abs(amt), 3)
                except Exception as be:
                    logger.warning(f"[POSITION_SNAPSHOT] Binance fetch failed: {be}")

            # User-scoped: publish via Redis ws:user_event so only this user's frontend receives it.
            # Must include `pairs` map to prevent overwriting PositionStreamer's complete snapshot.
            if self.user_id:
                try:
                    from app.core.redis_client import redis_client as _rc
                    import json as _json
                    from app.tasks.broadcast_tasks import position_streamer as _ps

                    # Build full pairs map so frontend store stays consistent
                    _mt5_by_user = await _ps._read_mt5_positions_all()
                    _mt5_syms = _mt5_by_user.get(self.user_id, {})
                    _bn_syms = dict(_ps._binance_positions.get(self.user_id, {}))
                    # Inject freshly-read Binance position
                    _bn_syms[sym_a] = (binance_long_xau, binance_short_xau)
                    # Also update the shared position_streamer cache for 1s broadcast
                    _ps.set_binance_positions(binance_long_xau, binance_short_xau, user_id=self.user_id, symbol=sym_a)
                    # Inject freshly-read MT5 position (only if direct read succeeded)
                    _has_direct_mt5 = (long_lots > 0 or short_lots > 0)
                    if _has_direct_mt5:
                        _mt5_syms[sym_b] = (long_lots, short_lots)
                        _ps.set_mt5_positions(long_lots, short_lots, user_id=self.user_id, symbol=sym_b)

                    _pairs_meta = {}
                    try:
                        from app.services.hedging_pair_service import hedging_pair_service
                        for _pair in (hedging_pair_service.list_active_pairs() or []):
                            if not _pair.is_active:
                                continue
                            _sa = _pair.symbol_a.symbol if _pair.symbol_a else None
                            _sb = _pair.symbol_b.symbol if _pair.symbol_b else None
                            if _sa and _sb:
                                _pairs_meta[_pair.pair_code] = {"sym_a": _sa, "sym_b": _sb}
                    except Exception:
                        pass

                    _pairs_out = {}
                    for _pc, _meta in _pairs_meta.items():
                        _sa, _sb = _meta["sym_a"], _meta["sym_b"]
                        _bl, _bs = _bn_syms.get(_sa, (0.0, 0.0))
                        _ml, _ms = _mt5_syms.get(_sb, (0.0, 0.0))
                        if _ml == 0.0 and _ms == 0.0:
                            _alt = _sb.replace("+", ".s")
                            _ml, _ms = _mt5_syms.get(_alt, (0.0, 0.0))
                        _pairs_out[_pc] = {
                            "mt5_long": _ml, "mt5_short": _ms,
                            "binance_long": _bl, "binance_short": _bs,
                        }

                    _xau_pd = _pairs_out.get("XAU", {})
                    evt = {
                        "user_id": self.user_id,
                        "type": "position_snapshot",
                        "data": {
                            "pair_code": self.pair_code,
                            "bybit_long_lots": _xau_pd.get("mt5_long", long_lots),
                            "bybit_short_lots": _xau_pd.get("mt5_short", short_lots),
                            "binance_long_xau": _xau_pd.get("binance_long", binance_long_xau),
                            "binance_short_xau": _xau_pd.get("binance_short", binance_short_xau),
                            "pairs": _pairs_out,
                        }
                    }
                    await _rc.publish("ws:user_event", _json.dumps(evt))
                    logger.info(f"[POSITION_SNAPSHOT] user={self.user_id} pairs={list(_pairs_out.keys())} bybit long={long_lots} short={short_lots} | binance long={binance_long_xau} short={binance_short_xau}")
                except Exception as pub_err:
                    logger.warning(f"[POSITION_SNAPSHOT] Redis publish failed: {pub_err}")
            else:
                logger.warning("[POSITION_SNAPSHOT] self.user_id is None, snapshot not published")
        except Exception as e:
            logger.warning(f"[POSITION_SNAPSHOT] Failed: {e}")

    async def _push_order_executed(
        self,
        ladder_idx: int,
        exec_result: Dict,
        current_spread: float
    ):
        """Push order executed notification"""
        if self.user_id:
            await status_pusher.push_order_executed(
                self.strategy_id,
                f"ladder_{ladder_idx}",
                ladder_idx,
                exec_result.get('binance_filled_qty', 0),
                exec_result.get('bybit_filled_qty', 0),
                current_spread,
                self.user_id
            )

    async def _push_execution_completed(self, strategy_type: str, reason: str = 'completed'):
        """Push execution completed notification via WebSocket"""
        if self.user_id:
            action = 'opening' if 'opening' in strategy_type else 'closing'
            await status_pusher.push_custom_event(
                self.strategy_id,
                'execution_completed',
                {
                    'action': action,
                    'strategy_type': strategy_type,
                    'reason': reason
                },
                self.user_id
            )
            if 'closing' in strategy_type:
                asyncio.ensure_future(self._delayed_zero_snapshot_push())

    async def _delayed_zero_snapshot_push(self):
        try:
            await asyncio.sleep(1.5)
            from app.tasks.broadcast_tasks import position_streamer as _ps
            await _ps.push_snapshot_for_user(self.user_id)
            await asyncio.sleep(2.0)
            await _ps.push_snapshot_for_user(self.user_id)
        except Exception as e:
            logger.debug(f"[DelayedZeroSnapshot] error: {e}")


    async def _snapshot_positions(
        self,
        binance_account: Account,
        bybit_account: Account
    ) -> Dict:
        """
        Snapshot current positions for both accounts before order execution.
        Used as baseline for single-leg detection via position delta comparison.
        """
        try:
            # Init Binance client if needed
            if not hasattr(binance_account, 'binance_client'):
                from app.services.binance_client import BinanceFuturesClient
                from app.core.proxy_utils import build_proxy_url
                binance_account.binance_client = BinanceFuturesClient(
                    api_key=binance_account.api_key,
                    api_secret=binance_account.api_secret,
                    proxy_url=build_proxy_url(binance_account.proxy_config),   # 必须走账户socks5代理,否则直连出口IP→币安-2015
                )

            sym_a, sym_b, conv_factor = _get_pair_config(self.pair_code)
            binance_positions = await asyncio.wait_for(
                binance_account.binance_client.get_position_risk(symbol=sym_a), timeout=8.0)  # 代理卡住防挂死
            binance_qty = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions)

            # Use HTTP bridge for MT5 positions (MT5Client requires Windows)
            bybit_qty_lot = 0.0
            try:
                from app.models.mt5_client import MT5Client as MT5ClientModel
                from app.core.database import AsyncSessionLocal
                from sqlalchemy import select as _sa_sel
                import httpx as _httpx
                async with AsyncSessionLocal() as _snap_db:
                    _mc = (await _snap_db.execute(
                        _sa_sel(MT5ClientModel)
                        .where(MT5ClientModel.account_id == bybit_account.account_id)
                        .where(MT5ClientModel.is_active == True)
                        .where(MT5ClientModel.is_system_service == False)
                        .order_by(MT5ClientModel.priority).limit(1)
                    )).scalar_one_or_none()
                if _mc:
                    _bridge = _mc.bridge_url or f"http://172.31.14.113:{_mc.bridge_service_port}"
                    _api_key = __import__('os').getenv("MT5_API_KEY", "")
                    _headers = {"X-Api-Key": _api_key} if _api_key else {}
                    async with _httpx.AsyncClient(timeout=3.0) as _hc:
                        _resp = await _hc.get(f"{_bridge}/mt5/positions", headers=_headers)
                        if _resp.status_code == 200:
                            _positions = _resp.json() if isinstance(_resp.json(), list) else _resp.json().get("positions", [])
                            bybit_qty_lot = sum(
                                abs(float(p.get("volume", 0)))
                                for p in _positions
                                if p.get("symbol", "") == sym_b
                            )
                else:
                    logger.warning("[SNAPSHOT] No active bridge for bybit account, skipping MT5 snapshot")
            except Exception as _bridge_err:
                logger.warning(f"[SNAPSHOT] Bridge position query failed: {_bridge_err}")
            bybit_qty_xau = bybit_qty_lot * conv_factor

            logger.info(f"[SNAPSHOT] Pre-execution: Binance={binance_qty} XAU, Bybit={bybit_qty_xau} XAU ({bybit_qty_lot} Lot)")
            return {'binance_qty': binance_qty, 'bybit_qty_xau': bybit_qty_xau}

        except Exception as e:
            logger.warning(f"[SNAPSHOT] Failed to snapshot positions: {e}")
            return {'binance_qty': None, 'bybit_qty_xau': None}

    async def _delayed_single_leg_check(
        self,
        strategy_type: str,
        exec_result: Dict,
        binance_account: Account,
        bybit_account: Account,
        pre_snapshot: Dict = None
    ):
        """
        Single-leg detection: two-phase check.

        Phase 1 (immediate): compare this iteration's exact fill quantities
                 from exec_result — immune to snapshot-window accumulation.
        Phase 2 (delayed):   query live positions to verify overall gap,
                 alert only — never auto-REPAIR.
        """
        try:
            sym_a, sym_b, conv_factor = _get_pair_config(self.pair_code)

            # ── Phase 1: exec_result based (no snapshot dependency) ──
            binance_filled = exec_result.get('binance_filled_qty', 0)
            bybit_filled_lot = exec_result.get('bybit_filled_qty', 0)
            bybit_filled_xau = bybit_filled_lot * conv_factor

            # ── 噪音过滤(P0): 本笔 A 腿成交过小=碎单, 直接跳过(经济意义可忽略, 且 B 腿最小
            #    步长=0.01手=conv_factor*0.01 XAU, 低于此根本无法对冲)。纯过滤显示侧,不改交易路径。──
            _sl_flt = _load_single_leg_filter()
            _min_trade = max(0.001, _sl_flt.get("min_trade_xau", 1.0)) if _sl_flt.get("enabled", True) else 0.001
            if binance_filled < _min_trade:
                logger.info(
                    f"[SINGLE_LEG_CHECK] 跳过(碎单): 本笔 Binance成交={binance_filled:.4f} XAU "
                    f"< min_trade_xau={_min_trade:.4f}"
                )
                return

            ratio = bybit_filled_xau / binance_filled if binance_filled > 0 else 0

            logger.info(
                f"[SINGLE_LEG_CHECK] Phase1: exec_result — "
                f"Binance={binance_filled:.4f} XAU, "
                f"Bybit={bybit_filled_xau:.4f} XAU ({bybit_filled_lot:.2f} Lot), "
                f"ratio={ratio:.2%}"
            )

            # 20260619修(Direction-1回归): 不再因 Phase1(基于 exec_result 采信数字)通过就跳过 Phase2。
            # Direction-1 下 B 侧成交量恒=请求量(HTTP200直接采信), ratio 几乎永远≥60% → Phase2
            # (真查两侧实盘持仓的总量对账)永不执行 → 单腿探测被弄瞎(cq002 reverse_opening
            # 9.362 vs 3 无告警实证)。改为: Phase1 仅作信息日志, Phase2 恒执行。本检查本就是
            # asyncio.create_task 异步、在成交之后跑, 不阻塞 B 侧即时下单/策略续跑 —— 即
            # "成交后查持仓": 既保即时成交能力, 又恢复单腿防线(实盘总量对账)。
            if ratio >= 0.60:
                logger.info(f"[SINGLE_LEG_CHECK] Phase1 ratio={ratio:.2%}(采信值仅供参考) → 仍执行Phase2实盘对账")
            else:
                logger.warning(f"[SINGLE_LEG_CHECK] Phase1 ratio={ratio:.2%} < 60% → Phase2实盘对账")

            # ── Phase 2: delayed live-position verification (恒执行, 非阻塞) ──
            await asyncio.sleep(self.delayed_single_leg_check_delay)

            try:
                if not hasattr(binance_account, 'binance_client'):
                    from app.services.binance_client import BinanceFuturesClient
                    from app.core.proxy_utils import build_proxy_url
                    binance_account.binance_client = BinanceFuturesClient(
                        api_key=binance_account.api_key,
                        api_secret=binance_account.api_secret,
                        proxy_url=build_proxy_url(binance_account.proxy_config),   # 必须走账户socks5代理,否则直连出口IP→币安-2015
                    )
                binance_positions = await asyncio.wait_for(
                    binance_account.binance_client.get_position_risk(symbol=sym_a), timeout=8.0)  # 代理卡住防挂死
                post_binance_qty = sum(abs(float(pos.get('positionAmt', 0))) for pos in binance_positions)
                post_binance_net = sum(float(pos.get('positionAmt', 0)) for pos in binance_positions)

                bybit_qty_lot = 0.0
                bybit_net_lot = 0.0
                _mt5_ok = False
                try:
                    from app.models.mt5_client import MT5Client as MT5ClientModel
                    from app.core.database import AsyncSessionLocal
                    from sqlalchemy import select as _sa_sel2
                    import httpx as _httpx2
                    async with AsyncSessionLocal() as _slc_db:
                        _mc2 = (await _slc_db.execute(
                            _sa_sel2(MT5ClientModel)
                            .where(MT5ClientModel.account_id == bybit_account.account_id)
                            .where(MT5ClientModel.is_active == True)
                            .where(MT5ClientModel.is_system_service == False)
                            .order_by(MT5ClientModel.priority).limit(1)
                        )).scalar_one_or_none()
                    if _mc2:
                        _bridge2 = _mc2.bridge_url or f"http://172.31.14.113:{_mc2.bridge_service_port}"
                        _api_key2 = __import__('os').getenv("MT5_API_KEY", "")
                        _headers2 = {"X-Api-Key": _api_key2} if _api_key2 else {}
                        async with _httpx2.AsyncClient(timeout=3.0) as _hc2:
                            _resp2 = await _hc2.get(f"{_bridge2}/mt5/positions", headers=_headers2)
                            if _resp2.status_code == 200:
                                _pos2 = _resp2.json() if isinstance(_resp2.json(), list) else _resp2.json().get("positions", [])
                                bybit_qty_lot = sum(
                                    abs(float(p.get("volume", 0)))
                                    for p in _pos2
                                    if p.get("symbol", "") == sym_b
                                )
                                bybit_net_lot = sum(
                                    (1.0 if int(p.get("type", 0)) == 0 else -1.0) * abs(float(p.get("volume", 0)))
                                    for p in _pos2
                                    if p.get("symbol", "") == sym_b
                                )
                                _mt5_ok = True
                except Exception as _bridge_err2:
                    logger.warning(f"[SINGLE_LEG_CHECK] Phase2 bridge query failed: {_bridge_err2}")
                post_bybit_qty_xau = bybit_qty_lot * conv_factor
                post_bybit_net_xau = bybit_net_lot * conv_factor

                position_gap = abs(post_binance_qty - post_bybit_qty_xau)

                logger.info(
                    f"[SINGLE_LEG_CHECK] Phase2: live positions — "
                    f"Binance={post_binance_qty:.4f} XAU, "
                    f"Bybit={post_bybit_qty_xau:.4f} XAU, "
                    f"gap={position_gap:.4f} XAU"
                )

                # 容差下限(20260619): 防 MT5 手数量化(1手=conv_factor XAU, 最小0.01手)的正常小偏差
                # 误报; conv_factor*0.02 ≈ 2个最小手数步长。真单腿(如 6.36 XAU 裸敞口)远超此容差,
                # 不会被掩盖; 总量对账用绝对缺口而非单笔比例, 才能抓住"累计偏离"。
                # 噪音过滤(P0): 在原相对容差之外, 再叠加一个【绝对最小告警缺口】min_gap_xau(默认10 XAU
                # =0.1手, 可在 config/single_leg_filter.json 热调)。缺口低于它=亚手/碎单噪音, 不告警;
                # 真单腿裸敞口 >= min_gap_xau 仍正常告警。两条件取“更宽松”地板, 杜绝碎单刷屏。
                _sl_enabled = _sl_flt.get("enabled", True)
                _min_gap = _sl_flt.get("min_gap_xau", 10.0) if _sl_enabled else 0.0
                _gap_tol = max(binance_filled * 0.5, conv_factor * 0.02, _min_gap)
                # ── 黄金专属告警地板(2026-07-06) ────────────────────────────
                # 需求: XAU品种 净敞口>gold_abs_gap_xau(0.6 XAU) 或 >两腿较大净仓×
                # gold_pct_gap(5%) 即弹框+飞书(其它品种以后另调, 暂不启用)。
                # 判定用【有向净敞口】=币安带号持仓+MT5带号持仓(多=+/空=−), 而非两腿
                # abs之差: abs口径会把MT5同品种多空双计数成20~41 XAU虚假站立偏移
                # (6/25完全成交误弹框的根子), 净口径下完全对冲≈0不误报、真裸敞口
                # (如币安多29.8 vs MT5空31 → 净−1.2)如实暴露。触发时绕过通用min_gap
                # 静默区与delta站立偏移抑制; 重复告警由发送层冷却/去重兜底。
                # 护栏: 仅桥查询成功(_mt5_ok)且1:1对冲(hedge_multiplier==1)时判定,
                # 防桥瞬断把对冲腿当0误报、防放大对冲模式天然净敞口误报。
                _gold_trigger = None
                # 20260708: 金族判定改看A或B品种(PAXG的A腿PAXGUSDT不含XAU但对冲XAUUSD)
                if (_sl_enabled and ('XAU' in (sym_a or '').upper() or 'XAU' in (sym_b or '').upper()) and _mt5_ok
                        and float(getattr(self, 'hedge_multiplier', 1.0) or 1.0) == 1.0):
                    _gold_abs = float(_sl_flt.get("gold_abs_gap_xau", 0.6))
                    _gold_pct = float(_sl_flt.get("gold_pct_gap", 0.05))
                    # 20260708 共享B品种组口径: 并入同用户共享同一MT5品种的姊妹对A腿净,
                    # 防把姊妹对(ICXAU↔PAXG共用XAUUSD)的对冲腿当成本对裸敞口(交叉误报)。
                    _sib_net = 0.0
                    try:
                        _sib_net = await asyncio.wait_for(
                            _sibling_binance_net(self.user_id, self.pair_code, sym_b), timeout=10.0)
                    except Exception:
                        _sib_net = 0.0
                    _net_exposure = post_binance_net + _sib_net + post_bybit_net_xau
                    _net_base = max(abs(post_binance_net + _sib_net), abs(post_bybit_net_xau))
                    if _gold_abs > 0 and abs(_net_exposure) > _gold_abs:
                        _gold_trigger = 'GOLD_ABS'
                    elif _gold_pct > 0 and _net_base > 0 and abs(_net_exposure) > _net_base * _gold_pct:
                        _gold_trigger = 'GOLD_PCT'
                    if _gold_trigger:
                        logger.warning(
                            f"[SINGLE_LEG_CHECK] 黄金地板触发({_gold_trigger}): "
                            f"净敞口={_net_exposure:+.4f} XAU (币安净={post_binance_net:+.4f}, "
                            f"MT5净={post_bybit_net_xau:+.4f}; abs阈={_gold_abs}, pct阈={_gold_pct:.0%})"
                        )
                if _gold_trigger is None and position_gap <= _gap_tol:
                    logger.info(
                        f"[SINGLE_LEG_CHECK] Phase2 RESOLVED: gap={position_gap:.4f} "
                        f"<= threshold={_gap_tol:.4f} (min_gap_xau={_min_gap:.2f}), no alert"
                    )
                    return

                # ── P1 根治(2026-07-04) signed delta-gap ──────────────────────────
                # 根因: 上面的 position_gap=abs(Σabs币安 − Σabs_MT5) 是【全账户绝对持仓差】。
                # MT5 可同时持多腿+空腿(abs双重计数)、加残留/并发开平共用symbol → 存在【恒定的
                # 站立偏移】(实测20~41 XAU)。于是每一笔成交(哪怕本笔exec_ratio=100%完全对冲)都撞上
                # 同一偏移 → 反复 CONFIRMED 误报(用户"完全成交也弹框"的根源)。
                # 修法: 判据从"绝对缺口水平"改为"【有向不平衡的变化量】":
                #   signed_imb = post_binance − post_bybit_xau  (有向, 不取abs)
                #   仅当 |signed_imb − 上次基线| >= delta_gap_xau (=新生裸敞口跳变) 才告警;
                #   站立偏移恒定 → 每笔 delta≈0 → 不报。用【有向】而非abs, 防"新裸腿恰好抵消旧偏移"漏报。
                # 绝对硬兜底 hard_gap_xau: 缺口 >= 它则【无条件】告警(防"缓慢漂移累积成大裸敞口"被delta漏报)。
                # 首次(无基线, 如重启后)只认硬兜底、不凭delta报(防重启首帧把站立偏移误当新敞口)。
                # enabled:false → 跳过本段, 回退旧"过gap_tol即告警"行为。纯判定, 零成交延迟。
                _trigger = 'LEGACY'
                if _sl_enabled:
                    signed_imb = post_binance_qty - post_bybit_qty_xau
                    _delta_gap = float(_sl_flt.get("delta_gap_xau", 16.0))
                    _hard_gap = float(_sl_flt.get("hard_gap_xau", 60.0))
                    _base_key = f"single_leg_imb_baseline:{self.user_id}:{self.pair_code}"
                    _last_base = None
                    try:
                        if self._redis:
                            _rv = await self._redis.get(_base_key)
                            if _rv is not None:
                                _last_base = float(_rv)
                    except Exception:
                        _last_base = None
                    _delta = abs(signed_imb - _last_base) if _last_base is not None else None
                    _is_hard = (_hard_gap > 0 and position_gap >= _hard_gap)
                    _is_new_naked = (_delta is not None and _delta_gap > 0 and _delta >= _delta_gap)
                    # 基线每次刷新: 站立偏移/已知敞口成为"新常态", 下次delta归零不再刷屏;
                    # 真新裸腿只在【形成的那一刻】跳变告警一次(不变的裸敞口靠hard_gap兜底持续报)。
                    try:
                        if self._redis:
                            await self._redis.set(_base_key, f"{signed_imb:.4f}", ex=86400)
                    except Exception:
                        pass
                    if _gold_trigger is None and not (_is_hard or _is_new_naked):
                        logger.info(
                            f"[SINGLE_LEG_CHECK] Phase2 SUPPRESSED(站立偏移非新敞口): "
                            f"gap={position_gap:.4f} signed_imb={signed_imb:.4f} "
                            f"last_base={_last_base} delta={_delta} "
                            f"(delta_gap={_delta_gap} hard_gap={_hard_gap}) — 不告警"
                        )
                        return
                    _trigger = _gold_trigger or ('HARD' if _is_hard else 'DELTA')

                logger.error(
                    f"[SINGLE_LEG_CHECK] Phase2 CONFIRMED SINGLE-LEG: "
                    f"Binance={post_binance_qty:.4f}, Bybit={post_bybit_qty_xau:.4f}, "
                    f"gap={position_gap:.4f} XAU, trigger={_trigger}, "
                    f"exec_ratio={ratio:.2%}"
                )
                exec_result['single_leg_details'] = {
                    'binance_filled': binance_filled,
                    'bybit_filled': bybit_filled_xau,
                    'bybit_filled_xau': bybit_filled_xau,
                    'unfilled_qty': binance_filled - bybit_filled_xau,
                    'fill_ratio': ratio,
                    'position_gap': position_gap,
                    'post_binance': post_binance_qty,
                    'post_bybit': post_bybit_qty_xau,
                    'trigger': _trigger,
                    'net_exposure': (post_binance_net + post_bybit_net_xau) if _mt5_ok else None,
                    'verification_method': 'exec_result_phase2'
                }
                await self._send_single_leg_alert(
                    strategy_type=strategy_type,
                    exec_result=exec_result
                )

            except Exception as e:
                logger.error(f"[SINGLE_LEG_CHECK] Phase2 position check error: {e}")

        except Exception as e:
            logger.error(f"[SINGLE_LEG_CHECK] Delayed check failed: {e}")


    async def _send_binance_api_emergency_alert(
        self,
        strategy_type: str,
        exec_result: Dict
    ):
        """
        Send emergency alert when Binance API is down during execution.
        Strategy is stopped immediately. Alert sent via WebSocket and Feishu.
        """
        if not self.user_id:
            return

        strategy_name = "正向套利" if "forward" in strategy_type else "反向套利"
        action = "开仓" if "opening" in strategy_type else "平仓"
        order_id = exec_result.get("binance_order_id", "未知")

        import datetime
        timestamp = datetime.datetime.utcnow().isoformat()

        # WebSocket emergency alert
        try:
            from app.websocket.manager import manager
            alert_message = {
                "type": "binance_api_emergency",
                "data": {
                    "strategy_type": strategy_name,
                    "action": action,
                    "order_id": order_id,
                    "timestamp": timestamp,
                    "level": "critical",
                    "title": "🚨 Binance交易系统异常 — 策略已紧急停止",
                    "message": (
                        f"{strategy_name} {action}：Binance API连续查询失败，"
                        f"订单 {order_id} 状态未知，策略已自动停止。"
                        f"请立即登录Binance交易软件人工核查持仓和挂单！"
                    )
                }
            }
            await manager.send_to_user(alert_message, self.user_id)
            logger.error(f"[EMERGENCY] WebSocket alert sent for Binance API outage: order_id={order_id}")
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed to send WebSocket alert: {e}")

        # Feishu emergency alert
        try:
            from app.services.feishu_service import get_feishu_service
            from app.core.database import get_db
            from app.models.user import User
            from sqlalchemy import select as sa_select
            feishu = get_feishu_service()
            if feishu:
                async for db in get_db():
                    result = await db.execute(sa_select(User).where(User.user_id == self.user_id))
                    user = result.scalar_one_or_none()
                    if user and (user.feishu_open_id or user.email):
                        receiver_id = user.feishu_open_id if user.feishu_open_id else user.email
                        receive_id_type = "open_id" if user.feishu_open_id else "email"
                        content = (
                            f"🚨 Binance交易系统异常\n"
                            f"策略：{strategy_name} {action}\n"
                            f"订单号：{order_id}\n"
                            f"时间：{timestamp}\n"
                            f"原因：Binance API连续{exec_result.get('api_error_count', 3)}次查询失败\n"
                            f"处理：策略已自动停止，请立即人工核查Binance持仓和挂单！"
                        )
                        await feishu.send_text_message(receiver_id, receive_id_type, content)
                    break
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed to send Feishu alert: {e}")

    async def _send_single_leg_alert(
        self,
        strategy_type: str,
        exec_result: Dict
    ):
        """Send single-leg trade alert via WebSocket and Feishu"""
        if not self.user_id:
            return

        # Determine strategy name and action
        if 'reverse' in strategy_type:
            strategy_name = "反向套利"
        else:
            strategy_name = "正向套利"

        if 'opening' in strategy_type:
            action = "开仓"
        else:
            action = "平仓"

        # Prepare alert details
        import datetime
        details = exec_result.get('single_leg_details', {})
        details['timestamp'] = datetime.datetime.utcnow().isoformat()

        # Send WebSocket notification via Redis bridge (Go Hub).
        # Python ws_manager.active_connections is empty — frontend only connects to Go /ws.
        # We wrap this as a risk_alert so the global handler in market.js dispatches it,
        # and so the alert_type "single_leg_alert" is gated by the frontend
        # singleLegAlertEnabled toggle (see notification.js handleRiskAlert).
        # 读取 single_leg_alert 模板的「跑马灯」推送渠道开关(enable_marquee),
        # 写入 WS 事件 data.marquee → 前端 MarketCards 跑马灯按此开关决定是否滚动展示。
        # 模板缺失/查询异常一律 False(fail-safe, 不影响弹窗/飞书原有链路)。
        _marquee_on = False
        try:
            from app.core.database import AsyncSessionLocal as _ASL
            from app.models.notification_config import NotificationTemplate as _NT
            from sqlalchemy import select as _sel
            async with _ASL() as _mdb:
                _row = (await _mdb.execute(
                    _sel(_NT.enable_marquee).where(_NT.template_key == "single_leg_alert")
                )).scalar_one_or_none()
                _marquee_on = bool(_row)
        except Exception as _me:
            logger.debug(f"[SINGLE_LEG] read enable_marquee failed (default off): {_me}")

        try:
            from app.core.redis_client import redis_client as _rc
            import json as _json

            # 多交易对(2026-07-04): 文案+payload 带品种, 前端去重键按 pair 隔离、用户一眼看清哪个品种
            _pair_label = _single_leg_pair_label(self.pair_code)
            msg = f"【{_pair_label}】{strategy_name} {action}: Binance成交 {details.get('binance_filled', 0)}, Bybit成交 {details.get('bybit_filled', 0)}, 未成交 {details.get('unfilled_qty', 0)}"
            if details.get('position_gap') is not None:
                try:
                    msg += (f", 两腿实盘 币安{float(details.get('post_binance', 0)):.2f}"
                            f"/MT5 {float(details.get('post_bybit', 0)):.2f}"
                            f", 缺口{float(details.get('position_gap', 0)):.2f} XAU")
                    if details.get('net_exposure') is not None:
                        msg += f", 净敞口{float(details['net_exposure']):+.2f} XAU"
                except Exception:
                    pass
            evt = {
                "user_id": self.user_id,
                "type": "risk_alert",
                "data": {
                    "alert_type": "single_leg_alert",
                    "level": "critical",
                    "title": f"单腿交易警告 - {_pair_label}",
                    "message": msg,
                    "pair_code": self.pair_code,
                    "pair_label": _pair_label,
                    "timestamp": details.get("timestamp"),
                    "template_key": "single_leg_alert",
                    # 跑马灯推送渠道(由 testadmin 通知模板的 enable_marquee 控制)
                    "marquee": _marquee_on,
                    "popup_config": {
                        "title": "单腿交易警告",
                        "content": msg,
                        "sound_file": "single_leg.mp3",
                        "sound_repeat": 5,
                    },
                    # Pass through raw fields so the frontend deduplication keeps working.
                    "strategy_type": strategy_name,
                    "action": action,
                    "binance_filled": details.get("binance_filled", 0),
                    "bybit_filled": details.get("bybit_filled", 0),
                    "unfilled_qty": details.get("unfilled_qty", 0),
                },
            }
            await _rc.publish("ws:user_event", _json.dumps(evt))
        except Exception as ws_err:
            logger.warning(f"[SINGLE_LEG] Redis WS publish failed: {ws_err}")

        # Send Feishu notification
        try:
            from app.services.risk_alert_service import RiskAlertService
            from app.core.database import get_db

            # Get database session
            async for db in get_db():
                risk_alert_service = RiskAlertService(db)

                # Determine direction based on strategy type
                direction = "多头" if "forward" in strategy_type.lower() else "空头"
                exchange = "Binance"  # Single-leg usually happens on Binance side

                await risk_alert_service.check_single_leg(
                    user_id=self.user_id,
                    exchange=exchange,
                    quantity=details.get("unfilled_qty", 0),
                    duration=0,  # Immediate alert
                    direction=direction,
                    binance_filled=details.get("binance_filled", 0),
                    bybit_filled=details.get("bybit_filled", 0),
                    pair_code=self.pair_code,  # 多交易对 per-pair 冷却隔离(2026-07-04)
                )
                break  # Only need first session
        except Exception as e:
            logger.error(f"Failed to send Feishu single-leg alert: {e}")

    def stop(self):
        """Request graceful stop.

        Sets stop_requested=True so the loop exits only at a safe point:
        - After Binance+Bybit both fill (双边成交完成)
        - After Binance order is cancelled (撤单，无单腿风险)
        Never interrupts mid-execution to prevent single-leg exposure.
        """
        logger.info(f"Stop requested for strategy {self.strategy_id} — will exit at next safe point")
        self.stop_requested = True
        try:
            self._stop_event.set()
        except Exception:
            pass
        try:
            asyncio.get_event_loop().create_task(self._cancel_inflight_on_stop())
        except Exception as _e:
            logger.debug(f"schedule cancel-on-stop failed: {_e}")

    async def _sleep_or_stop(self, secs: float):
        """可中断 sleep：收到停止信号(_stop_event)立即返回，否则睡满 secs。"""
        if secs and secs > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=secs)
            except asyncio.TimeoutError:
                pass

    async def _cancel_inflight_on_stop(self):
        """停止时主动撤掉 A 侧在途挂单，使其尽快进入已撤单安全点。"""
        try:
            acct = getattr(self, '_binance_account', None)
            if not acct:
                return
            sym_a, _, _ = _get_pair_config(self.pair_code)
            from app.core.proxy_utils import build_proxy_url
            pid = getattr(acct, 'platform_id', 1)
            if pid == 1:
                from app.services.binance_client import BinanceFuturesClient
                _cli = BinanceFuturesClient(acct.api_key, acct.api_secret,
                                            proxy_url=build_proxy_url(getattr(acct, 'proxy_config', None)))
                try:
                    await _cli.cancel_all_orders(sym_a)
                    logger.info(f"[GRACEFUL STOP] active-cancel {sym_a} done")
                finally:
                    await _cli.close()
            elif pid == 2:
                from app.services.bybit_client import BybitV5Client
                _cli = BybitV5Client(api_key=acct.api_key, api_secret=acct.api_secret,
                                     proxy_url=build_proxy_url(getattr(acct, 'proxy_config', None)))
                try:
                    await _cli.cancel_all_orders(category='linear', symbol=sym_a)
                    logger.info(f"[GRACEFUL STOP] active-cancel(Bybit) {sym_a} done")
                finally:
                    await _cli.close()
        except Exception as _e:
            logger.warning(f"[GRACEFUL STOP] active-cancel failed: {_e}")

    async def execute_forward_opening_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        opening_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute forward opening with continuous execution.

        Args:
            binance_account: Binance account for LONG positions
            bybit_account: Bybit account for SHORT positions
            ladders: List of ladder configurations
            opening_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting forward opening continuous execution for strategy {self.strategy_id}")
        logger.info(f"Binance: {binance_account.account_name}, Bybit: {bybit_account.account_name}, Ladders: {len(ladders)}")

        self.is_running = True
        self.stop_requested = False
        self.stop_reason = None
        try:
            self._stop_event.clear()
        except Exception:
            pass
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        _recon_register(self)  # 黄金净敞口周期对账注册(独立协程, 不碰下单/对冲路径)
        await self._init_redis()
        self._active_key = self._make_active_key('forward_opening')

        try:
            await self._redis.set(self._active_key, "1", ex=3600)
            return await self._execute_continuous_v2(
                strategy_type='forward_opening',
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                order_qty_limit=opening_m_coin,
            )
        except asyncio.CancelledError:
            logger.warning(f"Task cancelled for strategy {self.strategy_id} (forward_opening)")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('forward_opening')
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception(f"Error in forward opening continuous: {e}")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('forward_opening')
                except Exception:
                    pass
            return {'success': False, 'error': str(e)}
        finally:
            if getattr(self, '_active_key', None):
                try:
                    import redis.asyncio as _aioredis
                    _r = _aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                    await _r.delete(self._active_key)
                    await _r.aclose()
                except Exception:
                    pass
            self.is_running = False

    async def execute_reverse_closing_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        closing_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute reverse closing with continuous execution.

        Args:
            binance_account: Binance account
            bybit_account: Bybit account
            ladders: List of ladder configurations
            closing_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting reverse closing continuous execution for strategy {self.strategy_id}")

        self.is_running = True
        self.stop_requested = False
        self.stop_reason = None
        try:
            self._stop_event.clear()
        except Exception:
            pass
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        _recon_register(self)  # 黄金净敞口周期对账注册(独立协程, 不碰下单/对冲路径)

        await self._init_redis()
        self._active_key = self._make_active_key('reverse_closing')

        try:
            await self._redis.set(self._active_key, "1", ex=3600)
            result = await self._execute_continuous_v2(
                strategy_type='reverse_closing',
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                order_qty_limit=closing_m_coin,
            )
            return result
        except asyncio.CancelledError:
            logger.warning(f"Task cancelled for strategy {self.strategy_id} (reverse_closing)")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('reverse_closing')
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception(f"Error in reverse closing continuous: {e}")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('reverse_closing')
                except Exception:
                    pass
            return {'success': False, 'error': str(e)}
        finally:
            if getattr(self, '_active_key', None):
                try:
                    import redis.asyncio as _aioredis
                    _r = _aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                    await _r.delete(self._active_key)
                    await _r.aclose()
                except Exception:
                    pass
            self.is_running = False

    async def execute_forward_closing_continuous(
        self,
        binance_account: Account,
        bybit_account: Account,
        ladders: List[LadderConfig],
        closing_m_coin: float,
        user_id: str
    ) -> Dict:
        """
        Execute forward closing with continuous execution.

        Args:
            binance_account: Binance account
            bybit_account: Bybit account
            ladders: List of ladder configurations
            closing_m_coin: Max quantity per single order
            user_id: User ID for WebSocket notifications

        Returns:
            Execution result dictionary
        """
        logger.info(f"Starting forward closing continuous execution for strategy {self.strategy_id}")

        self.is_running = True
        self.stop_requested = False
        self.stop_reason = None
        try:
            self._stop_event.clear()
        except Exception:
            pass
        self.user_id = user_id
        self._bybit_account = bybit_account
        self._binance_account = binance_account
        _recon_register(self)  # 黄金净敞口周期对账注册(独立协程, 不碰下单/对冲路径)

        await self._init_redis()
        self._active_key = self._make_active_key('forward_closing')

        try:
            await self._redis.set(self._active_key, "1", ex=3600)
            result = await self._execute_continuous_v2(
                strategy_type='forward_closing',
                binance_account=binance_account,
                bybit_account=bybit_account,
                ladders=ladders,
                order_qty_limit=closing_m_coin,
            )
            return result
        except asyncio.CancelledError:
            logger.warning(f"Task cancelled for strategy {self.strategy_id} (forward_closing)")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('forward_closing')
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception(f"Error in forward closing continuous: {e}")
            if self.stop_requested and self.user_id:
                try:
                    await self._push_stop_confirmed('forward_closing')
                except Exception:
                    pass
            return {'success': False, 'error': str(e)}
        finally:
            if getattr(self, '_active_key', None):
                try:
                    import redis.asyncio as _aioredis
                    _r = _aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                    await _r.delete(self._active_key)
                    await _r.aclose()
                except Exception:
                    pass
            self.is_running = False

