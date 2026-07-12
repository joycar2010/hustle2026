"""账户列表 —— 读=六所权益快照真数据(dcm:account:*)；写与 KMS 执行 P0 未接线 501。
KMS 四道闸代码(security_kms)保留，真金化前置：审批流持久化 + 安全评审清单走完。"""
from fastapi import APIRouter, Depends, HTTPException
from ..schemas import AccountNode, AccountCreate, KmsTransfer
from ..deps import require_operator, require_admin, require_viewer, not_wired
from .. import adapters
from .. import datasources as ds

router = APIRouter(tags=["accounts"])


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


@router.post("/accounts/{id}/actions", status_code=202)
async def account_action(id: str, body: dict, op=Depends(require_operator)):
    not_wired(f"账户操作 {id}[{body.get('action')}]")


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
