import asyncio
import hashlib
import hmac
import logging
import time
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"

_global_semaphore = asyncio.Semaphore(10)


class BinanceTradingClient:
    def __init__(self, api_key: str, api_secret: str, timeout: int = 10, proxy_url: str | None = None):
        self._api_key = api_key
        self._api_secret = api_secret
        self._timeout = timeout
        self._proxy_url = proxy_url
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(3)
        self._lot_cache: dict[str, dict] = {}

    async def __aenter__(self):
        kwargs = {"timeout": self._timeout}
        if self._proxy_url:
            kwargs["proxy"] = self._proxy_url
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._api_key}

    async def _request(self, method: str, url: str, params: dict = None, signed: bool = True) -> dict:
        if params is None:
            params = {}
        if signed:
            params = self._sign(params)
        async with _global_semaphore, self._semaphore:
            if method == "GET":
                resp = await self._client.get(url, params=params, headers=self._headers())
            elif method == "POST":
                resp = await self._client.post(url, params=params, headers=self._headers())
            elif method == "DELETE":
                resp = await self._client.delete(url, params=params, headers=self._headers())
            else:
                raise ValueError(f"Unsupported method: {method}")

            weight = resp.headers.get("X-MBX-USED-WEIGHT-1M") or resp.headers.get("X-MBX-USED-WEIGHT-1m")
            if weight and int(weight) > 1000:
                await asyncio.sleep(1)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                logger.warning(f"Rate limited, sleeping {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self._request(method, url, params, signed=False)

            if resp.status_code >= 400:
                data = resp.json()
                raise BinanceAPIError(resp.status_code, data.get("code", 0), data.get("msg", resp.text))

            return resp.json()

    # ---- Margin ----

    async def margin_borrow(self, asset: str, amount: Decimal) -> dict:
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/loan", {
            "asset": asset, "amount": str(amount),
        })

    async def margin_repay(self, asset: str, amount: Decimal) -> dict:
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/repay", {
            "asset": asset, "amount": str(amount),
        })

    async def get_margin_account(self) -> dict:
        return await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/account")

    async def get_margin_interest_rate(self, asset: str) -> Decimal:
        data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/interestRateHistory", {
            "asset": asset, "limit": "1",
        })
        if data and len(data) > 0:
            return Decimal(str(data[0].get("dailyInterestRate", "0")))
        return Decimal("0")

    # ---- Spot Orders ----

    async def spot_market_sell(self, symbol: str, quantity: Decimal) -> dict:
        return await self._request("POST", f"{SPOT_BASE}/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": str(quantity),
        })

    async def spot_market_buy_qty(self, symbol: str, quantity: Decimal) -> dict:
        return await self._request("POST", f"{SPOT_BASE}/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": str(quantity),
        })

    # ---- Futures Orders ----

    async def futures_market_long(self, symbol: str, quantity: Decimal) -> dict:
        return await self._request("POST", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": str(quantity),
        })

    async def futures_market_close(self, symbol: str, quantity: Decimal) -> dict:
        return await self._request("POST", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": str(quantity), "reduceOnly": "true",
        })

    async def get_futures_position(self, symbol: str) -> dict | None:
        data = await self._request("GET", f"{FUTURES_BASE}/fapi/v2/positionRisk", {
            "symbol": symbol,
        })
        for p in data:
            if p["symbol"] == symbol and float(p.get("positionAmt", 0)) != 0:
                return p
        return None

    async def get_futures_account(self) -> dict:
        return await self._request("GET", f"{FUTURES_BASE}/fapi/v2/account")

    # ---- Transfers ----

    async def transfer(self, transfer_type: str, asset: str, amount: Decimal) -> dict:
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/asset/transfer", {
            "type": transfer_type, "asset": asset, "amount": str(amount),
        })

    # ---- Utilities ----

    async def get_bnb_balance(self) -> dict:
        margin = await self.get_margin_account()
        bnb_margin = Decimal("0")
        for a in margin.get("userAssets", []):
            if a["asset"] == "BNB":
                bnb_margin = Decimal(str(a["free"]))
                break
        return {"margin": bnb_margin}

    async def get_funding_rate(self, symbol: str) -> Decimal:
        data = await self._request("GET", f"{FUTURES_BASE}/fapi/v1/premiumIndex", {
            "symbol": symbol,
        }, signed=False)
        return Decimal(str(data.get("lastFundingRate", "0")))

    async def get_lot_size(self, symbol: str, market: str = "spot") -> dict:
        cache_key = f"{market}:{symbol}"
        if cache_key in self._lot_cache:
            return self._lot_cache[cache_key]

        if market == "spot":
            data = await self._request("GET", f"{SPOT_BASE}/api/v3/exchangeInfo", {
                "symbol": symbol,
            }, signed=False)
        else:
            data = await self._request("GET", f"{FUTURES_BASE}/fapi/v1/exchangeInfo", signed=False)

        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        result = {
                            "stepSize": f["stepSize"],
                            "minQty": f["minQty"],
                            "maxQty": f["maxQty"],
                        }
                        self._lot_cache[cache_key] = result
                        return result
        return {"stepSize": "0.001", "minQty": "0.001", "maxQty": "999999"}


class BinanceAPIError(Exception):
    def __init__(self, http_code: int, api_code: int, message: str):
        self.http_code = http_code
        self.api_code = api_code
        self.message = message
        super().__init__(f"Binance API error [{http_code}] code={api_code}: {message}")
