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

# §4A.7 门户错误状态(认证成功后才返回;认证前 /auth/login 统一普通失败防枚举)
# 内部操作员角色——误登门户给 OPERATOR_PORTAL_MISMATCH(指路管理端),不给 NO_PORTFOLIO_GRANT
_OPERATOR_ROLES = {"operator", "admin", "owner", "super_admin", "OPERATOR_MOBILE_LIMITED",
                   "OPERATOR_TABLET", "operator_mobile_trusted"}

_seeded_clients = False


async def ensure_client_seed():
    """§4A 最小切分幂等种子:为存量 share_account 建 client_party 并回填 client_id;
    为已有 login_user_id 绑定建 portfolio_access_grant。份额权威留 mix_main(不搬 dcm_main)。"""
    global _seeded_clients
    if _seeded_clients:
        return
    pool = await ds.pg_main()
    if pool is None:
        return
    # DDL 仅在表缺失时运行(表由 0012 迁移以 postgres 建,mix 角色非 owner 不能 ALTER/CREATE INDEX;
    # 已存在则跳过,避免 InsufficientPrivilege 冒泡到 require_investor)
    exists = await pool.fetchval("SELECT to_regclass('public.client_party')")
    if not exists:
        try:
            await pool.execute("""
                CREATE TABLE IF NOT EXISTS client_party (
                    client_id BIGSERIAL PRIMARY KEY,
                    client_type TEXT NOT NULL DEFAULT 'CORE_POOL'
                        CHECK (client_type IN ('CORE_POOL','SMA','HOUSE_RND')),
                    display_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','frozen','closed')),
                    note TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now());
                CREATE TABLE IF NOT EXISTS portfolio_access_grant (
                    id BIGSERIAL PRIMARY KEY, auth_subject_id BIGINT NOT NULL,
                    client_id BIGINT NOT NULL REFERENCES client_party(client_id),
                    portfolio_id TEXT NOT NULL DEFAULT 'CORE_POOL',
                    permissions TEXT NOT NULL DEFAULT 'read',
                    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
                    expires_at TIMESTAMPTZ, granted_by TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(auth_subject_id, client_id, portfolio_id));
                CREATE INDEX IF NOT EXISTS idx_pag_subject ON portfolio_access_grant (auth_subject_id) WHERE status='active';
                ALTER TABLE share_account ADD COLUMN IF NOT EXISTS client_id BIGINT REFERENCES client_party(client_id);
                CREATE INDEX IF NOT EXISTS idx_sa_client ON share_account (client_id)""")
        except Exception as e:  # noqa: BLE001  表由迁移建=正常,DDL 竞态忽略
            log.warning("client identity DDL (may pre-exist): %s", e)
            _seeded_clients = True
            return
    # 存量 share_account → client_party(一户一主体),回填 client_id(mix_app 有 INSERT/UPDATE GRANT)
    for r in await pool.fetch("SELECT investor_id, display_name, login_user_id, is_house FROM share_account WHERE client_id IS NULL"):
        ctype = "HOUSE_RND" if r["is_house"] else "CORE_POOL"
        cid = await pool.fetchval(
            "INSERT INTO client_party(client_type, display_name, note) VALUES($1,$2,'seed:from share_account') "
            "RETURNING client_id", ctype, r["display_name"])
        await pool.execute("UPDATE share_account SET client_id=$1 WHERE investor_id=$2", cid, r["investor_id"])
        # 已有 login_user_id 绑定 → 建授权(投资份额查看权,非操作权限)
        if r["login_user_id"] is not None:
            await pool.execute(
                "INSERT INTO portfolio_access_grant(auth_subject_id, client_id, portfolio_id, permissions, "
                "granted_by) VALUES($1,$2,$3,'read+confirm','seed-migration') ON CONFLICT DO NOTHING",
                int(r["login_user_id"]), cid, ctype)
    _seeded_clients = True
    log.info("client identity seed done")


async def require_investor(authorization: str | None = Header(default=None)) -> dict:
    """登录 JWT → uid → portfolio_access_grant → client → share_account(§4A)。
    份额归属客户主体(client_party),授权走 grant——操作员角色本身不产生投资权益。
    错误分级(§4A.7,认证后才返回):OPERATOR_PORTAL_MISMATCH/NO_PORTFOLIO_GRANT/SHARE_ACCOUNT_NOT_READY。"""
    from ..deps import _jwt_decode
    if not (authorization and authorization.lower().startswith("bearer ")):
        raise HTTPException(401, "需要投资者登录(Authorization: Bearer)")
    who = _jwt_decode(authorization[7:].strip())
    if not who or who.get("uid") is None:
        raise HTTPException(401, "无效登录令牌")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    uid = int(who["uid"])
    # 访问令牌撤销校验:JWT 带 jti(签发的长期访问令牌)→ 须与 mix_users.access_token_jti 一致;
    # 无 jti(账号密码登录的短期 JWT)= 正常放行。撤销/重置令牌即让旧 jti 失效。
    jti = who.get("jti")
    if jti:
        try:
            cur = await pool.fetchval("SELECT access_token_jti FROM mix_users WHERE id=$1", uid)
            if cur != jti:
                raise HTTPException(401, "访问令牌已失效(被重置或撤销),请向管理员索取新令牌")
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001  列未建=无撤销记录,放行(向后兼容)
            pass
    await ensure_client_seed()
    # 1) 授权解析(权威路径):auth_subject → active grant → client → share_account
    row = await pool.fetchrow(
        "SELECT sa.investor_id, sa.display_name, sa.status, g.client_id, g.permissions, cp.client_type "
        "FROM portfolio_access_grant g JOIN client_party cp ON cp.client_id=g.client_id "
        "LEFT JOIN share_account sa ON sa.client_id=g.client_id AND sa.status<>'closed' "
        "WHERE g.auth_subject_id=$1 AND g.status='active' "
        "AND (g.expires_at IS NULL OR g.expires_at>now()) "
        "AND cp.status<>'closed' ORDER BY g.id LIMIT 1", uid)
    if row and row["investor_id"] is not None:
        return {"investor_id": int(row["investor_id"]), "display_name": row["display_name"],
                "client_id": int(row["client_id"]), "client_type": row["client_type"],
                "permissions": row["permissions"], "uid": uid, "username": who.get("operator", "")}
    if row and row["investor_id"] is None:
        raise HTTPException(403, {"code": "SHARE_ACCOUNT_NOT_READY",
                                  "message": "投资账户正在配置中,请稍后再试或联系管理员"})
    # 2) 无授权:操作员误登门户 vs 尚未开通
    urole = str(who.get("urole") or "").lower()
    if urole in {r.lower() for r in _OPERATOR_ROLES}:
        raise HTTPException(403, {"code": "OPERATOR_PORTAL_MISMATCH",
                                  "message": "操作员账号请前往管理后台 mix.hustle2026.xyz,投资门户仅供投资人查看"})
    raise HTTPException(403, {"code": "NO_PORTFOLIO_GRANT",
                             "message": "尚未开通组合查看权限,请联系管理员开通"})


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
