"""OKX V5 API client (minimal — open-orders listing only).

Used by the pending-orders aggregator to show OKX SWAP/FUTURES pending orders
on the main trading dashboard. Full OKX trading (place/cancel) is not yet
integrated, so this client intentionally exposes a narrow surface.

Auth: HMAC-SHA256 base64 of (timestamp + METHOD + requestPath + body).
Timestamp format: ISO8601 UTC with milliseconds."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class OKXClient:
    """Minimal async client for OKX V5 — only implements the endpoints we
    need today (open-orders). Extend when OKX trading is added."""

    BASE_URL = "https://www.okx.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        proxy_url: Optional[str] = None,
    ):
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.passphrase = passphrase or ""
        self.proxy_url = proxy_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @staticmethod
    def _iso_timestamp() -> str:
        # OKX requires ISO-8601 UTC with ms: 2024-01-01T12:34:56.789Z
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def _sign(self, ts: str, method: str, request_path: str, body: str) -> str:
        msg = f"{ts}{method.upper()}{request_path}{body}"
        mac = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        session = await self._get_session()
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        request_path = f"{path}{query}"
        body_str = json.dumps(body) if body else ""
        ts = self._iso_timestamp()
        sign = self._sign(ts, method, request_path, body_str)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        url = f"{self.BASE_URL}{request_path}"
        try:
            async with session.request(
                method, url,
                headers=headers,
                data=body_str if body else None,
                proxy=self.proxy_url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                text = await resp.text()
                try:
                    return json.loads(text) if text else {}
                except json.JSONDecodeError:
                    logger.error(f"[OKX] {method} {path} non-JSON: {text[:200]}")
                    return {"code": "NETWORK", "msg": text[:200], "data": []}
        except aiohttp.ClientError as e:
            logger.error(f"[OKX] {method} {path} network error: {e}")
            return {"code": "NETWORK", "msg": str(e), "data": []}

    async def get_open_orders(
        self,
        inst_id: Optional[str] = None,
        inst_type: str = "SWAP",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return the currently-pending orders.

        inst_type: SWAP (永续) | FUTURES (交割) | SPOT — our pairs use SWAP +
        FUTURES so caller may iterate both if needed. Default SWAP covers all
        configured pairs except the two dated-futures ones (UM-260424).
        """
        params: Dict[str, Any] = {"instType": inst_type, "limit": limit}
        if inst_id:
            params["instId"] = inst_id
        resp = await self._request("GET", "/api/v5/trade/orders-pending", params=params)
        if not isinstance(resp, dict):
            return []
        if str(resp.get("code")) not in ("0", "NETWORK"):
            logger.warning(
                f"[OKX] orders-pending non-zero code={resp.get('code')} "
                f"msg={resp.get('msg')}"
            )
        data = resp.get("data") or []
        return data if isinstance(data, list) else []
