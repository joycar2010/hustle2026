"""
MT5 客户端状态同步服务
定期同步数据库中的 MT5 客户端连接状态
"""
import logging
import asyncio
import httpx
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mt5_client import MT5Client
from app.models.mt5_instance import MT5Instance
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class MT5SyncService:
    """MT5 客户端状态同步服务"""

    def __init__(self, sync_interval: int = 10):
        """
        初始化同步服务

        Args:
            sync_interval: 同步间隔（秒），默认 10 秒
        """
        self.sync_interval = sync_interval
        self.running = False
        self._task = None

    async def sync_client_status(self, db: AsyncSession):
        """同步所有 MT5 客户端状态"""
        try:
            # 获取所有活跃客户端
            result = await db.execute(
                select(MT5Client).where(MT5Client.is_active == True)
            )
            clients = result.scalars().all()

            logger.debug(f"Syncing status for {len(clients)} MT5 clients")

            for client in clients:
                try:
                    # 获取关联实例
                    instance_result = await db.execute(
                        select(MT5Instance)
                        .where(MT5Instance.client_id == client.client_id)
                        .where(MT5Instance.is_active == True)
                        .limit(1)
                    )
                    instance = instance_result.scalar_one_or_none()

                    if not instance:
                        # 无实例，标记为未连接
                        if client.connection_status != "disconnected":
                            client.connection_status = "disconnected"
                            logger.debug(f"Client {client.client_id} marked as disconnected (no instance)")
                        continue

                    # 检查桥接服务健康
                    try:
                        async with httpx.AsyncClient(timeout=2.0) as http_client:
                            # 先检查桥接服务是否运行
                            health_resp = await http_client.get(
                                f"http://{instance.server_ip}:{instance.service_port}/health"
                            )

                            if health_resp.status_code == 200:
                                health_data = health_resp.json()
                                mt5_connected = health_data.get("mt5", False)

                                if mt5_connected:
                                    client.connection_status = "connected"
                                    client.last_connected_at = datetime.utcnow()
                                    logger.debug(f"Client {client.client_id} connected")
                                else:
                                    client.connection_status = "disconnected"
                                    logger.debug(f"Client {client.client_id} bridge running but MT5 not connected")
                            else:
                                client.connection_status = "error"
                                logger.debug(f"Client {client.client_id} bridge returned status {health_resp.status_code}")

                    except httpx.TimeoutException:
                        client.connection_status = "error"
                        logger.debug(f"Client {client.client_id} health check timeout")
                    except httpx.ConnectError:
                        client.connection_status = "disconnected"
                        logger.debug(f"Client {client.client_id} bridge not reachable")
                    except Exception as e:
                        client.connection_status = "error"
                        logger.debug(f"Client {client.client_id} health check error: {e}")

                except Exception as e:
                    logger.error(f"Error syncing client {client.client_id}: {e}")
                    continue

            # 提交所有更改
            await db.commit()
            logger.debug("MT5 client status sync completed")

        except Exception as e:
            logger.error(f"MT5 sync error: {e}")
            await db.rollback()

    async def _sync_loop(self):
        """同步循环"""
        logger.info(f"MT5 sync service started (interval: {self.sync_interval}s)")

        while self.running:
            try:
                async with AsyncSessionLocal() as db:
                    await self.sync_client_status(db)
            except Exception as e:
                logger.error(f"MT5 sync loop error: {e}")

            # 等待下一次同步
            await asyncio.sleep(self.sync_interval)

        logger.info("MT5 sync service stopped")

    async def start(self):
        """启动同步服务"""
        if self.running:
            logger.warning("MT5 sync service is already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("MT5 sync service task created")

    async def stop(self):
        """停止同步服务"""
        if not self.running:
            return

        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("MT5 sync service stopped")


# 全局实例
mt5_sync_service = MT5SyncService(sync_interval=10)
