"""CLOB order book reader. HTTP polling; WSS upgrade can come later."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class TopOfBook:
    best_bid: Optional[float]
    bid_size: float
    best_ask: Optional[float]
    ask_size: float
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()

    def ask_with_size(self, min_size: float) -> Optional[float]:
        if self.best_ask is None or self.ask_size < min_size:
            return None
        return self.best_ask


def _levels(rows: list[dict], *, reverse: bool) -> tuple[BookLevel, ...]:
    by_price: dict[float, float] = {}
    for row in rows:
        try:
            price = float(row["price"])
            size = float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue
        by_price[price] = by_price.get(price, 0.0) + size
    return tuple(
        BookLevel(price=price, size=size)
        for price, size in sorted(by_price.items(), reverse=reverse)
    )


def fetch_book(clob_host: str, token_id: str) -> TopOfBook:
    r = requests.get(f"{clob_host}/book", params={"token_id": token_id}, timeout=3)
    r.raise_for_status()
    data = r.json()
    bid_levels = _levels(data.get("bids") or [], reverse=True)
    ask_levels = _levels(data.get("asks") or [], reverse=False)
    return TopOfBook(
        best_bid=bid_levels[0].price if bid_levels else None,
        bid_size=bid_levels[0].size if bid_levels else 0.0,
        best_ask=ask_levels[0].price if ask_levels else None,
        ask_size=ask_levels[0].size if ask_levels else 0.0,
        bids=bid_levels,
        asks=ask_levels,
    )


if __name__ == "__main__":
    from bot.config import load
    from bot.markets import fetch_live_market

    cfg = load()
    m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
    if not m:
        raise SystemExit("no live market right now")
    up = fetch_book(cfg.clob_host, m.up_token)
    dn = fetch_book(cfg.clob_host, m.down_token)
    print(f"market: {m.market_slug}  t_remaining={m.t_remaining():.1f}s")
    print(f"  UP   bid={up.best_bid}({up.bid_size:.0f})  ask={up.best_ask}({up.ask_size:.0f})")
    print(f"  DOWN bid={dn.best_bid}({dn.bid_size:.0f})  ask={dn.best_ask}({dn.ask_size:.0f})")
