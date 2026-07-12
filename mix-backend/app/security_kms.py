"""
KMS 钱包审批流 —— 安全不变量（invariants）在此集中实现，路由只调用。
把并入账户列表的 UI 便利与后端安全强度解耦：入口变了，闸门一个不能少。

四道闸（任一失败 → 拒绝，且记审计）：
  1) 白名单：to_address 必须在该钱包的 outbound 白名单内
  2) 限额：单笔 ≤ per_tx_cap，当日累计 ≤ daily_cap
  3) 发起/审批分离：approver_id != initiator_id（强制，不可配置关闭）
  4) 私钥不出 KMS：签名在 KMS 内完成，后端只拿签名结果与 txid
"""
from dataclasses import dataclass
from fastapi import HTTPException


@dataclass
class WalletPolicy:
    per_tx_cap: float
    daily_cap: float
    whitelist: set[str]


class KmsError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)


def check_transfer(wallet_id: str, to_address: str, amount: float,
                   initiator_id: str, policy: WalletPolicy, spent_today: float) -> None:
    """发起转账前置校验（闸 1/2）。通过后进入 pending_approval，绝不直接执行。"""
    if to_address not in policy.whitelist:
        raise KmsError("目标地址不在钱包白名单内")
    if amount > policy.per_tx_cap:
        raise KmsError(f"单笔超限：{amount} > {policy.per_tx_cap}")
    if spent_today + amount > policy.daily_cap:
        raise KmsError(f"当日累计超限：{spent_today + amount} > {policy.daily_cap}")
    # TODO(backend): 写入 kms_transfers(state='pending_approval', initiator_id, ...)


def approve_transfer(transfer_id: str, initiator_id: str, approver_id: str) -> None:
    """审批（闸 3）。审批人必须 != 发起人；审批人需具备 kms_approve 权限位。"""
    if approver_id == initiator_id:
        raise HTTPException(403, "发起人不得审批自己的转账（发起/审批分离，强制）")
    # TODO(backend): 校验 approver 具 kms_approve 权限 → 调 KMS 签名 → 落 txid → state='executed'
    #                全程写 kms_audit(prompt/发起/审批/签名结果)，与 AI 审计四件套同一审计域


def kms_audit(event: str, transfer_id: str, actor: str, detail: dict) -> None:
    """签名审计日志 —— 每一步（发起/审批/签名/冻结）都落库，不可删。"""
    # TODO(backend): append-only 落 kms_audit 表；对齐支撑域 B 的审计日志口径
    ...
