"""Order executor wrapper with persistence support"""
from typing import Dict, Any, Optional
from uuid import UUID
from datetime import timedelta, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.account import Account
from app.services.order_executor_v2 import OrderExecutorV2
from app.services.order_persistence_service import OrderPersistenceService
import logging

logger = logging.getLogger(__name__)


class OrderExecutorWithPersistence:
    """订单执行器（带持久化支持）"""

    def __init__(self):
        self.executor = OrderExecutorV2()

    async def execute_reverse_opening(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: AsyncSession,
        user_id: UUID,
        extra_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """执行反向开仓（带订单持久化）"""

        persistence_service = OrderPersistenceService(db)

        # 1. 创建Binance订单记录（PENDING状态）
        binance_pending = await persistence_service.create_pending_order(
            user_id=user_id,
            strategy_type="reverse_opening",
            platform="binance",
            symbol="XAUUSDT",
            side="SELL",
            quantity=quantity,
            price=binance_price,
            order_type="LIMIT",
            expires_in_seconds=10,
            extra_data=extra_data
        )

        try:
            # 2. 执行原有逻辑
            result = await self.executor.execute_reverse_opening(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                db=db
            )

            # 3. 更新Binance订单状态
            if result.get("binance_order_id"):
                await persistence_service.update_order_id(
                    binance_pending.id,
                    result["binance_order_id"]
                )

            binance_filled = result.get("binance_filled_qty", 0)

            if binance_filled >= quantity:
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="FILLED",
                    filled_quantity=binance_filled
                )
            elif binance_filled > 0:
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="PARTIAL",
                    filled_quantity=binance_filled
                )
            elif result.get("success"):
                # 订单未成交但执行成功（已取消）
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="CANCELLED",
                    extra_data={"reason": "not_filled"}
                )
            else:
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="FAILED",
                    extra_data={"error": result.get("error")}
                )

            # 4. 如果Bybit有成交，创建Bybit订单记录
            bybit_filled = result.get("bybit_filled_qty", 0)
            if bybit_filled > 0:
                bybit_pending = await persistence_service.create_pending_order(
                    user_id=user_id,
                    strategy_type="reverse_opening",
                    platform="bybit",
                    symbol="XAUUSD.s",
                    side="BUY",
                    quantity=bybit_filled,
                    price=None,
                    order_type="MARKET",
                    expires_in_seconds=1,
                    extra_data=extra_data
                )

                # 立即标记为FILLED（MT5市价单）
                await persistence_service.update_order_status(
                    bybit_pending.id,
                    status="FILLED",
                    filled_quantity=bybit_filled
                )

            return result

        except Exception as e:
            # 异常时标记为FAILED
            await persistence_service.update_order_status(
                binance_pending.id,
                status="FAILED",
                extra_data={"exception": str(e)}
            )
            raise

    async def execute_reverse_closing(
        self,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        binance_price: float,
        bybit_price: float,
        db: AsyncSession,
        user_id: UUID,
        extra_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """执行反向平仓（带订单持久化）"""

        persistence_service = OrderPersistenceService(db)

        # 创建Binance订单记录
        binance_pending = await persistence_service.create_pending_order(
            user_id=user_id,
            strategy_type="reverse_closing",
            platform="binance",
            symbol="XAUUSDT",
            side="BUY",
            quantity=quantity,
            price=binance_price,
            order_type="LIMIT",
            expires_in_seconds=10,
            extra_data=extra_data
        )

        try:
            result = await self.executor.execute_reverse_closing(
                binance_account=binance_account,
                bybit_account=bybit_account,
                quantity=quantity,
                binance_price=binance_price,
                bybit_price=bybit_price,
                db=db
            )

            # 更新订单状态（逻辑同上）
            if result.get("binance_order_id"):
                await persistence_service.update_order_id(
                    binance_pending.id,
                    result["binance_order_id"]
                )

            binance_filled = result.get("binance_filled_qty", 0)

            if binance_filled >= quantity:
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="FILLED",
                    filled_quantity=binance_filled
                )
            elif binance_filled > 0:
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="PARTIAL",
                    filled_quantity=binance_filled
                )
            elif result.get("success"):
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="CANCELLED",
                    extra_data={"reason": "not_filled"}
                )
            else:
                await persistence_service.update_order_status(
                    binance_pending.id,
                    status="FAILED",
                    extra_data={"error": result.get("error")}
                )

            # Bybit订单记录
            bybit_filled = result.get("bybit_filled_qty", 0)
            if bybit_filled > 0:
                bybit_pending = await persistence_service.create_pending_order(
                    user_id=user_id,
                    strategy_type="reverse_closing",
                    platform="bybit",
                    symbol="XAUUSD.s",
                    side="SELL",
                    quantity=bybit_filled,
                    price=None,
                    order_type="MARKET",
                    expires_in_seconds=1,
                    extra_data=extra_data
                )

                await persistence_service.update_order_status(
                    bybit_pending.id,
                    status="FILLED",
                    filled_quantity=bybit_filled
                )

            return result

        except Exception as e:
            await persistence_service.update_order_status(
                binance_pending.id,
                status="FAILED",
                extra_data={"exception": str(e)}
            )
            raise


# Global instance
order_executor_with_persistence = OrderExecutorWithPersistence()
