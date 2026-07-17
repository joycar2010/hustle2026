"""V6 统一客户门户 API(§9.2)——挂载前缀 /api/v6。

铁律:
- mix 域与 user 域部署同一前端与同一契约;数据范围由服务端 uid→share_account/managed_account
  决定,**绝不依赖域名或前端传参**。
- 只返回投影,不在门户层重算收益(消除 0/N/A 与 -24.69 双口径事故)。
- 所有金额=定点小数字符串;无数据返回 200+[]/明确业务状态,绝不 Not Found、绝不用 0 冒充。
- 内部交易所调拨=treasury,不进客户 capital_flow;只有认购/赎回/分配进流水。
- 客户端无任何下单/提现/划转/份额修改/账本修正接口;「账目确认」只能确认收到,不能改账。
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import datasources as ds
from .investor import require_investor

log = logging.getLogger("mix.portal")
router = APIRouter(tags=["v6-portal"])

_DDL = """CREATE TABLE IF NOT EXISTS client_statement (
    id BIGSERIAL PRIMARY KEY,
    investor_id INT NOT NULL,
    period TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    statement JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    UNIQUE(investor_id, period, version))"""


def _amt(x, dp: int = 2) -> str | None:
    """定点小数字符串(§9.2);None 保持 None(N/A),绝不用 '0.00' 冒充。"""
    if x is None:
        return None
    return f"{float(x):.{dp}f}"


async def _pool():
    p = await ds.pg_main()
    if p is None:
        raise HTTPException(503, "服务暂不可用,请稍后再试")
    await p.execute(_DDL)
    return p


@router.get("/portal/me")
async def portal_me(inv=Depends(require_investor)):
    """身份+账户类型。CORE_POOL=份额投资人;SMA=专属资产账户(预留,当前无 SMA 客户)。"""
    pool = await _pool()
    row = await pool.fetchrow(
        "SELECT p.units, p.nav_per_unit, p.investor_equity, p.as_of, n.nav_status "
        "FROM investor_projection p JOIN pool_nav_snapshot n ON n.id=p.nav_id "
        "WHERE p.investor_id=$1 ORDER BY p.as_of DESC LIMIT 1", inv["investor_id"])
    return {
        "display_name": inv["display_name"],
        "account_type": "CORE_POOL",   # SMA 客户上线后由 managed_account 判定,域名不决定权限
        "book": "CORE_POOL",
        "units": _amt(row["units"], 4) if row else "0.0000",
        "nav_per_unit": _amt(row["nav_per_unit"], 4) if row else None,
        "equity_usdt": _amt(row["investor_equity"]) if row else None,
        "as_of": row["as_of"].isoformat() if row and row["as_of"] else None,
        "data_status": (row["nav_status"] if row else "NO_SHARES"),
        "note": None if row else "尚未发行份额;发行后本页自动生效",
    }


@router.get("/portal/overview")
async def portal_overview(inv=Depends(require_investor)):
    """总览四卡+30日趋势+脱敏收益来源(设计帧 jGkCF)。缺数据一律 null(前端显示 N/A)。"""
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT p.as_of, p.investor_equity, p.nav_per_unit, p.units, p.pool_return_pct, n.nav_status "
        "FROM investor_projection p JOIN pool_nav_snapshot n ON n.id=p.nav_id "
        "WHERE p.investor_id=$1 ORDER BY p.as_of DESC LIMIT 62", inv["investor_id"])
    series = [{"as_of": r["as_of"].isoformat() if r["as_of"] else None,
               "equity": _amt(r["investor_equity"]),
               "nav_status": r["nav_status"]} for r in reversed(rows)][-31:]
    latest = rows[0] if rows else None
    # 累计收益=最新权益-净入金(share_event 外部流);缺任一如实 null
    cum, cum_pct = None, None
    try:
        flow = await pool.fetchrow(
            "SELECT coalesce(sum(e.units * coalesce(n.nav_per_unit,1)),0) AS net "
            "FROM share_event e LEFT JOIN pool_nav_snapshot n ON n.id=e.effective_nav_id "
            "WHERE e.investor_id=$1", inv["investor_id"])
        if latest and flow and float(flow["net"]) > 0:
            cum = float(latest["investor_equity"]) - float(flow["net"])
            cum_pct = cum / float(flow["net"]) * 100
    except Exception:  # noqa: BLE001
        pass
    today = None
    if len(rows) >= 2:
        today = float(rows[0]["investor_equity"]) - float(rows[1]["investor_equity"])
    # 收益来源脱敏汇总(不显示策略与平台明细)——账本投影类目
    attribution = None
    try:
        cat = await ds.fetch(
            "SELECT CASE WHEN income_type='FUNDING' THEN '资金费' "
            "WHEN income_type IN ('PNL','REALIZED_PNL') THEN '价差' "
            "WHEN income_type IN ('FEE','COMMISSION') THEN '费用' ELSE '其他' END AS c, "
            "round(sum(income)::numeric,2) AS v FROM income_records "
            "WHERE income_type != 'TRANSFER' GROUP BY 1")
        if cat:
            attribution = {r["c"]: _amt(r["v"]) for r in cat}
    except Exception:  # noqa: BLE001
        pass
    return {
        "equity_usdt": _amt(latest["investor_equity"]) if latest else None,
        "cumulative_pnl_usdt": _amt(cum),
        "cumulative_pnl_pct": _amt(cum_pct),
        "today_pnl_usdt": _amt(today),
        "nav_per_unit": _amt(latest["nav_per_unit"], 4) if latest else None,
        "units": _amt(latest["units"], 4) if latest else "0.0000",
        "as_of": latest["as_of"].isoformat() if latest and latest["as_of"] else None,
        "data_status": latest["nav_status"] if latest else "NO_SHARES",
        "trend": series,
        "attribution": attribution,
        "disclaimer": "部分数据正在核对时,以最近正式结算为准",
    }


@router.get("/portal/performance")
async def portal_performance(inv=Depends(require_investor), limit: int = 180):
    pool = await _pool()
    limit = max(1, min(limit, 400))
    rows = await pool.fetch(
        "SELECT p.as_of, p.investor_equity, p.nav_per_unit, p.pool_return_pct, n.nav_status "
        "FROM investor_projection p JOIN pool_nav_snapshot n ON n.id=p.nav_id "
        "WHERE p.investor_id=$1 ORDER BY p.as_of DESC LIMIT $2", inv["investor_id"], limit)
    return [{"as_of": r["as_of"].isoformat() if r["as_of"] else None,
             "equity_usdt": _amt(r["investor_equity"]),
             "nav_per_unit": _amt(r["nav_per_unit"], 4),
             "pool_return_pct": _amt(r["pool_return_pct"], 4),
             "data_status": r["nav_status"]} for r in reversed(rows)]


@router.get("/portal/cashflows")
async def portal_cashflows(inv=Depends(require_investor)):
    """客户资金流水=认购/赎回/分配(share_event 外部流)。
    内部交易所调拨=treasury,天然不在此表——结构性排除,非过滤。空=200+[]。"""
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT e.event_type, e.units, (e.units * coalesce(n.nav_per_unit,1)) AS amount_usdt, "
        "e.external_flow_id, e.approved_at, e.note, e.reverses_id "
        "FROM share_event e LEFT JOIN pool_nav_snapshot n ON n.id=e.effective_nav_id "
        "WHERE e.investor_id=$1 ORDER BY e.approved_at DESC LIMIT 200",
        inv["investor_id"])
    return [{"type": {"ISSUE": "入金/认购", "REDEEM": "赎回", "TRANSFER": "转让",
                      "ADJUST": "调整"}.get(r["event_type"], r["event_type"]),
             "units": _amt(r["units"], 4),
             "amount_usdt": _amt(r["amount_usdt"]),
             "flow_id": r["external_flow_id"],
             "at": r["approved_at"].isoformat() if r["approved_at"] else None,
             "status": ("冲正" if r["reverses_id"] else "已确认"),
             "note": r["note"]} for r in rows]


@router.get("/portal/statements")
async def portal_statements(inv=Depends(require_investor)):
    """正式对账单(已发布不可覆盖只加版本)。空=200+[]。"""
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT id, period, version, statement, published_at, confirmed_at "
        "FROM client_statement WHERE investor_id=$1 ORDER BY period DESC, version DESC LIMIT 60",
        inv["investor_id"])
    return [{"id": r["id"], "period": r["period"], "version": r["version"],
             "statement": (json.loads(r["statement"]) if isinstance(r["statement"], str) else r["statement"]),
             "published_at": r["published_at"].isoformat(),
             "confirmed": bool(r["confirmed_at"]),
             "confirmed_at": r["confirmed_at"].isoformat() if r["confirmed_at"] else None} for r in rows]


@router.post("/portal/statements/{sid}/confirm")
async def portal_statement_confirm(sid: int, inv=Depends(require_investor)):
    """账目确认=只读核对:客户只能确认收到,不能录入金额或修改账本(§9.3)。"""
    pool = await _pool()
    n = await pool.execute(
        "UPDATE client_statement SET confirmed_at=now() WHERE id=$1 AND investor_id=$2 AND confirmed_at IS NULL",
        sid, inv["investor_id"])
    if not n.endswith("1"):
        row = await pool.fetchrow("SELECT confirmed_at FROM client_statement WHERE id=$1 AND investor_id=$2",
                                  sid, inv["investor_id"])
        if row is None:
            raise HTTPException(403, "对账单不存在或不属于当前账户")
        return {"confirmed": True, "note": "此前已确认"}
    return {"confirmed": True}


@router.get("/portal/service-status")
async def portal_service_status():
    """公开服务状态(无鉴权,门户登录页/横幅消费):维护公告+脱敏平台风险,不含内部阈值。"""
    state, note = "NORMAL", ""
    try:
        pool = await ds.pg_main()
        if pool is not None:
            row = await pool.fetchrow(
                "SELECT state, note FROM maintenance_request WHERE state != 'CLOSED' ORDER BY id DESC LIMIT 1")
            if row:
                state, note = row["state"], row["note"]
    except Exception:  # noqa: BLE001
        pass
    pol = await ds.get_json("dcm:risk:policy") or {}
    restricted = [v for v, d in (pol.get("venues") or {}).items()
                  if d.get("mode") in ("NO_NEW_RISK", "REDUCE_ONLY", "EXIT_ONLY", "FROZEN")]
    return {
        "service_state": ("MAINTENANCE" if state in ("ANNOUNCED", "DRAINING", "DRAIN_BLOCKED",
                                                      "MAINTENANCE", "RECOVERY_CHECK") else "NORMAL"),
        "maintenance_state": state,
        "notice": note or ("系统正常运行" if not restricted else
                           "部分交易平台访问受限,系统已自动控制风险,数据以最近正式结算为准"),
        "platform_access_risk": bool(restricted),
    }
