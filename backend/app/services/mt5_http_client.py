"""
MT5 HTTP Client - 通过 HTTP 调用远程 MT5 Bridge 微服务
替代直接使用 MetaTrader5 SDK，用于远程服务器（无MT5终端）场景
"""
import httpx
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class MT5HttpClient:
    """MT5 HTTP 客户端 — 调用 MT5 Bridge 微服务 (port 8001/8002)

    提供与 MT5Client (SDK 直连版) 兼容的接口，
    使上层 market_service / account_service / mt5_bridge 无需关心底层是 SDK 还是 HTTP。
    """

    def __init__(self, base_url: str = "http://localhost:8001", api_key: str = "OQ6bUimHZDmXEZzJKE"):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10.0)
        self.headers = {"X-API-Key": self.api_key}
        # 兼容 MT5Client 接口的状态字段
        self.connected = False
        self.last_successful_request = None

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()

    # ─── 兼容 MT5Client 的同步接口（实际为同步 HTTP 调用） ───

    def disconnect(self):
        """兼容 MT5Client.disconnect()，HTTP 客户端无需断开"""
        self.connected = False

    # ─── 健康检查 ───

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            resp = await self.client.get(f"{self.base_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                self.connected = data.get("mt5", False)
                return True
            return False
        except Exception as e:
            logger.error(f"MT5 Bridge health check failed: {e}")
            self.connected = False
            return False

    async def get_connection_status(self) -> Dict[str, Any]:
        """获取 MT5 连接状态"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/connection/status",
                headers=self.headers
            )
            resp.raise_for_status()
            data = resp.json()
            self.connected = data.get("connected", False)
            return data
        except Exception as e:
            logger.error(f"Failed to get MT5 connection status: {e}")
            self.connected = False
            return {"connected": False, "error": str(e)}

    async def reconnect(self) -> bool:
        """请求 MT5 Bridge 重新连接"""
        try:
            resp = await self.client.post(
                f"{self.base_url}/mt5/connection/reconnect",
                headers=self.headers
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Failed to reconnect MT5: {e}")
            return False

    # ─── Tick 行情（替代 MT5Client.get_tick） ───

    async def get_tick(self, symbol: str = "XAUUSD+") -> Optional[Dict[str, Any]]:
        """获取最新 tick 数据，兼容 MT5Client.get_tick() 返回格式

        Returns:
            Dict with 'symbol', 'bid', 'ask', 'last', 'volume', 'time', 'time_msc'
            or None if unavailable
        """
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/tick/{symbol}",
                headers=self.headers
            )
            if resp.status_code == 200:
                data = resp.json()
                self.connected = True
                from datetime import datetime
                self.last_successful_request = datetime.utcnow()
                return data
            elif resp.status_code == 404:
                logger.warning(f"MT5 Bridge: no tick for {symbol}")
                return None
            elif resp.status_code == 503:
                logger.warning(f"MT5 Bridge: not connected (503)")
                self.connected = False
                return None
            else:
                logger.error(f"MT5 Bridge tick error: {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Failed to get MT5 tick for {symbol}: {e}")
            self.connected = False
            return None

    # ─── 同步版 get_tick（供 run_in_executor 调用） ───

    def get_tick_sync(self, symbol: str = "XAUUSD+") -> Optional[Dict[str, Any]]:
        """同步版 get_tick，用于 loop.run_in_executor 场景

        使用独立的同步 httpx 客户端，避免事件循环冲突。
        """
        try:
            with httpx.Client(timeout=8.0) as sync_client:
                resp = sync_client.get(
                    f"{self.base_url}/mt5/tick/{symbol}",
                    headers=self.headers
                )
                if resp.status_code == 200:
                    self.connected = True
                    from datetime import datetime
                    self.last_successful_request = datetime.utcnow()
                    return resp.json()
                return None
        except Exception as e:
            logger.error(f"Sync get_tick failed for {symbol}: {e}")
            return None

    # ─── 持仓查询（替代 MT5Client.get_positions） ───

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取持仓列表

        Args:
            symbol: 可选品种过滤

        Returns:
            持仓列表，格式与 MT5Client.get_positions() 兼容
        """
        try:
            params = {}
            if symbol:
                params["symbol"] = symbol
            resp = await self.client.get(
                f"{self.base_url}/mt5/positions",
                headers=self.headers,
                params=params
            )
            resp.raise_for_status()
            result = resp.json()
            self.connected = True
            return result.get("positions", [])
        except Exception as e:
            logger.error(f"Failed to get MT5 positions: {e}")
            return []

    def get_positions_sync(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """同步版 get_positions"""
        try:
            params = {}
            if symbol:
                params["symbol"] = symbol
            with httpx.Client(timeout=8.0) as sync_client:
                resp = sync_client.get(
                    f"{self.base_url}/mt5/positions",
                    headers=self.headers,
                    params=params
                )
                if resp.status_code == 200:
                    self.connected = True
                    return resp.json().get("positions", [])
                return []
        except Exception as e:
            logger.error(f"Sync get_positions failed: {e}")
            return []

    # ─── 账户余额（替代 MT5Client.get_account_info） ───

    async def get_account_balance(self) -> Optional[Dict[str, float]]:
        """获取账户余额"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/account/balance",
                headers=self.headers
            )
            resp.raise_for_status()
            self.connected = True
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get MT5 account balance: {e}")
            return None

    async def get_account_info(self) -> Optional[Dict[str, Any]]:
        """获取完整账户信息（含 swap），兼容 MT5Client.get_account_info() 返回格式"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/account/info",
                headers=self.headers
            )
            resp.raise_for_status()
            data = resp.json()
            self.connected = True
            return data
        except Exception as e:
            logger.error(f"Failed to get MT5 account info: {e}")
            return None

    def get_account_info_sync(self) -> Optional[Dict[str, Any]]:
        """同步版 get_account_info"""
        try:
            with httpx.Client(timeout=8.0) as sync_client:
                resp = sync_client.get(
                    f"{self.base_url}/mt5/account/info",
                    headers=self.headers
                )
                if resp.status_code == 200:
                    self.connected = True
                    return resp.json()
                return None
        except Exception as e:
            logger.error(f"Sync get_account_info failed: {e}")
            return None

    # ─── 下单（替代 MT5Client 下单） ───

    async def place_order(
        self,
        symbol: str,
        volume: float,
        order_type: str,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        deviation: int = 10,
        comment: str = "hustle2026",
    ) -> Optional[Dict[str, Any]]:
        """下单"""
        try:
            payload = {
                "symbol": symbol,
                "volume": volume,
                "order_type": order_type,
                "deviation": deviation,
                "comment": comment,
            }
            if price is not None:
                payload["price"] = price
            if sl is not None:
                payload["sl"] = sl
            if tp is not None:
                payload["tp"] = tp

            resp = await self.client.post(
                f"{self.base_url}/mt5/order",
                headers=self.headers,
                json=payload
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"MT5 order failed: {e.response.status_code} {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Failed to place MT5 order: {e}")
            return None

    # ─── 平仓 ───

    async def close_position(
        self,
        symbol: str,
        side: str,
        volume: Optional[float] = None,
        ticket: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """平仓"""
        try:
            payload = {"symbol": symbol, "side": side}
            if volume is not None:
                payload["volume"] = volume
            if ticket is not None:
                payload["ticket"] = ticket

            resp = await self.client.post(
                f"{self.base_url}/mt5/position/close",
                headers=self.headers,
                json=payload
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to close MT5 position: {e}")
            return None

    # ─── 历史成交查询（兼容 MT5Client.get_deals_by_ticket） ───

    async def get_deals_by_ticket_async(self, ticket: int) -> list:
        """通过 ticket (order ID) 查询成交记录。

        Bridge 的 /mt5/history/deals 返回所有历史成交，我们在本地过滤
        order 字段匹配 ticket 的记录（MT5 deal.order == 下单时的 order ticket）。
        只查最近5分钟的成交，减少数据量。
        """
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/history/deals",
                headers=self.headers,
                params={"days": 1}  # 只查近1天，减少数据量
            )
            if resp.status_code != 200:
                logger.warning(f"MT5 history/deals returned {resp.status_code}")
                return []
            data = resp.json()
            all_deals = data.get("deals", [])
            # Filter by order ticket (deal.order == the order that created this deal)
            matched = [d for d in all_deals if d.get("order") == ticket or d.get("ticket") == ticket]
            self.connected = True
            return matched
        except Exception as e:
            logger.error(f"Failed to get MT5 deals for ticket {ticket}: {e}")
            return []

    async def get_deals_history(self) -> list:
        """获取今日所有成交记录（用于计算当日已实现盈亏）

        Returns:
            List of deal dicts with profit, commission, swap, entry fields
        """
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/history/deals",
                headers=self.headers,
                params={"days": 1}
            )
            if resp.status_code != 200:
                logger.warning(f"MT5 history/deals returned {resp.status_code}")
                return []
            data = resp.json()
            self.connected = True
            return data.get("deals", [])
        except Exception as e:
            logger.error(f"Failed to get MT5 deals history: {e}")
            return []

    def get_deals_by_ticket(self, ticket: int) -> list:
        """同步版 get_deals_by_ticket — 供在 asyncio 事件循环之外调用。

        在 asyncio 上下文中请优先使用 get_deals_by_ticket_async。
        这里使用独立的同步 httpx 客户端，避免事件循环冲突。
        """
        try:
            with httpx.Client(timeout=5.0) as sync_client:
                resp = sync_client.get(
                    f"{self.base_url}/mt5/history/deals",
                    headers=self.headers,
                    params={"days": 1}
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                all_deals = data.get("deals", [])
                matched = [d for d in all_deals if d.get("order") == ticket or d.get("ticket") == ticket]
                self.connected = True
                return matched
        except Exception as e:
            logger.error(f"Sync get_deals_by_ticket failed for ticket {ticket}: {e}")
            return []

    # ─── 连接健康检查（兼容 MT5Client 接口） ───

    def is_connection_healthy(self) -> bool:
        """兼容 MT5Client.is_connection_healthy()"""
        return self.connected

    def ensure_connection(self) -> bool:
        """兼容 MT5Client.ensure_connection()，HTTP 模式下始终返回 True"""
        return True

    def connect(self) -> bool:
        """兼容 MT5Client.connect()，HTTP 模式下始终返回 True"""
        return True


# ─── 全局实例工厂 ───

_mt5_http_client: Optional[MT5HttpClient] = None


def get_mt5_http_client() -> MT5HttpClient:
    """获取 MT5 HTTP 客户端单例"""
    global _mt5_http_client
    if _mt5_http_client is None:
        import os
        base_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8001")
        api_key = os.getenv("MT5_BRIDGE_API_KEY", "OQ6bUimHZDmXEZzJKE")
        _mt5_http_client = MT5HttpClient(base_url=base_url, api_key=api_key)
    return _mt5_http_client
