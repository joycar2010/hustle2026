"""
统一的平台标识枚举 (single source of truth for platform_id).

业务代码必须使用 PlatformId.BINANCE / PlatformId.BYBIT 等枚举成员,
严禁写裸字符串 "binance" / "bybit" / "mt5" 或裸整数 1 / 2 / 3.

DB 层面:
  - accounts.platform_id / positions.platform_id 存 smallint (1/2/3/4),对应 PlatformId.BINANCE/BYBIT/IC_MARKETS/GATE
  - orders.platform / platforms.platform_name 存 varchar ("binance" 等小写字符串),对应 PlatformId.*.key
API 层面:
  - req.exchange 等外部字段保持字符串 "binance" 作为公共契约,入口用 PlatformId.from_key 归一化到枚举
"""
from enum import IntEnum
from typing import Optional, Union


class PlatformId(IntEnum):
    BINANCE = 1
    BYBIT = 2
    IC_MARKETS = 3
    GATE = 4
    OKX = 5
    BITGET = 6

    @property
    def key(self) -> str:
        """canonical lowercase string — 用于与 orders.platform / platforms.platform_name 等字符串列比较"""
        return _ID_TO_KEY[int(self)]

    @classmethod
    def from_key(cls, value: Union[str, int, "PlatformId", None]) -> Optional["PlatformId"]:
        """把任意外部输入(字符串名、整数 id、已有枚举)归一化为 PlatformId,失败返回 None."""
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError:
                return None
        # try numeric string like "1" first
        s = str(value).strip().lower()
        if not s:
            return None
        if s.isdigit():
            try:
                return cls(int(s))
            except ValueError:
                return None
        return _KEY_TO_ID.get(s)


_ID_TO_KEY = {
    1: "binance",
    2: "bybit",
    3: "ic_markets",
    4: "gate",
    5: "okx",
    6: "bitget",
}
# 所有已知别名 → 规范枚举值。覆盖历史数据里可能出现的变体
_KEY_TO_ID = {
    "binance": PlatformId.BINANCE,
    "bybit": PlatformId.BYBIT,
    "mt5": PlatformId.BYBIT,            # 历史 "mt5" 字符串 = Bybit-linked MT5 账户
    "ic_markets": PlatformId.IC_MARKETS,
    "icmarkets": PlatformId.IC_MARKETS,
    "ic": PlatformId.IC_MARKETS,
    "gate": PlatformId.GATE,
    "gate_io": PlatformId.GATE,
    "gateio": PlatformId.GATE,
    "okx": PlatformId.OKX,
    "bitget": PlatformId.BITGET,
    "bg": PlatformId.BITGET,
}

# 常用跨平台集合
HEDGE_SIDE_IDS = frozenset({PlatformId.BYBIT.value, PlatformId.IC_MARKETS.value})  # 对冲端:Bybit + IC Markets
ALL_MT5_CAPABLE_IDS = frozenset({PlatformId.BYBIT.value, PlatformId.IC_MARKETS.value})
