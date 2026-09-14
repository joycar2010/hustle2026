import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

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
    # 用 urlencode 算签名,与 httpx 实际发送的 query 编码一致;否则含特殊字符的参数
    # (如子账户 email 的 @ → %40)签名串与发送串不符 → 币安拒"Signature not valid"。
    query = urlencode(params)
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


async def get_api_restrictions(api_key: str, api_secret: str) -> dict:
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


async def get_ip_restriction(api_key: str, api_secret: str) -> dict:
    # /account/apiRestrictions/ipRestriction 查"自己 key"的 IP 限制,只需签名参数(无需 apiKey)。
    # 注:子账户 key 调此接口币安会拒("accountApiKey should not null"——该接口要求母账户/普通用户
    # key;子账户 IP 限制须母账户走 /sub-account/subAccountApi/ipRestriction 查)。失败由上层优雅降级。
    params = _sign({}, api_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.get(
            f"{SPOT_BASE}/sapi/v1/account/apiRestrictions/ipRestriction",
            params=params,
            headers={"X-MBX-APIKEY": api_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()


async def get_sub_ip_restriction(master_key: str, master_secret: str, sub_email: str, sub_api_key: str) -> dict:
    """母账户查子账户 API key 的 IP 限制(子账户 key 自身无权查 /account/apiRestrictions)。
    返回 {ipRestrict, ipList, ...};参数缺失或母账户未开权限会失败,由上层降级。"""
    params = _sign({"email": sub_email, "subAccountApiKey": sub_api_key}, master_secret)
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


async def add_ip_restriction(api_key: str, api_secret: str, ip_list: list[str]) -> dict:
    params = _sign({
        "ipRestrict": "true",
        "ipAddress": ",".join(ip_list),
    }, api_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.post(
            f"{SPOT_BASE}/sapi/v1/account/apiRestrictions/ipRestriction",
            params=params,
            headers={"X-MBX-APIKEY": api_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()


async def remove_ip_restriction(api_key: str, api_secret: str, ip: str) -> dict:
    params = _sign({"ipAddress": ip}, api_secret)
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.delete(
            f"{SPOT_BASE}/sapi/v1/account/apiRestrictions/ipRestriction",
            params=params,
            headers={"X-MBX-APIKEY": api_key},
        )
    if resp.status_code != 200:
        data = resp.json()
        raise Exception(data.get("msg", f"HTTP {resp.status_code}"))
    return resp.json()


async def get_server_ip() -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get("https://api.ipify.org?format=json")
        return resp.json().get("ip", "")


async def fetch_spot_exchange_info() -> list[dict]:
    async with httpx.AsyncClient(timeout=settings.binance_api_timeout) as client:
        resp = await client.get(f"{SPOT_BASE}/api/v3/exchangeInfo")
        if resp.status_code != 200:
            raise RuntimeError(f"Binance spot API returned {resp.status_code}: {resp.text[:200]}")
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
        if resp.status_code != 200:
            raise RuntimeError(f"Binance futures API returned {resp.status_code}: {resp.text[:200]}")
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
