"""用户端（mix.hustle2026.xyz）—— 多用户数据隔离版。
隔离规则（默认拒绝）：
  - operator/只读令牌、mix 用户 role∈{owner,admin} → 全量（venues=None）
  - 普通 mix 用户 → 仅 mix_user_scopes 绑定的交易所范围；零绑定 = 零数据（绝不回落全量）
merged/self 口径仍必须显式（历史事故：默认 merged 泄漏）。"""
from fastapi import APIRouter, Depends, Query, HTTPException
from ..deps import enforce_view, require_viewer
from .. import adapters
from .. import datasources as ds

router = APIRouter(prefix="/me", tags=["me"])


async def _scopes_of(who: dict) -> list[str] | None:
    """None=不受限；list=白名单（可为空=默认拒绝）。"""
    if who.get("kind") != "mix_user":
        return None  # operator/只读令牌 = 管理视角
    if who.get("urole") in ("owner", "admin"):
        return None
    pool = await ds.pg_main()
    if pool is None:
        return []  # 用户库不可用时对普通用户 fail-closed
    rows = await pool.fetch("SELECT venue FROM mix_user_scopes WHERE user_id=$1", who.get("uid"))
    return [r["venue"] for r in rows]


@router.get("/earnings/summary")
async def earnings_summary(view: str = Depends(enforce_view), who=Depends(require_viewer)):
    return await adapters.me_summary(view, await _scopes_of(who))


@router.get("/earnings/daily")
async def earnings_daily(who=Depends(require_viewer)):
    scopes = await _scopes_of(who)
    if scopes is None:
        return await adapters.report_pnl("90d")
    return await adapters.report_pnl_scoped("90d", scopes)


@router.get("/earnings/sources")
async def earnings_sources(who=Depends(require_viewer)):
    return await adapters.me_sources(await _scopes_of(who))


@router.get("/subaccounts")
async def subaccounts(view: str = Depends(enforce_view), who=Depends(require_viewer)):
    return await adapters.me_subaccounts(view, await _scopes_of(who))


@router.get("/fund-flows")
async def fund_flows(who=Depends(require_viewer)):
    return await adapters.me_fund_flows(await _scopes_of(who))


@router.get("/ledger")
async def ledger(_who=Depends(require_viewer)):
    return []  # 手工对账账本未建（P2：manual_ledger 模式平移）——空数组，不编数据


@router.post("/ledger", status_code=201)
async def ledger_add(body: dict, _who=Depends(require_viewer)):
    raise HTTPException(501, "手工记账写入未接线（P2）")
