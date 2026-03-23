"""Binance Futures API client"""
import hmac
import hashlib
import time
import re
from datetime import datetime
from typing import Dict, Any, Optional
import aiohttp
from app.core.config import settings

# 不可重试的终止性错误代码（继续重试只会浪费权重）
TERMINAL_ERROR_CODES = {
    -1111,   # Precision is over the maximum defined for this asset
    -5022,   # Post-only order rejected
    -1100,   # Illegal characters in parameter
    -1102,   # Mandatory parameter missing
    -1106,   # Parameter too many values
    -2011,   # Unknown order sent (cancel)
    -2013,   # Order does not exist
}


class BinanceIPBanError(Exception):
    """Raised when Binance bans the server IP due to rate limit abuse.

    Attributes:
        ip: Banned IP address
        ban_until_ms: Unix timestamp (ms) when ban expires
        message: Human-readable formatted message
    """

    def __init__(self, ip: str, ban_until_ms: int, message: str):
        super().__init__(message)
        self.ip = ip
        self.ban_until_ms = ban_until_ms
        self.message = message


class BinanceTerminalError(Exception):
    """Raised on non-retryable Binance API errors (e.g. -1111 precision).

    Attributes:
        code: Binance error code (negative integer)
        message: Human-readable error message
    """

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def format_binance_error(error_data: Dict[str, Any]) -> str:
    """
    格式化Binance API错误信息为中文

    Args:
        error_data: Binance API返回的错误数据

    Returns:
        格式化后的中文错误信息
    """
    if not isinstance(error_data, dict):
        return str(error_data)

    code = error_data.get('code', '')
    msg = error_data.get('msg', '')

    # 错误代码映射
    error_messages = {
        -1003: "请求频率过高",
        -1021: "时间戳不同步",
        -2010: "余额不足",
        -2011: "订单不存在",
        -2013: "订单不存在",
        -2014: "API密钥无效",
        -2015: "API密钥格式无效",
        -1022: "签名验证失败",
        -4000: "参数无效",
    }

    base_msg = error_messages.get(code, f"API错误 (代码: {code})")

    # 特殊处理IP封禁错误
    if code == -1003 and 'banned until' in msg:
        # 提取IP和解禁时间戳
        ip_match = re.search(r'IP\(([^)]+)\)', msg)
        timestamp_match = re.search(r'banned until (\d+)', msg)

        if ip_match and timestamp_match:
            ip = ip_match.group(1)
            ban_until_ms = int(timestamp_match.group(1))

            # 转换为北京时间
            ban_until_dt = datetime.fromtimestamp(ban_until_ms / 1000)
            beijing_time = ban_until_dt.strftime('%Y-%m-%d %H:%M:%S')

            # 计算剩余时间
            now_ms = int(time.time() * 1000)
            remaining_ms = ban_until_ms - now_ms

            if remaining_ms > 0:
                remaining_seconds = remaining_ms // 1000
                remaining_minutes = remaining_seconds // 60
                remaining_hours = remaining_minutes // 60

                if remaining_hours > 0:
                    time_str = f"{remaining_hours}小时{remaining_minutes % 60}分钟"
                elif remaining_minutes > 0:
                    time_str = f"{remaining_minutes}分钟{remaining_seconds % 60}秒"
                else:
                    time_str = f"{remaining_seconds}秒"

                return (
                    f"⚠️ IP地址 {ip} 因请求频率过高已被封禁\n"
                    f"📅 解禁时间: {beijing_time} (北京时间)\n"
                    f"⏱️ 剩余时间: {time_str}\n"
                    f"💡 建议: 请使用WebSocket获取实时数据以避免封禁"
                )
            else:
                return f"IP地址 {ip} 的封禁已解除，可以重新连接"

    # 其他错误
    if msg:
        return f"{base_msg}: {msg}"

    return base_msg


