"""Permission-aware Binance wallet reads.

Sub-accounts can have spot/margin enabled without futures permission.  Keeping
the wallet calls in one helper prevents an unavailable wallet from aborting the
whole balance snapshot (and keeps API error messages free of credentials).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


_EMPTY_SPOT: dict[str, Any] = {"balances": []}
_EMPTY_MARGIN: dict[str, Any] = {
    "userAssets": [],
    "marginLevel": "0",
    "totalNetAssetOfBtc": "0",
}
_EMPTY_FUTURES: dict[str, Any] = {}
_EMPTY_FUNDING: list[Any] = []
_EMPTY_EARN: dict[str, Any] = {"totalAmountInUSDT": "0", "rows": []}


@dataclass
class WalletFetchResult:
    """Wallet payloads plus errors for enabled calls that failed."""

    spot: dict[str, Any] = field(default_factory=lambda: dict(_EMPTY_SPOT))
    margin: dict[str, Any] = field(default_factory=lambda: dict(_EMPTY_MARGIN))
    futures: dict[str, Any] = field(default_factory=lambda: dict(_EMPTY_FUTURES))
    funding: list[Any] = field(default_factory=list)
    earn: dict[str, Any] = field(default_factory=lambda: dict(_EMPTY_EARN))
    errors: dict[str, BaseException] = field(default_factory=dict)


async def fetch_wallets(
    client: Any,
    *,
    spot_enabled: bool = True,
    margin_enabled: bool = True,
    futures_enabled: bool = True,
) -> WalletFetchResult:
    """Fetch only wallets authorized for an account.

    Spot, margin and futures are required calls when their corresponding
    permission flag is enabled; failures are recorded independently so a
    disabled or unavailable wallet cannot cancel sibling requests. Funding and
    Simple Earn are optional display data and always degrade to an empty value.
    """

    result = WalletFetchResult()

    async def _call(
        name: str,
        enabled: bool,
        fn: Callable[[], Awaitable[Any]],
        default: Any,
        *,
        required: bool,
    ) -> Any:
        if not enabled:
            return default
        try:
            return await fn()
        except Exception as exc:  # preserve sibling calls on API errors
            if required:
                result.errors[name] = exc
            return default

    # Keep concurrency bounded by the client's own semaphore while allowing a
    # failing futures call to coexist with successful spot/margin requests.
    spot, margin, futures, funding, earn = await asyncio.gather(
        _call("spot", spot_enabled, client.get_spot_account, dict(_EMPTY_SPOT), required=True),
        _call("margin", margin_enabled, client.get_margin_account, dict(_EMPTY_MARGIN), required=True),
        _call("futures", futures_enabled, client.get_futures_account, dict(_EMPTY_FUTURES), required=True),
        _call("funding", spot_enabled, client.get_funding_account, list(_EMPTY_FUNDING), required=False),
        _call("earn", spot_enabled, client.get_simple_earn_account, dict(_EMPTY_EARN), required=False),
    )
    result.spot = spot if isinstance(spot, dict) else dict(_EMPTY_SPOT)
    result.margin = margin if isinstance(margin, dict) else dict(_EMPTY_MARGIN)
    result.futures = futures if isinstance(futures, dict) else dict(_EMPTY_FUTURES)
    result.funding = funding if isinstance(funding, list) else list(_EMPTY_FUNDING)
    result.earn = earn if isinstance(earn, dict) else dict(_EMPTY_EARN)
    return result


def wallet_error_detail(errors: dict[str, BaseException]) -> str:
    """Return a safe, actionable detail without echoing Binance credentials."""

    if not errors:
        return "Binance wallet query failed"
    for wallet, exc in errors.items():
        code = getattr(exc, "api_code", getattr(exc, "code", None))
        try:
            code_int = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_int = None
        if code_int == -2015 or "-2015" in str(exc):
            return f"Binance {wallet} wallet unavailable: API key/IP/permissions denied (-2015)"
        if code_int is not None:
            return f"Binance {wallet} wallet query failed (API error {code_int})"
        return f"Binance {wallet} wallet query failed"
    return "Binance wallet query failed"
