"""
青果网络代理服务
API文档: https://www.qg.net/doc/2141.html
"""
import aiohttp
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.core.config import settings

logger = logging.getLogger(__name__)


class QingguoProxyService:
    """青果网络代理服务"""

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化青果网络代理服务

        Args:
            api_key: 青果网络API密钥，如果不提供则从环境变量读取
        """
        self.api_key = api_key or getattr(settings, 'QINGGUO_API_KEY', '')
        self.base_url = "https://api.qg.net"
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        """关闭session"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_proxies(
        self,
        num: int = 1,
        region: Optional[str] = None,
        protocol: str = "http",
        expire_time: int = 3600,
        format: str = "json"
    ) -> List[Dict[str, Any]]:
        """
        从青果网络获取代理IP

        Args:
            num: 提取数量 (1-100)
            region: 地区代码 (如: cn, us, jp等)
            protocol: 协议类型 (http, https, socks5)
            expire_time: 有效期(秒)
            format: 返回格式 (json, txt)

        Returns:
            代理列表，每个代理包含: host, port, username, password, expire_time等

        Raises:
            Exception: 获取代理失败时抛出异常
        """
        if not self.api_key:
            raise ValueError("青果网络API密钥未配置，请在环境变量中设置QINGGUO_API_KEY")

        session = await self._get_session()

        # 构建请求参数
        params = {
            "key": self.api_key,
            "num": num,
            "protocol": protocol,
            "format": format,
            "time": expire_time,
        }

        if region:
            params["region"] = region

        try:
            # 发送请求
            async with session.get(f"{self.base_url}/get", params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"青果网络API请求失败: HTTP {resp.status}, {error_text}")

                data = await resp.json()

                # 检查返回状态
                if data.get("code") != 0:
                    raise Exception(f"青果网络API错误: {data.get('msg', '未知错误')}")

                # 解析代理列表
                proxies = []
                proxy_list = data.get("data", [])

                for proxy_data in proxy_list:
                    # 青果网络返回格式: {"ip": "1.2.3.4", "port": 8080, "expire_time": "2026-03-16 20:00:00", ...}
                    proxy = {
                        "host": proxy_data.get("ip"),
                        "port": int(proxy_data.get("port")),
                        "username": proxy_data.get("user"),
                        "password": proxy_data.get("pass"),
                        "ip_address": proxy_data.get("ip"),
                        "region": proxy_data.get("region"),
                        "protocol": protocol,
                        "expire_time": self._parse_expire_time(proxy_data.get("expire_time")),
                        "provider": "qingguo",
                    }
                    proxies.append(proxy)

                logger.info(f"成功从青果网络获取 {len(proxies)} 个代理")
                return proxies

        except aiohttp.ClientError as e:
            logger.error(f"青果网络API网络错误: {str(e)}")
            raise Exception(f"网络错误: {str(e)}")
        except Exception as e:
            logger.error(f"获取青果网络代理失败: {str(e)}")
            raise

    def _parse_expire_time(self, expire_time_str: Optional[str]) -> Optional[datetime]:
        """
        解析过期时间字符串

        Args:
            expire_time_str: 过期时间字符串，格式: "2026-03-16 20:00:00"

        Returns:
            datetime对象，如果解析失败则返回None
        """
        if not expire_time_str:
            return None

        try:
            # 尝试解析常见格式
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(expire_time_str, fmt)
                except ValueError:
                    continue

            logger.warning(f"无法解析过期时间: {expire_time_str}")
            return None
        except Exception as e:
            logger.error(f"解析过期时间失败: {str(e)}")
            return None

    async def check_balance(self) -> Dict[str, Any]:
        """
        查询青果网络账户余额

        Returns:
            包含余额信息的字典: {"balance": 100.0, "unit": "元"}

        Raises:
            Exception: 查询失败时抛出异常
        """
        if not self.api_key:
            raise ValueError("青果网络API密钥未配置")

        session = await self._get_session()

        try:
            async with session.get(f"{self.base_url}/balance", params={"key": self.api_key}) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"查询余额失败: HTTP {resp.status}, {error_text}")

                data = await resp.json()

                if data.get("code") != 0:
                    raise Exception(f"查询余额错误: {data.get('msg', '未知错误')}")

                return {
                    "balance": float(data.get("data", {}).get("balance", 0)),
                    "unit": "元",
                }

        except aiohttp.ClientError as e:
            logger.error(f"查询余额网络错误: {str(e)}")
            raise Exception(f"网络错误: {str(e)}")
        except Exception as e:
            logger.error(f"查询余额失败: {str(e)}")
            raise

    async def get_proxy_info(self, proxy_ip: str) -> Dict[str, Any]:
        """
        查询代理IP信息

        Args:
            proxy_ip: 代理IP地址

        Returns:
            代理信息字典

        Raises:
            Exception: 查询失败时抛出异常
        """
        if not self.api_key:
            raise ValueError("青果网络API密钥未配置")

        session = await self._get_session()

        try:
            params = {
                "key": self.api_key,
                "ip": proxy_ip,
            }

            async with session.get(f"{self.base_url}/query", params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"查询代理信息失败: HTTP {resp.status}, {error_text}")

                data = await resp.json()

                if data.get("code") != 0:
                    raise Exception(f"查询代理信息错误: {data.get('msg', '未知错误')}")

                return data.get("data", {})

        except aiohttp.ClientError as e:
            logger.error(f"查询代理信息网络错误: {str(e)}")
            raise Exception(f"网络错误: {str(e)}")
        except Exception as e:
            logger.error(f"查询代理信息失败: {str(e)}")
            raise


# 全局单例
qingguo_proxy_service = QingguoProxyService()
