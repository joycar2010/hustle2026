"""Bitget V2 API client — futures, spot, and margin endpoints."""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from app.core.config import settings

logger = logging.getLogger(__name__)

TERMINAL_ERRORS = {
    '40001', '40002', '40003', '40004', '40005',  # auth / signature
    '40006', '40007', '40009',                      # permission / IP
    '43011', '43012',                                # API key disabled
}


class BitgetClient:
    """Async client for Bitget V2 REST API (futures + spot + margin)."""

    BASE_URL = "https://api.bitget.com"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        proxy_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.proxy_url = proxy_url
        self.base_url = getattr(settings, 'BITGET_API_BASE', self.BASE_URL)
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_sem = asyncio.Semaphore(8)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Authentication ────────────────────────────────────────

    def _sign(self, timestamp: str, method: str, path: str,
              query_string: str = "", body: str = "") -> str:
        prehash = timestamp + method.upper() + path
        if query_string:
            prehash += "?" + query_string
        prehash += body
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    # ── Core request ──────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        signed: bool = False,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}

        query_string = ""
        body_str = ""
        if method.upper() == "GET" and params:
            sorted_params = sorted(params.items(), key=lambda x: x[0])
            query_string = urlencode(sorted_params)
            url = f"{url}?{query_string}"
            params = None
        if json_body:
            body_str = json.dumps(json_body)

        if signed:
            ts = str(int(time.time() * 1000))
            sig = self._sign(ts, method.upper(), path, query_string, body_str)
            headers.update({
                "ACCESS-KEY": self.api_key,
                "ACCESS-SIGN": sig,
                "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": self.passphrase,
            })

        raw_proxy = self.proxy_url if self.proxy_url and self.proxy_url != 'direct' else (
            getattr(settings, 'HTTPS_PROXY', None) or getattr(settings, 'HTTP_PROXY', None)
        )
        proxy = None
        proxy_auth = None
        if raw_proxy:
            from urllib.parse import urlparse
            parsed = urlparse(raw_proxy)
            if parsed.username and parsed.password:
                proxy = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
                proxy_auth = aiohttp.BasicAuth(parsed.username, parsed.password)
            else:
                proxy = raw_proxy

        session = await self._get_session()
        async with self._rate_sem:
            try:
                kwargs: Dict[str, Any] = {"headers": headers, "proxy": proxy, "proxy_auth": proxy_auth}
                if json_body:
                    kwargs["data"] = body_str
                async with session.request(method, url, **kwargs) as resp:
                    data = await resp.json()
                    logger.debug(f"Bitget {method} {path} → {resp.status}")

                    if resp.status == 429:
                        logger.warning(f"Bitget rate limited on {path}")
                        return {"code": "429", "msg": "rate_limited", "data": None}

                    code = str(data.get("code", "0"))
                    if code != "00000" and code != "0":
                        msg = data.get("msg", "unknown_error")
                        if code in TERMINAL_ERRORS:
                            logger.error(f"Bitget terminal error {code}: {msg} on {path}")
                        else:
                            logger.warning(f"Bitget API error {code}: {msg} on {path}")
                        return data

                    return data
            except aiohttp.ClientError as e:
                logger.error(f"Bitget request failed: {e} on {method} {path}")
                return {"code": "NETWORK", "msg": str(e), "data": None}
            finally:
                await asyncio.sleep(0.1)

    def _ok(self, data: Dict) -> bool:
        return str(data.get("code", "")) in ("00000", "0")

    # ── Futures market data (public) ──────────────────────────

    async def get_ticker(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/market/ticker",
                                   params={"symbol": symbol, "productType": product_type})

    async def get_tickers(self, product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/market/tickers",
                                   params={"productType": product_type})

    async def get_orderbook(self, symbol: str, limit: int = 15,
                            product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/market/merge-depth",
                                   params={"symbol": symbol, "productType": product_type, "limit": str(limit)})

    async def get_funding_rate(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/market/current-fund-rate",
                                   params={"symbol": symbol, "productType": product_type})

    async def get_contracts(self, product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/market/contracts",
                                   params={"productType": product_type})

    async def get_candles(self, symbol: str, granularity: str = "1H",
                          limit: int = 100, product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/market/candles",
                                   params={"symbol": symbol, "productType": product_type,
                                           "granularity": granularity, "limit": str(limit)})

    # ── Futures account (private) ─────────────────────────────

    async def get_account(self, symbol: str, margin_coin: str = "USDT",
                          product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/account/account", signed=True,
                                   params={"symbol": symbol, "productType": product_type,
                                           "marginCoin": margin_coin})

    async def get_accounts(self, product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/account/accounts", signed=True,
                                   params={"productType": product_type})

    async def set_leverage(self, symbol: str, leverage: int,
                           margin_coin: str = "USDT",
                           product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("POST", "/api/v2/mix/account/set-leverage", signed=True,
                                   json_body={"symbol": symbol, "productType": product_type,
                                              "marginCoin": margin_coin, "leverage": str(leverage)})

    async def set_margin_mode(self, symbol: str, margin_mode: str = "crossed",
                              margin_coin: str = "USDT",
                              product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("POST", "/api/v2/mix/account/set-margin-mode", signed=True,
                                   json_body={"symbol": symbol, "productType": product_type,
                                              "marginCoin": margin_coin, "marginMode": margin_mode})

    # ── Futures positions (private) ───────────────────────────

    async def get_positions(self, product_type: str = "USDT-FUTURES",
                            margin_coin: str = "USDT") -> Dict:
        return await self._request("GET", "/api/v2/mix/position/all-position", signed=True,
                                   params={"productType": product_type, "marginCoin": margin_coin})

    async def get_single_position(self, symbol: str,
                                  product_type: str = "USDT-FUTURES",
                                  margin_coin: str = "USDT") -> Dict:
        return await self._request("GET", "/api/v2/mix/position/single-position", signed=True,
                                   params={"symbol": symbol, "productType": product_type,
                                           "marginCoin": margin_coin})

    # ── Futures trading (private) ─────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        trade_side: str = "open",
        order_type: str = "limit",
        size: str = "",
        price: Optional[str] = None,
        margin_coin: str = "USDT",
        product_type: str = "USDT-FUTURES",
        force: str = "gtc",
        client_oid: Optional[str] = None,
    ) -> Dict:
        body: Dict[str, Any] = {
            "symbol": symbol,
            "productType": product_type,
            "marginCoin": margin_coin,
            "side": side.lower(),
            "tradeSide": trade_side.lower(),
            "orderType": order_type.lower(),
            "size": str(size),
            "force": force,
        }
        if price is not None:
            body["price"] = str(price)
        if client_oid:
            body["clientOid"] = client_oid
        return await self._request("POST", "/api/v2/mix/order/place-order",
                                   signed=True, json_body=body)

    async def cancel_order(self, symbol: str, order_id: str,
                           product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("POST", "/api/v2/mix/order/cancel-order", signed=True,
                                   json_body={"symbol": symbol, "productType": product_type,
                                              "orderId": order_id})

    async def get_order(self, symbol: str, order_id: str,
                        product_type: str = "USDT-FUTURES") -> Dict:
        return await self._request("GET", "/api/v2/mix/order/detail", signed=True,
                                   params={"symbol": symbol, "productType": product_type,
                                           "orderId": order_id})

    async def get_open_orders(self, symbol: str = "",
                              product_type: str = "USDT-FUTURES") -> Dict:
        params: Dict[str, str] = {"productType": product_type}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/api/v2/mix/order/orders-pending",
                                   signed=True, params=params)

    async def get_fills(self, symbol: str = "", product_type: str = "USDT-FUTURES",
                        limit: int = 50) -> Dict:
        params: Dict[str, str] = {"productType": product_type, "limit": str(limit)}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/api/v2/mix/order/fills",
                                   signed=True, params=params)

    # ── Spot market (public) ──────────────────────────────────

    async def get_spot_ticker(self, symbol: str) -> Dict:
        return await self._request("GET", "/api/v2/spot/market/tickers",
                                   params={"symbol": symbol})

    async def get_spot_symbols(self, symbol: str = "") -> Dict:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/api/v2/spot/public/symbols", params=params or None)

    # ── Spot account (private) ────────────────────────────────

    async def get_spot_account(self, coin: Optional[str] = None) -> Dict:
        params = {}
        if coin:
            params["coin"] = coin
        return await self._request("GET", "/api/v2/spot/account/assets",
                                   signed=True, params=params or None)

    # ── Margin borrow / repay (private) ───────────────────────

    async def margin_borrow(self, coin: str, amount: str,
                            symbol: Optional[str] = None,
                            margin_type: str = "isolated") -> Dict:
        body: Dict[str, str] = {"coin": coin, "borrowAmount": str(amount)}
        if margin_type == "isolated" and symbol:
            body["symbol"] = symbol
        return await self._request("POST", f"/api/v2/margin/{margin_type}/account/borrow",
                                   signed=True, json_body=body)

    async def margin_repay(self, coin: str, amount: str,
                           symbol: Optional[str] = None,
                           margin_type: str = "isolated") -> Dict:
        body: Dict[str, str] = {"coin": coin, "repayAmount": str(amount)}
        if margin_type == "isolated" and symbol:
            body["symbol"] = symbol
        return await self._request("POST", f"/api/v2/margin/{margin_type}/account/repay",
                                   signed=True, json_body=body)

    async def get_margin_account(self, symbol: Optional[str] = None,
                                 margin_type: str = "isolated") -> Dict:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", f"/api/v2/margin/{margin_type}/account/assets",
                                   signed=True, params=params or None)

    async def place_margin_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "limit",
        base_quantity: Optional[str] = None,
        quote_amount: Optional[str] = None,
        price: Optional[str] = None,
        margin_type: str = "isolated",
        loan_type: str = "normal",
        time_in_force: str = "gtc",
    ) -> Dict:
        body: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.lower(),
            "orderType": order_type.lower(),
            "loanType": loan_type,
            "timeInForce": time_in_force,
        }
        if base_quantity:
            body["baseQuantity"] = str(base_quantity)
        if quote_amount:
            body["quoteAmount"] = str(quote_amount)
        if price:
            body["price"] = str(price)
        return await self._request("POST", f"/api/v2/margin/{margin_type}/place-order",
                                   signed=True, json_body=body)

    async def get_margin_max_borrowable(self, coin: str,
                                        symbol: Optional[str] = None,
                                        margin_type: str = "isolated") -> Dict:
        body: Dict[str, str] = {"coin": coin}
        if symbol:
            body["symbol"] = symbol
        return await self._request("POST",
                                   f"/api/v2/margin/{margin_type}/account/max-borrowable-amount",
                                   signed=True, json_body=body)
