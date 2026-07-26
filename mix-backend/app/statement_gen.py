"""§4A 投资人对账单生成器(client_statement) —— 只读投影快照,不重算收益,不动钱/份额/armed 管道。

数据源(权威投影,绝不在此层重算):
  - investor_projection(该投资人最新一条)= units / nav_per_unit / investor_equity / pool_return_pct
  - pool_nav_snapshot(投影关联的 nav_id)= 池上下文 + nav_status(ESTIMATED/FINALIZED 如实带出)
  - share_event(现金流:ISSUE/REDEEM/TRANSFER/ADJUST,冲正 reverses_id 不计入净额)

period 默认 'INCEPTION' 自成立至今滚动单张;每次生成 version=max+1 追加(append-only,不覆盖历史版本)。
投资人经 /portal/statements 只读查看 + confirm 确认;客户端无任何编辑/账本修正入口。
"""
from __future__ import annotations

import json
import datetime as dt


def _iso(x):
    return x.isoformat() if x is not None else None


async def targets_with_units(pool):
    """有份额(累计 units>0)的投资人 id 列表(升序)。"""
    rows = await pool.fetch(
        "SELECT sa.investor_id FROM share_account sa "
        "JOIN (SELECT investor_id, sum(units) u FROM share_event GROUP BY investor_id) t "
        "ON t.investor_id=sa.investor_id WHERE t.u > 1e-9 ORDER BY sa.investor_id")
    return [r["investor_id"] for r in rows]


async def build_statement(pool, inv_id: int, period: str):
    """构造某投资人的对账单 JSONB(不落库)。无投影则返回 None。"""
    proj = await pool.fetchrow(
        "SELECT p.units, p.nav_per_unit, p.investor_equity, p.pool_return_pct, p.as_of, p.nav_id, "
        "sa.display_name FROM investor_projection p "
        "JOIN share_account sa ON sa.investor_id=p.investor_id "
        "WHERE p.investor_id=$1 ORDER BY p.as_of DESC LIMIT 1", inv_id)
    if not proj:
        return None
    nav = await pool.fetchrow(
        "SELECT id,nav_status,pool_nav,total_units,nav_per_unit,net_flow,as_of "
        "FROM pool_nav_snapshot WHERE id=$1", proj["nav_id"])
    evs = await pool.fetch(
        "SELECT id,event_type,units,effective_nav_id,external_flow_id,approved_at,reverses_id,note "
        "FROM share_event WHERE investor_id=$1 ORDER BY id", inv_id)
    contrib = sum(float(e["units"]) for e in evs
                  if e["event_type"] == "ISSUE" and e["reverses_id"] is None)
    redeem = sum(-float(e["units"]) for e in evs
                 if e["event_type"] == "REDEEM" and e["reverses_id"] is None)
    events = [{
        "id": e["id"], "type": e["event_type"], "units": float(e["units"]),
        "nav_id": e["effective_nav_id"], "flow": e["external_flow_id"],
        "at": _iso(e["approved_at"]), "reverses_id": e["reverses_id"], "note": e["note"],
    } for e in evs]
    return {
        "schema": "client_statement.v1",
        "period": period,
        "as_of": _iso(proj["as_of"]),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "basis": "projection-snapshot(只快照不重算;权益取 investor_projection 权威投影)",
        "investor": {"investor_id": inv_id, "display_name": proj["display_name"]},
        "position": {
            "units": float(proj["units"]),
            "nav_per_unit": float(proj["nav_per_unit"]),
            "equity_usdt": float(proj["investor_equity"]),
        },
        "performance": {
            "pool_return_pct": float(proj["pool_return_pct"]) if proj["pool_return_pct"] is not None else None,
        },
        "cashflows": {
            "contributions_units": round(contrib, 10),
            "redemptions_units": round(redeem, 10),
            "net_units": round(contrib - redeem, 10),
            "events": events,
        },
        "nav_context": {
            "nav_id": nav["id"] if nav else None,
            "nav_status": nav["nav_status"] if nav else None,
            "pool_nav_usdt": float(nav["pool_nav"]) if nav else None,
            "total_units": float(nav["total_units"]) if nav else None,
            "as_of": _iso(nav["as_of"]) if nav else None,
        },
    }


async def persist_statement(pool, inv_id: int, period: str):
    """构造并落库(append-only,version=max+1)。返回 {statement_id,version,...} 或 {skipped}。"""
    stmt = await build_statement(pool, inv_id, period)
    if stmt is None:
        return {"investor_id": inv_id, "skipped": "无投影快照"}
    ver = await pool.fetchval(
        "SELECT coalesce(max(version),0)+1 FROM client_statement WHERE investor_id=$1 AND period=$2",
        inv_id, period)
    row = await pool.fetchrow(
        "INSERT INTO client_statement(investor_id,period,version,statement,published_at) "
        "VALUES($1,$2,$3,$4,now()) RETURNING id",
        inv_id, period, ver, json.dumps(stmt, ensure_ascii=False))
    return {"investor_id": inv_id, "statement_id": row["id"], "period": period,
            "version": ver, "equity_usdt": stmt["position"]["equity_usdt"]}
