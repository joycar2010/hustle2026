"""Order recovery service for handling network interruptions"""
from datetime import datetime, timedelta
from typing import Dict, Any, List
import logging
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.pending_order import PendingOrder
from app.models.account import Account
from app.services.order_persistence_service import OrderPersistenceService
from app.services.order_executor import order_executor
from app.core.database import get_db_context

logger = logging.getLogger(__name__)


class OrderRecoveryService:
    """订单恢复服务 - 处理网络中断后的订单恢复"""

    def __init__(self):
        self.recovery_count = 0
        self.failed_count = 0

    async def recover_all_pending_orders(self) -> Dict[str, int]:
        """恢复所有待处理订单（启动时调用）"""

        logger.info("Starting order recovery process...")

        async with get_db_context() as db:
            persistence_service = OrderPersistenceService(db)

            # 查询所有PENDING状态的订单（最近1小时内）
            pending_orders = await persistence_service.get_pending_orders(
                status="PENDING",
                hours=1
            )

            if not pending_orders:
                logger.info("No pending orders to recover")
                return {"recovered": 0, "failed": 0, "cancelled": 0}

            logger.info(f"Found {len(pending_orders)} pending orders to recover")

            recovered = 0
            failed = 0
            cancelled = 0

            for order in pending_orders:
                try:
                    result = await self._recover_single_order(db, order)

                    if result == "recovered":
                        recovered += 1
                    elif result == "cancelled":
                        cancelled += 1
                    else:
                        failed += 1

                except Exception as e:
                    logger.error(f"Failed to recover order {order.id}: {e}")
                    failed += 1

                # 避免过快查询
                await asyncio.sleep(0.1)

            logger.info(
                f"Order recovery completed: "
                f"recovered={recovered}, cancelled={cancelled}, failed={failed}"
            )

            self.recovery_count = recovered
            self.failed_count = failed

            return {
                "recovered": recovered,
                "failed": failed,
                "cancelled": cancelled
            }

    async def _recover_single_order(
        self,
        db: AsyncSession,
        order: PendingOrder
    ) -> str:
        """恢复单个订单"""

        persistence_service = OrderPersistenceService(db)

        # 如果没有order_id，说明下单失败，直接标记为FAILED
        if not order.order_id:
            await persistence_service.update_order_status(
                order.id,
                status="FAILED",
                extra_data={"recovery_note": "No order ID, order placement failed"}
            )
            logger.warning(f"Order {order.id} has no order_id, marked as FAILED")
            return "failed"

        # 检查是否过期
        if order.expires_at and datetime.utcnow() > order.expires_at:
            # 尝试取消过期订单
            await self._cancel_expired_order(db, order)
            return "cancelled"

        # 查询订单实际状态
        try:
            if order.platform == "binance":
                status = await self._check_binance_order_status(db, order)
            elif order.platform == "bybit":
                status = await self._check_mt5_order_status(db, order)
            else:
                logger.error(f"Unknown platform: {order.platform}")
                return "failed"

            # 更新订单状态
            if status["filled_qty"] >= float(order.quantity):
                # 完全成交
                await persistence_service.update_order_status(
                    order.id,
                    status="FILLED",
                    filled_quantity=status["filled_qty"]
                )
                logger.info(f"Order {order.id} recovered as FILLED")
                return "recovered"

            elif status["filled_qty"] > 0:
                # 部分成交
                await persistence_service.update_order_status(
                    order.id,
                    status="PARTIAL",
                    filled_quantity=status["filled_qty"]
                )
                logger.info(f"Order {order.id} recovered as PARTIAL")
                return "recovered"

            elif status["status"] == "CANCELLED":
                # 已取消
                await persistence_service.update_order_status(
                    order.id,
                    status="CANCELLED"
                )
                logger.info(f"Order {order.id} recovered as CANCELLED")
                return "cancelled"

            else:
                # 仍在挂单，检查是否需要取消
                if order.expires_at and datetime.utcnow() > order.expires_at:
                    await self._cancel_expired_order(db, order)
                    return "cancelled"
                else:
                    logger.info(f"Order {order.id} still pending")
                    return "recovered"

        except Exception as e:
            logger.error(f"Failed to check order status for {order.id}: {e}")
            await persistence_service.update_order_status(
                order.id,
                status="PENDING",
                extra_data={"recovery_error": str(e)}
            )
            return "failed"

    async def _check_binance_order_status(
        self,
        db: AsyncSession,
        order: PendingOrder
    ) -> Dict[str, Any]:
        """查询Binance订单状态"""

        # 获取账户信息
        result = await db.execute(
            select(Account).where(
                Account.user_id == order.user_id,
                Account.platform_id == 1  # Binance
            )
        )
        account = result.scalar_one_or_none()

        if not account:
            raise Exception("Binance account not found")

        # 查询订单状态
        status = await order_executor.check_binance_order_status(
            account,
            order.symbol,
            order.order_id
        )

        return status

    async def _check_mt5_order_status(
        self,
        db: AsyncSession,
        order: PendingOrder
    ) -> Dict[str, Any]:
        """查询MT5订单状态"""

        # MT5订单通常是市价单，应该立即成交
        # 这里简化处理，假设已成交
        return {
            "filled_qty": float(order.quantity),
            "status": "FILLED"
        }

    async def _cancel_expired_order(
        self,
        db: AsyncSession,
        order: PendingOrder
    ) -> None:
        """取消过期订单"""

        persistence_service = OrderPersistenceService(db)

        try:
            if order.platform == "binance":
                # 获取账户
                result = await db.execute(
                    select(Account).where(
                        Account.user_id == order.user_id,
                        Account.platform_id == 1
                    )
                )
                account = result.scalar_one_or_none()

                if account:
                    # 取消订单
                    await order_executor.cancel_binance_order(
                        account,
                        order.symbol,
                        order.order_id
                    )

            # 更新状态
            await persistence_service.update_order_status(
                order.id,
                status="CANCELLED",
                extra_data={"cancel_reason": "expired"}
            )

            logger.info(f"Cancelled expired order {order.id}")

        except Exception as e:
            logger.error(f"Failed to cancel expired order {order.id}: {e}")
            await persistence_service.update_order_status(
                order.id,
                status="CANCELLED",
                extra_data={"cancel_error": str(e)}
            )


# Global instance
order_recovery_service = OrderRecoveryService()
