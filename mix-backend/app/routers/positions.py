"""坑位行 —— 真数据：S2=dualperp_positions / S1=basis_positions / S3=coin 面板 1:1。
干预动作（P2 代理制，绝不直写引擎）：
  S3(CN-*) → dcm:coin:cmd 命令队列（桥白名单 → coin FastAPI 权威：状态机/还币闸在 coin 侧原样生效）
  S2(DP-*) 强制平仓 → gateway /api/admin/route 置 off（dcm 的正规平仓路径：引擎平仓且不再新开）
  未接线动作 → 501 诚实拒绝（绝不假 202）。"""
from fastapi import APIRouter, Query, HTTPException, Depends, Header
from ..schemas import PositionRow, PositionAction
from ..enums import StrategyCode
from ..deps import require_operator, require_viewer, not_wired
from .. import adapters
from .. import proxy

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionRow])
async def list_positions(
    view: str = Query(..., description="flat|grouped，必填"),
    sort: str = Query(..., description="opened_at|pnl，必填"),
    dir: str = Query(..., description="asc|desc，必填"),
    strategy: StrategyCode | None = Query(default=None),
    _who=Depends(require_viewer),
):
    """契约铁律 #2：口径参数必填缺参 400；排序键用后端字段(opened_at/pnl)。"""
    if view not in ("flat", "grouped"):
        raise HTTPException(400, "view must be flat|grouped")
    if sort not in ("opened_at", "pnl") or dir not in ("asc", "desc"):
        raise HTTPException(400, "sort/dir 非法")
    rows = await adapters.position_rows(strategy.value if strategy else None)
    rev = dir == "desc"
    if sort == "pnl":
        rows.sort(key=lambda r: (r.get("pnl") is None, r.get("pnl") or 0), reverse=rev)
    else:
        rows.sort(key=lambda r: r.get("openedAt") or "", reverse=rev)
    return rows


# S3 菜单键 → coin API 动作（桥白名单同名；coin 端校验状态机：
# manual_close 仅 OPEN / manual_repay 仅 PENDING_REPAY / manual_hedge 仅 BORROWED_IDLE）
S3_ACTIONS = {"force_close": "manual_close", "manual_repay": "manual_repay", "add_hedge": "manual_hedge"}


@router.post("/{id}/actions", status_code=202)
async def position_action(id: str, body: PositionAction, op=Depends(require_operator),
                          x_op_token: str | None = Header(default=None)):
    action = body.action

    # ---- S3：coin 命令队列 ----
    if id.startswith("CN-") and action in S3_ACTIONS:
        sym = id[3:]
        pos = await adapters.resolve_coin_position(sym, body.accountId)
        if not pos:
            raise HTTPException(409, f"{sym} 无在管持仓行（候选币无仓可操作）")
        res = await proxy.coin_cmd(S3_ACTIONS[action], {"position_id": int(pos["id"])}, op["operator"])
        await proxy.audit(op["operator"], op["role"], f"position.{action}", f"{sym}#{pos['id']}",
                          {"accountId": body.accountId}, "ok" if res.get("ok") else str(res)[:120])
        if not res.get("ok"):
            # coin 状态机拒绝（400/409）原样透传语义
            detail = res.get("body") or res.get("err")
            raise HTTPException(409 if res.get("status") in (400, 409) else 502, f"coin：{detail}")
        return {"accepted": True, "coin": res.get("body"),
                "note": "coin 权威执行，结果以 WS position:updates 对账"}

    if id.startswith("CN-") and action == "blacklist":
        sym = id[3:]
        res = await proxy.coin_cmd("blacklist_add",
                                   {"symbol": sym, "reason": f"mix:{op['operator']} 坑位行移入"},
                                   op["operator"])
        await proxy.audit(op["operator"], op["role"], "blacklist.add", sym, {},
                          "ok" if res.get("ok") else str(res)[:120])
        if not res.get("ok"):
            raise HTTPException(502, f"coin：{res.get('err') or res.get('body')}")
        return {"accepted": True, "note": "已移入 coin 黑名单（只拦新开仓，存量自然退出）"}

    # ---- S2：route off = dcm 正规平仓路径 ----
    if id.startswith("DP-") and action == "force_close":
        sym = id[3:]
        rt = await adapters.route_of(sym)
        if not rt:
            raise HTTPException(409, f"{sym} 无路由行，无法置 off（请在 dcm 控制台处理）")
        route_body = {"symbol": sym, "engine": rt.get("engine", "dualperp"),
                      "venue_long": rt.get("venue_long", ""), "market_long": rt.get("market_long", ""),
                      "venue_short": rt.get("venue_short", ""), "market_short": rt.get("market_short", ""),
                      "target_notional_usdt": str(rt.get("target_notional_usdt", "0")),
                      "state": "off", "reason": f"mix:{op['operator']} 强制平仓(route off)",
                      "version": rt.get("version")}
        import httpx
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(f"{proxy.GATEWAY_BASE}/api/admin/route", json=route_body,
                                headers={"X-Op-Token": x_op_token})
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:  # noqa: BLE001
                err = {"error": resp.text[:120]}
            raise HTTPException(resp.status_code, f"gateway：{err.get('error') or err}")
        return {"accepted": True,
                "note": "路由已置 off：引擎将按平仓路径退出且不再新开（advisor 不会翻回，退出滞回不适用 off）"}

    # ---- 其余动作未接线 ----
    not_wired(f"positions/{id}/actions[{action}]（该动作尚未进桥白名单/引擎无对应权威 API）")
