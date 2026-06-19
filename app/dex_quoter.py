"""DEX 报价(Base / Uniswap V3,任意 base/quote 标的)—— 只读,绝不发交易。

主价源:QuoterV2.quoteExactInputSingle 经 eth_call 静态调用,返回买入 `notional`
美元能拿到的真实 base 数量(已含池费 + 价格冲击/滑点)。
交叉校验:slot0() sqrtPriceX96 给中间价(按 token0/token1 与 decimals 通用换算)。
另:gas_price(L2)、l1_fee_wei(GasPriceOracle 实时 L1)、eth_usd(WETH/USDC 参考价,统一折 gas)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from web3 import Web3

from .constants import (
    FACTORY,
    FACTORY_ABI,
    GAS_ORACLE,
    GAS_ORACLE_ABI,
    POOL_ABI,
    Q96,
    QUOTER_V2,
    QUOTER_V2_ABI,
    SWAP_TX_SAMPLE,
    USDC,
    USDC_DECIMALS,
    WETH,
    WETH_DECIMALS,
    WETH_USDC_REF_POOL,
)
from .markets import Market


@dataclass
class DexQuote:
    eff_price: float          # 有效成交价 quote/base(含费+滑点)
    mid_price: float          # 池中间价 quote/base(slot0)
    base_out: float           # notional 美元买到的 base 数量
    slippage_bps: float       # (eff - mid)/mid,正数=买贵了(含池费)
    pool: str


def _retry(fn, tries: int = 4, delay: float = 0.8):
    """平滑公共 RPC 的瞬时 429/超时(递增退避);Alchemy 端点基本用不到。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(delay * (i + 1))
    raise last


class Quoter:
    def __init__(self, rpc_url: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 12}))
        self.quoter = self.w3.eth.contract(address=Web3.to_checksum_address(QUOTER_V2), abi=QUOTER_V2_ABI)
        self.factory = self.w3.eth.contract(address=Web3.to_checksum_address(FACTORY), abi=FACTORY_ABI)
        self.gas_oracle = self.w3.eth.contract(address=Web3.to_checksum_address(GAS_ORACLE), abi=GAS_ORACLE_ABI)
        self._pool_cache: dict[str, str] = {}      # market.key -> pool addr
        self._token0_cache: dict[str, str] = {}    # pool addr -> token0 addr
        self._pool_obj: dict[str, object] = {}

    # ---- 基础 ----
    def connected(self) -> bool:
        return self.w3.is_connected()

    def block_number(self) -> int:
        return self.w3.eth.block_number

    def gas_price_wei(self) -> int:
        return _retry(lambda: self.w3.eth.gas_price)

    def l1_fee_wei(self) -> int:
        """一次 swap 的实时 L1 data 费(wei),来自 OP-Stack GasPriceOracle。"""
        return _retry(lambda: self.gas_oracle.functions.getL1Fee(SWAP_TX_SAMPLE).call())

    def eth_usd_price(self) -> float:
        """ETH/USD 参考价(WETH/USDC 0.05% 池中间价),统一用于把 gas(ETH)折 USD。"""
        return _retry(lambda: self._read_mid(
            Web3.to_checksum_address(WETH_USDC_REF_POOL),
            Web3.to_checksum_address(WETH), WETH_DECIMALS, USDC_DECIMALS,
        ))

    # ---- 池与中间价 ----
    def _pool_contract(self, pool_addr: str):
        if pool_addr not in self._pool_obj:
            self._pool_obj[pool_addr] = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_addr), abi=POOL_ABI)
        return self._pool_obj[pool_addr]

    def _token0(self, pool_addr: str) -> str:
        if pool_addr not in self._token0_cache:
            t0 = self._pool_contract(pool_addr).functions.token0().call()
            self._token0_cache[pool_addr] = Web3.to_checksum_address(t0)
        return self._token0_cache[pool_addr]

    def _read_mid(self, pool_addr: str, base_addr: str, base_dec: int, quote_dec: int) -> float:
        """通用中间价 quote/base。

        raw = (sqrtP/2^96)^2 = token1_raw/token0_raw。
        若 token0==base:mid = raw * 10^(base_dec-quote_dec)
        否则(token0==quote):mid = (1/raw) * 10^(base_dec-quote_dec)
        两式指数同为 (base_dec-quote_dec),仅 raw 取正/倒。
        """
        pool = self._pool_contract(pool_addr)
        sqrt_p = pool.functions.slot0().call()[0] / Q96
        raw = sqrt_p * sqrt_p
        scale = 10 ** (base_dec - quote_dec)
        token0 = self._token0(pool_addr)
        if token0 == Web3.to_checksum_address(base_addr):
            return raw * scale
        return (1.0 / raw) * scale if raw > 0 else 0.0

    def _resolve_pool(self, m: Market) -> str:
        if m.key in self._pool_cache:
            return self._pool_cache[m.key]
        if m.pool:
            addr = Web3.to_checksum_address(m.pool)
        else:
            base = Web3.to_checksum_address(m.base_token)
            quote = Web3.to_checksum_address(m.quote_token)
            got = _retry(lambda: self.factory.functions.getPool(base, quote, m.fee_tier).call())
            if int(got, 16) == 0:
                raise RuntimeError(f"{m.key}: {m.base_token}/{m.quote_token} fee={m.fee_tier} 池不存在")
            addr = Web3.to_checksum_address(got)
        self._pool_cache[m.key] = addr
        return addr

    def prewarm(self, markets) -> None:
        """单线程预解析池地址 + token0,避免线程池冷启动并发重复 RPC(加剧 429)。"""
        for m in markets:
            try:
                pool = self._resolve_pool(m)
                self._token0(pool)
            except Exception:  # noqa: BLE001
                pass  # 起循环后 quote_buy 仍会重试
        try:
            self._token0(Web3.to_checksum_address(WETH_USDC_REF_POOL))
        except Exception:  # noqa: BLE001
            pass

    # ---- 报价 ----
    def quote_buy(self, m: Market, notional_usd: float) -> DexQuote:
        """用 notional_usd 的 quote(USDC)买 base,返回真实可成交价。"""
        amount_in = int(round(notional_usd * (10 ** m.quote_decimals)))
        base = Web3.to_checksum_address(m.base_token)
        quote = Web3.to_checksum_address(m.quote_token)
        out = _retry(lambda: self.quoter.functions.quoteExactInputSingle(
            (quote, base, amount_in, m.fee_tier, 0)).call())
        base_out_wei = out[0]
        if base_out_wei <= 0:
            raise RuntimeError(f"{m.key}: quoter 返回 0,池无流动性")
        base_out = base_out_wei / (10 ** m.base_decimals)
        eff_price = notional_usd / base_out  # quote per base(含费+滑点)
        pool = self._resolve_pool(m)
        mid = self._read_mid(pool, m.base_token, m.base_decimals, m.quote_decimals)
        slippage_bps = (eff_price - mid) / mid * 1e4 if mid > 0 else 0.0
        return DexQuote(eff_price=eff_price, mid_price=mid, base_out=base_out,
                        slippage_bps=slippage_bps, pool=pool)
