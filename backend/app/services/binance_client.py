"""Binance Futures API client"""
import hmac
import hashlib
import time
from typing import Dict, Any, Optional
import aiohttp
from app.core.config import settings


class BinanceFuturesClient:
    """Async client for Binance Futures API"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = settings.BINANCE_API_BASE
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()

    def _sign(self, params: Dict[str, Any]) -> str:
        """Generate HMAC SHA256 signature"""
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        endpoint: str,
        signed: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make HTTP request to Binance API"""
        url = f"{self.base_url}{endpoint}"
        headers = {}

        if signed:
            headers["X-MBX-APIKEY"] = self.api_key
            params = kwargs.get("params", {})
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
            kwargs["params"] = params

        session = await self._get_session()

        try:
            async with session.request(method, url, headers=headers, **kwargs) as resp:
                data = await resp.json()

                if resp.status != 200:
                    raise Exception(f"Binance API error: {data}")

                return data
        except aiohttp.ClientError as e:
            raise Exception(f"Network error: {str(e)}")

    # Public endpoints (no authentication required)

    async def get_server_time(self) -> Dict[str, Any]:
        """Get server time for synchronization"""
        return await self._request("GET", "/fapi/v1/time")

    async def get_exchange_info(self) -> Dict[str, Any]:
        """Get exchange trading rules and symbol information"""
        return await self._request("GET", "/fapi/v1/exchangeInfo")

    async def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        """Get latest price for a symbol"""
        return await self._request("GET", "/fapi/v1/ticker/price", params={"symbol": symbol})

    async def get_book_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get best bid/ask price and quantity"""
        return await self._request("GET", "/fapi/v1/ticker/bookTicker", params={"symbol": symbol})

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list:
        """Get kline/candlestick data"""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return await self._request("GET", "/fapi/v1/klines", params=params)

    async def get_funding_rate(self, symbol: str, limit: int = 1) -> list:
        """Get funding rate history"""
        return await self._request(
            "GET", "/fapi/v1/fundingRate", params={"symbol": symbol, "limit": limit}
        )

    # Private endpoints (authentication required)

    async def get_account(self) -> Dict[str, Any]:
        """Get account information"""
        return await self._request("GET", "/fapi/v2/account", signed=True)

    async def get_balance(self) -> list:
        """Get account balance"""
        return await self._request("GET", "/fapi/v2/balance", signed=True)

    async def get_position_risk(self, symbol: Optional[str] = None) -> list:
        """Get position information"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v2/positionRisk", signed=True, params=params)

    async def get_income(
        self,
        symbol: Optional[str] = None,
        income_type: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 100,
    ) -> list:
        """Get income history (P&L, funding fees, etc.)"""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if income_type:
            params["incomeType"] = income_type
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return await self._request("GET", "/fapi/v1/income", signed=True, params=params)

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """Place a new order"""
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
        }

        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("Price is required for LIMIT orders")
            params["price"] = price
            params["timeInForce"] = time_in_force

        if reduce_only:
            params["reduceOnly"] = "true"

        return await self._request("POST", "/fapi/v1/order", signed=True, params=params)

    async def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel an active order"""
        params = {"symbol": symbol, "orderId": order_id}
        return await self._request("DELETE", "/fapi/v1/order", signed=True, params=params)

    async def get_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Query order status"""
        params = {"symbol": symbol, "orderId": order_id}
        return await self._request("GET", "/fapi/v1/order", signed=True, params=params)

    async def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """Get all open orders"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v1/openOrders", signed=True, params=params)

    async def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """Cancel all open orders for a symbol"""
        params = {"symbol": symbol}
        return await self._request("DELETE", "/fapi/v1/allOpenOrders", signed=True, params=params)
