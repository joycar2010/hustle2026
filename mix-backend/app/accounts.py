"""账户列表 —— 读=六所权益快照真数据(dcm:account:*)；写与 KMS 执行 P0 未接线 501。
KMS 四道闸代码(security_kms)保留，真金化前置：审批流持久化 + 安全评审清单走完。"""
import time

from fastapi import APIRouter, Depends, HTTPException
from ..schemas import AccountNode, AccountCreate, KmsTransfer
from ..deps import require_operator, require_admin, require_viewer, not_wired
from .. import adapters
from .. import proxy
from .. import datasources as ds

router = APIRouter(tags=["accounts"])

# 三机拓扑事实(作用域分配/IP白名单指引用;key 只存 B 机 .env 纪律)
MACHINES = {"A": "52.193.224.137 · 数据面(feed/universe/funding/采样)",
            "B": "54.65.42.207 · 执行面(五所key/引擎/监控)",
            "C": "57.181.130.126 · 控制面(gateway/decision/mix)"}


@router.get("/accounts", response_model=list[AccountNode])
async def accounts(_who=Depends(require_viewer)):
    """CEX 主账号行=account-snapshot 六所权益（B 机持 key，本服务只读总线快照）。
    子账户细分与 KMS 钱包组待 Phase B/P2。"""
    return await adapters.account_nodes()


@router.post("/accounts", status_code=201)
async def create_account(body: AccountCreate, admin=Depends(require_admin)):
    if body.kind == "sub" and not body.parentId:
        raise HTTPException(400, "子账户须指定挂载主账户 parentId")
    not_wired("新建账户")


async def _venue_status(vid: str) -> dict | None:
    """账户活体状态:dcm 六所走 dcm:account:{venue};coin 子账户走 panel balances(备注名匹配)。"""
    snap = await ds.get_json(f"dcm:account:{vid.lower()}")
    if snap:
        age = int(time.time() - float(snap.get("ts") or 0))
        return {"kind": "dcm", "equity_usdt": snap.get("equity_usdt"), "age_sec": age,
                "auth": "ok" if age < 300 else f"快照超龄 {age}s(key/网络需排查)"}
    panel = await ds.get_json("dcm:coin:panel") or {}
    for b in (panel.get("balances") or {}).get("balances") or []:
        if str(b.get("note") or "") == vid or f"sub:{b.get('account_id')}" == vid:
            return {"kind": "coin", "equity_usdt": b.get("total_equity") or b.get("net_asset_usdt"),
                    "age_sec": int(time.time() - float(panel.get("ts") or 0)),
                    "auth": "ok" if not b.get("api_restricted") else "受限(-2015 IP 白名单)"}
    return None


