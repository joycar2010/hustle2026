"""市场定义(标的 × 池 × 币安合约)。

每个 Market = 在某 DEX 池用 USDC 买入 base_token(做多现货)+ 在币安做空 binance_symbol。
默认集为【链上实测核实】过的 Base 市场(probe_markets.py 验证 symbol/decimals/池/报价)。
可用同目录 markets.json 覆盖(数组,字段同 Market),便于影子阶段加标的而不改代码。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_DECIMALS = 6


@dataclass(frozen=True)
class Market:
    key: str               # 显示/索引键,如 "BASE:ETH"
    base_token: str        # 要买入的代币地址
    base_decimals: int
    fee_tier: int          # Uniswap V3 费档:100/500/3000/10000(source=agg 时忽略,填0)
    binance_symbol: str    # 做空腿币安 USDT 永续
    pool: str = ""         # 已知池地址(省一次 getPool;留空则运行时 factory 解析)
    quote_token: str = USDC
    quote_decimals: int = USDC_DECIMALS
    notional_usd: float | None = None  # 该市场名义额;None=用全局默认
    source: str = "univ3"  # 买入腿价源:"univ3"(直连深池)| "agg"(KyberSwap聚合,跨源多跳)
    chain: str = "BASE"    # 所在链:BASE/ETH/BSC/ARB(决定 agg 的 slug 与计价稳定币)


# —— 链上实测核实(2026-06,Base mainnet)——
DEFAULT_MARKETS = [
    Market("BASE:ETH",     "0x4200000000000000000000000000000000000006", 18, 500,  "ETHUSDT",
           pool="0xd0b53D9277642d899DF5C87A3966A349A798F224"),
    Market("BASE:BTC",     "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",  8, 500,  "BTCUSDT",
           pool="0xfBB6Eed8e7aa03B138556eeDaF5D271A5E1e43ef"),
    Market("BASE:VIRTUAL", "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b", 18, 0, "VIRTUALUSDT", source="agg"),
    Market("BASE:AERO",    "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18, 0, "AEROUSDT",    source="agg"),
    # —— 以下走 KyberSwap 聚合器(深流动性在 Slipstream CL/经WETH,经发现脚本验证 $2500 深度 ratio≈1.01)——
    # notional 按池深度定:深的用 $2500,浅的缩小到滑点可控档(发现脚本实测)
    Market("BASE:BRETT",   "0x532f27101965dd16442E59d40670FaF5eBB142E4", 18, 0, "BRETTUSDT",   source="agg"),
    Market("BASE:ZORA",    "0x1111111111166b7FE7bd91427724B487980aFc69", 18, 0, "ZORAUSDT",    source="agg"),
    Market("BASE:TOSHI",   "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4", 18, 0, "TOSHIUSDT",   source="agg"),
    Market("BASE:MORPHO",  "0xBAa5CC21fd487B8Fcc2F632f3f4E8D37262a0842", 18, 0, "MORPHOUSDT",  source="agg"),
    Market("BASE:AIXBT",   "0x4F9Fd6Be4a90f2620860d680c0d4d5Fb53d1A825", 18, 0, "AIXBTUSDT",   source="agg", notional_usd=1000),
    Market("BASE:ZRO",     "0x6985884C4392D348587B19cb9eAAf157F13271cd", 18, 0, "ZROUSDT",     source="agg", notional_usd=1000),
    Market("BASE:KAITO",   "0x98d0baa52b2D063E780DE12F615f963Fe8537553", 18, 0, "KAITOUSDT",   source="agg", notional_usd=500),

    # —— Ethereum 主网(USDC 计价;深但 gas 随主网波动,KyberSwap 路由 gasUsd 实时反映)——
    Market("ETH:ETH",  "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18, 0, "ETHUSDT",  source="agg", chain="ETH"),
    Market("ETH:BTC",  "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8,  0, "BTCUSDT",  source="agg", chain="ETH"),
    Market("ETH:LINK", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18, 0, "LINKUSDT", source="agg", chain="ETH"),
    Market("ETH:UNI",  "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18, 0, "UNIUSDT",  source="agg", chain="ETH"),

    # —— BSC(USDT 计价)——
    Market("BSC:BNB",  "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", 18, 0, "BNBUSDT",  source="agg", chain="BSC"),
    Market("BSC:CAKE", "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", 18, 0, "CAKEUSDT", source="agg", chain="BSC"),

    # —— Arbitrum(USDC 计价;L2 gas 极低)——
    Market("ARB:ARB",  "0x912CE59144191C1204E64559FE8253a0e49E6548", 18, 0, "ARBUSDT",  source="agg", chain="ARB"),
    Market("ARB:ETH",  "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", 18, 0, "ETHUSDT",  source="agg", chain="ARB"),
    Market("ARB:BTC",  "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f", 8,  0, "BTCUSDT",  source="agg", chain="ARB"),
    Market("ARB:GMX",  "0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a", 18, 0, "GMXUSDT",  source="agg", chain="ARB"),
    Market("ARB:LINK", "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4", 18, 0, "LINKUSDT", source="agg", chain="ARB"),
]


def load_markets() -> list[Market]:
    """优先读同目录 markets.json,否则用实测默认集。"""
    path = Path(__file__).resolve().parent.parent / "markets.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Market(**m) for m in raw]
    return DEFAULT_MARKETS