class BinanceFuturesClient:
    """Async client for Binance Futures API"""

    def __init__(self, api_key: str = "", api_secret: str = "", proxy_url: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = settings.BINANCE_API_BASE
        self.spot_base_url = "https://api.binance.com"  # Spot API base URL
        self.session: Optional[aiohttp.ClientSession] = None
        self.proxy_url = proxy_url  # 代理URL，格式: http://user:pass@host:port

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()

    def _raise_typed_error(self, data: Dict[str, Any]) -> None:
        """Parse Binance error response and raise the appropriate typed exception."""
        code = data.get('code', 0) if isinstance(data, dict) else 0
        msg = data.get('msg', '') if isinstance(data, dict) else str(data)

        # IP封禁 — 最优先处理，触发告警流程
        if code == -1003 and 'banned until' in str(msg):
            ip_match = re.search(r'IP\(([^)]+)\)', msg)
            timestamp_match = re.search(r'banned until (\d+)', msg)
            if ip_match and timestamp_match:
                ip = ip_match.group(1)
                ban_until_ms = int(timestamp_match.group(1))
                friendly = format_binance_error(data)
                raise BinanceIPBanError(ip=ip, ban_until_ms=ban_until_ms, message=friendly)

        # 终止性错误码 — 不可重试
        if code in TERMINAL_ERROR_CODES:
            friendly = format_binance_error(data)
            raise BinanceTerminalError(code=code, message=f"Binance API 错误: {friendly}")

        # 普通错误
        raise Exception(f"Binance API 错误: {format_binance_error(data)}")

    def _sign(self, query_string: str) -> str:
        """Generate HMAC SHA256 signature for a query string"""
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
        use_spot_api: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make HTTP request to Binance API"""
        base_url = self.spot_base_url if use_spot_api else self.base_url
        url = f"{base_url}{endpoint}"
        headers = {}

        if signed:
            headers["X-MBX-APIKEY"] = self.api_key
            params = kwargs.pop("params", {})
            params["timestamp"] = int(time.time() * 1000)
            # Build query string preserving insertion order, timestamp last
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            signature = self._sign(query_string)
            full_url = f"{url}?{query_string}&signature={signature}"
            session = await self._get_session()
            try:
                # 使用代理（如果配置了）
                proxy = self.proxy_url if self.proxy_url and self.proxy_url != 'direct' else None
                async with session.request(method, full_url, headers=headers, proxy=proxy, **kwargs) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        self._raise_typed_error(data)
                    return data
            except aiohttp.ClientError as e:
                raise Exception(f"网络错误: {str(e)}")

        session = await self._get_session()

        try:
            # 使用代理（如果配置了）
            proxy = self.proxy_url if self.proxy_url and self.proxy_url != 'direct' else None
            async with session.request(method, url, headers=headers, proxy=proxy, **kwargs) as resp:
                data = await resp.json()

                if resp.status != 200:
                    self._raise_typed_error(data)

                return data
        except aiohttp.ClientError as e:
            raise Exception(f"网络错误: {str(e)}")

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

    async def get_premium_index(self, symbol: str) -> dict:
        """Get real-time mark price and funding rate (premiumIndex)"""
        return await self._request(
            "GET", "/fapi/v1/premiumIndex", params={"symbol": symbol}
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

    # Spot API endpoints

    async def get_spot_account(self) -> Dict[str, Any]:
        """Get spot account information"""
        return await self._request("GET", "/api/v3/account", signed=True, use_spot_api=True)

    async def get_margin_account(self) -> Dict[str, Any]:
        """Get cross margin account information - /sapi/v1/margin/account"""
        return await self._request("GET", "/sapi/v1/margin/account", signed=True, use_spot_api=True)

    async def get_spot_prices(self) -> list:
        """Get all spot ticker prices"""
        return await self._request("GET", "/api/v3/ticker/price", use_spot_api=True)

    async def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        """Get spot price for a specific symbol"""
        return await self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol}, use_spot_api=True)

    async def get_commission_rate(self, symbol: str = "XAUUSDT") -> Dict[str, Any]:
        """Get user commission rate for a symbol (maker/taker fee tier)"""
        return await self._request("GET", "/fapi/v1/commissionRate", signed=True, params={"symbol": symbol})

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        position_side: Optional[str] = None,
        post_only: bool = False,
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
            # GTX (Good Till Crossing): POST_ONLY mode, reject if order would be TAKER
            params["timeInForce"] = "GTX" if post_only else time_in_force

        if reduce_only:
            params["reduceOnly"] = "true"

        if position_side:
            params["positionSide"] = position_side.upper()

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

    async def get_user_trades(
        self,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> list:
        """Get account trade history"""
        params = {"symbol": symbol, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self._request("GET", "/fapi/v1/userTrades", signed=True, params=params)

    async def get_all_orders(
        self,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> list:
        """Get all orders (including filled, canceled, etc.)"""
        params = {"symbol": symbol, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self._request("GET", "/fapi/v1/allOrders", signed=True, params=params)