@router.post("/accounts/{id}/actions")
async def account_action(id: str, body: dict, op=Depends(require_operator)):
    """账户操作——纪律:真实动作真实做;做不到的(密钥经网页传输类)诚实拒绝并给出正确路径,绝不假 202。"""
    action = str(body.get("action") or "")
    pool = await ds.pg_main()

    async def _audit(result: str):
        await proxy.audit(op["operator"], op["role"], f"account.{action}", id,
                          {k: v for k, v in body.items() if k != "action"}, result)

    if action in ("verify", "refresh"):
        ds._cache.clear()   # 绕 3s 读缓存=真刷新
        st = await _venue_status(id)
        await _audit("ok" if st else "not_found")
        if st is None:
            raise HTTPException(404, f"{id} 无活体快照(不在 dcm 六所快照与 coin 面板中)")
        return {"ok": True, "action": action, **st,
                "note": "verify=鉴权/快照鲜度实证;refresh=绕缓存重读(快照源 60s 轮询)"}

    if action == "toggle":
        if pool is None:
            raise HTTPException(503, "mix_main 未配置")
        row = await pool.fetchrow("SELECT enabled FROM accounts_registry WHERE account_key=$1", id)
        new_val = not (row["enabled"] if row else True)
        await pool.execute(
            "INSERT INTO accounts_registry(account_key, enabled, updated_at) VALUES($1,$2,now()) "
            "ON CONFLICT (account_key) DO UPDATE SET enabled=$2, updated_at=now()", id, new_val)
        await _audit(f"enabled={new_val}")
        return {"ok": True, "enabled": new_val,
                "note": "运营标记(别名簿级):停用=面板置灰提醒;引擎启停请走 策略/规则中心(权威门闸)"}

    if action == "assign_scope":
        machine = str(body.get("machine") or "").upper()
        if machine not in MACHINES:
            raise HTTPException(400, "machine 必须是 A/B/C")
        if pool is None:
            raise HTTPException(503, "mix_main 未配置")
        await pool.execute(
            "INSERT INTO accounts_registry(account_key, machine, updated_at) VALUES($1,$2,now()) "
            "ON CONFLICT (account_key) DO UPDATE SET machine=$2, updated_at=now()", id, machine)
        await _audit(f"machine={machine}")
        return {"ok": True, "machine": machine, "desc": MACHINES[machine]}

    if action == "ip_whitelist":
        st = await _venue_status(id)
        await _audit("info")
        return {"ok": True, "machines": MACHINES,
                "current_auth": (st or {}).get("auth", "未知"),
                "note": "交易所后台该 key 需加白的出口 IP=执行机(B)。改完点「验证」实证生效。"}

    if action in ("set_api", "ip_proxy"):
        await _audit("refused")
        raise HTTPException(
            501, "密钥纪律:五所 key 只存 B 机 ~/dexcexmix/.env(600),不经网页/数据库传输。"
                 "换 key=SSH B 机改 .env 后重启 account-snapshot/引擎;IP 代理层现架构未用(直连+白名单)。")

    if action == "purge":
        if pool is None:
            raise HTTPException(503, "mix_main 未配置")
        n = await pool.execute("DELETE FROM accounts_registry WHERE account_key=$1", id)
        await _audit(n)
        return {"ok": True, "note": "已清除别名簿记录(别名/备注/作用域/启用标记);账户本体与快照不受影响"}

    not_wired(f"账户操作 {id}[{action}]")


