"""Bounded CLOB market/user WebSocket caches; no order submission capability.

The public book is usable only after a complete snapshot in the current
connection generation. Restored REST observations are explicitly marked and
never masquerade as a fresh WS snapshot. Authenticated events contain only
normalized own order/fill evidence: API owner strings never leave this class.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import threading
import time
from typing import Any, Callable, Iterable, Optional

from bot.book import BookLevel, TopOfBook, fetch_book
from bot.order_evidence import iter_account_trade_fills

MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
USER_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/user"


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _timestamp(value: Any) -> Optional[float]:
    result = _number(value)
    if result is not None:
        return result / 1000. if result > 10_000_000_000 else result
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError):
            pass
    return None


def _value(row: dict, *names, default=None):
    return next((row[name] for name in names if row.get(name) is not None), default)


def _levels(rows) -> Optional[dict[float, float]]:
    if not isinstance(rows, (list, tuple)):
        return None
    output = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        price, size = _number(row.get("price")), _number(row.get("size"))
        if price is None or size is None or not 0 < price <= 1 or size < 0:
            return None
        if size:
            output[price] = size
    return output


@dataclass(frozen=True)
class BookSnapshot:
    book: TopOfBook
    source: str
    event_ts: float
    received_ts: float
    generation: int
    condition_id: str = ""

    def fresh(self, now: float, max_age_sec: float) -> bool:
        return (-2. <= now - self.event_ts <= max_age_sec
                and -2. <= now - self.received_ts <= max_age_sec)


@dataclass
class _BookState:
    bids: dict
    asks: dict
    event_ts: float
    received_ts: float
    generation: int
    condition_id: str
    valid: bool = True

    def snapshot(self):
        bids = tuple(BookLevel(p, q) for p, q in sorted(self.bids.items(), reverse=True))
        asks = tuple(BookLevel(p, q) for p, q in sorted(self.asks.items()))
        return BookSnapshot(TopOfBook(bids[0].price if bids else None, bids[0].size if bids else 0.,
            asks[0].price if asks else None, asks[0].size if asks else 0., bids, asks,
            fetched_at=self.received_ts), "market_ws", self.event_ts, self.received_ts,
            self.generation, self.condition_id)


class ClobStreams:
    """Two independent reader threads and one condition-variable event cursor.

    ``subscribe`` replaces desired subscriptions. Callers must include held
    assets/markets when rolling to a new window. Ring consumers can detect a
    gap using ``health()['market_oldest_sequence']`` and resynchronize.
    ``wait`` never executes application callbacks or network reads.
    """
    def __init__(self, *, clob_host="https://clob.polymarket.com", api_key="",
                 api_secret="", api_passphrase="", owner_addresses=(),
                 market_url=MARKET_WS, user_url=USER_WS, connect=None,
                 clock=time.time, ring_size=4096, compact_events=True, on_event: Optional[Callable] = None):
        self.clob_host, self.market_url, self.user_url = clob_host, market_url, user_url
        self._auth = ({"apiKey": str(api_key), "secret": str(api_secret),
                       "passphrase": str(api_passphrase)}
                      if all((api_key, api_secret, api_passphrase)) else None)
        self._owners = tuple(str(x).lower() for x in owner_addresses if x)
        self._clock, self._connect, self._on_event = clock, connect, on_event
        self._compact_events = bool(compact_events)
        self._condition = threading.Condition(threading.RLock())
        self._stop = threading.Event()
        self._threads = {}
        self._tokens, self._markets = set(), set()
        self._subscription_revision = 0
        self._revision = 0
        self._market_seq = self._user_seq = 0
        self._market_events = deque(maxlen=max(32, int(ring_size)))
        self._user_events = deque(maxlen=max(32, int(ring_size)))
        self._seen = {"market": OrderedDict(), "user": OrderedDict()}
        self._books: dict[str, _BookState] = {}
        self._rest: dict[str, BookSnapshot] = {}
        self._orders: dict[str, dict] = {}
        self._resync = set()
        self._channels = {name: {"connected": False, "generation": 0,
            "received_at": None, "event_at": None, "reconnects": 0,
            "events": 0, "duplicates": 0, "out_of_order": 0,
            "invalid": 0, "invalid_reasons": {}, "latest_ingress_lag_sec": None,
            "max_ingress_lag_sec": 0., "error_type": None}
            for name in ("market", "user")}

    @classmethod
    def from_cfg(cls, cfg, *, authenticated=False, **kwargs):
        return cls(clob_host=cfg.clob_host,
            api_key=getattr(cfg, "api_key", "") if authenticated else "",
            api_secret=getattr(cfg, "api_secret", "") if authenticated else "",
            api_passphrase=getattr(cfg, "api_passphrase", "") if authenticated else "",
            owner_addresses=(getattr(cfg, "wallet_address", ""),
                getattr(cfg, "funder_address", ""), getattr(cfg, "deposit_wallet_address", "")),
            **kwargs)

    def subscribe(self, token_ids: Iterable[str], condition_ids: Iterable[str] = ()):
        tokens = {str(x) for x in token_ids if x}
        markets = {str(x).lower() for x in condition_ids if x}
        with self._condition:
            if tokens == self._tokens and markets == self._markets:
                return
            removed = self._tokens - tokens
            self._tokens, self._markets = tokens, markets
            for token in removed:
                self._books.pop(token, None)
                self._rest.pop(token, None)
            self._resync.intersection_update(tokens)
            self._subscription_revision += 1
            self._wake()

    def subscribe_market(self, market):
        self.subscribe((market.up_token, market.down_token), (market.condition_id,))

    def start(self):
        self._stop.clear()
        for channel in ("market", "user"):
            if channel == "user" and self._auth is None:
                continue
            thread = self._threads.get(channel)
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=self._thread_main, args=(channel,),
                    name="clob-" + channel + "-ws", daemon=True)
                self._threads[channel] = thread
                thread.start()
        return self

    def stop(self, timeout=3.):
        self._stop.set()
        with self._condition:
            self._wake()
        for thread in self._threads.values():
            if thread is not threading.current_thread():
                thread.join(timeout=max(0., timeout))

    @property
    def revision(self):
        with self._condition:
            return self._revision

    def wait(self, after_revision, timeout=.25):
        with self._condition:
            if self._revision <= after_revision and not self._stop.is_set():
                self._condition.wait(max(0., timeout))
            return self._revision

    def snapshot(self, token_id, *, max_age_sec=1.5, allow_rest=False):
        token = str(token_id)
        with self._condition:
            state = self._books.get(token)
            observation = (state.snapshot() if state and state.valid
                and state.generation == self._channels["market"]["generation"] else None)
            if observation is not None and observation.fresh(self._clock(), max_age_sec):
                return observation
            rest = self._rest.get(token)
            if allow_rest and rest is not None and rest.fresh(self._clock(), max_age_sec):
                return rest
            return None

    def latest_book(self, token_id, *, max_age_sec=1.5):
        observation = self.snapshot(token_id, max_age_sec=max_age_sec)
        return observation.book if observation is not None else None

    def refresh_rest(self, token_id, condition_id="", *, loader=None):
        """Explicit blocking recovery read; run it outside an urgent exit lock."""
        started = self._clock()
        book = (loader or fetch_book)(self.clob_host, str(token_id))
        received = self._clock()
        # Book.fetched_at is the actual response boundary. A missing legacy
        # timestamp gets the request-start lower bound, never an artificial
        # newer source timestamp than the HTTP evidence permits.
        event_ts = _number(getattr(book, "fetched_at", None)) or started
        observation = BookSnapshot(book, "rest", min(event_ts, received), received,
                                   self._channels["market"]["generation"], str(condition_id))
        with self._condition:
            self._rest[str(token_id)] = observation
            self._wake()
        return observation

    def market_events(self, after_sequence=0):
        with self._condition:
            return ([deepcopy(x) for x in self._market_events if x["sequence"] > after_sequence], self._market_seq)

    def user_events(self, after_sequence=0):
        with self._condition:
            return ([deepcopy(x) for x in self._user_events if x["sequence"] > after_sequence], self._user_seq)

    events = market_events

    def health(self):
        with self._condition:
            now = self._clock()
            books = {}
            for token in self._tokens:
                state = self._books.get(token)
                books[token] = {"snapshot_valid": bool(state and state.valid),
                    "source": "market_ws" if state else None,
                    "source_age_sec": now-state.event_ts if state else None,
                    "received_age_sec": now-state.received_ts if state else None,
                    "generation": state.generation if state else None,
                    "resync_required": token in self._resync}
            return {"market": deepcopy(self._channels["market"]), "user": deepcopy(self._channels["user"]),
                "user_enabled": self._auth is not None, "books": books,
                "compact_events": self._compact_events,
                "revision": self._revision, "market_sequence": self._market_seq,
                "user_sequence": self._user_seq,
                "market_ring_capacity": self._market_events.maxlen,
                "user_ring_capacity": self._user_events.maxlen,
                "market_ring_dropped": max(0, self._market_seq-len(self._market_events)),
                "user_ring_dropped": max(0, self._user_seq-len(self._user_events)),
                "market_oldest_sequence": self._market_events[0]["sequence"] if self._market_events else None,
                "user_oldest_sequence": self._user_events[0]["sequence"] if self._user_events else None}

    def _wake(self):
        self._revision += 1
        self._condition.notify_all()

    def _emit(self, channel, event):
        if channel == "market":
            self._market_seq += 1
            event["sequence"] = self._market_seq
            self._market_events.append(event)
        else:
            self._user_seq += 1
            event["sequence"] = self._user_seq
            self._user_events.append(event)
        self._channels[channel]["events"] += 1
        self._wake()

    def _dedup(self, channel, event):
        key = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"),
                                         default=str).encode()).hexdigest()
        seen = self._seen[channel]
        if key in seen:
            self._channels[channel]["duplicates"] += 1
            return False
        seen[key] = None
        if len(seen) > 16384:
            seen.popitem(last=False)
        return True

    def _book_event(self, token, state, kind, event_id, changes=None):
        event = {"type": "book", "event_type": kind, "token_id": token,
            "condition_id": state.condition_id, "ts": state.event_ts,
            "received_ts": state.received_ts, "event_id": event_id,
            "generation": state.generation, "source": "market_ws"}
        if changes is not None and self._compact_events:
            # The ring records exact observed updates, rather than allocating
            # and sorting thousands of unchanged depth levels per tick.
            event.update(is_delta=True,changes=[{"price":p,"size":q,"side":s} for p,q,s in changes])
        else:
            event.update(is_delta=False,
                bids=[{"price":p,"size":q} for p,q in sorted(state.bids.items(),reverse=True)],
                asks=[{"price":p,"size":q} for p,q in sorted(state.asks.items())])
        return event

    def _reject(self, channel, reason):
        state = self._channels[channel]
        state['invalid'] += 1
        state['invalid_reasons'][reason] = state['invalid_reasons'].get(reason,0)+1

    def ingest_market(self, message):
        """Parse raw API or SDK envelope; also usable by deterministic replay."""
        return self._ingest("market", message)

    def ingest_user(self, message):
        return self._ingest("user", message)

    def _ingest(self, channel, message):
        if message in ("PING", "PONG", b"PING", b"PONG"):
            with self._condition:
                self._channels[channel]["received_at"] = self._clock()
            return False
        if isinstance(message, (str, bytes)):
            try:
                message = json.loads(message)
            except (ValueError, UnicodeError):
                with self._condition:
                    self._reject(channel,'invalid_json')
                return False
        if isinstance(message, list):
            return any([self._ingest(channel, item) for item in message])
        if not isinstance(message, dict):
            return False
        received = self._clock()
        row = message.get("payload") if isinstance(message.get("payload"), dict) else message
        kind = str(message.get("event_type") or message.get("type") or "").lower()
        if kind not in {"book", "price_change", "last_trade_price", "best_bid_ask", "tick_size_change",
                        "market_resolved", "new_market", "order", "trade"}:
            return False
        source_ts = _timestamp(_value(row, "timestamp", "ts"))
        with self._condition:
            self._channels[channel]["received_at"] = received
            if source_ts is not None:
                lag = received-source_ts
                self._channels[channel]['latest_ingress_lag_sec'] = lag
                self._channels[channel]['max_ingress_lag_sec'] = max(self._channels[channel]['max_ingress_lag_sec'],lag)
            if (source_ts is None or received-source_ts < -2.
                    or channel == "market" and received-source_ts > 30.):
                self._reject(channel,'missing_timestamp' if source_ts is None else 'future_timestamp'
                    if received-source_ts < -2. else 'source_older_than_30s')
                return False
            if not self._dedup(channel, message):
                return False
            self._channels[channel]["event_at"] = source_ts
            changed = (self._market(row, kind, source_ts, received) if channel == "market"
                       else self._user(row, kind, source_ts, received))
        if changed and self._on_event is not None:
            try:
                self._on_event()
            except Exception:
                # Callbacks are notifications, not part of authenticated
                # parsing or the reader's process lifetime.
                pass
        return changed

    def _market(self, row, kind, ts, received):
        token = str(_value(row, "asset_id", "assetId", "token_id", default=""))
        market = str(_value(row, "market", "condition_id", "conditionId", default="")).lower()
        if self._markets and market and market not in self._markets:
            return False
        event_id = str(row.get("hash") or hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest())
        if kind == "price_change":
            changes = _value(row, "price_changes", "priceChanges", default=[])
            changed = False
            if not isinstance(changes, list):
                return False
            grouped = {}
            for delta in changes:
                if not isinstance(delta, dict): continue
                asset = str(_value(delta, "asset_id", "assetId", default=""))
                grouped.setdefault(asset, []).append(delta)
            for asset, deltas in grouped.items():
                state = self._books.get(asset)
                if asset not in self._tokens or state is None or not state.valid:
                    if asset in self._tokens: self._resync.add(asset)
                    continue
                if ts < state.event_ts:
                    self._channels["market"]["out_of_order"] += 1
                    continue
                parsed = [(_number(delta.get("price")), _number(delta.get("size")),
                           str(delta.get("side") or "").upper()) for delta in deltas]
                if any(price is None or size is None or not 0 < price <= 1 or size < 0
                       or side not in {"BUY", "SELL"} for price, size, side in parsed):
                    self._reject('market','invalid_delta_level')
                    state.valid = False
                    self._resync.add(asset)
                    continue
                for price, size, side in parsed:
                    levels = state.bids if side == "BUY" else state.asks
                    if size == 0: levels.pop(price, None)
                    else: levels[price] = size
                state.event_ts, state.received_ts = ts, received
                if self._consistent_best(state, deltas[-1]):
                    self._emit("market", self._book_event(asset, state, kind, str(deltas[-1].get("hash") or event_id),parsed))
                    changed = True
                else:
                    self._reject('market','delta_best_mismatch')
                    state.valid = False
                    self._resync.add(asset)
            return changed
        if kind == "market_resolved":
            winner = str(_value(row, "winning_asset_id", "winningAssetId", default=""))
            self._emit("market", {"type": kind, "condition_id": market, "winning_token_id": winner,
                "ts": ts, "received_ts": received, "event_id": event_id, "source": "market_ws"})
            return True
        if token not in self._tokens:
            return False
        previous = self._books.get(token)
        if previous and ts < previous.event_ts:
            self._channels["market"]["out_of_order"] += 1
            return False
        if kind == "book":
            bids, asks = _levels(row.get("bids")), _levels(row.get("asks"))
            if bids is None or asks is None or (bids and asks and max(bids) >= min(asks)):
                self._reject('market','invalid_book_snapshot')
                if previous: previous.valid = False
                self._resync.add(token)
                return False
            state = _BookState(bids, asks, ts, received, self._channels["market"]["generation"], market)
            self._books[token] = state
            self._resync.discard(token)
            self._emit("market", self._book_event(token, state, kind, event_id))
            return True
        if kind == "last_trade_price":
            price, size = _number(row.get("price")), _number(row.get("size"))
            side = str(row.get("side") or "").upper()
            if price is None or not 0 < price <= 1 or side not in {"BUY", "SELL"}:
                return False
            self._emit("market", {"type": "trade", "event_type": kind, "token_id": token,
                "condition_id": market, "price": price, "size": size if size is not None and size > 0 else None,
                "side": side, "ts": ts, "received_ts": received, "event_id": event_id,
                "transaction_hash": _value(row, "transaction_hash", "transactionHash"), "source": "market_ws"})
            return True
        if kind == "best_bid_ask":
            if previous and not self._consistent_best(previous, row):
                self._reject('market','top_depth_mismatch')
                previous.valid = False
                self._resync.add(token)
                self._wake()
            # A top-of-book tick has no depth; never fabricate sizes or renew
            # a full-depth observation from just this abbreviated message.
            return False
        if kind == "tick_size_change":
            tick = _number(_value(row, "new_tick_size", "newTickSize"))
            if tick is None or tick <= 0: return False
            self._emit("market", {"type": kind, "token_id": token, "condition_id": market,
                "tick_size": tick, "ts": ts, "received_ts": received,
                "event_id": event_id, "source": "market_ws"})
            return True
        return False

    @staticmethod
    def _consistent_best(state, row):
        for keys, actual in ((("best_bid", "bestBid"), max(state.bids) if state.bids else None),
                             (("best_ask", "bestAsk"), min(state.asks) if state.asks else None)):
            raw = _value(row, *keys)
            if raw is None: continue
            stated = _number(raw)
            if stated == 0 and actual is None: continue
            if stated is None or actual is None or abs(stated-actual) > 1e-8:
                return False
        return not (state.bids and state.asks and max(state.bids) >= min(state.asks))

    def _user(self, row, kind, ts, received):
        market = str(_value(row, "market", "condition_id", "conditionId", default="")).lower()
        if self._markets and market not in self._markets:
            return False
        token = str(_value(row, "asset_id", "assetId", default=""))
        if kind == "order":
            order_id = str(row.get("id") or "")
            if not order_id: return False
            matched = _number(_value(row, "size_matched", "sizeMatched"))
            original = _number(_value(row, "original_size", "originalSize"))
            if matched is None or original is None or matched < 0 or original < 0 or matched > original + 1e-6:
                return False
            status = str(row.get("status") or "").upper()
            event_type = str(_value(row, "order_event_type", "orderEventType", "type", default="")).upper()
            if event_type == "CANCELLATION" and not status: status = "CANCELED"
            previous = self._orders.get(order_id)
            if previous and (ts < previous["ts"] or matched < previous["size_matched"] - 1e-8
                    or (previous["terminal"] and status in {"LIVE", "DELAYED", "UNMATCHED"})):
                self._channels["user"]["out_of_order"] += 1
                return False
            event = {"type": "order", "order_id": order_id, "token_id": token,
                "condition_id": market, "side": str(row.get("side") or "").upper(),
                "price": _number(row.get("price")), "size_matched": matched,
                "original_size": original, "remaining_size": max(0., original-matched),
                "terminal": (status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}
                             or original > 0 and matched >= original - 1e-8),
                "status": status, "order_event_type": event_type,
                "ts": ts, "received_ts": received, "source": "user_ws"}
            self._orders[order_id] = event
            self._emit("user", dict(event))
            return True
        if kind != "trade": return False
        # Adapt modern SDK envelopes to the same account-leg evidence parser
        # used by authenticated REST. Never expose its embedded raw trade.
        adapted = dict(row)
        for snake, camel in (("taker_order_id", "takerOrderId"), ("trader_side", "traderSide"),
                ("maker_address", "makerAddress"), ("trade_owner", "tradeOwner"),
                ("transaction_hash", "transactionHash")):
            if snake not in adapted and camel in adapted: adapted[snake] = adapted[camel]
        adapted.update(market=market, asset_id=token, match_time=ts)
        adapted["status"] = str(row.get("status") or "").upper().removeprefix("TRADE_STATUS_")
        makers = []
        for leg in _value(row, "maker_orders", "makerOrders", default=[]) or []:
            normalized = dict(leg)
            for snake, camel in (("order_id", "orderId"), ("maker_address", "makerAddress"),
                    ("matched_amount", "matchedAmount"), ("asset_id", "assetId")):
                if snake not in normalized and camel in normalized: normalized[snake] = normalized[camel]
            makers.append(normalized)
        adapted["maker_orders"] = makers
        fills = list(iter_account_trade_fills([adapted], owner_addresses=self._owners,
                        api_owner=self._auth["apiKey"] if self._auth else None))
        safe_keys = ("order_id", "token_id", "condition_id", "side", "size", "price", "amount",
                     "trade_id", "status", "ts", "liquidity_role")
        self._emit("user", {"type": "trade", "trade_id": str(row.get("id") or ""),
            "token_id": token, "condition_id": market, "status": adapted["status"],
            "fills": [{k: fill.get(k) for k in safe_keys} for fill in fills],
            "ts": ts, "received_ts": received, "source": "user_ws"})
        return True

    def _mark_connected(self, channel):
        with self._condition:
            state = self._channels[channel]
            state["generation"] += 1
            state.update(connected=True, received_at=self._clock(), error_type=None)
            if channel == "market":
                for book in self._books.values(): book.valid = False
                self._resync.clear()
                self._seen["market"].clear()
            self._wake()

    def _mark_disconnected(self, channel, error=None):
        with self._condition:
            state = self._channels[channel]
            state.update(connected=False, error_type=type(error).__name__ if error else None)
            if channel == "market":
                for book in self._books.values(): book.valid = False
            self._wake()

    def _thread_main(self, channel):
        asyncio.run(self._reader(channel))

    def _targets(self):
        with self._condition:
            return set(self._tokens), set(self._markets), self._subscription_revision

    async def _reader(self, channel):
        if self._connect is None:
            import websockets
            connector = websockets.connect
        else:
            connector = self._connect
        backoff = .25
        url = self.market_url if channel == "market" else self.user_url
        while not self._stop.is_set():
            tokens, markets, subscription_revision = self._targets()
            if channel == "market" and not tokens:
                await asyncio.sleep(.1)
                continue
            try:
                async with connector(url, ping_interval=None, close_timeout=2,
                        open_timeout=5, max_queue=2048, max_size=4*1024*1024) as ws:
                    frame = ({"assets_ids": sorted(tokens), "type": "market", "custom_feature_enabled": True}
                        if channel == "market" else {"auth": dict(self._auth or {}), "type": "user"})
                    if channel == "user" and markets: frame["markets"] = sorted(markets)
                    await ws.send(json.dumps(frame))
                    self._mark_connected(channel)
                    sent_tokens, sent_markets = set(tokens), set(markets)
                    backoff, last_ping = .25, time.monotonic()
                    last_resync = {}
                    while not self._stop.is_set():
                        tokens, markets, revision = self._targets()
                        if channel == "market" and not tokens: break
                        if revision != subscription_revision:
                            if channel == "market":
                                for operation, assets in (("unsubscribe", sent_tokens-tokens), ("subscribe", tokens-sent_tokens)):
                                    if assets: await ws.send(json.dumps({"operation": operation, "assets_ids": sorted(assets), "custom_feature_enabled": True}))
                                sent_tokens = tokens
                            else:
                                # Empty markets means the whole account; the
                                # old filtered socket cannot safely be widened
                                # to that implicit subscription by an empty delta.
                                if bool(markets) != bool(sent_markets): break
                                for operation, ids in (("unsubscribe", sent_markets-markets), ("subscribe", markets-sent_markets)):
                                    if ids: await ws.send(json.dumps({"operation": operation, "markets": sorted(ids)}))
                                sent_markets = markets
                            subscription_revision = revision
                        if channel == "market":
                            with self._condition: pending = self._resync.intersection(tokens)
                            now_mono = time.monotonic()
                            for asset in pending:
                                if now_mono-last_resync.get(asset, -10.) < 2.: continue
                                await ws.send(json.dumps({"operation": "unsubscribe", "assets_ids": [asset]}))
                                await ws.send(json.dumps({"operation": "subscribe", "assets_ids": [asset], "custom_feature_enabled": True}))
                                last_resync[asset] = now_mono
                        if time.monotonic()-last_ping >= 10.:
                            await ws.send("PING")
                            last_ping = time.monotonic()
                        with self._condition: last_received = self._channels[channel]["received_at"]
                        if last_received is not None and self._clock()-last_received > 25.:
                            raise TimeoutError("clob_ws_heartbeat_timeout")
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=.5)
                        except asyncio.TimeoutError:
                            continue
                        if message in ("PING", b"PING"):
                            await ws.send("PONG")
                        self._ingest(channel, message)
            except Exception as exc:
                self._mark_disconnected(channel, exc)
            else:
                self._mark_disconnected(channel)
            if self._stop.is_set(): break
            with self._condition: self._channels[channel]["reconnects"] += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff*2, 10.)
