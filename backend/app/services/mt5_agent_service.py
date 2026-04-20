"""
MT5 Agent service - communicates with Windows Agent via HTTP.
Configuration loaded from mt5_config DB table with env var fallback.
"""
import os
from typing import Dict, Any
import httpx


_config_cache: Dict[str, str] = {}


async def _load_config():
    """Load agent config from mt5_config table. Falls back to env vars."""
    global _config_cache
    if _config_cache:
        return
    try:
        from app.core.database import get_db_context
        async with get_db_context() as db:
            from sqlalchemy import text
            result = await db.execute(text("SELECT key, value FROM mt5_config"))
            _config_cache = {row[0]: row[1] for row in result.fetchall()}
    except Exception:
        pass


def _get_config(key: str, env_key: str = "", default: str = "") -> str:
    if _config_cache and key in _config_cache:
        return _config_cache[key]
    if env_key:
        v = os.getenv(env_key)
        if v:
            return v
    return default


def _service_name_from_deploy_path(deploy_path: str) -> str:
    import ntpath
    return ntpath.basename(deploy_path.rstrip(chr(47) + chr(92)))


class MT5AgentService:
    """MT5 Agent service - manages communication with Windows Agent."""

    def __init__(self, server_ip: str, agent_port: int = 8765):
        self.server_ip = server_ip
        self.agent_port = agent_port
        self.base_url = f"http://{server_ip}:{agent_port}"
        self.timeout = 30.0

    @property
    def api_key(self) -> str:
        return _get_config("agent_api_key", "MT5_AGENT_API_KEY", "HustleXAU_MT5_Agent_Key_2026")

    async def _http_request(self, endpoint: str, method: str = "GET",
                            data: Dict = None, timeout: float = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        req_timeout = timeout or self.timeout
        headers = {"X-API-Key": self.api_key}
        async with httpx.AsyncClient(timeout=req_timeout) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, json=data or {}, headers=headers)
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                raise Exception(f"Agent request timeout: {url}")
            except httpx.HTTPStatusError as e:
                raise Exception(f"HTTP {e.response.status_code}: {e.response.text}")
            except Exception as e:
                if "HTTP" in str(e) or "Agent" in str(e):
                    raise
                raise Exception(f"Agent request failed: {str(e)}")

    # Bridge service management (NSSM services)

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
        sn = _service_name_from_deploy_path(deploy_path)
        params = []
        if service_port:
            params.append(f"mt5_client_port={service_port}")
        if mt5_login:
            params.append(f"mt5_login={mt5_login}")
        qs = f"?{'&'.join(params)}" if params else ""
        return await self._http_request(f"/bridge/{sn}{qs}", method="DELETE", timeout=120.0)

    # MT5 terminal process management

    async def list_instances(self) -> list:
        return await self._http_request("/instances")

    async def instance_start(self, instance_name: str) -> Dict[str, Any]:
        return await self._http_request(f"/instances/{instance_name}/start", method="POST")

    async def instance_stop(self, instance_name: str) -> Dict[str, Any]:
        return await self._http_request(f"/instances/{instance_name}/stop", method="POST")

    async def instance_restart(self, instance_name: str) -> Dict[str, Any]:
        return await self._http_request(f"/instances/{instance_name}/restart", method="POST")

    # Backward-compatible methods

    async def start_instance(self, port_or_name) -> Dict[str, Any]:
        return await self.instance_start(str(port_or_name))

    async def stop_instance(self, port_or_name) -> Dict[str, Any]:
        return await self.instance_stop(str(port_or_name))

    async def restart_instance(self, port_or_name) -> Dict[str, Any]:
        return await self.instance_restart(str(port_or_name))

    async def get_instance_status(self, port: int) -> Dict[str, Any]:
        return await self._http_request(f"/bridge/{port}/status")

    async def deploy_instance(self, port: int, mt5_path: str, deploy_path: str,
                              auto_start: bool = True, account: str = None,
                              server: str = None) -> Dict[str, Any]:
        return await self.bridge_deploy(deploy_path, port, mt5_path, auto_start, account, server)

    async def delete_instance(self, port: int) -> Dict[str, Any]:
        return await self._http_request(f"/bridge/{port}", method="DELETE")

    async def health_check(self) -> Dict[str, Any]:
        return await self._http_request("/health")
