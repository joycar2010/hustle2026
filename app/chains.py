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


CHAINS = {
    "BASE": Chain("BASE", 8453,  "base",     "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),   # USDC
    "ETH":  Chain("ETH",  1,     "ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),   # USDC
    "BSC":  Chain("BSC",  56,    "bsc",      "0x55d398326f99059fF775485246999027B3197955", 18),  # USDT(BSC 18位)
    "ARB":  Chain("ARB",  42161, "arbitrum", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),   # USDC(Arb 原生)
}


def chain_of(name: str) -> Chain:
    return CHAINS.get(name, CHAINS["BASE"])
