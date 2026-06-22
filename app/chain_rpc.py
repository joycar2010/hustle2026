"""极简以太坊 JSON-RPC 客户端 + ERC20 助手 —— 仅 live 链上执行用,零 web3 依赖。

只实现 live 路径必需的几个调用(nonce/费用/估gas/eth_call/广播/回执 + ERC20 approve/allowance/balanceOf),
保持与 P0 一致的 requests 极简风格,避免引入 web3 整套依赖与版本坑。
所有写操作(广播)由上层 KMS 签名后才发;本模块自身从不持私钥。
"""
from __future__ import annotations

import time

import requests
from eth_utils import to_checksum_address

# 知名 ERC20 函数选择器(keccak[:4],写死避免运行时计算)
SEL_APPROVE = "095ea7b3"      # approve(address,uint256)
SEL_ALLOWANCE = "dd62ed3e"    # allowance(address,address)
SEL_BALANCEOF = "70a08231"    # balanceOf(address)


def _enc_addr(addr: str) -> str:
    return "0" * 24 + addr.lower().replace("0x", "")


def _enc_uint(v: int) -> str:
    return f"{v:064x}"


class ChainRpc:
    def __init__(self, rpc_url: str, chain_id: int, timeout: int = 12):
        self.url = rpc_url
        self.chain_id = chain_id
        self._t = timeout
        self._s = requests.Session()
        self._id = 0

    def _call(self, method: str, params: list):
        self._id += 1
        r = self._s.post(self.url, json={"jsonrpc": "2.0", "id": self._id,
                                         "method": method, "params": params}, timeout=self._t)
        r.raise_for_status()
        d = r.json()
        if "error" in d and d["error"]:
            raise RuntimeError(f"RPC {method} 错误: {d['error']}")
        return d.get("result")

    # ---- 基础读 ----
    def nonce(self, addr: str) -> int:
        return int(self._call("eth_getTransactionCount", [addr, "pending"]), 16)

    def eth_balance(self, addr: str) -> int:
        return int(self._call("eth_getBalance", [addr, "latest"]), 16)

    def call(self, to: str, data: str) -> str:
        return self._call("eth_call", [{"to": to, "data": data}, "latest"])

    def estimate_gas(self, tx: dict) -> int:
        return int(self._call("eth_estimateGas", [tx]), 16)

    def base_fee(self) -> int:
        blk = self._call("eth_getBlockByNumber", ["latest", False])
        return int(blk.get("baseFeePerGas", "0x0"), 16)

    def priority_fee(self) -> int:
        try:
            return int(self._call("eth_maxPriorityFeePerGas", []), 16)
        except Exception:  # noqa: BLE001 —— 部分 RPC 不支持,用 OP 典型极小值兜底
            return 1_000_000  # 0.001 gwei

    def fees(self) -> tuple[int, int]:
        """返回 (maxFeePerGas, maxPriorityFeePerGas);maxFee 留 2x base 余量防区块抬费。"""
        prio = self.priority_fee()
        base = self.base_fee()
        return base * 2 + prio, prio

    # ---- 广播 + 回执 ----
    def send_raw(self, raw_hex: str) -> str:
        if not raw_hex.startswith("0x"):
            raw_hex = "0x" + raw_hex
        return self._call("eth_sendRawTransaction", [raw_hex])

    def wait_receipt(self, tx_hash: str, timeout: float = 120.0, poll: float = 2.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            rc = self._call("eth_getTransactionReceipt", [tx_hash])
            if rc:
                return rc
            time.sleep(poll)
        raise TimeoutError(f"等回执超时 {tx_hash}")

    # ---- ERC20 ----
    def erc20_balance(self, token: str, owner: str) -> int:
        res = self.call(token, "0x" + SEL_BALANCEOF + _enc_addr(owner))
        return int(res, 16) if res and res != "0x" else 0

    def erc20_allowance(self, token: str, owner: str, spender: str) -> int:
        res = self.call(token, "0x" + SEL_ALLOWANCE + _enc_addr(owner) + _enc_addr(spender))
        return int(res, 16) if res and res != "0x" else 0

    @staticmethod
    def erc20_approve_data(spender: str, amount: int) -> str:
        return "0x" + SEL_APPROVE + _enc_addr(spender) + _enc_uint(amount)

    @staticmethod
    def checksum(addr: str) -> str:
        return to_checksum_address(addr)
