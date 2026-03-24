"""
MT5 HTTP Client - 通过 HTTP 调用 MT5 微服务
替代直接使用 MetaTrader5 SDK
"""
import httpx
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class MT5HttpClient:
    """MT5 HTTP 客户端，调用 MT5 微服务"""
    
    def __init__(self, base_url: str = "http://54.249.66.53:8001", api_key: str = "OQ6bUimHZDmXEZzJKE"):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
        self.headers = {"X-API-Key": self.api_key}
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            resp = await self.client.get(f"{self.base_url}/health")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"MT5 health check failed: {e}")
            return False
    
    async def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/connection/status",
                headers=self.headers
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get MT5 connection status: {e}")
            return {"connected": False}
    
    async def reconnect(self) -> bool:
        """重新连接"""
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
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """获取持仓"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/positions",
                headers=self.headers
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get("positions", [])
        except Exception as e:
            logger.error(f"Failed to get MT5 positions: {e}")
            return []
    
    async def get_account_balance(self) -> Optional[Dict[str, float]]:
        """获取账户余额"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/mt5/account/balance",
                headers=self.headers
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get MT5 account balance: {e}")
            return None
    
    async def place_order(
        self,
        symbol: str,
        volume: float,
        order_type: str,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """下单"""
        try:
            payload = {
                "symbol": symbol,
                "volume": volume,
                "order_type": order_type,
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
        except Exception as e:
            logger.error(f"Failed to place MT5 order: {e}")
            return None

# 全局实例
mt5_http_client: Optional[MT5HttpClient] = None

def get_mt5_http_client() -> MT5HttpClient:
    """获取 MT5 HTTP 客户端实例"""
    global mt5_http_client
    if mt5_http_client is None:
        # 从环境变量读取配置
        import os
        base_url = os.getenv("MT5_SERVICE_URL", "http://localhost:8001")
        api_key = os.getenv("MT5_SERVICE_API_KEY", "OQ6bUimHZDmXEZzJKE")
        mt5_http_client = MT5HttpClient(base_url=base_url, api_key=api_key)
    return mt5_http_client
