"""
Intent/Saga 工厂 - Intent 类型定义
关4 攻关: Phase A 基础类型
"""
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from enum import Enum
import time
import uuid


class IntentType(Enum):
    """Intent 类型枚举"""
    OPEN_PAIR = "OPEN_PAIR"
    CLOSE_PAIR = "CLOSE_PAIR"
    REBALANCE = "REBALANCE"
    EVACUATE = "EVACUATE"


@dataclass
class Intent:
    """Intent 基类"""
    intent_id: str
    intent_type: IntentType
    created_at: int  # Unix timestamp
    reason: str = ""

    @classmethod
    def generate_id(cls) -> str:
        """生成唯一 Intent ID"""
        return f"intent-{uuid.uuid4().hex[:12]}-{int(time.time())}"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        d = asdict(self)
        d["intent_type"] = self.intent_type.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Intent":
        """从字典反序列化(基类方法,子类覆盖)"""
        raise NotImplementedError("Use concrete intent classes")


@dataclass
class OpenPairIntent(Intent):
    """开仓意图"""
    pair_id: str = ""
    symbol: str = ""
    venue_long: str = ""   # 做多腿 venue
    venue_short: str = ""  # 做空腿 venue
    target_notional_usdt: float = 0.0

    def __post_init__(self):
        if not self.intent_id:
            self.intent_id = Intent.generate_id()
        if not self.created_at:
            self.created_at = int(time.time())
        self.intent_type = IntentType.OPEN_PAIR

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OpenPairIntent":
        return cls(
            intent_id=d.get("intent_id", ""),
            intent_type=IntentType.OPEN_PAIR,
            created_at=d.get("created_at", 0),
            reason=d.get("reason", ""),
            pair_id=d.get("pair_id", ""),
            symbol=d.get("symbol", ""),
            venue_long=d.get("venue_long", ""),
            venue_short=d.get("venue_short", ""),
            target_notional_usdt=d.get("target_notional_usdt", 0.0),
        )


@dataclass
class ClosePairIntent(Intent):
    """平仓意图"""
    pair_id: str = ""
    symbol: str = ""
    venue_long: str = ""
    venue_short: str = ""

    def __post_init__(self):
        if not self.intent_id:
            self.intent_id = Intent.generate_id()
        if not self.created_at:
            self.created_at = int(time.time())
        self.intent_type = IntentType.CLOSE_PAIR

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ClosePairIntent":
        return cls(
            intent_id=d.get("intent_id", ""),
            intent_type=IntentType.CLOSE_PAIR,
            created_at=d.get("created_at", 0),
            reason=d.get("reason", ""),
            pair_id=d.get("pair_id", ""),
            symbol=d.get("symbol", ""),
            venue_long=d.get("venue_long", ""),
            venue_short=d.get("venue_short", ""),
        )


@dataclass
class RebalanceIntent(Intent):
    """再平衡意图(调整仓位大小)"""
    pair_id: str = ""
    symbol: str = ""
    venue_long: str = ""
    venue_short: str = ""
    target_notional_usdt: float = 0.0
    current_notional_usdt: float = 0.0

    def __post_init__(self):
        if not self.intent_id:
            self.intent_id = Intent.generate_id()
        if not self.created_at:
            self.created_at = int(time.time())
        self.intent_type = IntentType.REBALANCE

    @property
    def delta_notional(self) -> float:
        """计算需要调整的名义金额"""
        return self.target_notional_usdt - self.current_notional_usdt

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RebalanceIntent":
        return cls(
            intent_id=d.get("intent_id", ""),
            intent_type=IntentType.REBALANCE,
            created_at=d.get("created_at", 0),
            reason=d.get("reason", ""),
            pair_id=d.get("pair_id", ""),
            symbol=d.get("symbol", ""),
            venue_long=d.get("venue_long", ""),
            venue_short=d.get("venue_short", ""),
            target_notional_usdt=d.get("target_notional_usdt", 0.0),
            current_notional_usdt=d.get("current_notional_usdt", 0.0),
        )


@dataclass
class EvacuateIntent(Intent):
    """撤离意图(风险撤退,强平所有仓位)"""
    venue: str = ""  # 撤离的 venue
    symbols: list = None  # 要撤离的币对列表,None=全部

    def __post_init__(self):
        if not self.intent_id:
            self.intent_id = Intent.generate_id()
        if not self.created_at:
            self.created_at = int(time.time())
        self.intent_type = IntentType.EVACUATE
        if self.symbols is None:
            self.symbols = []

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvacuateIntent":
        return cls(
            intent_id=d.get("intent_id", ""),
            intent_type=IntentType.EVACUATE,
            created_at=d.get("created_at", 0),
            reason=d.get("reason", ""),
            venue=d.get("venue", ""),
            symbols=d.get("symbols", []),
        )


# 工厂函数:从字典创建正确的 Intent 子类
def intent_from_dict(d: Dict[str, Any]) -> Intent:
    """从字典创建 Intent 对象(自动识别类型)"""
    intent_type = d.get("intent_type", "")
    if intent_type == IntentType.OPEN_PAIR.value:
        return OpenPairIntent.from_dict(d)
    elif intent_type == IntentType.CLOSE_PAIR.value:
        return ClosePairIntent.from_dict(d)
    elif intent_type == IntentType.REBALANCE.value:
        return RebalanceIntent.from_dict(d)
    elif intent_type == IntentType.EVACUATE.value:
        return EvacuateIntent.from_dict(d)
    else:
        raise ValueError(f"Unknown intent_type: {intent_type}")
