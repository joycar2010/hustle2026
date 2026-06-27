"""极简以太坊 JSON-RPC 客户端 + ERC20 助手 —— 仅 live 链上执行用,零 web3 依赖。

只实现 live 路径必需的几个调用(nonce/费用/估gas/eth_call/广播/回执 + ERC20 approve/allowance/balanceOf),
保持与 P0 一致的 requests 极简风格,避免引入 web3 整套依赖与版本坑。
所有写操作(广播)由上层 KMS 签名后才发;本模块自身从不持私钥。
"""
from __future__ import annotations

import time

import requests

# 知名 ERC20 函数选择器(keccak[:4],写死避免运行时计算)
SEL_APPROVE = "095ea7b3"      # approve(address,uint256)
SEL_ALLOWANCE = "dd62ed3e"    # allowance(address,address)
SEL_BALANCEOF = "70a08231"    # balanceOf(address)
SEL_TRANSFER = "a9059cbb"     # transfer(address,uint256)


def _enc_addr(addr: str) -> str:
    clean = addr.lower().replace("0x", "")
    if len(clean) != 40 or any(c not in "0123456789abcdef" for c in clean):
        raise ValueError(f"非法地址(需40位hex): {addr}")
    return "0" * 24 + clean


def _enc_uint(v: int) -> str:
    return f"{v:064x}"


# ERC20 Transfer 事件 topic0 = keccak("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def receipt_ok(rc: dict) -> bool:
    """健壮判定回执成功:容忍 status 为 hex 串("0x1")或整数(1);缺字段视为失败。"""
    if not rc:
        return False
    st = rc.get("status")
    if st is None:
        return False
    try:
        return (int(st, 16) if isinstance(st, str) else int(st)) == 1
    except (ValueError, TypeError):
        return False


class PendingTxError(Exception):
    """交易已广播但超时仍在 mempool —— 状态未知。严禁当失败重发(会双花)。"""


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
        """pending nonce(含 mempool 未确认)。approve→swap 连续两笔间用 confirmed_nonce+本地推进,
        不重复查 pending(L2 pending 视图滞后会致两笔同 nonce 冲突)。"""
        return int(self._call("eth_getTransactionCount", [addr, "pending"]), 16)

    def confirmed_nonce(self, addr: str) -> int:
        """已确认 nonce(latest);approve 回执后用它派生 swap 的 nonce,避免 pending 滞后冲突。"""
        return int(self._call("eth_getTransactionCount", [addr, "latest"]), 16)

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
        """返回 (maxFeePerGas, maxPriorityFeePerGas);按链区分 gas 地板。
        - OP/Arbitrum/Base 等 L2:base_fee 趋近0,prio 0.001gwei,base*3 余量;
        - BSC(56):不走标准EIP-1559,baseFeePerGas常取不到(返回~0),但BSC实际要求
          gasPrice≥~1gwei否则交易卡mempool不被打包。故 BSC 用 eth_gasPrice + 1gwei地板。
        maxFee 留 3x 余量防区块抬费。"""
        if self.chain_id == 56:  # BSC:用 legacy gasPrice,设 1gwei 地板防卡单
            try:
                gp = int(self._call("eth_gasPrice", []), 16)
            except Exception:  # noqa: BLE001
                gp = 0
            floor = 1_000_000_000  # 1 gwei,BSC 最低可打包价
            gp = max(gp, floor)
            return gp * 2, gp  # BSC prio==gasPrice 同源(legacy 语义),2x 余量
        # L2(OP/ARB/BASE...):EIP-1559,base 趋近 0
        blk = self._call("eth_getBlockByNumber", ["latest", False])
        base = int(blk.get("baseFeePerGas", "0x0"), 16)
        prio = 1_000_000  # 0.001 gwei,OP 典型;base*3 余量已足够覆盖波动
        return base * 3 + prio, prio

    # ---- 广播 + 回执 ----
    def send_raw(self, raw_hex: str) -> str:
        if not raw_hex.startswith("0x"):
            raw_hex = "0x" + raw_hex
        return self._call("eth_sendRawTransaction", [raw_hex])

    def tx_by_hash(self, tx_hash: str) -> dict | None:
        """查交易本身(判断是否已被打包/仍在 mempool);None=节点不知道此交易。"""
        return self._call("eth_getTransactionByHash", [tx_hash])

    def wait_receipt(self, tx_hash: str, timeout: float = 120.0, poll: float = 2.0) -> dict:
        """等回执。超时不立即放弃 —— 先做一次终态确认(交易可能已上链只是回执慢):
        - 若已有回执 → 返回(成败由上层 receipt_ok 判)
        - 若交易仍在 mempool(pending,blockNumber=None)→ 抛 PendingError(状态未知,严禁当失败重发=防双花)
        - 若节点完全不知道此交易 → 抛 TimeoutError(可安全判失败)"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            rc = self._call("eth_getTransactionReceipt", [tx_hash])
            if rc:
                return rc
            time.sleep(poll)
        # 超时终态确认
        rc = self._call("eth_getTransactionReceipt", [tx_hash])
        if rc:
            return rc
        tx = self.tx_by_hash(tx_hash)
        if tx is not None and tx.get("blockNumber") is None:
            raise PendingTxError(f"交易仍在mempool未确认(状态未知,勿重发): {tx_hash}")
        raise TimeoutError(f"等回执超时且节点无此交易(可判失败): {tx_hash}")

    # ---- ERC20 ----
    def erc20_balance(self, token: str, owner: str) -> int:
        res = self.call(token, "0x" + SEL_BALANCEOF + _enc_addr(owner))
        return int(res, 16) if res and res != "0x" else 0

    def erc20_allowance(self, token: str, owner: str, spender: str) -> int:
        res = self.call(token, "0x" + SEL_ALLOWANCE + _enc_addr(owner) + _enc_addr(spender))
        return int(res, 16) if res and res != "0x" else 0

    @staticmethod
    def transfer_in_from_logs(rc: dict, token: str, to_wallet: str) -> int:
        """从回执 logs 解析【本笔交易】转入 wallet 的指定 token 总量(只信本 tx 的 Transfer 事件,
        不依赖全局余额差 —— 避免同区块其他转账污染)。token/to_wallet 不区分大小写。"""
        token_l = token.lower()
        to_l = to_wallet.lower().replace("0x", "")
        total = 0
        for lg in rc.get("logs", []):
            if lg.get("address", "").lower() != token_l:
                continue
            topics = lg.get("topics", [])
            if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
                continue
            # topics[2] = to(左填充到32B);取后40位比对
            if topics[2][-40:].lower() != to_l:
                continue
            data = lg.get("data", "0x")
            total += int(data, 16) if data and data != "0x" else 0
        return total

    @staticmethod
    def erc20_approve_data(spender: str, amount: int) -> str:
        return "0x" + SEL_APPROVE + _enc_addr(spender) + _enc_uint(amount)

    @staticmethod
    def erc20_transfer_data(to: str, amount: int) -> str:
        """ERC20 transfer(to, amount) calldata —— 退款转 USDC 用。"""
        return "0x" + SEL_TRANSFER + _enc_addr(to) + _enc_uint(amount)

    @staticmethod
    def checksum(addr: str) -> str:
        from eth_utils import to_checksum_address  # 惰性:dry-run 不依赖 eth_utils
        return to_checksum_address(addr)
