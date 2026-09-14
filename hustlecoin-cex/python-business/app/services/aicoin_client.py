import base64
import hashlib
import hmac
import time
import uuid

import httpx


class AiCoinClient:

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign_params(self) -> dict:
        nonce = uuid.uuid4().hex[:16]
        ts = str(int(time.time()))
        sign_str = f"AccessKeyId={self.api_key}&SignatureNonce={nonce}&Timestamp={ts}"
        digest = hmac.new(
            self.api_secret.encode(), sign_str.encode(), hashlib.sha1
        ).hexdigest()
        signature = base64.b64encode(digest.encode()).decode()
        return {
            "AccessKeyId": self.api_key,
            "SignatureNonce": nonce,
            "Timestamp": ts,
            "Signature": signature,
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        all_params = self._sign_params()
        if params:
            all_params.update(params)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://open.aicoin.com{path}", params=all_params)
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success", True) and body.get("errorCode") not in (200, None):
                raise Exception(f"AiCoin error {body.get('errorCode')}: {body.get('error')}")
            return body

    async def get_kline(self, symbol: str, period: str, size: int = 200) -> list:
        data = await self._get("/api/v2/commonKline/dataRecords", {
            "symbol": symbol,
            "period": period,
            "size": str(min(size, 500)),
        })
        kline = data.get("data", {})
        if isinstance(kline, dict):
            return kline.get("kline_data", [])
        return kline if isinstance(kline, list) else []

    async def get_coin_ticker(self, coin_list: str) -> list:
        data = await self._get("/api/v2/coin/ticker", {"coin_list": coin_list})
        result = data.get("data", [])
        return result if isinstance(result, list) else []

    async def get_coin_list(self) -> list:
        data = await self._get("/api/v2/coin")
        result = data.get("data", [])
        return result if isinstance(result, list) else []

    async def search_coin(self, keyword: str) -> list:
        data = await self._get("/api/upgrade/v2/coin/search", {
            "search": keyword,
            "page": "1",
            "page_size": "20",
        })
        result = data.get("data", {})
        if isinstance(result, dict):
            return result.get("list", [])
        return result if isinstance(result, list) else []
