"""AWS KMS 以太坊交易签名 —— 仅 live 模式调用,dry-run/testnet 永不触达。

设计契约(不可妥协的私钥安全):
- 私钥【从不】以明文出现在代码/内存/磁盘/日志/git。签名在 KMS 内部完成,只取出签名结果(r,s)。
- KMS key 必须是 secp256k1(ECC_SECG_P256K1, SIGN_VERIFY),与以太坊同曲线。
- 钱包地址由 KMS 公钥派生一次(keccak(pubkey)[-20:]),与充值地址核对一致才允许 live。
- 每笔签名前由协调器的熔断(单笔/单日上限)把关;KMS 这层只负责"安全地签",不负责"该不该签"。

签名流程(EIP-1559 / type-2):
  RLP 编码未签名 tx → keccak256 摘要 → KMS Sign(MessageType=DIGEST, ECDSA_SHA_256)
  → DER 解出 (r,s) → s 规范化到低半区(EIP-2)→ 试 y_parity∈{0,1} 用恢复地址==expected 定 v
  → encode_transaction 组装可广播 raw bytes。
"""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key
from eth_account._utils.signing import encode_transaction
from eth_account.typed_transactions import TypedTransaction
from eth_keys import keys
from eth_utils import keccak, to_checksum_address

# secp256k1 群阶 n;低-s 规范化阈值 n/2(EIP-2:s 必须 ≤ n/2)
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SECP256K1_HALF_N = SECP256K1_N // 2


class KmsSigner:
    def __init__(self, key_id: str, expected_address: str = "", region: str = "ap-northeast-1"):
        if not key_id:
            raise RuntimeError("KmsSigner 需 key_id(live 模式)")
        self.key_id = key_id
        self.expected_address = (expected_address or "").lower()
        self.region = region
        self._kms = None
        self._addr = None  # 派生地址缓存(checksum)

    def _client(self):
        if self._kms is None:
            import boto3  # 延迟导入:dry-run/testnet 不依赖 boto3
            self._kms = boto3.client("kms", region_name=self.region)
        return self._kms

    def address(self) -> str:
        """从 KMS 公钥派生以太坊地址(GetPublicKey → DER 解 secp256k1 点 → keccak[-20:])。
        若设了 expected_address,派生结果必须一致,否则拒绝(防 key 配错动错钱包)。"""
        if self._addr is not None:
            return self._addr
        der = self._client().get_public_key(KeyId=self.key_id)["PublicKey"]
        pub = load_der_public_key(der)
        if pub.curve.name != "secp256k1":
            raise RuntimeError(f"KMS key 曲线非 secp256k1: {pub.curve.name}")
        nums = pub.public_numbers()
        raw = nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
        addr = to_checksum_address(keccak(raw)[-20:])
        if not self.expected_address:
            # live 必须显式指定钱包地址核对 —— 否则任意 KMS key 派生地址都被接受,可能动错钱包
            raise RuntimeError(
                f"KmsSigner 缺 expected_address(live 必填,防动错钱包)。当前 KMS 派生地址={addr}")
        if addr.lower() != self.expected_address:
            raise RuntimeError(
                f"KMS 派生地址 {addr} 与期望 {self.expected_address} 不符 —— 拒绝签名(防动错钱包)")
        self._addr = addr
        return addr

    def sign_transaction(self, tx: dict, chain_id: int) -> bytes:
        """对 EIP-1559 交易签名,返回可广播的 raw bytes。tx 必含:
        nonce, maxPriorityFeePerGas, maxFeePerGas, gas, to, value, data。"""
        signer_addr = self.address()  # 同时强制校验 == expected
        signer_bytes = bytes.fromhex(signer_addr[2:])

        txd = dict(tx)
        txd["chainId"] = chain_id
        txd.setdefault("type", 2)
        txd.setdefault("accessList", [])

        unsigned = TypedTransaction.from_dict(txd)
        msg_hash = unsigned.hash()  # 32B 签名摘要

        # KMS 内部签名(MessageType=DIGEST:KMS 不再二次哈希,直接对摘要做 EC 运算)
        der = self._client().sign(
            KeyId=self.key_id, Message=msg_hash,
            MessageType="DIGEST", SigningAlgorithm="ECDSA_SHA_256",
        )["Signature"]
        r, s = decode_dss_signature(der)
        if s > SECP256K1_HALF_N:  # 低-s 规范化(EIP-2;否则节点拒收)
            s = SECP256K1_N - s

        # 恢复 y_parity:试 0/1,取反推地址 == 签名人地址者
        v = None
        for cand in (0, 1):
            try:
                rec = keys.Signature(vrs=(cand, r, s)).recover_public_key_from_msg_hash(msg_hash)
            except Exception:  # noqa: BLE001
                continue
            if rec.to_canonical_address() == signer_bytes:
                v = cand
                break
        if v is None:
            raise RuntimeError("无法从签名恢复出签名人地址(r/s 异常),拒绝广播")

        raw = encode_transaction(unsigned, vrs=(v, r, s))
        return bytes(raw)
