"""Order persistence service for saving and recovering orders"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from app.models.pending_order import PendingOrder
import logging

logger = logging.getLogger(__name__)


class OrderPersistenceService:
    """订单持久化服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_pending_order(
        self,
        user_id: UUID,
        strategy_type: str,
        platform: str,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float],
        order_type: str,
        expires_in_seconds: int = 10,
        extra_data: Optional[Dict] = None
    ) -> PendingOrder:
        """创建待处理订单记录"""

        pending_order = PendingOrder(
            user_id=user_id,
            strategy_type=strategy_type,
            platform=platform,
            order_id=None,  # 先创建记录，下单后更新
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            status="PENDING",
            filled_quantity=0,
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
            extra_data=extra_data or {}
        )

        self.db.add(pending_order)
        await self.db.commit()
        await self.db.refresh(pending_order)

        logger.info(
            f"Created pending order: {pending_order.id} "
            f"({platform} {side} {quantity} {symbol})"
        )

        return pending_order

    async def update_order_id(
        self,
        pending_order_id: UUID,
        order_id: str
    ) -> None:
        """更新订单ID（下单成功后立即调用）"""

        await self.db.execute(
            update(PendingOrder)
            .where(PendingOrder.id == pending_order_id)
            .values(
                order_id=order_id,
                updated_at=datetime.utcnow()
            )
        )
        await self.db.commit()

        logger.info(f"Updated order ID for {pending_order_id}: {order_id}")

    async def update_order_status(
        self,
        pending_order_id: UUID,
        status: str,
        filled_quantity: Optional[float] = None,
        extra_data: Optional[Dict] = None
    ) -> None:
        """更新订单状态"""

        values = {
            "status": status,
            "updated_at": datetime.utcnow()
        }

        if filled_quantity is not None:
            values["filled_quantity"] = filled_quantity

        if extra_data is not None:
            # 合并extra_data
            result = await self.db.execute(
                select(PendingOrder).where(PendingOrder.id == pending_order_id)
            )
            order = result.scalar_one_or_none()
            if order and order.extra_data:
                merged_extra_data = {**order.extra_data, **extra_data}
                values["extra_data"] = merged_extra_data
            else:
                values["extra_data"] = extra_data

        await self.db.execute(
            update(PendingOrder)
            .where(PendingOrder.id == pending_order_id)
            .values(**values)
        )
        await self.db.commit()

        logger.info(
            f"Updated order status for {pending_order_id}: {status} "
            f"(filled: {filled_quantity})"
        )

    async def get_pending_orders(
        self,
        user_id: Optional[UUID] = None,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        hours: int = 1
    ) -> List[PendingOrder]:
        """查询待处理订单"""

        query = select(PendingOrder).where(
            PendingOrder.created_at > datetime.utcnow() - timedelta(hours=hours)
        )

        if user_id:
            query = query.where(PendingOrder.user_id == user_id)

        if status:
            query = query.where(PendingOrder.status == status)

        if platform:
            query = query.where(PendingOrder.platform == platform)

        result = await self.db.execute(query.order_by(PendingOrder.created_at.desc()))
        return result.scalars().all()

    async def cleanup_old_orders(self, days: int = 7) -> int:
        """清理旧订单记录"""

        result = await self.db.execute(
            delete(PendingOrder).where(
                PendingOrder.status.in_(["FILLED", "CANCELLED", "FAILED"]),
                PendingOrder.created_at < datetime.utcnow() - timedelta(days=days)
            )
        )
        await self.db.commit()

        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old orders")

        return deleted_count
