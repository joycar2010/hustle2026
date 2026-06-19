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
    fee_tier: int          # Uniswap V3 费档:100/500/3000/10000
    binance_symbol: str    # 做空腿币安 USDT 永续
    pool: str = ""         # 已知池地址(省一次 getPool;留空则运行时 factory 解析)
    quote_token: str = USDC
    quote_decimals: int = USDC_DECIMALS
    notional_usd: float | None = None  # 该市场名义额;None=用全局默认


# —— 链上实测核实(2026-06,Base mainnet)——
DEFAULT_MARKETS = [
    Market("BASE:ETH",     "0x4200000000000000000000000000000000000006", 18, 500,  "ETHUSDT",
           pool="0xd0b53D9277642d899DF5C87A3966A349A798F224"),
    Market("BASE:BTC",     "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",  8, 500,  "BTCUSDT",
           pool="0xfBB6Eed8e7aa03B138556eeDaF5D271A5E1e43ef"),
    Market("BASE:VIRTUAL", "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b", 18, 3000, "VIRTUALUSDT",
           pool="0x529d2863a1521d0b57db028168fdE2E97120017C"),
]


def load_markets() -> list[Market]:
    """优先读同目录 markets.json,否则用实测默认集。"""
    path = Path(__file__).resolve().parent.parent / "markets.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Market(**m) for m in raw]
    return DEFAULT_MARKETS
