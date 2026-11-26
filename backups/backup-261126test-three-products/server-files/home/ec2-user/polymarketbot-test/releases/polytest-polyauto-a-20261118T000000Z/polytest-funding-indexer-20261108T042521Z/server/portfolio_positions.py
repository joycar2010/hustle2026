"""Read an atomic, complete public-wallet position snapshot for the dashboard.

Contract: https://data-api.polymarket.com/v2/openapi.json, checked 2026-11-05.
OPEN includes unredeemed winners; REDEEMABLE is a subset. Archived markets
must be explicitly included. A mergeable pair is still an active position.
No local strategy ledger, entry costs or aggregate /value response is used
to replace the marked value of individual holdings.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any, Callable

import requests

POSITIONS_URL = "https://data-api.polymarket.com/v2/positions"


class PositionSnapshotError(ValueError):
    """The upstream snapshot is incomplete or invalid; retain last good data."""


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise PositionSnapshotError(f"missing/invalid position {field}")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise PositionSnapshotError(f"invalid position {field}") from exc
    if not math.isfinite(number) or number < 0:
        raise PositionSnapshotError(f"invalid position {field}")
    return number


def _boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def normalize_position(position: dict[str, Any]) -> dict[str, Any]:
    """Keep current holdings, including zero marks and fractional shares.

    ``total_size`` is lifetime purchased quantity in v2, never current size.
    It must not resurrect fully sold/redeemed tokens after current_size=0.
    """
    if not isinstance(position, dict):
        raise PositionSnapshotError("position row is not an object")
    row = dict(position)
    token = _first(row, "token_id", "tokenId", "asset")
    condition = _first(row, "condition_id", "conditionId")
    if not token or not condition:
        raise PositionSnapshotError("position identity missing")
    size = _number(_first(row, "current_size", "currentSize", "size"), "current_size")
    price = _number(_first(row, "current_price", "currentPrice", "curPrice"), "current_price")
    supplied_value = _first(row, "current_value", "currentValue", "currentValueUsd")
    value = size * price if supplied_value is None else _number(supplied_value, "current_value")
    redeemable = _boolean(row.get("redeemable")) or str(row.get("status", "")).upper() == "REDEEMABLE"
    row.update({
        "token_id": str(token), "tokenId": str(token),
        "condition_id": str(condition), "conditionId": str(condition),
        "current_size": size, "size": size,
        "current_price": price, "curPrice": price,
        "current_value": value, "currentValue": value,
        "redeemable": redeemable,
        "mergeable": _boolean(row.get("mergeable")),
        "archived": _boolean(row.get("archived")),
        "avgPrice": _first(row, "avg_price", "avgPrice"),
    })
    return row


def summarize_positions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Deduplicate outcome tokens and split trading holdings from redemption.

    Zero quantity rows remain in ``rows`` for diagnostics but are not counted
    as wallet holdings. Zero *price* rows with a positive balance stay visible.
    """
    unique: dict[str, dict[str, Any]] = {}
    for position in rows:
        row = normalize_position(position)
        key = row["tokenId"]
        old = unique.get(key)
        if old is not None and old["conditionId"].lower() != row["conditionId"].lower():
            raise PositionSnapshotError("conflicting condition for outcome token")
        if old is not None:
            old_ts = float(old.get("last_event_at") or 0)
            new_ts = float(row.get("last_event_at") or 0)
            if new_ts < old_ts:
                continue
            row = {**old, **row}
        unique[key] = row
    normalized = list(unique.values())
    held = [row for row in normalized if row["size"] > 0]
    active = [row for row in held if not row["redeemable"]]
    redeemable = [row for row in held if row["redeemable"]]
    active_value = math.fsum(row["currentValue"] for row in active)
    redeemable_value = math.fsum(row["currentValue"] for row in redeemable)
    return {
        "rows": normalized,
        "positions": active,
        "active_positions": active,
        "settled_positions": redeemable,
        "redeemable_positions": redeemable,
        "pending_count": len(active),
        "redeemable_count": len(redeemable),
        "total_count": len(held),
        "active_value_usd": active_value,
        "pending_value_usd": active_value,
        "redeemable_value_usd": redeemable_value,
        "value_usd": active_value + redeemable_value,
        "total_value_usd": active_value + redeemable_value,
    }


def _fetch_pages(user: str, status: str, get: Callable[..., Any], *,
                 timeout: float, page_size: int, max_pages: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(max_pages):
        params: dict[str, Any] = {
            "user": user, "limit": page_size, "status": status,
            # Keep the same filtering contract as the Polymarket portfolio
            # page.  ``filter_amount=0`` is not equivalent to "no filter" on
            # the v2 endpoint and can produce an empty page while the web UI
            # still shows a holding during indexer catch-up.
            "include_archived": "true", "filter_type": "TOKENS", "filter_amount": 0.1,
            "sort_by": "CURRENT_VALUE", "sort_direction": "DESC",
        }
        if cursor is not None:
            params["cursor"] = cursor
        response = get(POSITIONS_URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PositionSnapshotError("positions response data is not a list")
        pagination = payload.get("pagination")
        if not isinstance(pagination, dict) or not isinstance(pagination.get("has_more"), bool):
            raise PositionSnapshotError("positions pagination missing")
        batch = payload["data"]
        if any(not isinstance(row, dict) for row in batch):
            raise PositionSnapshotError("invalid position row")
        rows.extend(batch)
        next_cursor = pagination.get("next_cursor")
        if not pagination["has_more"]:
            if next_cursor:
                raise PositionSnapshotError("contradictory final-page cursor")
            return rows
        if not batch or not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise PositionSnapshotError("positions pagination incomplete or repeated")
        seen.add(next_cursor)
        cursor = next_cursor
    raise PositionSnapshotError("positions pagination exceeded maximum pages")


def fetch_positions_snapshot(user: str, *, get: Callable[..., Any] | None = None,
                             timeout: float = 5, page_size: int = 500,
                             max_pages: int = 20) -> dict[str, Any]:
    """Fetch OPEN and REDEEMABLE completely, or raise without partial success.

    v2 accepts ``status=REDEEMABLE``, not the retired v1 ``redeemable=true``
    query. OPEN is a superset, so the two scans are de-duplicated by token.
    Callers should publish all counts/rows/value atomically after this returns.
    """
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", user or ""):
        raise PositionSnapshotError("invalid wallet address")
    if not 1 <= page_size <= 1000 or max_pages < 1:
        raise ValueError("invalid page size/limit")
    fetch = requests.get if get is None else get
    rows = _fetch_pages(user, "OPEN", fetch, timeout=timeout, page_size=page_size, max_pages=max_pages)
    rows.extend(_fetch_pages(user, "REDEEMABLE", fetch, timeout=timeout, page_size=page_size, max_pages=max_pages))
    snapshot = summarize_positions(rows)
    snapshot.update({"available": True, "stale": False, "source": "data_api_v2_positions", "wallet": user,
                     "updated_at": time.time(), "include_archived": True})
    return snapshot


def fetch_portfolio_positions(user: str, *, get: Callable[..., Any] | None = None,
                              timeout: float = 5, page_size: int = 500,
                              max_pages: int = 20) -> dict[str, Any]:
    """Dashboard integration entry point; errors are deliberately propagated."""
    return fetch_positions_snapshot(user, get=get, timeout=timeout,
                                    page_size=page_size, max_pages=max_pages)
