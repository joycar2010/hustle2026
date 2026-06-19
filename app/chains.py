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


# spec 5.2 流动性阈值与交易规模:ETH>$5M / BSC>$3M / ARB>$2M / BASE>$1M,单笔 $2000-3000
CHAINS = {
    "BASE": Chain("BASE", 8453,  "base",     "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6,  1_000_000, 2500),
    "ETH":  Chain("ETH",  1,     "ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6,  5_000_000, 2500),
    "BSC":  Chain("BSC",  56,    "bsc",      "0x55d398326f99059fF775485246999027B3197955", 18, 3_000_000, 2500),
    "ARB":  Chain("ARB",  42161, "arbitrum", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6,  2_000_000, 2500),
}


def chain_of(name: str) -> Chain:
    return CHAINS.get(name, CHAINS["BASE"])
