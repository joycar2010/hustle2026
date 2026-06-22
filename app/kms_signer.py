"""AWS KMS 以太坊交易签名 —— 仅 live 模式调用,dry-run/testnet 永不触达。

设计契约(不可妥协的私钥安全):
- 私钥【从不】以明文出现在代码/内存/磁盘/日志/git。签名在 KMS 内部完成,只取出签名结果。
- KMS key 必须是 secp256k1(ECC_SECG_P256K1, SIGN_VERIFY),与以太坊同曲线。
- 钱包地址由 KMS 公钥派生一次(keccak(pubkey)[-20:]),与充值地址核对一致才允许 live。
- 每笔签名前由协调器的熔断(单笔/单日上限)把关;KMS 这层只负责"安全地签",不负责"该不该签"。

实现状态:接口与流程已就位;真正的 boto3 KMS 调用 + secp256k1 v 恢复 + RLP 编码留到 live 启用时填。
当前任何调用都显式抛错,确保 dry-run/testnet 阶段【不可能】误签真金交易。
"""
from __future__ import annotations


class KmsSigner:
    def __init__(self, key_id: str, expected_address: str = ""):
        if not key_id:
            raise RuntimeError("KmsSigner 需 key_id(live 模式)")
        self.key_id = key_id
        self.expected_address = (expected_address or "").lower()
        # 真正启用时:import boto3; self._kms = boto3.client("kms")
        self._kms = None

    def address(self) -> str:
        """从 KMS 公钥派生以太坊地址(GetPublicKey → DER 解 secp256k1 点 → keccak[-20:])。"""
        raise NotImplementedError(
            "KMS 地址派生待 live 启用:GetPublicKey(key_id) → 解 DER → keccak(pubkey)[-20:];"
            "并与 expected_address 核对一致")

    def sign_transaction(self, tx: dict, chain_id: int) -> bytes:
        """对 EIP-1559 交易签名,返回可广播的 raw bytes。
        流程:RLP 编码未签名 tx → keccak256 摘要 → KMS Sign(MessageType=DIGEST,
              SigningAlgorithm=ECDSA_SHA_256)→ 解 DER 得 r,s → 规范化 s(<n/2)→
              试 v∈{0,1} 用恢复地址==expected_address 定 v → 组装签名 raw tx。"""
        raise NotImplementedError(
            "KMS 交易签名待 live 启用(boto3 kms.sign + secp256k1 v 恢复 + RLP)。"
            "当前 dry-run/testnet 不应调用此函数 —— 调到即说明 mode 配置有误,已安全拦截")
