"""链上 DEX 买入腿执行 —— 安全分档,默认绝不签名/发送。

dry-run / testnet:只走 KyberSwap 报价(HTTP,与 P0 只读一致),返回"会买到多少"。绝不构造交易、绝不签名、绝不上链。
live(仅当 mode=live + KMS 配齐):routes→/route/build 构造 calldata→KMS 签名→广播→等回执→按余额差实测到账。
  ——KMS 签名为不可逆真金动作,未配齐 KMS/钱包时显式抛错,绝不静默执行;
  ——KmsSigner/ChainRpc 仅在 live 分支惰性导入,dry-run/testnet 不依赖 boto3/eth_account/web3。
"""
from __future__ import annotations

import logging

from .agg_quoter import AggQuoter
from .chains import chain_of
from .markets import Market

logger = logging.getLogger(__name__)


class OnchainExec:
    def __init__(self, mode: str = "dry-run", wallet_addr: str = "", kms_key_id: str = "",
                 kyber_client_id: str = "crossarb", rpc_url: str = "",
                 kms_region: str = "ap-northeast-1", slippage_bps: int = 50,
                 approve_cap_usd: float = 3000.0, recv_timeout: float = 120.0):
        self.mode = mode
        self.wallet_addr = wallet_addr
        self.kms_key_id = kms_key_id
        self.rpc_url = rpc_url
        self.kms_region = kms_region
        self.slippage_bps = int(slippage_bps)
        self.approve_cap_usd = approve_cap_usd
        self.recv_timeout = recv_timeout
        self._agg = AggQuoter(kyber_client_id)
        self._signer = None
        self._rpc_cache: dict[int, object] = {}

    def quote_buy(self, m: Market, notional_usd: float):
        """看价(只读):复用 P0 的 KyberSwap 报价。返回 DexQuote(eff/mid/base_out/slippage/gas)。"""
        return self._agg.quote_buy(m, notional_usd)

    # ---- live 基础设施(惰性)----
    def _get_signer(self):
        if self._signer is None:
            from .kms_signer import KmsSigner
            self._signer = KmsSigner(self.kms_key_id, expected_address=self.wallet_addr,
                                     region=self.kms_region)
        return self._signer

    def _get_rpc(self, chain_id: int):
        if chain_id not in self._rpc_cache:
            from .chain_rpc import ChainRpc
            self._rpc_cache[chain_id] = ChainRpc(self.rpc_url, chain_id, timeout=12)
        return self._rpc_cache[chain_id]

    def _send_tx(self, rpc, signer, wallet: str, to: str, value: int, data_hex: str,
                 gas_hint=None, nonce: int | None = None) -> str:
        """构造 EIP-1559 交易 → KMS 签名 → 广播,返回 tx hash(不等回执)。
        nonce 显式传入时用传入值(approve→swap 连续两笔须显式递增,防 pending 视图滞后冲突)。"""
        max_fee, prio = rpc.fees()
        est_tx = {"from": wallet, "to": to, "value": hex(value), "data": data_hex}
        try:
            gas = int(rpc.estimate_gas(est_tx) * 1.25)
        except Exception as e:  # noqa: BLE001 —— 估gas失败用 build 提示兜底
            gas = int((gas_hint or 800000) * 1.3)
            logger.warning("estimate_gas 失败(%s),用兜底 gas=%d", e, gas)
        tx = {
            "nonce": rpc.nonce(wallet) if nonce is None else nonce,
            "maxPriorityFeePerGas": prio,
            "maxFeePerGas": max_fee,
            "gas": gas,
            "to": to,
            "value": value,
            "data": bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex),
        }
        raw = signer.sign_transaction(tx, rpc.chain_id)
        return rpc.send_raw(raw.hex())

    def _ensure_allowance(self, rpc, signer, wallet: str, token: str, spender: str,
                          need: int, stable_decimals: int) -> int | None:
        """授权不足则授权一笔(有上限,非无限授权),等回执确认。
        返回 approve 后应使用的下一个 nonce(None=未发approve,调用方查pending)。"""
        from .chain_rpc import receipt_ok
        cur = rpc.erc20_allowance(token, wallet, spender)
        if cur >= need:
            return None
        cap = int(round(self.approve_cap_usd * (10 ** stable_decimals)))
        if need > cap:  # cap 是硬上限:需求超限即拒,绝不放大授权(防风控失效)
            raise RuntimeError(f"授权需求 {need} 超配置上限 {cap}(${self.approve_cap_usd}),拒绝执行")
        approve_amt = cap  # 一次授到上限,避免每笔都 approve;但有限额非无限
        data = rpc.erc20_approve_data(spender, approve_amt)
        approve_nonce = rpc.nonce(wallet)
        txh = self._send_tx(rpc, signer, wallet, to=token, value=0, data_hex=data, nonce=approve_nonce)
        rc = rpc.wait_receipt(txh, self.recv_timeout)
        if not receipt_ok(rc):
            raise RuntimeError(f"approve 交易失败 status!=1 tx={txh}")
        logger.info("approve 完成 token=%s spender=%s amt=%d tx=%s", token, spender, approve_amt, txh)
        # approve 已确认 → swap 用 confirmed_nonce(latest),避免 pending 滞后致两笔同 nonce
        return rpc.confirmed_nonce(wallet)

    def execute_buy(self, m: Market, notional_usd: float, quote) -> dict:
        """执行买入腿。
        dry-run/testnet:不上链,返回"假装买到 quote.base_out"(供协调器/埋点继续走流程)。
        live:稳定币→base 真 swap 上链,从【本笔回执 Transfer 事件】实测真实到账量(不用余额差,防同区块污染)。
        返回 {executed, mode, base_out, eff_price, gas_usd, tx_hash?}。
        """
        if self.mode != "live":
            return {"executed": False, "mode": self.mode,
                    "base_out": quote.base_out, "eff_price": quote.eff_price,
                    "gas_usd": quote.gas_usd, "tx_hash": None,
                    "note": "dry-run/testnet: 链上腿仅报价不上链"}
        # ---- live:真金不可逆,守卫齐全才执行 ----
        if not (self.kms_key_id and self.wallet_addr and self.rpc_url):
            raise RuntimeError("live 模式缺 KMS_KEY_ID / WALLET_ADDR / RPC,拒绝执行(防误触真金)")
        from .chain_rpc import receipt_ok
        ch = chain_of(m.chain)
        rpc = self._get_rpc(ch.chain_id)
        signer = self._get_signer()
        wallet = signer.address()  # 同时强制校验 == expected,不符即抛错
        amount_in = int(round(notional_usd * (10 ** ch.stable_decimals)))

        # ① 构造可上链 calldata(GET routes → POST build),minOut 滑点保护已编进 data
        rs = self._agg.route_raw(ch.kyber_slug, ch.stable, m.base_token, amount_in)
        build = self._agg.route_build(ch.kyber_slug, rs, sender=wallet, recipient=wallet,
                                      slippage_bps=self.slippage_bps)
        router = rpc.checksum(build["routerAddress"])
        calldata = build["data"]
        value = int(build.get("transactionValue", 0) or 0)

        # ② 授权(USDC → router),不足才授权;返回 approve 后应用的 nonce
        next_nonce = self._ensure_allowance(rpc, signer, wallet, rpc.checksum(ch.stable), router,
                                            amount_in, ch.stable_decimals)

        # ③ swap → 等回执 → 从本笔 Transfer 事件实测到账(只信本 tx,不用全局余额差)
        txh = self._send_tx(rpc, signer, wallet, to=router, value=value, data_hex=calldata,
                            gas_hint=build.get("gas"), nonce=next_nonce)
        rc = rpc.wait_receipt(txh, self.recv_timeout)
        if not receipt_ok(rc):
            raise RuntimeError(f"swap 交易失败 status!=1 tx={txh}")
        got_raw = rpc.transfer_in_from_logs(rc, m.base_token, wallet)
        if got_raw <= 0:
            raise RuntimeError(f"swap 成交但回执无转入 base 的 Transfer 事件 tx={txh}")
        base_out = got_raw / (10 ** m.base_decimals)
        # 与报价偏离过大(>3%)→ 可能小数位配错/路由异常,拒绝(防错量去做空致裸腿)
        if quote.base_out > 0 and abs(base_out - quote.base_out) / quote.base_out > 0.03:
            raise RuntimeError(f"实测到账 {base_out:.8f} 与报价 {quote.base_out:.8f} 偏离>3%,拒绝(疑小数位/路由异常)tx={txh}")
        eff_price = notional_usd / base_out
        logger.info("买入成交 %s base_out=%.8f eff=%.6f tx=%s", m.key, base_out, eff_price, txh)
        return {"executed": True, "mode": "live", "base_out": base_out, "eff_price": eff_price,
                "gas_usd": quote.gas_usd, "tx_hash": txh}

    def sell_back(self, m: Market, base_qty: float) -> dict:
        """回滚:链上把刚买的 base 卖回稳定币(币安做空失败时止损用)。dry-run 不上链。"""
        if self.mode != "live":
            return {"executed": False, "mode": self.mode, "note": "dry-run: 不实际卖回"}
        if not (self.kms_key_id and self.wallet_addr and self.rpc_url):
            raise RuntimeError("live 卖回缺 KMS/钱包/RPC,拒绝执行")
        from .chain_rpc import receipt_ok
        ch = chain_of(m.chain)
        rpc = self._get_rpc(ch.chain_id)
        signer = self._get_signer()
        wallet = signer.address()
        amount_in = int(round(base_qty * (10 ** m.base_decimals)))
        rs = self._agg.route_raw(ch.kyber_slug, m.base_token, ch.stable, amount_in)
        build = self._agg.route_build(ch.kyber_slug, rs, sender=wallet, recipient=wallet,
                                      slippage_bps=self.slippage_bps)
        router = rpc.checksum(build["routerAddress"])
        next_nonce = self._ensure_allowance(rpc, signer, wallet, m.base_token, router, amount_in, m.base_decimals)
        txh = self._send_tx(rpc, signer, wallet, to=router, value=int(build.get("transactionValue", 0) or 0),
                            data_hex=build["data"], gas_hint=build.get("gas"), nonce=next_nonce)
        rc = rpc.wait_receipt(txh, self.recv_timeout)
        if not receipt_ok(rc):
            raise RuntimeError(f"卖回交易失败 status!=1 tx={txh}")
        usdc_raw = rpc.transfer_in_from_logs(rc, ch.stable, wallet)
        usdc_out = usdc_raw / (10 ** ch.stable_decimals)
        logger.info("卖回成交 %s usdc_out=%.4f tx=%s", m.key, usdc_out, txh)
        return {"executed": True, "mode": "live", "usdc_out": usdc_out, "tx_hash": txh}
