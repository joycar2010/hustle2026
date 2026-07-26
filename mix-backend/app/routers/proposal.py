"""DRY_RUN 提案链 + Passkey/TOTP 审批 + 两步平仓预演报价(V5 深化,shadow 铁律)。

设计流程(qx5QC 规约):候选 → DRY_RUN → COOLDOWN → WebAuthn/TOTP → ACTIVE。
本模块实现前四步的 shadow 骨架:
  - 提案落 mix_main.dry_run_proposal(状态机 DRAFT→DRY_RUN→COOLDOWN→PENDING_APPROVAL→APPROVED/REJECTED/EXPIRED)。
  - **APPROVED 绝不下单、绝不武装**——只记录"人工已批准该经济意图",armed 执行仍须专场+显式放行。
  - 审批第二因子=TOTP(RFC6238,规约允许 WebAuthn/TOTP);操作员先绑定 secret 再用 6 位码批准。
两步平仓预演报价=只读:读实时盘口算两腿报价/费用/预计滑点/放弃 funding/最终净收益,不触发任何下单。
"""
import base64
import hashlib
import hmac
import json
import struct
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer, require_operator, require_admin
from .. import datasources as ds

router = APIRouter()

_PROP_DDL = """CREATE TABLE IF NOT EXISTS dry_run_proposal (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT 'C2.H',
    venue_long TEXT NOT NULL DEFAULT '',
    venue_short TEXT NOT NULL DEFAULT '',
    target_notional NUMERIC NOT NULL DEFAULT 0,
    econ_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL DEFAULT 'DRY_RUN'
        CHECK (state IN ('DRAFT','DRY_RUN','COOLDOWN','PENDING_APPROVAL','APPROVED','REJECTED','EXPIRED')),
    cooldown_until TIMESTAMPTZ,
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""

_TOTP_DDL = """CREATE TABLE IF NOT EXISTS operator_totp (
    operator TEXT PRIMARY KEY,
    secret TEXT NOT NULL,
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""

COOLDOWN_SEC = 300   # 冷静期(V5 规约:DRY_RUN→COOLDOWN→二次认证)


# ───────── RFC6238 TOTP(无第三方依赖) ─────────
def _b32secret() -> str:
    import os
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _totp_now(secret: str, drift: int = 0) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int(time.time()) // 30 + drift
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    off = h[-1] & 0x0F
    code = (struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def _totp_verify(secret: str, code: str) -> bool:
    code = (code or "").strip()
    return any(_totp_now(secret, d) == code for d in (-1, 0, 1))   # ±30s 容差


# ───────── 两步平仓预演报价(只读) ─────────
@router.get("/close-preview")
async def close_preview(symbol: str, _who=Depends(require_viewer)):
    """读实时盘口算两腿平仓报价/费用/滑点/放弃funding/最终净收益。纯只读,不触发下单。"""
    mgr = await ds.get_json("dcm:exec:manager") or {}
    pair = next((p for p in (mgr.get("pairs") or [])
                 if (p.get("symbol") or p.get("pair")) == symbol), None)
    if not pair:
        # C1 单所形态(manager.symbols):永续腿=reduce-only,现货腿=卖出(理财须先赎回)
        ss = next((x for x in (mgr.get("symbols") or []) if x.get("symbol") == symbol), None)
        if ss:
            amt = float(ss.get("perp_amt") or 0)
            pair = {"symbol": symbol, "legs": [{"venue": "binance", "amt": amt}]}
        else:
            raise HTTPException(404, f"{symbol} 非在管组合(exec-manager 无此 pair/symbol)")
    TAKER_BPS = 5.0
    legs_out, gross_fee, gross_slip, notional = [], 0.0, 0.0, 0.0
    for lg in (pair.get("legs") or []):
        v, amt = lg.get("venue"), float(lg.get("amt") or 0)
        if abs(amt) < 1e-12:
            continue
        try:
            raw = await ds.rds().hget(f"dcm:feed:{v}:perp", symbol)
            l1 = json.loads(raw) if raw else None
        except Exception:
            l1 = None
        bid = float((l1 or {}).get("bid") or 0)
        ask = float((l1 or {}).get("ask") or 0)
        mid = (bid + ask) / 2 if bid and ask else 0
        # 平仓方向=持仓反向;穿价成交价=对手侧(BUY吃ask/SELL吃bid)
        close_side = "BUY" if amt < 0 else "SELL"
        fill_px = ask if close_side == "BUY" else bid
        leg_notional = abs(amt) * mid if mid else 0
        fee = leg_notional * TAKER_BPS / 10000
        slip = (leg_notional * ((ask - bid) / 2 / mid)) if mid else 0
        gross_fee += fee
        gross_slip += slip
        notional += leg_notional
        legs_out.append({"venue": v, "side": close_side, "qty": abs(amt),
                         "quote_px": fill_px or None, "mid": mid or None,
                         "est_fee_usdt": round(-fee, 4), "est_slip_usdt": round(-slip, 4),
                         "fresh": bool(l1 and (time.time() * 1000 - float(l1.get("recv_ts") or 0) < 120000))})
    # 放弃 funding=当前周期已计提但未结算的资金费(估:净差×名义按已过周期比例;简化只标注方向)
    upnl = 0.0
    for lg in (pair.get("legs") or []):
        pd = ((await ds.get_json(f"dcm:account:{lg.get('venue')}") or {}).get("pos_detail") or {}).get(symbol) or {}
        if pd.get("upnl") is not None:
            upnl += float(pd["upnl"])
    net = upnl - gross_fee - gross_slip
    return {
        "symbol": symbol, "legs": legs_out,
        "unrealized_pnl_usdt": round(upnl, 4),
        "total_fee_usdt": round(-gross_fee, 4),
        "total_slippage_usdt": round(-gross_slip, 4),
        "forfeit_funding_note": "平仓即放弃本周期未结算 funding(估额需结算边界,见组合下一现金流)",
        "final_net_usdt": round(net, 4),
        "all_fresh": all(lg["fresh"] for lg in legs_out) if legs_out else False,
        "note": "预演报价=只读快照;两步确认第2步(Passkey/TOTP)才真正提交",
    }


# ───────── DRY_RUN 提案链 ─────────
@router.post("/proposal/create")
async def proposal_create(body: dict, op=Depends(require_operator)):
    """从机会候选生成 DRY_RUN 提案:记录经济闸快照,进入 COOLDOWN 计时。shadow——不下单。"""
    from .maintenance import block_new_risk
    await block_new_risk()   # 维护排空期 API 入口即拒新增(权威闸在 policy/engine 层)
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    await pool.execute(_PROP_DDL)
    sym = str(body.get("symbol") or "").strip().upper()
    if not sym:
        raise HTTPException(400, "symbol 必填")
    # 现拉候选经济快照(风调E/charge/两腿mode)——审批时可对比是否漂移
    op_snap = await ds.get_json("dcm:exec:opener") or {}
    cand = next((c for c in (op_snap.get("candidates") or []) if c.get("symbol") == sym), None)
    pol = await ds.get_json("dcm:risk:policy") or {}
    econ = {"candidate": cand, "policy_version": pol.get("policy_version"),
            "policy_epoch": pol.get("policy_epoch"), "snapped_at": int(time.time())}
    row = await pool.fetchrow(
        "INSERT INTO dry_run_proposal(symbol, product, venue_long, venue_short, target_notional, "
        "econ_snapshot, state, cooldown_until, created_by) "
        "VALUES($1,$2,$3,$4,$5,$6::jsonb,'COOLDOWN', now() + ($7||' seconds')::interval, $8) RETURNING id",
        sym, str(body.get("product") or "C2.H"),
        (cand or {}).get("venue_long", ""), (cand or {}).get("venue_short", ""),
        float((cand or {}).get("target_notional_usdt") or body.get("target_notional") or 0),
        json.dumps(econ), str(COOLDOWN_SEC), str(op.get("operator") or op.get("username") or "op"))
    return {"ok": True, "id": row["id"], "state": "COOLDOWN", "cooldown_sec": COOLDOWN_SEC,
            "note": "DRY_RUN 已记录,冷静期后可二次认证批准(APPROVED 仍为 shadow,不武装)"}


@router.get("/proposals")
async def proposals_list(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return {"rows": []}
    await pool.execute(_PROP_DDL)
    # 冷静期到期→自动转 PENDING_APPROVAL;超 24h 未批→EXPIRED
    await pool.execute("UPDATE dry_run_proposal SET state='PENDING_APPROVAL', updated_at=now() "
                       "WHERE state='COOLDOWN' AND cooldown_until < now()")
    await pool.execute("UPDATE dry_run_proposal SET state='EXPIRED', updated_at=now() "
                       "WHERE state IN ('COOLDOWN','PENDING_APPROVAL') AND created_at < now() - interval '24 hours'")
    rows = await pool.fetch(
        "SELECT id, symbol, product, venue_long, venue_short, target_notional::float8, state, "
        "extract(epoch from cooldown_until - now())::int AS cooldown_left, created_by, approved_by, "
        "created_at::text, econ_snapshot FROM dry_run_proposal "
        "WHERE state NOT IN ('EXPIRED','REJECTED') OR updated_at > now() - interval '6 hours' "
        "ORDER BY id DESC LIMIT 30")
    return {"rows": [dict(r) for r in rows]}


@router.post("/proposal/{pid}/approve")
async def proposal_approve(pid: int, body: dict, op=Depends(require_operator)):
    """二次认证批准(TOTP)。**APPROVED 是 shadow 终态:仅记录人工已批准该经济意图,
    绝不下单、绝不武装**——armed 执行须专场+显式放行(V5 铁律)。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    operator = str(op.get("operator") or op.get("username") or "op")
    # 强会话免逐笔(2026-07-19拍板:超管免二次认证;操作员登录已验TOTP=sa→会话内免逐笔)。
    # 弱会话(未登录TOTP的mix用户)才回退逐笔 WebAuthn/TOTP。
    from ..deps import is_strong_session
    if not is_strong_session(op):
        from .webauthn_auth import check_reauth_ticket
        if not await check_reauth_ticket(operator, str(body.get("reauth_ticket") or "")):
            trow = await pool.fetchrow("SELECT secret, confirmed FROM operator_totp WHERE operator=$1", operator)
            if not trow or not trow["confirmed"]:
                raise HTTPException(403, "未绑定/未确认 TOTP:先在 系统配置 → 二次认证 绑定 Authenticator(或注册 Passkey)")
            if not _totp_verify(trow["secret"], str(body.get("code") or "")):
                raise HTTPException(403, "TOTP 验证码错误或过期")
    row = await pool.fetchrow("SELECT state FROM dry_run_proposal WHERE id=$1", pid)
    if not row:
        raise HTTPException(404, "提案不存在")
    if row["state"] != "PENDING_APPROVAL":
        raise HTTPException(409, f"状态={row['state']},仅 PENDING_APPROVAL 可批准(须过冷静期)")
    await pool.execute("UPDATE dry_run_proposal SET state='APPROVED', approved_by=$2, updated_at=now() "
                       "WHERE id=$1", pid, operator)
    return {"ok": True, "state": "APPROVED",
            "note": "已批准(shadow 终态)——记录人工意图,不触发任何下单/武装"}


@router.post("/proposal/{pid}/reject")
async def proposal_reject(pid: int, op=Depends(require_operator)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    await pool.execute("UPDATE dry_run_proposal SET state='REJECTED', "
                       "approved_by=$2, updated_at=now() WHERE id=$1 AND state IN ('COOLDOWN','PENDING_APPROVAL')",
                       pid, str(op.get("operator") or op.get("username") or "op"))
    return {"ok": True, "state": "REJECTED"}


# ───────── TOTP 绑定(二次认证) ─────────
@router.post("/totp/provision")
async def totp_provision(op=Depends(require_operator)):
    """生成 TOTP secret + otpauth URI(前端出二维码);须再调 /totp/confirm 验证一次才启用。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    await pool.execute(_TOTP_DDL)
    operator = str(op.get("operator") or op.get("username") or "op")
    secret = _b32secret()
    await pool.execute("INSERT INTO operator_totp(operator, secret, confirmed) VALUES($1,$2,FALSE) "
                       "ON CONFLICT (operator) DO UPDATE SET secret=$2, confirmed=FALSE", operator, secret)
    uri = f"otpauth://totp/HustleMix:{operator}?secret={secret}&issuer=HustleMix&period=30&digits=6"
    return {"secret": secret, "otpauth_uri": uri,
            "note": "扫码加入 Authenticator,再输入一次动态码调 /totp/confirm 启用"}


@router.post("/totp/confirm")
async def totp_confirm(body: dict, op=Depends(require_operator)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    operator = str(op.get("operator") or op.get("username") or "op")
    row = await pool.fetchrow("SELECT secret FROM operator_totp WHERE operator=$1", operator)
    if not row:
        raise HTTPException(400, "先调 /totp/provision")
    if not _totp_verify(row["secret"], str(body.get("code") or "")):
        raise HTTPException(403, "验证码错误")
    await pool.execute("UPDATE operator_totp SET confirmed=TRUE WHERE operator=$1", operator)
    return {"ok": True, "note": "TOTP 已启用,后续提案审批用此动态码"}


@router.get("/totp/status")
async def totp_status(op=Depends(require_operator)):
    pool = await ds.pg_main()
    if pool is None:
        return {"bound": False}
    try:
        row = await pool.fetchrow("SELECT confirmed FROM operator_totp WHERE operator=$1",
                                  str(op.get("operator") or op.get("username") or "op"))
        return {"bound": bool(row and row["confirmed"])}
    except Exception:
        return {"bound": False}