# ---------------- KMS 钱包（审批流已持久化 mix_main；执行层保持未武装） ----------------
async def _kms_audit(actor: str, action: str, transfer_id, detail: dict):
    pool = await ds.pg_main()
    if pool:
        try:
            import json as _json
            await pool.execute(
                "INSERT INTO kms_audit(actor, action, transfer_id, detail) VALUES($1,$2,$3,$4)",
                actor, action, transfer_id, _json.dumps(detail, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001
            pass


@router.get("/kms/wallets")
async def kms_wallets(_who=Depends(require_viewer)):
    """已知链上资产（HL 主钱包 KMS 托管）。私钥不出 KMS，UI 只见掩码。"""
    return [{
        "id": "hl-master", "kind": "wallet", "platformType": "kms_wallet",
        "venue": "Arbitrum/HL", "domain": "KMS",
        "apiStatus": "ok",
        "metrics": {"地址": "0x7CB0…74d0", "托管": "AWS KMS（私钥不出 KMS）", "用途": "HL 桥入金/授权"},
        "approvalState": None, "children": [],
    }]


@router.get("/kms/transfers")
async def kms_transfers_list(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return []
    rows = await pool.fetch(
        "SELECT id, from_wallet, to_address, ccy, amount, state, initiator, approver, note, created_at "
        "FROM kms_transfers ORDER BY id DESC LIMIT 50")
    return [dict(r) for r in rows]


@router.post("/kms/transfers", status_code=202)
async def kms_transfer(body: KmsTransfer, op=Depends(require_operator)):
    """发起 —— 闸1(地址白名单)+闸2(单笔/日累计双限额) DB 强制；过闸才落 pending_approval。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    wl = await pool.fetchrow("SELECT 1 FROM kms_whitelist WHERE address=$1", body.to_address)
    if not wl:
        await _kms_audit(op["operator"], "initiate.denied_whitelist", None, body.model_dump(by_alias=True))
        raise HTTPException(403, "闸1拒绝：收款地址不在白名单（先经 SUPER_ADMIN 加白）")
    policy = await pool.fetchrow("SELECT per_tx_cap, daily_cap, armed FROM kms_policy WHERE id=1")
    if body.amount <= 0 or body.amount > float(policy["per_tx_cap"]):
        await _kms_audit(op["operator"], "initiate.denied_per_tx", None, body.model_dump(by_alias=True))
        raise HTTPException(403, f"闸2拒绝：单笔限额 {policy['per_tx_cap']}")
    spent = await pool.fetchval(
        "SELECT coalesce(sum(amount),0) FROM kms_transfers "
        "WHERE created_at > date_trunc('day', now()) AND state NOT IN ('rejected','failed')")
    if float(spent) + body.amount > float(policy["daily_cap"]):
        await _kms_audit(op["operator"], "initiate.denied_daily", None, body.model_dump(by_alias=True))
        raise HTTPException(403, f"闸2拒绝：日累计限额 {policy['daily_cap']}（今日已占 {spent}）")
    row = await pool.fetchrow(
        "INSERT INTO kms_transfers(from_wallet, to_address, ccy, amount, initiator) "
        "VALUES($1,$2,$3,$4,$5) RETURNING id", body.from_wallet, body.to_address,
        body.ccy, body.amount, op["operator"])
    await _kms_audit(op["operator"], "initiate", row["id"], body.model_dump(by_alias=True))
    return {"id": row["id"], "state": "pending_approval", "note": "闸1/2 通过；等待审批（发起人≠审批人强制）"}


@router.post("/kms/transfers/{tid}/approve")
async def kms_approve(tid: int, admin=Depends(require_admin)):
    """审批 —— 闸3(发起≠审批 DB 行强制)。闸4=私钥不出 KMS：执行层未武装(kms_policy.armed=false)，
    审批通过只落 approved，**绝不静默置 executed**（还币闸回滚静默失败的历史教训）。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    row = await pool.fetchrow("SELECT id, initiator, state FROM kms_transfers WHERE id=$1", tid)
    if not row:
        raise HTTPException(404, "转账单不存在")
    if row["state"] != "pending_approval":
        raise HTTPException(409, f"状态机拒绝：当前 {row['state']}，仅 pending_approval 可审批")
    if row["initiator"] == admin["admin"]:
        await _kms_audit(admin["admin"], "approve.denied_same_person", tid, {})
        raise HTTPException(403, "闸3拒绝：发起人不得审批自己的转账")
    policy = await pool.fetchrow("SELECT armed FROM kms_policy WHERE id=1")
    await pool.execute(
        "UPDATE kms_transfers SET state='approved', approver=$2, updated_at=now(), "
        "note='执行层未武装(armed=false)：KMS 签名待上线检查清单走完+用户显式放行' WHERE id=$1",
        tid, admin["admin"])
    await _kms_audit(admin["admin"], "approve", tid, {"armed": policy["armed"]})
    return {"id": tid, "state": "approved",
            "note": "审批通过。执行未武装：KMS 签名层按 SECURITY_KMS 清单走完并显式放行后才会真金执行"}


@router.post("/kms/whitelist", status_code=201)
async def kms_whitelist_add(body: dict, admin=Depends(require_admin)):
    addr = str(body.get("address") or "").strip()
    if not addr:
        raise HTTPException(400, "address required")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    await pool.execute(
        "INSERT INTO kms_whitelist(address, label, added_by) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
        addr, str(body.get("label") or ""), admin["admin"])
    await _kms_audit(admin["admin"], "whitelist.add", None, {"address": addr})
    return {"ok": True}
