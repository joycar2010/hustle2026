import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx

from app.config import settings

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"


@dataclass
class ValidationResult:
    is_valid: bool
    can_trade: bool = False
    can_withdraw: bool = False
    permissions: list[str] | None = None
    error: str | None = None


def _sign(params: dict, secret: str) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


async def validate_api_key(api_key: str, api_secret: str, proxy_url: str | None = None) -> ValidationResult:
    params = _sign({}, api_secret)
    effective_proxy = proxy_url or settings.proxy_url
    client_kwargs = {"timeout": settings.binance_api_timeout}
    if effective_proxy:
        client_kwargs["proxy"] = effective_proxy
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                f"{SPOT_BASE}/api/v3/account",
                params=params,
                headers={"X-MBX-APIKEY": api_key},
            )
        if resp.status_code != 200:
            data = resp.json()
            return ValidationResult(is_valid=False, error=data.get("msg", f"HTTP {resp.status_code}"))
        data = resp.json()
        return ValidationResult(
            is_valid=True,
            can_trade=data.get("canTrade", False),
            can_withdraw=data.get("canWithdraw", False),
            permissions=data.get("permissions", []),
        )
    except httpx.TimeoutException:
        return ValidationResult(is_valid=False, error="Request timeout")
    except Exception as e:
        return ValidationResult(is_valid=False, error=str(e))


async def fetch_spot_exchange_info() -> list[dict]:
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.get(f"{SPOT_BASE}/api/v3/exchangeInfo")
        resp.raise_for_status()
        data = resp.json()

    results = []
    for s in data.get("symbols", []):
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
            results.append({
                "symbol": s["symbol"],
                "base_asset": s["baseAsset"],
                "quote_asset": s["quoteAsset"],
                "is_margin": s.get("isMarginTradingAllowed", False),
            })
    return results


async def fetch_futures_exchange_info() -> list[dict]:
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.get(f"{FUTURES_BASE}/fapi/v1/exchangeInfo")
        resp.raise_for_status()
        data = resp.json()

    results = []
    for s in data.get("symbols", []):
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
            results.append({
                "symbol": s["symbol"],
                "base_asset": s["baseAsset"],
                "quote_asset": s["quoteAsset"],
            })
    return results
