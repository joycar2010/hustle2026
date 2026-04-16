"""
MT5 Agent 服务层 - 与 Windows Agent 通信
通过 HTTP 调用 Windows 服务器上的 Agent API

Agent 端点:
  /health                              GET   Agent 健康
  /instances                           GET   MT5 终端进程列表
  /instances/{instance_name}/start     POST  启动 MT5 终端
  /instances/{instance_name}/stop      POST  停止 MT5 终端
  /instances/{instance_name}/restart   POST  重启 MT5 终端
  /bridge/{service_name}/status        GET   Bridge NSSM 服务状态
  /bridge/{service_name}/start         POST  启动 Bridge 服务
  /bridge/{service_name}/stop          POST  停止 Bridge 服务
  /bridge/{service_name}/restart       POST  重启 Bridge 服务
  /bridge/deploy                       POST  部署新 Bridge 服务
  /bridge/{service_name}               DELETE 删除 Bridge 服务
"""
import os
from typing import Dict, Any, Optional
import httpx


def _service_name_from_deploy_path(deploy_path: str) -> str:
    """从 deploy_path 提取 NSSM 服务名 (目录名), 兼容 Linux 解析 Windows 路径"""
    import ntpath
    return ntpath.basename(deploy_path.rstrip('/\\'))


class MT5AgentService:
    """MT5 Agent 服务 — 管理与 Windows Agent 的通信"""

    def __init__(self, server_ip: str, agent_port: int = 8765):
        self.server_ip = server_ip
        self.agent_port = agent_port
        self.base_url = f"http://{server_ip}:{agent_port}"
        self.timeout = 30.0
        self.headers = {"X-API-Key": "HustleXAU_MT5_Agent_Key_2026"}

    async def _http_request(self, endpoint: str, method: str = "GET", data: Dict = None, timeout: float = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        req_timeout = timeout or self.timeout
        async with httpx.AsyncClient(timeout=req_timeout) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=self.headers)
                elif method == "POST":
                    response = await client.post(url, json=data or {}, headers=self.headers)
                elif method == "DELETE":
                    response = await client.delete(url, headers=self.headers)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                raise Exception(f"Agent 请求超时: {url}")
            except httpx.HTTPStatusError as e:
                raise Exception(f"HTTP {e.response.status_code}: {e.response.text}")
            except Exception as e:
                if "HTTP" in str(e) or "Agent" in str(e):
                    raise
                raise Exception(f"Agent 请求失败: {str(e)}")

    # ── Bridge 服务管理 (NSSM 服务, 用 service_name = deploy_path 目录名) ──

    async def bridge_status(self, deploy_path: str) -> Dict[str, Any]:
        sn = _service_name_from_deploy_path(deploy_path)
        return await self._http_request(f"/bridge/{sn}/status")

    async def bridge_start(self, deploy_path: str) -> Dict[str, Any]:
        sn = _service_name_from_deploy_path(deploy_path)
        return await self._http_request(f"/bridge/{sn}/start", method="POST")

    async def bridge_stop(self, deploy_path: str) -> Dict[str, Any]:
        sn = _service_name_from_deploy_path(deploy_path)
        return await self._http_request(f"/bridge/{sn}/stop", method="POST")

    async def bridge_restart(self, deploy_path: str) -> Dict[str, Any]:
        sn = _service_name_from_deploy_path(deploy_path)
        return await self._http_request(f"/bridge/{sn}/restart", method="POST")

    async def bridge_deploy(self, deploy_path: str, port: int, mt5_path: str,
                            mt5_login: str = "", mt5_password: str = "",
                            mt5_server: str = "", auto_start: bool = True,
                            symbols: list = None, mt5_template_path: str = "") -> Dict[str, Any]:
        """部署新 Bridge 服务 — 匹配 Agent BridgeDeployRequest schema"""
        sn = _service_name_from_deploy_path(deploy_path)
        data = {
            "service_name": sn,
            "service_port": port,
            "mt5_path": mt5_path,
            "mt5_login": mt5_login,
            "mt5_password": mt5_password,
            "mt5_server": mt5_server,
            "symbols": symbols or [],
            "mt5_template_path": mt5_template_path,
        }
        return await self._http_request("/bridge/deploy", method="POST", data=data, timeout=180.0)

    async def bridge_delete(self, deploy_path: str, service_port: int = None,
                            mt5_login: str = None) -> Dict[str, Any]:
        """删除 Bridge 服务 + MT5 客户端目录 + 桌面快捷方式"""
        sn = _service_name_from_deploy_path(deploy_path)
        params = []
        if service_port:
            params.append(f"mt5_client_port={service_port}")
        if mt5_login:
            params.append(f"mt5_login={mt5_login}")
        qs = f"?{'&'.join(params)}" if params else ""
        return await self._http_request(f"/bridge/{sn}{qs}", method="DELETE", timeout=120.0)

    # ── MT5 终端进程管理 (用 instance_name) ──

    async def list_instances(self) -> list:
        return await self._http_request("/instances")

    async def instance_start(self, instance_name: str) -> Dict[str, Any]:
        return await self._http_request(f"/instances/{instance_name}/start", method="POST")

    async def instance_stop(self, instance_name: str) -> Dict[str, Any]:
        return await self._http_request(f"/instances/{instance_name}/stop", method="POST")

    async def instance_restart(self, instance_name: str) -> Dict[str, Any]:
        return await self._http_request(f"/instances/{instance_name}/restart", method="POST")

    # ── 兼容旧接口 (用于 mt5_instances.py 调用) ──

    async def start_instance(self, port_or_name) -> Dict[str, Any]:
        return await self.instance_start(str(port_or_name))

    async def stop_instance(self, port_or_name) -> Dict[str, Any]:
        return await self.instance_stop(str(port_or_name))

    async def restart_instance(self, port_or_name) -> Dict[str, Any]:
        return await self.instance_restart(str(port_or_name))

    async def get_instance_status(self, port: int) -> Dict[str, Any]:
        """获取实例状态 — 尝试 bridge status"""
        return await self._http_request(f"/bridge/{port}/status")

    async def deploy_instance(self, port: int, mt5_path: str, deploy_path: str,
                              auto_start: bool = True, account: str = None,
                              server: str = None) -> Dict[str, Any]:
        return await self.bridge_deploy(deploy_path, port, mt5_path, auto_start, account, server)

    async def delete_instance(self, port: int) -> Dict[str, Any]:
        return await self._http_request(f"/bridge/{port}", method="DELETE")

    async def health_check(self) -> Dict[str, Any]:
        return await self._http_request("/health")
