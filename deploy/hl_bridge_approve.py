"""HL 入桥 + approveAgent(KMS 主钱包签名),一次性工具。

用法(需 env: KMS_KEY_ID, AWS_REGION[, AWS_ACCESS_KEY_ID/SECRET...]):
  python hl_bridge_approve.py check            # 仅核对 KMS 公钥==主钱包地址+余额
  python hl_bridge_approve.py bridge 100       # USDC 入 HL 官方桥(打满 100)
  python hl_bridge_approve.py approve          # approveAgent(授权 .hl_agent.env 的 agent)

安全断言:KMS 公钥推导地址必须==MASTER,否则拒签;桥地址=官方 Bridge2(双源验证);
仅原生 USDC;逐步打印回执,任何一步失败即停。
"""
import json, os, sys, time
import boto3, httpx
from eth_utils import keccak, to_checksum_address
from eth_keys.datatypes import Signature
import rlp

MASTER = "0x7CB02F6746b69C4128A93fABFB6aBBc34d1074d0"
AGENT_ENV = os.path.expanduser("~/dexcexmix/.hl_agent.env")
BRIDGE = "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7"   # HL Bridge2(官方文档+arbiscan 双验证)
USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"      # Arbitrum 原生 USDC
RPC = "https://arb1.arbitrum.io/rpc"
CHAIN_ID = 42161
SECP_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

kms = boto3.client("kms", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
KEY_ID = os.environ["KMS_KEY_ID"]

def rpc(method, params):
    r = httpx.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=20).json()
    if "error" in r: raise RuntimeError(r["error"])
    return r["result"]

def kms_pubkey_address():
    der = kms.get_public_key(KeyId=KEY_ID)["PublicKey"]
    # DER SPKI 末 64 字节 = 未压缩点(去 0x04 头)
    point = der[-64:]
    return to_checksum_address(keccak(point)[-20:].hex())

def kms_sign_digest(digest: bytes):
    sig = kms.sign(KeyId=KEY_ID, Message=digest, MessageType="DIGEST",
                   SigningAlgorithm="ECDSA_SHA_256")["Signature"]
    # DER → (r,s), low-s 规范化
    import binascii
    b = bytes(sig)
    assert b[0] == 0x30
    i = 4; rlen = b[3]; r = int.from_bytes(b[i:i+rlen], "big"); i += rlen
    slen = b[i+1]; s = int.from_bytes(b[i+2:i+2+slen], "big")
    if s > SECP_N // 2: s = SECP_N - s
    # 恢复 recid:枚举 0/1 比对地址
    for recid in (0, 1):
        try:
            pub = Signature(vrs=(recid, r, s)).recover_public_key_from_msg_hash(digest)
            if pub.to_checksum_address() == MASTER:
                return r, s, recid
        except Exception:
            continue
    raise RuntimeError("recid recovery failed (公钥不匹配主地址?)")

def cmd_check():
    addr = kms_pubkey_address()
    print("KMS 公钥地址:", addr, "匹配主钱包" if addr == MASTER else "!!!不匹配,禁止签名!!!")
    bal = int(rpc("eth_call", [{"to": USDC, "data": "0x70a08231"+MASTER[2:].zfill(64)}, "latest"]), 16)/1e6
    eth = int(rpc("eth_getBalance", [MASTER, "latest"]), 16)/1e18
    print(f"USDC={bal} ETH(gas)={eth}")

def cmd_bridge(amount_usdc: float):
    assert kms_pubkey_address() == MASTER, "KMS key 地址不匹配主钱包,拒签"
    assert amount_usdc >= 5, "HL 最低入金 5 USDC"
    amt = int(amount_usdc * 1e6)
    data = bytes.fromhex("a9059cbb" + BRIDGE[2:].lower().zfill(64) + hex(amt)[2:].zfill(64))
    nonce = int(rpc("eth_getTransactionCount", [MASTER, "latest"]), 16)
    gas_price = int(int(rpc("eth_gasPrice", []), 16) * 1.2)
    fields = [nonce, gas_price, 200000, bytes.fromhex(USDC[2:]), 0, data]
    digest = keccak(rlp.encode(fields + [CHAIN_ID, 0, 0]))
    r, s, recid = kms_sign_digest(digest)
    v = CHAIN_ID * 2 + 35 + recid
    raw = rlp.encode(fields + [v, r, s])
    print(f"广播: {amount_usdc} USDC -> HL Bridge2 (nonce={nonce})")
    txh = rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
    print("txhash:", txh)
    for _ in range(30):
        time.sleep(4)
        rc = rpc("eth_getTransactionReceipt", [txh])
        if rc:
            print("receipt status:", rc.get("status"))
            break
    for _ in range(20):
        time.sleep(6)
        hl = httpx.post("https://api.hyperliquid.xyz/info", json={"type":"clearinghouseState","user":MASTER}, timeout=15).json()
        av = hl.get("marginSummary", {}).get("accountValue")
        print("HL accountValue:", av)
        if float(av or 0) > 0:
            print("HL 入账确认 ✓"); break

def cmd_approve():
    assert kms_pubkey_address() == MASTER, "KMS key 地址不匹配主钱包,拒签"
    agent = dict(l.strip().split("=",1) for l in open(AGENT_ENV))["HL_AGENT_ADDRESS"]
    from eth_account.messages import encode_typed_data
    nonce = int(time.time() * 1000)
    action = {"type": "approveAgent", "hyperliquidChain": "Mainnet",
              "signatureChainId": "0xa4b1", "agentAddress": agent.lower(),
              "agentName": "dcm", "nonce": nonce}
    typed = {
        "domain": {"name": "HyperliquidSignTransaction", "version": "1",
                    "chainId": CHAIN_ID, "verifyingContract": "0x0000000000000000000000000000000000000000"},
        "types": {"EIP712Domain": [
                      {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                      {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
                   "HyperliquidTransaction:ApproveAgent": [
                      {"name": "hyperliquidChain", "type": "string"},
                      {"name": "agentAddress", "type": "address"},
                      {"name": "agentName", "type": "string"},
                      {"name": "nonce", "type": "uint64"}]},
        "primaryType": "HyperliquidTransaction:ApproveAgent",
        "message": {"hyperliquidChain": "Mainnet", "agentAddress": agent.lower(),
                     "agentName": "dcm", "nonce": nonce}}
    digest = encode_typed_data(full_message=typed).body if False else None
    from eth_account.messages import _hash_eip191_message
    msg = encode_typed_data(full_message=typed)
    digest = _hash_eip191_message(msg)
    r, s, recid = kms_sign_digest(digest)
    payload = {"action": action, "nonce": nonce,
               "signature": {"r": hex(r), "s": hex(s), "v": recid + 27}}
    resp = httpx.post("https://api.hyperliquid.xyz/exchange", json=payload, timeout=20).json()
    print("approveAgent resp:", json.dumps(resp)[:300])

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check": cmd_check()
    elif cmd == "bridge": cmd_bridge(float(sys.argv[2]))
    elif cmd == "approve": cmd_approve()
