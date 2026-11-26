"""Public trade evidence and a conservative Paper queue approximation.

This is not an exchange queue replay: the public tape cannot reveal cancels
or an order's actual priority.  A quote starts behind all displayed liquidity
at its price; only fresh opposing taker trades consume that queue.  A static
book or the passage of time never creates a fill.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import requests

from btc5m.book import TopOfBook


@dataclass
class PublicTradeTape:
    host: str = "https://data-api.polymarket.com/v2"
    poll_sec: float = 1.0
    freshness_sec: float = 10.0
    _cache: dict[str, tuple[float, Optional[list[dict]]]] = field(default_factory=dict)
    last_error: str = ""
    last_cache_age_sec: Optional[float] = None

    def fetch(self, condition_id: str, now: float) -> Optional[list[dict]]:
        """Fetch once per market/poll; failure is missing evidence, never a fill."""
        hit = self._cache.get(condition_id)
        if hit and now - hit[0] < max(self.poll_sec, 0.2):
            return hit[1]
        try:
            host = self.host.rstrip("/")
            if host == "https://data-api.polymarket.com":
                host += "/v2"  # Official v1 responds 410; upgrade old config.
            response = requests.get(
                f"{host}/trades",
                # v2 documents taker_only: each fill appears exactly once on
                # the aggressor side; never request duplicate maker rows.
                params={"condition": condition_id, "limit": 100, "taker_only": "true",
                        # The official market feed ignores time bounds, but
                        # supports this documented parameter. A changing start
                        # also avoids reusing its 300-second CDN snapshot. We
                        # still enforce freshness independently on each print.
                        "start": int(now) - int(self.freshness_sec)},
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                timeout=2,
            )
            response.raise_for_status()
            headers = getattr(response, "headers", {})
            try:
                self.last_cache_age_sec = float(headers["Age"]) if "Age" in headers else 0.0
            except (TypeError, ValueError):
                self.last_cache_age_sec = None
            rows = response.json()
            if isinstance(rows, dict):
                rows = rows.get("data")
            if not isinstance(rows, list):
                raise ValueError("public trade response is not a list")
            rows = [row for row in rows if isinstance(row, dict)]
            self.last_error = ""
        except (requests.RequestException, ValueError, TypeError) as exc:
            rows = None
            self.last_error = type(exc).__name__
        self._cache[condition_id] = (now, rows)
        # There is only one active window per engine.  Bound old-market memory.
        if len(self._cache) > 8:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)
        return rows


@dataclass
class PaperQueue:
    token_id: str
    price: float
    execution_side: str
    placed_ts: float
    queue_ahead: Optional[float] = None
    evidence_after_ts: Optional[float] = None
    seen: set[tuple] = field(default_factory=set)

    def observe_book(self, book: TopOfBook, now: float) -> None:
        """Initialize only where depth at our price is known, never infer cancels."""
        if self.queue_ahead is not None:
            return
        buy = self.execution_side == "BUY"
        touch = book.best_bid if buy else book.best_ask
        depth = book.bid_size if buy else book.ask_size
        opposite = book.best_ask if buy else book.best_bid
        if touch is not None and abs(touch - self.price) <= 1e-9:
            self.queue_ahead = max(float(depth), 0.0)
        elif touch is not None and (
            (buy and touch < self.price and (opposite is None or self.price < opposite))
            or (not buy and touch > self.price and (opposite is None or self.price > opposite))
        ):
            # A newly improved post-only quote has no displayed orders ahead.
            self.queue_ahead = 0.0
        else:
            return
        # Historical tape from before queue initialization cannot consume it.
        self.evidence_after_ts = max(self.placed_ts, now)

    def consume(
        self,
        rows: Optional[list[dict]],
        *,
        now: float,
        freshness_sec: float,
        max_size: float,
        condition_id: str = "",
    ) -> tuple[float, str]:
        if rows is None:
            return 0.0, "public_trade_unavailable"
        if self.queue_ahead is None:
            return 0.0, "queue_depth_unknown"
        minimum_ts = self.evidence_after_ts or self.placed_ts
        opposite_side = "SELL" if self.execution_side == "BUY" else "BUY"
        eligible: list[tuple[float, tuple, float]] = []
        newest_token_stamp: Optional[float] = None
        for row in rows:
            try:
                token = str(row.get("token_id") or row.get("asset") or row.get("asset_id") or "")
                market = str(row.get("conditionId") or row.get("condition_id") or "")
                side = str(row.get("side") or "").upper()
                stamp = float(row.get("timestamp") or 0)
                if stamp > 1e12:
                    stamp /= 1000.0
                size = float(row.get("size") or 0)
                price = float(row.get("price") or 0)
            except (ValueError, TypeError):
                continue
            if not all(math.isfinite(value) for value in (stamp, size, price)):
                continue
            if token != self.token_id or size <= 0 or not 0 < price < 1:
                continue
            if condition_id and market != condition_id:
                continue
            if stamp <= now:
                newest_token_stamp = max(newest_token_stamp or stamp, stamp)
            if side != opposite_side:
                continue
            if stamp <= minimum_ts or stamp > now or now - stamp > freshness_sec:
                continue
            if self.execution_side == "BUY" and price > self.price + 1e-9:
                continue
            if self.execution_side == "SELL" and price < self.price - 1e-9:
                continue
            # Public records can repeat across polling pages.  Deduplicate with
            # transaction, asset, account and trade values; undercounting two
            # identical prints is preferable to inventing a duplicate fill.
            identity = (
                str(row.get("id") or row.get("transaction_hash") or row.get("transactionHash") or ""),
                token, side, stamp, size, price,
                str(row.get("proxy_wallet") or row.get("proxyWallet") or ""),
            )
            if identity not in self.seen:
                eligible.append((stamp, identity, size))
        available = 0.0
        for _stamp, identity, size in sorted(eligible, key=lambda item: item[0]):
            if identity in self.seen:
                continue
            self.seen.add(identity)
            ahead_consumed = min(self.queue_ahead, size)
            self.queue_ahead -= ahead_consumed
            available += size - ahead_consumed
        # Excess tape volume cannot be saved to fill a later/replenished order.
        filled = min(max(float(max_size), 0.0), available)
        if filled > 0:
            return filled, "public_trade_full_visible_queue_model"
        if newest_token_stamp is not None and now - newest_token_stamp > freshness_sec:
            return 0.0, "public_trade_stale"
        return 0.0, "waiting_public_trade_queue_consumption"
