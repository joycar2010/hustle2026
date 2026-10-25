"""Small, read-only client for Binance's public announcement CMS.

The CMS is fronted by CloudFront and occasionally returns a transient 403/429
for requests that do not look like a browser request.  Keep this client
side-effect free and bounded: announcement consumers must never turn a
temporary WAF response into an empty, authoritative announcement set.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

BINANCE_CMS_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
BINANCE_CMS_PARAMS = {
    "type": 1,
    "catalogId": 48,
    "pageNo": 1,
    "pageSize": 30,
}
BINANCE_CMS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://www.binance.com",
    "Referer": "https://www.binance.com/en/support/announcement",
}
_RETRYABLE_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}


class BinanceCmsError(RuntimeError):
    """The public CMS could not provide a valid article list."""


def _articles(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise BinanceCmsError("Binance CMS returned a non-object payload")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BinanceCmsError("Binance CMS response has no data object")
    catalogs = data.get("catalogs")
    if isinstance(catalogs, list) and catalogs:
        first = catalogs[0]
        if isinstance(first, dict) and isinstance(first.get("articles"), list):
            return [a for a in first["articles"] if isinstance(a, dict)]
    direct = data.get("articles")
    if isinstance(direct, list):
        return [a for a in direct if isinstance(a, dict)]
    raise BinanceCmsError("Binance CMS response has no article list")


def _request_error(response: httpx.Response) -> BinanceCmsError:
    # Do not include the HTML body: it can be large and sometimes contains
    # CloudFront request identifiers that are not useful to API callers.
    return BinanceCmsError(
        f"Binance CMS HTTP {response.status_code}"
    )


def fetch_articles_sync(*, page_size: int | None = None, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Fetch announcements for synchronous FastAPI admin handlers."""
    params = dict(BINANCE_CMS_PARAMS)
    if page_size is not None:
        params["pageSize"] = max(1, min(int(page_size), 100))
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout, headers=BINANCE_CMS_HEADERS) as client:
        for attempt in range(3):
            try:
                response = client.get(BINANCE_CMS_URL, params=params)
                if response.status_code in _RETRYABLE_STATUS:
                    raise _request_error(response)
                response.raise_for_status()
                return _articles(response.json())
            except (httpx.HTTPError, BinanceCmsError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
    raise BinanceCmsError(str(last_error or "request failed"))


async def fetch_articles(*, page_size: int | None = None, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Fetch announcements for async worker/orchestrator code."""
    params = dict(BINANCE_CMS_PARAMS)
    if page_size is not None:
        params["pageSize"] = max(1, min(int(page_size), 100))
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout, headers=BINANCE_CMS_HEADERS) as client:
        for attempt in range(3):
            try:
                response = await client.get(BINANCE_CMS_URL, params=params)
                if response.status_code in _RETRYABLE_STATUS:
                    raise _request_error(response)
                response.raise_for_status()
                return _articles(response.json())
            except (httpx.HTTPError, BinanceCmsError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
    raise BinanceCmsError(str(last_error or "request failed"))

