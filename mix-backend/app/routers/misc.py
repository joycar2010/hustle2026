"""监控/黑名单/币管理/报表/告警/通知 —— 读=真数据；写=P0 未接线 501。"""
from fastapi import APIRouter, Query, HTTPException, Depends
from ..schemas import NotifySettings
from ..enums import enums_payload
from ..deps import require_operator, require_viewer, not_wired
from .. import adapters
from .. import proxy
from .. import datasources as ds

router = APIRouter(tags=["misc"])


# ---- 元数据（开放：无敏感数据，前端启动依赖） ----
@router.get("/meta/enums")
async def meta_enums():
    return enums_payload()


# ---- 监控 ----
@router.get("/monitor/heartbeats")
async def heartbeats(_who=Depends(require_viewer)):
    """dcm:hb:* 真相源，阈值对齐 risk-ledger EXPECTED_HB。"""
    return await adapters.heartbeats()


@router.get("/monitor/freshness")
async def freshness(_who=Depends(require_viewer)):
    return await adapters.freshness()


@router.get("/monitor/balance-watermarks")
async def watermarks(_who=Depends(require_viewer)):
    """水位=fund-scheduler 提案口径（equity vs target），提案制只建议不动手。"""
    return await adapters.watermarks()


@router.post("/monitor/transfer-suggestions/{account}/create-order", status_code=202)
async def create_transfer_order(account: str, op=Depends(require_operator)):
    not_wired("划转单创建")


@router.get("/monitor/spreads")
async def spreads(_who=Depends(require_viewer)):
    """跨所费差榜（五所+HL funding 实时差）；开/平点差列待 depth 采样接入（P1）。"""
    return await adapters.spreads_board()


@router.get("/monitor/borrowables")
async def borrowables(_who=Depends(require_viewer)):
    """borrow-monitor 真源 dcm:borrow:avail。"""
    return await adapters.borrowables()


@router.get("/monitor/overview")
async def monitor_overview(_who=Depends(require_viewer)):
    """主控台聚合：全局管道(8段,分策略堆叠)+系统健康+风控护栏+顾问+支撑域B。全真信号。"""
    return await adapters.monitor_overview()


@router.get("/monitor/events")
async def monitor_events(_who=Depends(require_viewer)):
    """公告/上市事件（event-calendar）。"""
    return await adapters.monitor_events()


@router.get("/monitor/advisors-chat")
async def advisors_chat(_who=Depends(require_viewer)):
    """AI 决策动态化：分域顾问的最新'发言'（对话气泡形式）。"""
    return await adapters.advisors_chat()


# ---- 黑名单（读=panel 透传；写=coin 命令队列代理，coin 逻辑权威） ----
@router.get("/blacklist")
async def blacklist(_who=Depends(require_viewer)):
    return await adapters.blacklist_rows()


def _norm_symbol(s: str) -> str:
    sym = str(s or "").upper().strip()
    if not sym:
        raise HTTPException(400, "symbol required")
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym


@router.post("/blacklist", status_code=201)
async def blacklist_add(body: dict, op=Depends(require_operator)):
    sym = _norm_symbol(body.get("symbol"))
    reason = str(body.get("reason") or f"mix:{op['operator']} 手动加入")
    res = await proxy.coin_cmd("blacklist_add", {"symbol": sym, "reason": reason}, op["operator"])
    await proxy.audit(op["operator"], op["role"], "blacklist.add", sym,
                      {"reason": reason}, "ok" if res.get("ok") else str(res)[:120])
    if not res.get("ok"):
        raise HTTPException(502, f"coin 侧执行失败：{res.get('err') or res.get('body')}")
    return {"ok": True, "coin": res.get("body")}


@router.post("/blacklist/remove")
async def blacklist_remove(body: dict, op=Depends(require_operator)):
    sym = _norm_symbol(body.get("symbol") or body.get("rawSymbol"))
    res = await proxy.coin_cmd("blacklist_remove", {"symbol": sym}, op["operator"])
    await proxy.audit(op["operator"], op["role"], "blacklist.remove", sym,
                      {}, "ok" if res.get("ok") else str(res)[:120])
    if not res.get("ok"):
        raise HTTPException(502, f"coin 侧执行失败：{res.get('err') or res.get('body')}")
    return {"ok": True, "coin": res.get("body")}


