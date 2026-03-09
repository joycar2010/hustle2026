"""MT5 Bridge Service - Real-time position updates via WebSocket"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import MetaTrader5 as mt5
from app.websocket.manager import manager
from app.core.database import get_db_context
from app.models.account import Account
from sqlalchemy import select

logger = logging.getLogger(__name__)


class MT5Bridge:
    """
    MT5数据桥接服务

    功能：
    - 1秒轮询MT5持仓数据
    - 检测数据变化
    - 通过WebSocket实时推送到前端
    - 只在数据变化时推送（节省带宽）
    """

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 1  # 1秒轮询间隔
        self.last_positions: Dict[str, Any] = {}
        self.broadcast_count = 0
        self.error_count = 0
        self.last_broadcast_time = None

        # MT5连接状态
        self.mt5_clients: Dict[str, Any] = {}  # account_id -> MT5Client

    async def start(self):
        """启动MT5桥接服务"""
        if self.running:
            logger.warning("MT5 Bridge already running")
            return

        self.running = True
        self.task = asyncio.create_task(self._bridge_loop())
        logger.info(f"MT5 Bridge started (interval: {self.interval}s)")

    async def stop(self):
        """停止MT5桥接服务"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("MT5 Bridge stopped")

    async def _bridge_loop(self):
        """主循环：轮询MT5数据并推送变化"""
        while self.running:
            try:
                # 只在有WebSocket连接时才轮询
                if manager.get_connection_count() == 0:
                    await asyncio.sleep(self.interval)
                    continue

                # 获取所有活跃的MT5账户
                async with get_db_context() as db:
                    result = await db.execute(
                        select(Account).where(
                            Account.is_active == True,
                            Account.is_mt5_account == True
                        )
                    )
                    mt5_accounts = result.scalars().all()

                    if not mt5_accounts:
                        await asyncio.sleep(self.interval)
                        continue

                    # 获取所有MT5账户的持仓数据
                    all_positions = []
                    for account in mt5_accounts:
                        positions = await self._fetch_mt5_positions(account)
                        if positions:
                            all_positions.extend(positions)

                    # 检测变化并推送
                    if self._has_positions_changed(all_positions):
                        await self._broadcast_positions(all_positions)
                        self.last_positions = self._build_position_cache(all_positions)
                        self.broadcast_count += 1
                        self.last_broadcast_time = datetime.now().isoformat()

                await asyncio.sleep(self.interval)

            except Exception as e:
                logger.error(f"MT5 Bridge error: {str(e)}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(self.interval)

    async def _fetch_mt5_positions(self, account: Account) -> List[Dict[str, Any]]:
        """
        获取MT5账户的持仓数据

        Args:
            account: MT5账户对象

        Returns:
            持仓数据列表
        """
        try:
            # 导入MT5Client
            from app.services.mt5_client import MT5Client

            # 获取或创建MT5客户端
            account_id = str(account.account_id)
            if account_id not in self.mt5_clients:
                # 获取MT5密码（使用mt5_primary_pwd字段，如果为空则使用api_secret）
                mt5_password = account.mt5_primary_pwd or account.api_secret

                # 获取MT5账户ID（使用mt5_id字段，如果为空则使用api_key）
                mt5_login = account.mt5_id or account.api_key

                # 获取MT5服务器
                mt5_server = account.mt5_server or account.server or "Bybit-Live-2"

                # 创建MT5客户端
                mt5_client = MT5Client(
                    login=int(mt5_login),
                    password=mt5_password,
                    server=mt5_server
                )

                # 连接MT5
                if not mt5_client.connect():
                    logger.error(f"Failed to connect MT5 account {account_id}")
                    return []

                self.mt5_clients[account_id] = mt5_client

            mt5_client = self.mt5_clients[account_id]

            # 检查连接健康状态
            if not mt5_client.is_connection_healthy():
                logger.warning(f"MT5 connection unhealthy for account {account_id}, reconnecting...")
                if not mt5_client.connect():
                    logger.error(f"Failed to reconnect MT5 account {account_id}")
                    return []

            # 获取持仓
            positions = mt5_client.get_positions(symbol="XAUUSD.s")

            if not positions:
                return []

            # 格式化持仓数据
            formatted_positions = []
            for pos in positions:
                formatted_positions.append({
                    "account_id": account_id,
                    "account_name": account.account_name,
                    "ticket": pos.get("ticket"),
                    "symbol": pos.get("symbol"),
                    "volume": pos.get("volume"),
                    "price_open": pos.get("price_open"),
                    "price_current": pos.get("price_current"),
                    "profit": pos.get("profit"),
                    "swap": pos.get("swap"),
                    "type": pos.get("type"),
                    "time": pos.get("time"),
                    "comment": pos.get("comment", "")
                })

            return formatted_positions

        except Exception as e:
            logger.error(f"Error fetching MT5 positions for account {account.account_id}: {e}")
            return []

    def _has_positions_changed(self, current_positions: List[Dict[str, Any]]) -> bool:
        """
        检测持仓是否发生变化

        Args:
            current_positions: 当前持仓列表

        Returns:
            True if changed, False otherwise
        """
        # 如果是首次获取数据
        if not self.last_positions:
            return len(current_positions) > 0

        # 构建当前持仓缓存
        current_cache = self._build_position_cache(current_positions)

        # 比较持仓数量
        if len(current_cache) != len(self.last_positions):
            return True

        # 比较每个持仓的关键字段
        for ticket, pos in current_cache.items():
            if ticket not in self.last_positions:
                return True

            last_pos = self.last_positions[ticket]

            # 检查关键字段变化
            if (pos["volume"] != last_pos["volume"] or
                abs(pos["profit"] - last_pos["profit"]) > 0.01 or  # 盈亏变化超过0.01
                abs(pos["swap"] - last_pos["swap"]) > 0.01 or      # 掉期费变化超过0.01
                abs(pos["price_current"] - last_pos["price_current"]) > 0.01):  # 当前价格变化
                return True

        return False

    def _build_position_cache(self, positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        构建持仓缓存字典

        Args:
            positions: 持仓列表

        Returns:
            {ticket: position_data}
        """
        return {
            str(pos["ticket"]): pos
            for pos in positions
        }

    async def _broadcast_positions(self, positions: List[Dict[str, Any]]):
        """
        广播持仓数据到所有WebSocket客户端

        Args:
            positions: 持仓数据列表
        """
        try:
            message = {
                "type": "mt5_position_update",
                "data": {
                    "positions": positions,
                    "timestamp": datetime.now().isoformat(),
                    "count": len(positions)
                }
            }

            await manager.broadcast(message)
            logger.debug(f"Broadcasted {len(positions)} MT5 positions")

        except Exception as e:
            logger.error(f"Error broadcasting MT5 positions: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取桥接服务统计信息"""
        return {
            "running": self.running,
            "interval": self.interval,
            "broadcast_count": self.broadcast_count,
            "error_count": self.error_count,
            "last_broadcast_time": self.last_broadcast_time,
            "active_mt5_accounts": len(self.mt5_clients),
            "cached_positions": len(self.last_positions)
        }


# 创建全局实例
mt5_bridge = MT5Bridge()
