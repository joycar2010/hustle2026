"""链配置(一等维度)。报价统一走 KyberSwap(按链 slug 自动路由各链 DEX),
   故每链只需:slug + 计价稳定币(地址/精度)。gas 用 KyberSwap 路由自带的 gasUsd(按链真实)。
   做空腿恒为币安永续,链无关。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chain:
    name: str            # 市场 key 前缀:BASE/ETH/BSC/ARB
    chain_id: int
    kyber_slug: str      # KyberSwap 路径段
    stable: str          # 计价稳定币地址
    stable_decimals: int
    min_liquidity_usd: float = 0.0   # spec 每链最小流动性门槛(展示/参考用)
    target_notional_usd: float = 2500.0  # spec 实际交易规模(2000-3000)
    recycle_bps: float = 1.5  # 资金回收(链上现货搬回币安:提现/桥费)摊到名义额的成本,按链


# spec 5.2 流动性阈值与交易规模:ETH>$5M / BSC>$3M / ARB>$2M / BASE>$1M,单笔 $2000-3000
# recycle_bps:按 $2500 名义、单次回收成本估算(ETH主网提现贵≈12bps,L2≈1.2bps)
CHAINS = {
    "BASE": Chain("BASE", 8453,  "base",     "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6,  1_000_000, 2500, 1.2),
    "ETH":  Chain("ETH",  1,     "ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6,  5_000_000, 2500, 12.0),
    "BSC":  Chain("BSC",  56,    "bsc",      "0x55d398326f99059fF775485246999027B3197955", 18, 3_000_000, 2500, 2.0),
    "ARB":  Chain("ARB",  42161, "arbitrum", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6,  2_000_000, 2500, 1.2),
    # 第二批(实测 KyberSwap✅ + 币安永续✅ + 深池 + 低gas)
    "OP":   Chain("OP",   10,    "optimism", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6,  2_000_000, 2500, 1.2),  # USDC原生
    "AVAX": Chain("AVAX", 43114, "avalanche","0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E", 6,  2_000_000, 2500, 2.0),  # USDC原生
    "POLY": Chain("POLY", 137,   "polygon",  "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6,  2_000_000, 2500, 1.6),  # USDC原生
    "SONIC":Chain("SONIC",146,   "sonic",    "0x29219dd400f2Bf60E5a23d13Be72B486D4038894", 6,  1_000_000, 2500, 2.0),  # USDC.e(探索位)
}


def chain_of(name: str) -> Chain:
    return CHAINS.get(name, CHAINS["BASE"])
