"""Fail-closed polling for Binance's account-scoped margin inventory.

The endpoint returns every asset in one UID-weighted request.  Callers pass
their current candidate set only to suppress unnecessary polling; snapshots
are never filtered to that set.  A probe says only that pool inventory exists,
not that collateral, VIP limits, spread rules, or order guards permit a borrow.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Awaitable, Callable, Iterable, Mapping, Protocol


logger = logging.getLogger(__name__)

# Binance returns every asset in one account-scoped response. Keep one
# account-wide cadence and divide its display allocation across candidates.
DEFAULT_INVENTORY_PROBE_RATE = 2.0
MAX_INVENTORY_PROBE_RATE = 10.0
_ZERO = Decimal("0")
_EMPTY_ASSETS: Mapping[str, Decimal] = MappingProxyType({})


class InventoryClient(Protocol):
    async def get_margin_available_inventory(self) -> dict: ...


class InventoryProbeError(RuntimeError):
    """The latest inventory request cannot prove that inventory is usable."""


class MalformedInventoryResponse(InventoryProbeError):
    """Binance returned an invalid or unsafe inventory snapshot."""


@dataclass(frozen=True)
class InventorySnapshot:
    """One complete response from ``available-inventory``.

    ``healthy=False`` is deliberately equivalent to zero inventory.  This
    prevents a previous positive response from surviving a timeout, 429, or
    malformed follow-up response.
    """

    assets: Mapping[str, Decimal]
    update_time_ms: int | None
    observed_at: float
    healthy: bool
    error: str | None = None

    def amount_for(self, asset: object) -> Decimal:
        if not self.healthy:
            return _ZERO
        key = str(asset or "").strip().upper()
        return self.assets.get(key, _ZERO)

    def has_inventory(self, asset: object, minimum: Decimal = _ZERO) -> bool:
        """Return true only for a healthy, positive amount above ``minimum``."""
        amount = self.amount_for(asset)
        return amount > _ZERO and amount >= minimum


def _closed_snapshot(now: float, reason: str) -> InventorySnapshot:
    return InventorySnapshot(
        assets=_EMPTY_ASSETS,
        update_time_ms=None,
        observed_at=now,
        healthy=False,
        error=reason,
    )


def _parse_update_time(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("updateTime must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError("updateTime must be an integer")
    if parsed <= 0:
        raise ValueError("updateTime must be positive")
    return parsed


def parse_inventory_snapshot(payload: object, observed_at: float) -> InventorySnapshot:
    """Validate the entire payload before exposing any positive amount."""
    if not isinstance(payload, dict):
        raise MalformedInventoryResponse("inventory response must be an object")

    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, dict):
        raise MalformedInventoryResponse("inventory assets must be an object")

    try:
        update_time_ms = _parse_update_time(payload.get("updateTime"))
    except (TypeError, ValueError) as exc:
        raise MalformedInventoryResponse(str(exc)) from exc

    assets: dict[str, Decimal] = {}
    for raw_asset, raw_amount in raw_assets.items():
        if not isinstance(raw_asset, str) or not raw_asset.strip():
            raise MalformedInventoryResponse("inventory asset name is invalid")
        asset = raw_asset.strip().upper()
        if asset in assets:
            raise MalformedInventoryResponse(
                f"inventory contains duplicate asset {asset}"
            )
        if isinstance(raw_amount, bool):
            raise MalformedInventoryResponse(
                f"inventory amount for {asset} is invalid"
            )
        try:
            amount = Decimal(str(raw_amount).strip())
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise MalformedInventoryResponse(
                f"inventory amount for {asset} is invalid"
            ) from exc
        if not amount.is_finite() or amount < _ZERO:
            raise MalformedInventoryResponse(
                f"inventory amount for {asset} must be finite and non-negative"
            )
        assets[asset] = amount

    return InventorySnapshot(
        assets=MappingProxyType(assets),
        update_time_ms=update_time_ms,
        observed_at=observed_at,
        healthy=True,
    )


class InventoryProbe:
    """Rate-limited, coalescing inventory probe for exactly one account."""

    def __init__(
        self,
        client: InventoryClient,
        *,
        account_id: int,
        rate_per_sec: float = DEFAULT_INVENTORY_PROBE_RATE,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wake_event: asyncio.Event | None = None,
        wake_callback: Callable[[], object] | None = None,
        snapshot_max_age: float | None = None,
    ) -> None:
        try:
            rate = float(rate_per_sec)
        except (TypeError, ValueError) as exc:
            raise ValueError("inventory probe rate must be numeric") from exc
        if not math.isfinite(rate) or rate <= 0 or rate > MAX_INVENTORY_PROBE_RATE:
            raise ValueError(
                f"inventory probe rate must be in (0, {MAX_INVENTORY_PROBE_RATE:g}]"
            )

        self.client = client
        self.account_id = int(account_id)
        self.rate_per_sec = rate
        self._interval = 1.0 / rate
        self._snapshot_age_tracks_rate = snapshot_max_age is None
        if snapshot_max_age is None:
            snapshot_max_age = max(0.5, self._interval * 2.5)
        try:
            max_age = float(snapshot_max_age)
        except (TypeError, ValueError) as exc:
            raise ValueError("inventory snapshot max age must be numeric") from exc
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError("inventory snapshot max age must be positive")
        self.snapshot_max_age = max_age
        self._clock = clock
        self._sleep = sleep
        self._wake_event = wake_event
        self._wake_callback = wake_callback
        self._state_lock = asyncio.Lock()
        self._inflight: asyncio.Task[InventorySnapshot] | None = None
        self._last_request_at: float | None = None
        self._generation = 0
        self._positive_candidates: frozenset[str] = frozenset()
        self._snapshot = _closed_snapshot(self._clock(), "not probed")

    @property
    def snapshot(self) -> InventorySnapshot:
        return self._snapshot

    @property
    def in_flight(self) -> bool:
        task = self._inflight
        return task is not None and not task.done()

    @property
    def interval(self) -> float:
        return self._interval

    def set_rate(self, rate_per_sec: float) -> None:
        """Apply a validated runtime rate without replacing in-flight state."""
        try:
            rate = float(rate_per_sec)
        except (TypeError, ValueError) as exc:
            raise ValueError("inventory probe rate must be numeric") from exc
        if not math.isfinite(rate) or rate <= 0 or rate > MAX_INVENTORY_PROBE_RATE:
            raise ValueError(
                f"inventory probe rate must be in (0, {MAX_INVENTORY_PROBE_RATE:g}]"
            )
        changed = rate != self.rate_per_sec
        self.rate_per_sec = rate
        self._interval = 1.0 / rate
        if self._snapshot_age_tracks_rate:
            self.snapshot_max_age = max(0.5, self._interval * 2.5)
        if changed:
            self.wake()

    def has_fresh_inventory(
        self,
        asset: object,
        minimum: Decimal = _ZERO,
    ) -> bool:
        """Return true only while the last successful snapshot is still fresh."""
        snapshot = self._snapshot
        age = max(0.0, self._clock() - snapshot.observed_at)
        return age <= self.snapshot_max_age and snapshot.has_inventory(asset, minimum)

    def wake(self) -> None:
        """Wake an integration-owned loop after candidates or rules change."""
        if self._wake_event is not None:
            self._wake_event.set()
        if self._wake_callback is not None:
            try:
                result = self._wake_callback()
                if inspect.isawaitable(result):
                    asyncio.ensure_future(result)
            except Exception:
                logger.exception(
                    "Inventory wake callback failed for account %s", self.account_id
                )

    async def probe(self, candidates: Iterable[object]) -> InventorySnapshot:
        """Refresh once, coalescing concurrent callers into one HTTP request."""
        candidate_assets = frozenset(
            asset
            for asset in (self._candidate_asset(item) for item in (candidates or ()))
            if asset
        )
        if not candidate_assets:
            async with self._state_lock:
                self._generation += 1
                self._positive_candidates = frozenset()
                self._snapshot = _closed_snapshot(self._clock(), "no candidates")
                snapshot = self._snapshot
            return snapshot

        async with self._state_lock:
            task = self._inflight
            if task is None or task.done():
                self._generation += 1
                generation = self._generation
                # Keep the latest successful snapshot during a normal refresh.
                # ``has_fresh_inventory`` expires it after a few probe periods,
                # while an actual request failure closes it immediately.
                task = asyncio.create_task(self._refresh(generation, candidate_assets))
                self._inflight = task

        try:
            return await asyncio.shield(task)
        finally:
            async with self._state_lock:
                if self._inflight is task and task.done():
                    self._inflight = None

    @staticmethod
    def _candidate_asset(value: object) -> str:
        raw = str(value or "").strip().upper().replace("-", "").replace("_", "")
        return raw[:-4] if raw.endswith("USDT") else raw

    async def _refresh(
        self,
        generation: int,
        candidate_assets: frozenset[str],
    ) -> InventorySnapshot:
        now = self._clock()
        if self._last_request_at is not None:
            delay = self._interval - (now - self._last_request_at)
            if delay > 0:
                await self._sleep(delay)
        self._last_request_at = self._clock()

        try:
            payload = await self.client.get_margin_available_inventory()
            snapshot = parse_inventory_snapshot(payload, self._clock())
        except asyncio.CancelledError:
            await self._publish_failure(generation, "inventory request cancelled")
            raise
        except Exception as exc:
            # Transport exceptions may embed the signed request URL.  Keep the
            # fail-closed state diagnostic useful without retaining a query
            # signature or other request material in memory/UI payloads.
            reason = f"inventory request failed: {type(exc).__name__}"
            http_code = getattr(exc, "http_code", None)
            api_code = getattr(exc, "api_code", None)
            if http_code is not None or api_code is not None:
                reason += f" (http={http_code}, code={api_code})"
            elif isinstance(exc, MalformedInventoryResponse):
                reason += f": {exc}"
            await self._publish_failure(
                generation,
                reason,
            )
            if isinstance(exc, InventoryProbeError):
                raise
            raise InventoryProbeError("inventory request failed") from exc

        newly_positive: frozenset[str] = frozenset()
        async with self._state_lock:
            if generation != self._generation:
                return self._snapshot
            positive = frozenset(
                asset
                for asset in candidate_assets
                if snapshot.has_inventory(asset)
            )
            newly_positive = positive - self._positive_candidates
            self._positive_candidates = positive
            self._snapshot = snapshot
        if newly_positive:
            self.wake()
        return snapshot

    async def _publish_failure(self, generation: int, reason: str) -> None:
        async with self._state_lock:
            if generation != self._generation:
                return
            self._positive_candidates = frozenset()
            self._snapshot = _closed_snapshot(self._clock(), reason)
