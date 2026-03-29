"""
MT5 Agent 服务层 - 与 Windows Agent 通信
通过 SSH 调用 Windows 服务器上的 Agent API
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
            server_ip: Windows 服务器 IP
            agent_port: Agent 服务端口（默认 9000）
        """
        self.server_ip = server_ip
        self.agent_port = agent_port
        self.base_url = f"http://127.0.0.1:{agent_port}"
        self.ssh_key_path = "~/.ssh/id_ed25519"
        self.ssh_user = "Administrator"

    async def _ssh_curl(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        """
        通过 SSH 隧道调用 Agent API

        Args:
            endpoint: API 端点
            method: HTTP 方法
            data: 请求数据

        Returns:
            API 响应数据
        """
        url = f"{self.base_url}{endpoint}"

        # SSH 选项：禁用主机密钥验证，设置超时
        ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"

        if method == "GET":
            cmd = f"ssh {ssh_opts} -i {self.ssh_key_path} {self.ssh_user}@{self.server_ip} \"curl -s {url}\""
        elif method == "POST":
            json_data = json.dumps(data) if data else "{}"
            # 使用临时文件避免转义问题
            import base64
            json_b64 = base64.b64encode(json_data.encode()).decode()
            temp_file = f"C:/Windows/Temp/mt5_agent_{hash(json_data)}.json"
            cmd = f"ssh {ssh_opts} -i {self.ssh_key_path} {self.ssh_user}@{self.server_ip} \"powershell -Command \\\"[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{json_b64}')) | Out-File -FilePath {temp_file} -Encoding UTF8 -NoNewline; curl.exe -s -X POST -H 'Content-Type: application/json' -d @{temp_file} {url}; Remove-Item {temp_file}\\\"\""
        elif method == "DELETE":
            cmd = f"ssh {ssh_opts} -i {self.ssh_key_path} {self.ssh_user}@{self.server_ip} \"curl -s -X DELETE {url}\""
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        # 执行 SSH 命令
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

        return await self._ssh_curl("/instances/deploy", method="POST", data=data)

    async def start_instance(self, port: int) -> Dict[str, Any]:
        """启动 MT5 实例"""
        return await self._ssh_curl(f"/instances/{port}/start", method="POST")

    async def stop_instance(self, port: int) -> Dict[str, Any]:
        """停止 MT5 实例"""
        return await self._ssh_curl(f"/instances/{port}/stop", method="POST")

    async def restart_instance(self, port: int) -> Dict[str, Any]:
        """重启 MT5 实例"""
        return await self._ssh_curl(f"/instances/{port}/restart", method="POST")

    async def get_instance_status(self, port: int) -> Dict[str, Any]:
        """获取 MT5 实例状态"""
        return await self._ssh_curl(f"/instances/{port}/status", method="GET")

    async def list_instances(self) -> Dict[str, Any]:
        """列出所有 MT5 实例"""
        return await self._ssh_curl("/instances", method="GET")

    async def delete_instance(self, port: int) -> Dict[str, Any]:
        """删除 MT5 实例"""
        return await self._ssh_curl(f"/instances/{port}", method="DELETE")

    async def health_check(self) -> Dict[str, Any]:
        """Agent 健康检查"""
        return await self._ssh_curl("/", method="GET")
