"""Bybit V5 API client"""
import hmac
import hashlib
import time
import logging
from typing import Dict, Any, Optional
import aiohttp
from app.core.config import settings

logger = logging.getLogger(__name__)


class BybitV5Client:
    """Async client for Bybit V5 API"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = settings.BYBIT_API_BASE
        # MT5 API 使用相同的域名，只是端点路径不同
        self.mt5_base_url = settings.BYBIT_API_BASE
        self.session: Optional[aiohttp.ClientSession] = None
        self.recv_window = "5000"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            # Configure proxy if available
            connector = None
            if settings.HTTP_PROXY or settings.HTTPS_PROXY:
                proxy_url = settings.HTTPS_PROXY or settings.HTTP_PROXY
                logger.info(f"Using proxy: {proxy_url}")
                connector = aiohttp.TCPConnector(ssl=False)  # Disable SSL verification for proxy

            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()

    def _sign(self, timestamp: str, params: str) -> str:
        """Generate HMAC SHA256 signature for V5 API"""
        param_str = timestamp + self.api_key + self.recv_window + params
        return hmac.new(
            self.api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        endpoint: str,
        signed: bool = False,
        use_mt5_base: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make HTTP request to Bybit API"""
        base = self.mt5_base_url if use_mt5_base else self.base_url
        url = f"{base}{endpoint}"
        headers = {"Content-Type": "application/json"}

        if signed:
            timestamp = str(int(time.time() * 1000))

            # Prepare params string for signature
            if method == "GET":
                params = kwargs.get("params", {})
                # Convert all parameter values to strings and sort alphabetically
                sorted_params = sorted(params.items(), key=lambda x: x[0])
                param_str = "&".join([f"{k}={v}" for k, v in sorted_params])
                # Ensure all values in params are strings for the actual request
                from collections import OrderedDict
                kwargs["params"] = OrderedDict([(k, str(v)) for k, v in sorted_params])
            else:
                import json
                param_str = json.dumps(kwargs.get("json", {})) if kwargs.get("json") else ""

            signature = self._sign(timestamp, param_str)

            headers.update({
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": signature,
                "X-BAPI-RECV-WINDOW": self.recv_window,
            })

        session = await self._get_session()

        # Configure proxy if available
        proxy = settings.HTTPS_PROXY or settings.HTTP_PROXY or None

        try:
            async with session.request(method, url, headers=headers, proxy=proxy, **kwargs) as resp:
                data = await resp.json()

                # Log all Bybit API requests and responses for debugging
                logger.info(f"Bybit API Request: {method} {url}")
                logger.info(f"Request params: {kwargs.get('params', {})}")
                logger.info(f"Response: {data}")

                # Handle None response
                if data is None:
                    logger.error(f"Bybit API returned None response")
                    logger.error(f"Request URL: {url}")
                    logger.error(f"Request params: {kwargs.get('params', {})}")
                    logger.error(f"Response status: {resp.status}")
                    raise Exception("Bybit API returned empty response")

                # Log Bybit API response for debugging
                if data.get("retCode") != 0:
                    logger.error(f"Bybit API error: {data.get('retMsg', 'Unknown error')}")
                    logger.error(f"Request URL: {url}")
                    logger.error(f"Request params: {kwargs.get('params', {})}")
                    logger.error(f"Full response: {data}")

                if data.get("retCode") != 0:
                    raise Exception(f"Bybit API error: {data.get('retMsg', 'Unknown error')}")

                return data.get("result", {})
        except aiohttp.ClientError as e:
            logger.error(f"Network error calling Bybit API: {str(e)}")
            raise Exception(f"Network error: {str(e)}")

    # Public endpoints (no authentication required)

    async def get_server_time(self) -> Dict[str, Any]:
        """Get server time"""
        return await self._request("GET", "/v5/market/time")

    async def get_tickers(self, category: str, symbol: str) -> Dict[str, Any]:
        """Get latest ticker information

        Args:
            category: Product type (linear, inverse, spot, option)
            symbol: Symbol name (e.g., XAUUSDT)
        """
        params = {"category": category, "symbol": symbol}
        return await self._request("GET", "/v5/market/tickers", params=params)

    async def get_orderbook(self, category: str, symbol: str, limit: int = 25) -> Dict[str, Any]:
        """Get orderbook data"""
        params = {"category": category, "symbol": symbol, "limit": limit}
        return await self._request("GET", "/v5/market/orderbook", params=params)

    async def get_klines(
        self,
        category: str,
        symbol: str,
        interval: str,
        limit: int = 200,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get kline/candlestick data"""
        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        return await self._request("GET", "/v5/market/kline", params=params)

    async def get_funding_rate(
        self,
        category: str,
        symbol: str,
        limit: int = 1,
    ) -> Dict[str, Any]:
        """Get funding rate history"""
        params = {"category": category, "symbol": symbol, "limit": limit}
        return await self._request("GET", "/v5/market/funding/history", params=params)

    # Private endpoints (authentication required)

    async def get_wallet_balance(self, account_type: str = "UNIFIED", coin: str = "USDT") -> Dict[str, Any]:
        """Get wallet balance

        Args:
            account_type: Account type (UNIFIED, CONTRACT, SPOT)
            coin: Coin name (default: USDT)
        """
        params = {"accountType": account_type, "coin": coin}
        return await self._request("GET", "/v5/account/wallet-balance", signed=True, params=params)

    async def get_positions(
        self,
        category: str,
        symbol: Optional[str] = None,
        settle_coin: str = "USDT",
    ) -> Dict[str, Any]:
        """Get position information

        Args:
            category: Product type (linear, inverse)
            symbol: Symbol name (optional)
            settle_coin: Settle coin (default: USDT)
        """
        params = {"category": category, "settleCoin": settle_coin}
        if symbol:
            params["symbol"] = symbol

        return await self._request("GET", "/v5/position/list", signed=True, params=params)

    async def get_account_info(self, coin: str = "USDT") -> Dict[str, Any]:
        """Get account information including risk ratio

        Args:
            coin: Coin name (default: USDT)
        """
        params = {"coin": coin}
        return await self._request("GET", "/v5/account/info", signed=True, params=params)

    async def get_transaction_log(
        self,
        account_type: str = "UNIFIED",
        category: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get transaction log (P&L history)"""
        params = {"accountType": account_type, "limit": limit}
        if category:
            params["category"] = category
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return await self._request("GET", "/v5/account/transaction-log", signed=True, params=params)

    async def get_fee_rate(self, category: str, symbol: str) -> Dict[str, Any]:
        """Get trading fee rate"""
        params = {"category": category, "symbol": symbol}
        return await self._request("GET", "/v5/account/fee-rate", signed=True, params=params)

    async def place_order(
        self,
        category: str,
        symbol: str,
        side: str,
        order_type: str,
        qty: str,
        price: Optional[str] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        close_on_trigger: bool = False,
    ) -> Dict[str, Any]:
        """Place a new order"""
        data = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": qty,
        }

        if order_type == "Limit":
            if price is None:
                raise ValueError("Price is required for Limit orders")
            data["price"] = price
            data["timeInForce"] = time_in_force

        if reduce_only:
            data["reduceOnly"] = True

        if close_on_trigger:
            data["closeOnTrigger"] = True

        return await self._request("POST", "/v5/order/create", signed=True, json=data)

    async def cancel_order(
        self,
        category: str,
        symbol: str,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancel an active order"""
        if not order_id and not order_link_id:
            raise ValueError("Either order_id or order_link_id is required")

        data = {"category": category, "symbol": symbol}
        if order_id:
            data["orderId"] = order_id
        if order_link_id:
            data["orderLinkId"] = order_link_id

        return await self._request("POST", "/v5/order/cancel", signed=True, json=data)

    async def get_order(
        self,
        category: str,
        symbol: str,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query order status"""
        if not order_id and not order_link_id:
            raise ValueError("Either order_id or order_link_id is required")

        params = {"category": category, "symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if order_link_id:
            params["orderLinkId"] = order_link_id

        return await self._request("GET", "/v5/order/realtime", signed=True, params=params)

    async def get_open_orders(
        self,
        category: str,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get all open orders"""
        params = {"category": category, "limit": limit}
        if symbol:
            params["symbol"] = symbol

        return await self._request("GET", "/v5/order/realtime", signed=True, params=params)

    async def cancel_all_orders(
        self,
        category: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancel all open orders"""
        data = {"category": category}
        if symbol:
            data["symbol"] = symbol

        return await self._request("POST", "/v5/order/cancel-all", signed=True, json=data)

    async def get_profit_loss(
        self,
        category: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        settle_coin: str = "USDT",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get closed P&L records from /v5/position/closed-pnl

        Args:
            category: Product type (linear, inverse)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            settle_coin: Settle coin (default: USDT)
            limit: Limit for data size per page. [1, 100]. Default: 50
        """
        params = {"category": category, "settleCoin": settle_coin, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return await self._request("GET", "/v5/position/closed-pnl", signed=True, params=params)

    async def get_funding_fee(
        self,
        category: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        settle_coin: str = "USDT",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get funding fee history from /v5/account/funding-fee

        Args:
            category: Product type (linear, inverse)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            settle_coin: Settle coin (default: USDT)
            limit: Limit for data size per page. [1, 200]. Default: 50
        """
        params = {"category": category, "settleCoin": settle_coin, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return await self._request("GET", "/v5/account/funding-fee", signed=True, params=params)

    # TRADFI MT5 API endpoints

    async def get_mt5_account_balance(self, mt5_account: str) -> Dict[str, Any]:
        """Get MT5 account balance from TRADFI MT5 API

        Args:
            mt5_account: MT5 account number

        Returns:
            Dict with balance, equity, freeMargin, marginUsed, marginBalance, unrealizedPnl, marginLevel
        """
        params = {"mt5Account": mt5_account}
        return await self._request("GET", "/asset/v1/mt5/account/balance", signed=True, use_mt5_base=True, params=params)

    async def get_mt5_position_list(
        self,
        mt5_account: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get MT5 position list from TRADFI MT5 API

        Args:
            mt5_account: MT5 account number
            symbol: Optional symbol filter (e.g., XAUUSD)

        Returns:
            Dict with list of positions
        """
        params = {"mt5Account": mt5_account}
        if symbol:
            params["symbol"] = symbol

        return await self._request("GET", "/asset/v1/mt5/position/list", signed=True, use_mt5_base=True, params=params)

    async def get_mt5_transaction_list(
        self,
        mt5_account: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        transaction_type: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get MT5 transaction list (fees, swap, commission) from TRADFI MT5 API

        Args:
            mt5_account: MT5 account number
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            transaction_type: Transaction type (SWAP, COMMISSION, FUNDING_FEE)
            limit: Limit for data size per page

        Returns:
            Dict with list of transactions
        """
        params = {"mt5Account": mt5_account, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if transaction_type:
            params["type"] = transaction_type

        return await self._request("GET", "/asset/v1/mt5/transaction/list", signed=True, use_mt5_base=True, params=params)

    async def get_mt5_order_history(
        self,
        mt5_account: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get MT5 order history from TRADFI MT5 API

        Args:
            mt5_account: MT5 account number
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            limit: Limit for data size per page

        Returns:
            Dict with list of orders
        """
        params = {"mt5Account": mt5_account, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return await self._request("GET", "/asset/v1/mt5/order/history", signed=True, use_mt5_base=True, params=params)
