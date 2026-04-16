"""
MT5 Agent 服务层 - 与 Windows Agent 通信（优化版）
直接通过内网 HTTP 访问，使用连接池减少延迟
"""
import asyncio
import json
from typing import Dict, Any, Optional
import httpx


class MT5AgentService:
    """MT5 Agent 服务 - 管理与 Windows Agent 的通信"""

    # 类级别的 HTTP 客户端，所有实例共享连接池
    _http_client: Optional[httpx.AsyncClient] = None
    _client_lock = asyncio.Lock()

    def __init__(self, server_ip: str, agent_port: int = 9000):
        """
        初始化 Agent 服务

        Args:
            server_ip: Windows 服务器 IP（内网地址）
            agent_port: Agent 服务端口（默认 9000）
        """
        self.server_ip = server_ip
        self.agent_port = agent_port
        # 优先使用内网 IP，如果是公网 IP 则使用 SSH 隧道
        self.use_ssh_tunnel = not server_ip.startswith('172.31.')
        self.ssh_key_path = "/home/ubuntu/.ssh/id_ed25519"
        self.ssh_user = "Administrator"

    @classmethod
    async def get_http_client(cls) -> httpx.AsyncClient:
        """获取共享的 HTTP 客户端（连接池）"""
        if cls._http_client is None:
            async with cls._client_lock:
                if cls._http_client is None:
                    cls._http_client = httpx.AsyncClient(
                        timeout=httpx.Timeout(30.0, connect=5.0),
                        limits=httpx.Limits(
                            max_connections=50,
                            max_keepalive_connections=10
                        ),
                        http2=False  # Windows Agent 可能不支持 HTTP/2
                    )
        return cls._http_client

    @classmethod
    async def close_http_client(cls):
        """关闭共享的 HTTP 客户端"""
        if cls._http_client is not None:
            await cls._http_client.aclose()
            cls._http_client = None

    async def _http_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Dict = None
    ) -> Dict[str, Any]:
        """
        直接通过 HTTP 调用 Agent API（内网优化）

        Args:
            endpoint: API 端点
            method: HTTP 方法
            data: 请求数据

        Returns:
            API 响应数据
        """
        url = f"http://{self.server_ip}:{self.agent_port}{endpoint}"
        client = await self.get_http_client()

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

        except httpx.HTTPStatusError as e:
            raise Exception(f"HTTP {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"Request failed: {str(e)}")

    async def _ssh_curl(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        """
        通过 SSH 隧道调用 Agent API（备用方案）

        Args:
            endpoint: API 端点
            method: HTTP 方法
            data: 请求数据

        Returns:
            API 响应数据
        """
        url = f"http://127.0.0.1:{self.agent_port}{endpoint}"
        ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ControlMaster=auto -o ControlPath=/tmp/ssh-%r@%h:%p -o ControlPersist=300"

        if method == "GET":
            cmd = f"ssh {ssh_opts} -i {self.ssh_key_path} {self.ssh_user}@{self.server_ip} \"curl -s {url}\""
        elif method == "POST":
            json_data = json.dumps(data) if data else "{}"
            import base64
            json_b64 = base64.b64encode(json_data.encode()).decode()
            temp_file = f"C:/Windows/Temp/mt5_agent_{hash(json_data)}.json"
            cmd = f"ssh {ssh_opts} -i {self.ssh_key_path} {self.ssh_user}@{self.server_ip} \"powershell -Command \\\"[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{json_b64}')) | Out-File -FilePath {temp_file} -Encoding UTF8 -NoNewline; curl.exe -s -X POST -H 'Content-Type: application/json' -d @{temp_file} {url}; Remove-Item {temp_file}\\\"\""
        elif method == "DELETE":
            cmd = f"ssh {ssh_opts} -i {self.ssh_key_path} {self.ssh_user}@{self.server_ip} \"curl -s -X DELETE {url}\""
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            if not error_msg:
                error_msg = f"Command exited with code {process.returncode}"
            raise Exception(f"SSH command failed: {error_msg}")

        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response: {stdout.decode()[:200]} (Error: {str(e)})")

    async def _call_agent(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        """
        调用 Agent API（自动选择最优方式）
        """
        if self.use_ssh_tunnel:
            return await self._ssh_curl(endpoint, method, data)
        else:
            return await self._http_request(endpoint, method, data)

    async def deploy_instance(
        self,
        port: int,
        mt5_path: str,
        deploy_path: str,
        auto_start: bool = True,
        account: str = None,
        server: str = None
    ) -> Dict[str, Any]:
        """部署新的 MT5 实例"""
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
        return await self._call_agent("/instances/deploy", method="POST", data=data)

    async def start_instance(self, port: int) -> Dict[str, Any]:
        """启动 MT5 实例"""
        return await self._call_agent(f"/instances/{port}/start", method="POST")

    async def stop_instance(self, port: int) -> Dict[str, Any]:
        """停止 MT5 实例"""
        return await self._call_agent(f"/instances/{port}/stop", method="POST")

    async def restart_instance(self, port: int) -> Dict[str, Any]:
        """重启 MT5 实例"""
        return await self._call_agent(f"/instances/{port}/restart", method="POST")

    async def get_instance_status(self, port: int) -> Dict[str, Any]:
        """获取 MT5 实例状态"""
        return await self._call_agent(f"/instances/{port}/status", method="GET")

    async def list_instances(self) -> Dict[str, Any]:
        """列出所有 MT5 实例"""
        return await self._call_agent("/instances", method="GET")

    async def delete_instance(self, port: int) -> Dict[str, Any]:
        """删除 MT5 实例"""
        return await self._call_agent(f"/instances/{port}", method="DELETE")

    async def health_check(self) -> Dict[str, Any]:
        """Agent 健康检查"""
        return await self._call_agent("/", method="GET")

