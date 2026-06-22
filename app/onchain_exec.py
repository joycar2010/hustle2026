"""链上 DEX 买入腿执行 —— 安全分档,默认绝不签名/发送。

dry-run / testnet:只走 KyberSwap 报价(HTTP,与 P0 只读一致),返回"会买到多少"。绝不构造交易、绝不签名、绝不上链。
live(仅当 mode=live + KMS 配齐):routes→/route/build 构造 calldata→KMS 签名→广播→等回执。
  ——KMS 签名为不可逆真金动作,未配齐 KMS 时显式抛错,绝不静默执行。
"""
from __future__ import annotations

import logging

from .agg_quoter import AggQuoter
from .chains import chain_of
from .markets import Market

logger = logging.getLogger(__name__)


class OnchainExec:
    def __init__(self, mode: str = "dry-run", wallet_addr: str = "", kms_key_id: str = "",
                 kyber_client_id: str = "crossarb"):
        self.mode = mode
        self.wallet_addr = wallet_addr
        self.kms_key_id = kms_key_id
        self._agg = AggQuoter(kyber_client_id)

    def quote_buy(self, m: Market, notional_usd: float):
        """看价(只读):复用 P0 的 KyberSwap 报价。返回 DexQuote(eff/mid/base_out/slippage/gas)。"""
        return self._agg.quote_buy(m, notional_usd)

    def execute_buy(self, m: Market, notional_usd: float, quote) -> dict:
        """执行买入腿。
        dry-run/testnet:不上链,返回"假装买到 quote.base_out"(供协调器/埋点继续走流程)。
        live:真签名上链(需 KMS + wallet)。
        返回 {executed, mode, base_out, eff_price, gas_usd, tx_hash?}。
        """
        if self.mode != "live":
            return {"executed": False, "mode": self.mode,
                    "base_out": quote.base_out, "eff_price": quote.eff_price,
                    "gas_usd": quote.gas_usd, "tx_hash": None,
                    "note": "dry-run/testnet: 链上腿仅报价不上链"}
        # ---- live:真金不可逆,守卫齐全才执行 ----
        if not (self.kms_key_id and self.wallet_addr):
            raise RuntimeError("live 模式缺 KMS_KEY_ID / WALLET_ADDR,拒绝执行(防误触真金)")
        # 真实路径(待 KMS 接好后启用):
        #   1) ch=chain_of(m.chain); POST /{slug}/api/v1/route/build {routeSummary, sender, recipient, slippageTolerance}
        #   2) 取 data/routerAddress → 构造 EIP-1559 交易(approve 一次性 + swap)
        #   3) KMS 签名(secp256k1)→ eth_sendRawTransaction → 轮询 receipt → 解析实际 amountOut
        raise NotImplementedError("live 链上执行待 KMS 接入后启用(当前仅 dry-run/testnet)")

    def sell_back(self, m: Market, base_qty: float) -> dict:
        """回滚:链上把刚买的 base 卖回稳定币(币安做空失败时止损用)。dry-run 不上链。"""
        if self.mode != "live":
            return {"executed": False, "mode": self.mode, "note": "dry-run: 不实际卖回"}
        raise NotImplementedError("live 卖回待 KMS 接入后启用")
