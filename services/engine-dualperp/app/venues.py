"""ExchangeClient 抽象接口:执行面 venue 适配器的统一契约。

coin 没有这层抽象(binance_trading.py 是单所具体类,URL/错误码散布调用点,反面教材)——
五所+HL 适配器必须先有接口再有实现。本文件 v1 只定义契约与错误分类;
签名实现等 API key 到位后逐所补(canary 真金小额验证纪律),写盲签名=攒未验证的雷。

错误分类是接口的一部分:每所的原生错误码→统一 ErrClass,重试/自愈策略按类而非按所写
(coin -3045/-2015 分类自愈经验的推广)。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ErrClass(Enum):
    OK = "ok"
    RATE_LIMIT = "rate_limit"          # 退避重试
    INSUFFICIENT = "insufficient"      # 资金/保证金不足:停开仓,告警
    INVALID_SYMBOL = "invalid_symbol"  # 下架/停牌:剔宇宙,告警
    REJECTED = "rejected"              # 交易所拒单(参数/状态):不重试,人工
    TIMEOUT_UNKNOWN = "timeout_unknown"  # 超时未知结果:必须实盘对账,绝不采信(testgo 铁律)
    AUTH = "auth"                      # 鉴权失效:熔断该 venue,fatal 告警
    OTHER = "other"


@dataclass
class OrderResult:
    ok: bool
    err_class: ErrClass
    order_id: str = ""
    filled_qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    raw: str = ""


class ExchangeClient(ABC):
    """每所一个实现;实例绑定 (venue, market, account) 组合——限频预算与密钥按此隔离。"""

    venue: str
    market: str
    account: str
    armed: bool = False  # 无 key = 永不武装;armed=False 时任何下单调用直接抛

    @abstractmethod
    async def place_limit(self, symbol: str, side: str, qty: Decimal,
                          price: Decimal, reduce_only: bool = False) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> OrderResult: ...

    @abstractmethod
    async def fetch_order(self, symbol: str, order_id: str) -> OrderResult:
        """实盘核对单据——HTTP 200 ≠ 成交,状态只信这里(testgo Phase2 铁律)。"""

    @abstractmethod
    async def fetch_position(self, symbol: str) -> Decimal:
        """净持仓(base,带方向)。体外对账的实盘真相源。"""

    @abstractmethod
    async def fetch_balance(self) -> dict: ...


class NotArmedError(RuntimeError):
    """未配置 API key 的客户端被调用下单——shadow 模式的硬护栏,永不静默吞。"""
