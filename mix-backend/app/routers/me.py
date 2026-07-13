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


# ---------------- 飞书通知自助绑定（个人接收通道;不含账号/令牌治理） ----------------
def _who_key(who: dict) -> str:
    return who.get("operator") or f"user:{who.get('uid')}" or "anon"


@router.get("/feishu")
async def feishu_get(who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return {}
    row = await pool.fetchrow("SELECT open_id, phone, union_id, enabled FROM operator_feishu WHERE operator=$1",
                              _who_key(who))
    return dict(row) if row else {}


@router.post("/feishu")
async def feishu_bind(body: dict, who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    await pool.execute(
        "INSERT INTO operator_feishu(operator, open_id, phone, union_id, enabled, updated_at) "
        "VALUES($1,$2,$3,$4,$5,now()) ON CONFLICT (operator) DO UPDATE SET "
        "open_id=$2, phone=$3, union_id=$4, enabled=$5, updated_at=now()",
        _who_key(who), str(body.get("open_id") or "")[:80], str(body.get("phone") or "")[:24],
        str(body.get("union_id") or "")[:80], bool(body.get("enabled", True)))
    return {"saved": True}


@router.get("/feishu/lookup")
async def feishu_lookup(phone: str = Query(...), _who=Depends(require_viewer)):
    """手机号→飞书 open_id/union_id（contact/v3/users/batch_get_id，DexCexMix 自建应用）。"""
    import os
    import httpx
    app_id = os.environ.get("DCM_FEISHU_APP_ID", "")
    app_secret = os.environ.get("DCM_FEISHU_APP_SECRET", "")
    if not (app_id and app_secret):
        raise HTTPException(501, "飞书应用未配置（DCM_FEISHU_APP_ID/SECRET）")
    async with httpx.AsyncClient(timeout=10) as c:
        tk = await c.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                          json={"app_id": app_id, "app_secret": app_secret})
        token = (tk.json() or {}).get("tenant_access_token")
        if not token:
            raise HTTPException(502, "飞书 token 获取失败")
        r = await c.post("https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id",
                         headers={"Authorization": f"Bearer {token}"},
                         json={"mobiles": [phone.strip()]})
        j = r.json() or {}
        users = ((j.get("data") or {}).get("user_list") or [])
        if not users or not users[0].get("user_id"):
            raise HTTPException(404, "该手机号不在飞书通讯录（需先加入企业）")
        return {"open_id": users[0].get("user_id"), "union_id": users[0].get("union_id", "")}