# ---- 币管理 ----
@router.get("/coins")
async def coins(_who=Depends(require_viewer)):
    """P0 口径：路由权威表(route_assignments) ∪ 在管仓位 + binance 资金费。"""
    return await adapters.coins_board()


@router.post("/coins/{symbol}/actions", status_code=202)
async def coin_action(symbol: str, body: dict, op=Depends(require_operator)):
    not_wired(f"币状态流转 {symbol}[{body.get('action')}]")


# ---- 报表 ----
@router.get("/report/pnl")
async def report_pnl(range: str = Query(..., description="30d|90d|180d|all"), _who=Depends(require_viewer)):
    """income_records 三表真账（dcm 五所+HL；coin 账本待并入）。"""
    if range not in ("30d", "90d", "180d", "all"):
        raise HTTPException(400, "range must be 30d|90d|180d|all")
    return await adapters.report_pnl(range)


@router.get("/report/attribution")
async def report_attribution(_who=Depends(require_viewer)):
    """归因=币种集合映射（S1/S2 可分；S3 coin 账本待接入）。
    根治方案是引擎逐回路写 strategy_code（P0 评估结论），届时替换本实现。"""
    return await adapters.attribution()


# ---- 告警 / 通知 ----
@router.get("/alerts")
async def alerts(strategy: str = Query(default=""), _who=Depends(require_viewer)):
    """alerts_log 真表（dcm 全服务落库告警）；?strategy=S3 按策略过滤。"""
    return await adapters.alerts(strategy=strategy or None)


@router.get("/settings/notifications")
async def notify_get(_who=Depends(require_viewer)):
    """权威=mix_main.notify_settings；生效链路=Redis dcm:notify:config(dcm_common 60s 缓存热读)。"""
    pool = await ds.pg_main()
    row = await pool.fetchrow("SELECT * FROM notify_settings WHERE id=1") if pool else None
    applied = await ds.get_json("dcm:notify:config")
    import json as _json
    return {
        "channels": _json.loads(row["channels"]) if row else ["feishu", "marquee"],
        "intervalSec": row["interval_sec"] if row else 300,
        "maxPerHour": row["max_per_hour"] if row else 6,
        "cooldownSec": row["cooldown_sec"] if row else 600,
        "tokenBucket": {"rate": float(row["token_rate"]), "burst": row["token_burst"]} if row
        else {"rate": 1, "burst": 3},
        "applied": applied,   # dcm 侧当前生效配置(空=各服务用内置默认;fatal 300s/1 地板恒不受影响)
    }


@router.put("/settings/notifications")
async def notify_put(body: dict, op=Depends(require_operator)):
    """保存并热下发：写 mix_main + SET dcm:notify:config（dcm_common Notifier 60s 内生效）。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    import json as _json
    interval = int(body.get("intervalSec") or 300)
    max_hour = int(body.get("maxPerHour") or 6)
    cooldown = int(body.get("cooldownSec") or 600)
    tb = body.get("tokenBucket") or {}
    await pool.execute(
        "UPDATE notify_settings SET channels=$1, interval_sec=$2, max_per_hour=$3, cooldown_sec=$4, "
        "token_rate=$5, token_burst=$6, updated_by=$7, updated_at=now() WHERE id=1",
        _json.dumps(body.get("channels") or ["feishu", "marquee"]), interval, max_hour, cooldown,
        float(tb.get("rate") or 1), int(tb.get("burst") or 3), op["operator"])
    r = ds.rds()
    cfg = {"interval_sec": interval, "max_count": max_hour, "cooldown_sec": cooldown,
           "rate": float(tb.get("rate") or 1), "burst": int(tb.get("burst") or 3),
           "updated_by": op["operator"], "ts": int(__import__("time").time())}
    if r is not None:
        await r.set("dcm:notify:config", _json.dumps(cfg))
    await proxy.audit(op["operator"], op["role"], "notify.config", "dcm:notify:config", cfg, "applied")
    return {"saved": True, "applied": cfg,
            "note": "dcm_common 60s 缓存热生效（fatal 300s/1 硬地板不受影响）"}


# ---- 数据源健康（运维自检） ----
@router.get("/meta/datasources")
async def meta_datasources(_who=Depends(require_viewer)):
    info = ds.degraded()
    hb = await adapters.heartbeats()
    return {**info, "bus_services_seen": len(hb)}
