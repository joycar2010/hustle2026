"""
Intent/Saga 工厂 - Planner 层
关4 攻关: Phase B Planner 核心
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import time

from intent import Intent, OpenPairIntent, ClosePairIntent, RebalanceIntent, EvacuateIntent


@dataclass
class SagaPlan:
    """Saga 执行计划"""
    saga_id: str
    intent_id: str
    legs: List[Dict[str, Any]]  # 腿序列
    rollback_strategy: str = "FIFO"  # FIFO(先开先平), LIFO(后开先平), PARALLEL(并行平)
    risk_policy: Optional[str] = None  # G1 风险策略引用
    created_at: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = int(time.time())


class IntentPlanner:
    """Intent → Saga Plan 编排器"""

    def __init__(self, min_order_usdt: float = 5.0):
        """
        Args:
            min_order_usdt: 最小订单金额(USDT),低于此值不生成 leg
        """
        self.min_order_usdt = min_order_usdt

    def plan(self, intent: Intent) -> SagaPlan:
        """
        核心方法: Intent → SagaPlan
        根据 Intent 类型分发到具体 planner
        """
        if isinstance(intent, OpenPairIntent):
            return self._plan_open_pair(intent)
        elif isinstance(intent, ClosePairIntent):
            return self._plan_close_pair(intent)
        elif isinstance(intent, RebalanceIntent):
            return self._plan_rebalance(intent)
        elif isinstance(intent, EvacuateIntent):
            return self._plan_evacuate(intent)
        else:
            raise ValueError(f"Unknown intent type: {type(intent)}")

    def _plan_open_pair(self, intent: OpenPairIntent) -> SagaPlan:
        """
        开仓 Planner:
        - 生成两腿: BUY long venue, SELL short venue
        - Saga ID: open-{pair_id}-{timestamp}
        """
        saga_id = f"open-{intent.pair_id}-{int(time.time())}"

        # 计算每腿数量(假设合约面值=1,实际需要从市场数据获取)
        # 这里简化处理,实际应该查询 mark price
        target_qty = intent.target_notional_usdt  # 简化: qty = notional

        legs = [
            {
                "venue": intent.venue_long,
                "symbol": intent.symbol,
                "side": "BUY",
                "market": "perp",
                "qty": target_qty,
                "reduce_only": False,
            },
            {
                "venue": intent.venue_short,
                "symbol": intent.symbol,
                "side": "SELL",
                "market": "perp",
                "qty": target_qty,
                "reduce_only": False,
            },
        ]

        return SagaPlan(
            saga_id=saga_id,
            intent_id=intent.intent_id,
            legs=legs,
            rollback_strategy="FIFO",
        )

    def _plan_close_pair(self, intent: ClosePairIntent) -> SagaPlan:
        """
        平仓 Planner:
        - 生成两腿 reduce-only: SELL long venue, BUY short venue
        - Saga ID: close-{pair_id}-{timestamp}
        """
        saga_id = f"close-{intent.pair_id}-{int(time.time())}"

        # 平仓时 qty 从当前持仓获取(这里简化,实际需要查询账户)
        # Manager 调用时会传入 current positions
        legs = [
            {
                "venue": intent.venue_long,
                "symbol": intent.symbol,
                "side": "SELL",
                "market": "perp",
                "qty": 0,  # 将由 Manager 填充实际持仓
                "reduce_only": True,
            },
            {
                "venue": intent.venue_short,
                "symbol": intent.symbol,
                "side": "BUY",
                "market": "perp",
                "qty": 0,  # 将由 Manager 填充实际持仓
                "reduce_only": True,
            },
        ]

        return SagaPlan(
            saga_id=saga_id,
            intent_id=intent.intent_id,
            legs=legs,
            rollback_strategy="PARALLEL",  # 平仓并行更快
        )

    def _plan_rebalance(self, intent: RebalanceIntent) -> SagaPlan:
        """
        再平衡 Planner:
        - delta > 0: 加仓(BUY long, SELL short)
        - delta < 0: 减仓(SELL long, BUY short)
        - Saga ID: rebal-{pair_id}-{timestamp}
        """
        saga_id = f"rebal-{intent.pair_id}-{int(time.time())}"
        delta = intent.delta_notional

        if abs(delta) < self.min_order_usdt:
            # delta 太小,不生成 leg
            return SagaPlan(
                saga_id=saga_id,
                intent_id=intent.intent_id,
                legs=[],
                rollback_strategy="FIFO",
            )

        if delta > 0:
            # 加仓
            side_long = "BUY"
            side_short = "SELL"
            reduce_only = False
        else:
            # 减仓
            side_long = "SELL"
            side_short = "BUY"
            reduce_only = True
            delta = abs(delta)

        legs = [
            {
                "venue": intent.venue_long,
                "symbol": intent.symbol,
                "side": side_long,
                "market": "perp",
                "qty": delta,
                "reduce_only": reduce_only,
            },
            {
                "venue": intent.venue_short,
                "symbol": intent.symbol,
                "side": side_short,
                "market": "perp",
                "qty": delta,
                "reduce_only": reduce_only,
            },
        ]

        return SagaPlan(
            saga_id=saga_id,
            intent_id=intent.intent_id,
            legs=legs,
            rollback_strategy="FIFO" if delta > 0 else "PARALLEL",
        )

    def _plan_evacuate(self, intent: EvacuateIntent) -> SagaPlan:
        """
        撤离 Planner:
        - 生成 N 腿,每个 symbol 一腿 reduce-only
        - Saga ID: evac-{venue}-{timestamp}
        """
        saga_id = f"evac-{intent.venue}-{int(time.time())}"

        # 这里简化,实际需要查询账户当前持仓
        # Manager 调用时会传入 positions
        legs = []
        for symbol in intent.symbols:
            legs.append({
                "venue": intent.venue,
                "symbol": symbol,
                "side": "SELL",  # 假设都是多头,实际需要判断
                "market": "perp",
                "qty": 0,  # 将由 Manager 填充
                "reduce_only": True,
            })

        return SagaPlan(
            saga_id=saga_id,
            intent_id=intent.intent_id,
            legs=legs,
            rollback_strategy="PARALLEL",  # 撤离并行最快
        )


# 便捷函数: 直接从 Intent 生成 Plan
def plan_from_intent(intent: Intent, min_order_usdt: float = 5.0) -> SagaPlan:
    """便捷函数: Intent → Plan"""
    planner = IntentPlanner(min_order_usdt=min_order_usdt)
    return planner.plan(intent)
