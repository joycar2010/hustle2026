"""CLOB top-of-book reader."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class TopOfBook:
    best_bid: Optional[float]
    bid_size: float
    best_ask: Optional[float]
    ask_size: float

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
    r = requests.get(f"{clob_host}/book", params={"token_id": token_id}, timeout=3)
    r.raise_for_status()
    data = r.json()
    best_bid, bid_size = _best(data.get("bids") or [], reverse=True)
    best_ask, ask_size = _best(data.get("asks") or [], reverse=False)
    return TopOfBook(
        best_bid=best_bid,
        bid_size=bid_size,
        best_ask=best_ask,
        ask_size=ask_size,
    )
