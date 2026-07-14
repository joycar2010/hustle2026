"""投资者只读投影 API(V4.0 §12.4)—— 严格身份隔离,只读 investor_projection。
铁律:
- investor_id 一律由登录 JWT 的 uid 反查 share_account,**绝不信任前端传入的 investor_id**;
- 只读脱敏投影,不碰任何交易/控制表(positions/routes/engine_config 全不可达);
- 无绑定 share_account 的登录用户 = 零数据(fail-closed),不泄漏池信息;
- 组合收益率(pool_return)全员相同,权益金额按各自 Units 不同。
NAV 权威 = pool_nav_snapshot(FINALIZED);投影可重算,不是权威。
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import datasources as ds

log = logging.getLogger("mix.investor")
router = APIRouter(tags=["investor"])


async def require_investor(authorization: str | None = Header(default=None)) -> dict:
    """登录 JWT → uid → share_account.investor_id。无绑定=403(fail-closed,不泄漏池)。"""
    from ..deps import _jwt_decode
    if not (authorization and authorization.lower().startswith("bearer ")):
        raise HTTPException(401, "需要投资者登录(Authorization: Bearer)")
    who = _jwt_decode(authorization[7:].strip())
    if not who or who.get("uid") is None:
        raise HTTPException(401, "无效登录令牌")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    # 只按 token 的 uid 反查——前端即便传 investor_id 也一律忽略
    row = await pool.fetchrow(
        "SELECT investor_id, display_name, status FROM share_account "
        "WHERE login_user_id=$1 AND status<>'closed'", int(who["uid"]))
    if not row:
        raise HTTPException(403, "该账号未绑定投资份额(如属误配请联系管理员)")
    return {"investor_id": int(row["investor_id"]), "display_name": row["display_name"],
            "uid": int(who["uid"]), "username": who.get("operator", "")}


async def _audit(pool, inv, action, detail="", ip=""):
    try:
        await pool.execute(
            "INSERT INTO investor_audit_event(investor_id, action, detail, ip) VALUES($1,$2,$3,$4)",
            inv["investor_id"], action, str(detail)[:200], ip[:64])
    except Exception as e:  # noqa: BLE001
        log.warning("investor audit: %s", e)


@router.get("/investor/me")
async def investor_me(inv=Depends(require_investor), x_forwarded_for: str | None = Header(default=None)):
    """本人最新权益:Units × 单位净值 + 组合收益率 + as-of。"""
    pool = await ds.pg_main()
    await _audit(pool, inv, "view", "me", (x_forwarded_for or "").split(",")[0])
    row = await pool.fetchrow(
        "SELECT p.units, p.nav_per_unit, p.investor_equity, p.pool_return_pct, p.as_of, n.nav_status "
        "FROM investor_projection p JOIN pool_nav_snapshot n ON n.id=p.nav_id "
        "WHERE p.investor_id=$1 ORDER BY p.as_of DESC LIMIT 1", inv["investor_id"])
    if not row:
        # 份额未发行/无投影=如实空态(不是错误),门户显示"暂无份额"
        return {"investor": inv["display_name"], "units": 0, "nav_per_unit": None,
                "investor_equity": 0, "pool_return_pct": None, "as_of": None, "nav_status": None,
                "note": "尚未发行份额或暂无净值快照"}
    return {"investor": inv["display_name"],
            "units": float(row["units"]), "nav_per_unit": float(row["nav_per_unit"]),
            "investor_equity": float(row["investor_equity"]),
            "pool_return_pct": float(row["pool_return_pct"]) if row["pool_return_pct"] is not None else None,
            "as_of": row["as_of"].isoformat() if row["as_of"] else None,
            "nav_status": row["nav_status"]}


@router.get("/investor/performance")
async def investor_performance(inv=Depends(require_investor), limit: int = 180):
    """本人权益/组合收益率时间序列(ESTIMATED/FINALIZED 标识)。"""
    pool = await ds.pg_main()
    limit = max(1, min(limit, 400))
    rows = await pool.fetch(
        "SELECT p.as_of, p.investor_equity, p.nav_per_unit, p.pool_return_pct, n.nav_status "
        "FROM investor_projection p JOIN pool_nav_snapshot n ON n.id=p.nav_id "
        "WHERE p.investor_id=$1 ORDER BY p.as_of DESC LIMIT $2", inv["investor_id"], limit)
    return [{"as_of": r["as_of"].isoformat() if r["as_of"] else None,
             "equity": float(r["investor_equity"]),
             "nav_per_unit": float(r["nav_per_unit"]),
             "pool_return_pct": float(r["pool_return_pct"]) if r["pool_return_pct"] is not None else None,
             "nav_status": r["nav_status"]} for r in reversed(rows)]


@router.get("/investor/capital-history")
async def investor_capital_history(inv=Depends(require_investor)):
    """本人已确认份额事件(发行/赎回/调整)——脱敏,只见本人。"""
    pool = await ds.pg_main()
    rows = await pool.fetch(
        "SELECT event_type, units, external_flow_id, approved_at, note "
        "FROM share_event WHERE investor_id=$1 ORDER BY approved_at DESC LIMIT 200", inv["investor_id"])
    return [{"type": r["event_type"], "units": float(r["units"]),
             "flow": r["external_flow_id"], "at": r["approved_at"].isoformat() if r["approved_at"] else None,
             "note": r["note"]} for r in rows]


@router.get("/investor/pool")
async def investor_pool(inv=Depends(require_investor)):
    """组合层信息(全员相同):最新池净值状态 + 收益曲线口径说明。不含任何账户/仓位明细。"""
    pool = await ds.pg_main()
    row = await pool.fetchrow(
        "SELECT nav_status, nav_per_unit, as_of FROM pool_nav_snapshot ORDER BY as_of DESC LIMIT 1")
    return {"nav_status": row["nav_status"] if row else None,
            "nav_per_unit": float(row["nav_per_unit"]) if row else None,
            "as_of": row["as_of"].isoformat() if row and row["as_of"] else None,
            "note": "组合收益率全员一致,权益金额按各自份额不同;日度 FINALIZED 为准,盘中 ESTIMATED 可修订"}


@router.get("/investor/platform-risk")
async def investor_platform_risk(inv=Depends(require_investor)):
    """客户端"平台访问风险"黄卡(V5 §16.1):只给 NAV 影响与处理状态,
    不暴露具体交易所账号/内部阈值/仓位明细。"""
    pol = await ds.get_json("dcm:risk:policy") or {}
    nav = pol.get("nav") or {}
    restricted = [v for v, d in (pol.get("venues") or {}).items()
                  if d.get("mode") in ("NO_NEW_RISK", "REDUCE_ONLY", "EXIT_ONLY", "FROZEN")]
    trapped = float(nav.get("trapped_usdt") or 0)
    return {
        "has_access_risk": bool(restricted) or trapped > 0,
        "affected_platforms": len(restricted),
        "nav_impact_usdt": round(trapped, 2),
        "status_text": ("部分交易平台访问受限,系统已自动禁止新增风险并按风险政策对受限资产折价;"
                        "处理进展将在本页更新" if restricted or trapped > 0
                        else "全部交易平台访问正常"),
        "handling": "自动风控:禁止新增→受限资产折价→必要时外部对冲;人工事件处置流程在岗" if restricted else "",
    }
