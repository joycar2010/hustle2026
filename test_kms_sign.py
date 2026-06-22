"""无资金验证:KMS 签名链路是否产出可被节点正确还原签名人的交易。
构造一笔合成 EIP-1559 交易(不广播),KMS 签名后用 eth_account 反推 sender,核对 == 钱包。
用法: PYTHONUTF8=1 python test_kms_sign.py
"""
import os
from eth_account import Account

from app.kms_signer import KmsSigner

KEY_ID = os.environ.get("KMS_KEY_ID", "002cffe4-fe31-478d-a77b-ed943c90eac7")
WALLET = "0x7CB02F6746b69C4128A93fABFB6aBBc34d1074d0"
OP_CHAIN_ID = 10

signer = KmsSigner(KEY_ID, expected_address=WALLET, region="ap-northeast-1")

print("=== ① 地址派生 ===")
addr = signer.address()
print("  KMS 派生:", addr)
print("  期望钱包:", WALLET)
assert addr.lower() == WALLET.lower(), "地址不符!"
print("  ✅ 一致")

print("=== ② 合成交易签名(不广播) ===")
tx = {
    "nonce": 0,
    "maxPriorityFeePerGas": 1_000_000,      # 0.001 gwei
    "maxFeePerGas": 50_000_000,             # 0.05 gwei(OP 典型)
    "gas": 120_000,
    "to": WALLET,                           # 发给自己
    "value": 0,
    "data": b"",
}
raw = signer.sign_transaction(tx, OP_CHAIN_ID)
print("  raw tx 前缀:", raw[:1].hex(), "(应为 02 = EIP-1559)")
print("  raw 长度:", len(raw), "bytes")

print("=== ③ 像节点一样反推签名人 ===")
recovered = Account.recover_transaction("0x" + raw.hex())
print("  反推 sender:", recovered)
assert recovered.lower() == WALLET.lower(), f"签名人不符! {recovered} != {WALLET}"
print("  ✅ 签名人 == 钱包地址 —— KMS 签名链路【全程正确】")
print()
print("结论: 地址派生 ✅  签名 ✅  节点级反推 ✅  —— live 签名路径可用(本测试未广播任何交易)")
