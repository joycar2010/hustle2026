"""
MT5 Agent 服务层 - 与 Windows Agent 通信
通过 HTTP 直接调用 Windows 服务器上的 Agent API
"""
import asyncio
import json
from typing import Dict, Any
import httpx


class MT5AgentService:
    """MT5 Agent 服务 - 管理与 Windows Agent 的通信"""

    def __init__(self, server_ip: str, agent_port: int = 9000):
        """
        初始化 Agent 服务

        Args:
            server_ip: Windows 服务器 IP（内网地址）
            agent_port: Agent 服务端口（默认 9000）
        """
        self.server_ip = server_ip
        self.agent_port = agent_port
        self.base_url = f"http://{server_ip}:{agent_port}"
        self.timeout = 30.0

    async def _http_request(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        """
        通过 HTTP 直接调用 Agent API

        Args:
            endpoint: API 端点
            method: HTTP 方法
            data: 请求数据

        Returns:
            API 响应数据
        """
        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                if method == "GET":
                    response = await client.get(url)
                elif method == "POST":
                    response = await client.post(url, json=data or {})
                elif method == "DELETE":
                    response = await client.delete(url)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException:
                raise Exception(f"Request timeout: {url}")
            except httpx.HTTPStatusError as e:
                raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
            except Exception as e:
                raise Exception(f"Request failed: {str(e)}")

    async def deploy_instance(
        self,
        port: int,
        mt5_path: str,
        deploy_path: str,
        auto_start: bool = True,
        account: str = None,
        server: str = None
    ) -> Dict[str, Any]:
        """
        部署新的 MT5 实例

        Args:
            port: 服务端口
            mt5_path: MT5 可执行文件路径
            deploy_path: 服务部署路径
            auto_start: 是否开机自启
            account: MT5 账号（可选）
            server: MT5 服务器（可选）

        Returns:
            部署结果
        """
        data = {
            "port": port,
            "mt5_path": mt5_path,
            "deploy_path": deploy_path,
            "auto_start": auto_start
        }

        if account:
            data["account"] = account
        if server:
            data["server"] = server

        return await self._http_request("/instances/deploy", method="POST", data=data)

    async def start_instance(self, port: int) -> Dict[str, Any]:
        """启动 MT5 实例"""
        return await self._http_request(f"/instances/{port}/start", method="POST")

    async def stop_instance(self, port: int) -> Dict[str, Any]:
        """停止 MT5 实例"""
        return await self._http_request(f"/instances/{port}/stop", method="POST")

    async def restart_instance(self, port: int) -> Dict[str, Any]:
        """重启 MT5 实例"""
        return await self._http_request(f"/instances/{port}/restart", method="POST")

    async def get_instance_status(self, port: int) -> Dict[str, Any]:
        """获取 MT5 实例状态"""
        return await self._http_request(f"/instances/{port}/status", method="GET")

    async def list_instances(self) -> Dict[str, Any]:
        """列出所有 MT5 实例"""
        return await self._http_request("/instances", method="GET")

    async def delete_instance(self, port: int) -> Dict[str, Any]:
        """删除 MT5 实例"""
        return await self._http_request(f"/instances/{port}", method="DELETE")

    async def health_check(self) -> Dict[str, Any]:
        """Agent 健康检查"""
        return await self._http_request("/", method="GET")
