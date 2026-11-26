"""CLOB top-of-book reader."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

import requests


@dataclass(frozen=True)
class TopOfBook:
    best_bid: Optional[float]
    bid_size: float
    best_ask: Optional[float]
    ask_size: float
    fetched_at: float = 0.0
    request_latency_sec: float = 0.0

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0


def _best(levels: list[dict], *, reverse: bool) -> tuple[Optional[float], float]:
    parsed: list[tuple[float, float]] = []
    for row in levels:
        try:
            price = float(row["price"])
            size = float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and size > 0:
            parsed.append((price, size))
    if not parsed:
        return None, 0.0
    parsed.sort(key=lambda x: x[0], reverse=reverse)
    return parsed[0][0], parsed[0][1]


def fetch_book(clob_host: str, token_id: str) -> TopOfBook:
    """Read a book with bounded retries and reject slow responses."""
    last_error: Exception | None = None
    started = time.monotonic()
    for attempt in range(3):
        request_started = time.monotonic()
        try:
            r = requests.get(
                f"{clob_host}/book",
                params={"token_id": token_id},
                timeout=(1.5, 3),
            )
            if r.status_code in {408, 425, 429} or r.status_code >= 500:
                r.raise_for_status()
                raise requests.HTTPError(f"retryable CLOB status {r.status_code}")
            r.raise_for_status()
            latency = time.monotonic() - request_started
            if latency > 4.0:
                raise TimeoutError(f"CLOB book response stale latency={latency:.3f}s")
            fetched_at = time.time()
            break
        except (requests.RequestException, TimeoutError) as exc:
            last_error = exc
            if attempt == 2:
                raise RuntimeError(
                    f"CLOB book unavailable after 3 attempts token={token_id[:12]}"
                ) from exc
            time.sleep(0.20 * (2**attempt))
    else:  # pragma: no cover
        raise RuntimeError("CLOB book retry loop exhausted") from last_error
    data = r.json()
    best_bid, bid_size = _best(data.get("bids") or [], reverse=True)
    best_ask, ask_size = _best(data.get("asks") or [], reverse=False)
    return TopOfBook(
        best_bid=best_bid,
        bid_size=bid_size,
        best_ask=best_ask,
        ask_size=ask_size,
        fetched_at=fetched_at,
        request_latency_sec=time.monotonic() - started,
    )
