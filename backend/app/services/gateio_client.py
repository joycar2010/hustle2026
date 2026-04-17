"""Gate.io Futures API V4 client — modular, async, proxy-aware.

Drop this file to add Gate.io support; delete it to remove.
No other file imports this unconditionally — all references are
behind `if platform_id == 4` guards.

Gate.io V4 Futures (USDT-settled) docs:
  https://www.gate.com/docs/developers/apiv4/en/
  Base URL: https://api.gateio.ws/api/v4
  Auth: HMAC-SHA512 — headers KEY, Timestamp, SIGN

Contract naming: XAU_USDT, XAUT_USDT, XAG_USDT, XTI_USDT, NG_USDT
Order size is in "contracts" (张). Actual qty = size * quanto_multiplier.
"""

import hashlib
import hmac
import json
import logging
import time as _time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Gate.io non-retryable error labels
TERMINAL_ERRORS = {
    "INVALID_KEY",
    "INVALID_SIGN",
    "FORBIDDEN",
    "SUB_ACCOUNT_NOT_FOUND",
    "INVALID_PROTOCOL",
}


class GateioError(Exception):
    def __init__(self, label: str, message: str, status: int = 0):
        super().__init__(f"[{label}] {message}")
        self.label = label
        self.message = message
        self.status = status


class GateioFuturesClient:
    """Async client for Gate.io USDT-settled Futures API V4."""

    BASE_URL = "https://api.gateio.ws/api/v4"
    PREFIX = "/api/v4"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        proxy_url: Optional[str] = None,
        settle: str = "usdt",
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.proxy_url = proxy_url
        self.settle = settle
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Session management ─────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── Auth / signing ────────────────────────────────────────────────

    def _sign(
        self, method: str, path: str, query: str = "", body: str = ""
    ) -> Dict[str, str]:
        """Generate Gate.io V4 HMAC-SHA512 signature headers."""
        ts = str(int(_time.time()))
        body_hash = hashlib.sha512(body.encode()).hexdigest()
        sign_str = f"{method}\n{self.PREFIX}{path}\n{query}\n{body_hash}\n{ts}"
        signature = hmac.new(
            self.api_secret.encode(), sign_str.encode(), hashlib.sha512
        ).hexdigest()
        return {
            "KEY": self.api_key,
            "Timestamp": ts,
            "SIGN": signature,
            "Content-Type": "application/json",
        }

    # ── HTTP transport ────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
        auth: bool = True,
    ) -> Any:
        session = await self._get_session()
        url = f"{self.BASE_URL}{path}"
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        body_str = json.dumps(body) if body else ""

        headers = self._sign(method, path, query, body_str) if auth else {
            "Content-Type": "application/json"
        }

        if query:
            url = f"{url}?{query}"

        proxy = self.proxy_url if self.proxy_url else None

        try:
            async with session.request(
                method, url, headers=headers, data=body_str if body else None,
                proxy=proxy, timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    try:
                        err = json.loads(text)
                        label = err.get("label", "UNKNOWN")
                        msg = err.get("message", text)
                    except Exception:
                        label, msg = "HTTP_ERROR", text
                    logger.error(
                        f"[GATEIO] {method} {path} → {resp.status}: [{label}] {msg}"
                    )
                    raise GateioError(label, msg, resp.status)
                return json.loads(text) if text else {}
        except aiohttp.ClientError as e:
            logger.error(f"[GATEIO] Network error: {method} {path} → {e}")
            raise

    # ── Public endpoints (no auth) ────────────────────────────────────

    async def get_contract_info(self, contract: str) -> Dict:
        """GET /futures/{settle}/contracts/{contract}"""
        return await self._request(
            "GET", f"/futures/{self.settle}/contracts/{contract}", auth=False
        )

    async def get_ticker(self, contract: str) -> Dict:
        """GET /futures/{settle}/tickers — returns single ticker."""
        tickers = await self._request(
            "GET", f"/futures/{self.settle}/tickers",
            params={"contract": contract}, auth=False,
        )
        return tickers[0] if tickers else {}

    async def get_orderbook(self, contract: str, limit: int = 5) -> Dict:
        """GET /futures/{settle}/order_book"""
        return await self._request(
            "GET", f"/futures/{self.settle}/order_book",
            params={"contract": contract, "limit": str(limit)}, auth=False,
        )

    # ── Account ───────────────────────────────────────────────────────

    async def get_account(self) -> Dict:
        """GET /futures/{settle}/accounts"""
        return await self._request("GET", f"/futures/{self.settle}/accounts")

    async def get_positions(self, contract: Optional[str] = None) -> List[Dict]:
        """GET /futures/{settle}/positions"""
        params = {}
        if contract:
            params["contract"] = contract
        # Single contract → returns dict, all → returns list
        result = await self._request(
            "GET", f"/futures/{self.settle}/positions", params=params if contract else None,
        )
        if isinstance(result, dict):
            return [result] if result.get("size", 0) != 0 else []
        return [p for p in result if p.get("size", 0) != 0]

    # ── Orders ────────────────────────────────────────────────────────

    async def place_order(
        self,
        contract: str,
        size: int,
        price: Optional[str] = None,
        tif: str = "poc",  # poc = PostOnly (pending or cancelled)
        reduce_only: bool = False,
        text: str = "t-hustle2026",
    ) -> Dict:
        """POST /futures/{settle}/orders

        Args:
            contract: e.g. "XAU_USDT"
            size: positive=long, negative=short (in contracts)
            price: limit price string; None → market order (tif must be "ioc")
            tif: "poc" (PostOnly), "gtc", "ioc", "fok"
            reduce_only: close existing position only
            text: custom order label (max 28 chars, must start with t-)
        """
        order = {
            "contract": contract,
            "size": size,
            "price": price or "0",
            "tif": tif,
            "text": text,
        }
        if reduce_only:
            order["reduce_only"] = True
        if price is None or tif == "ioc":
            # Market order: set price to 0, tif to ioc
            order["price"] = "0"
            order["tif"] = "ioc"

        logger.info(f"[GATEIO] Placing order: {order}")
        return await self._request(
            "POST", f"/futures/{self.settle}/orders", body=order,
        )

    async def cancel_order(self, order_id: str) -> Dict:
        """DELETE /futures/{settle}/orders/{order_id}"""
        return await self._request(
            "DELETE", f"/futures/{self.settle}/orders/{order_id}",
        )

    async def get_order(self, order_id: str) -> Dict:
        """GET /futures/{settle}/orders/{order_id}"""
        return await self._request(
            "GET", f"/futures/{self.settle}/orders/{order_id}",
        )

    # ── Trade history / PnL ───────────────────────────────────────────

    async def get_position_close(
        self, contract: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """GET /futures/{settle}/position_close — realized PnL records."""
        params = {"limit": str(limit)}
        if contract:
            params["contract"] = contract
        return await self._request(
            "GET", f"/futures/{self.settle}/position_close", params=params,
        )

    async def get_my_trades(
        self, contract: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """GET /futures/{settle}/my_trades"""
        params = {"limit": str(limit)}
        if contract:
            params["contract"] = contract
        return await self._request(
            "GET", f"/futures/{self.settle}/my_trades", params=params,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def size_to_qty(size: int, quanto_multiplier: float) -> float:
        """Convert contract size to actual quantity (oz, bbl, etc.)."""
        return abs(size) * quanto_multiplier

    @staticmethod
    def qty_to_size(qty: float, quanto_multiplier: float) -> int:
        """Convert actual quantity to contract size (rounded to int)."""
        return int(round(qty / quanto_multiplier))
