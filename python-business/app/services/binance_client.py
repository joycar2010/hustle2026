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


async def validate_api_key(api_key: str, api_secret: str) -> ValidationResult:
    params = _sign({}, api_secret)
    try:
        async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
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


async def get_api_restrictions(api_key: str, api_secret: str) -> dict:
    """Query API key restrictions using the key's own credentials.
    Returns: ipRestrict, enableMargin, enableFutures, enableInternalTransfer,
    permitsUniversalTransfer, enableSpotAndMarginTrading, enableVanillaOptions, etc.
    """
    params = _sign({}, api_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.get(
            f"{SPOT_BASE}/sapi/v1/account/apiRestrictions",
            params=params,
            headers={"X-MBX-APIKEY": api_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()


async def get_sub_account_ip_restriction(
    master_key: str, master_secret: str, email: str, sub_account_api_key: str,
) -> dict:
    params = _sign({"email": email, "subAccountApiKey": sub_account_api_key}, master_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.get(
            f"{SPOT_BASE}/sapi/v1/sub-account/subAccountApi/ipRestriction",
            params=params,
            headers={"X-MBX-APIKEY": master_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()


async def update_sub_account_ip_restriction(
    master_key: str, master_secret: str, email: str, sub_account_api_key: str,
    ip_restrict: bool, ip_list: list[str] | None = None,
) -> dict:
    params: dict = {
        "email": email,
        "subAccountApiKey": sub_account_api_key,
        "status": "2" if ip_restrict else "1",
    }
    if ip_list:
        for i, ip in enumerate(ip_list):
            params[f"ipAddress[{i}]"] = ip
    params = _sign(params, master_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.post(
            f"{SPOT_BASE}/sapi/v2/sub-account/subAccountApi/ipRestriction",
            params=params,
            headers={"X-MBX-APIKEY": master_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()


async def delete_sub_account_ip(
    master_key: str, master_secret: str, email: str, sub_account_api_key: str,
    ip_address: str,
) -> dict:
    params = _sign({
        "email": email,
        "subAccountApiKey": sub_account_api_key,
        "ipAddress": ip_address,
    }, master_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.request(
            "DELETE",
            f"{SPOT_BASE}/sapi/v1/sub-account/subAccountApi/ipRestriction/ipList",
            params=params,
            headers={"X-MBX-APIKEY": master_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()
