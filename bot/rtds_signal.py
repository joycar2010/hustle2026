"""Polymarket RTDS Chainlink TWAP price cache.

The 5-minute crypto markets resolve against Chainlink TWAP streams. This module
keeps a small in-process websocket cache so both the current price and the
market-start price-to-beat come from the same TWAP source.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

import websockets
import requests

from bot.config import Config
from bot.markets import LiveMarket

log = logging.getLogger("bot.rtds")


@dataclass(frozen=True)
class RtdsSample:
    symbol: str
    value: float
    ts: float
    received_ts: float
    window_s: int


@dataclass(frozen=True)
class RtdsSignalData:
    price_to_beat: float
    current_price: float
    delta_usd: float
    source: str
    source_ts: float
    age_sec: float
    feed_id: str


class RtdsTwapClient:
    def __init__(
        self,
        *,
        url: str,
        topic: str,
        symbols: list[str],
        retention_sec: float,
    ) -> None:
        self.url = url
        self.topic = topic
        self.symbols = sorted({s.lower() for s in symbols})
        self.retention_sec = max(float(retention_sec), 60.0)
        self._lock = threading.RLock()
        self._samples: dict[str, deque[RtdsSample]] = defaultdict(deque)
        self._latest: dict[str, RtdsSample] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        for symbol in self.symbols:
            thread = self._threads.get(symbol)
            if thread and thread.is_alive():
                continue
            thread = threading.Thread(
                target=self._thread_main,
                args=(symbol,),
                name=f"rtds-twap-{symbol.replace('/', '-')}",
                daemon=True,
            )
            self._threads[symbol] = thread
            thread.start()

    def latest(self, symbol: str) -> Optional[RtdsSample]:
        with self._lock:
            return self._latest.get(symbol.lower())

    def wait_for_fresh_latest(
        self,
        symbol: str,
        *,
        max_age_sec: float,
        timeout_sec: float,
    ) -> Optional[RtdsSample]:
        deadline = time.time() + max(float(timeout_sec), 0.0)
        symbol = symbol.lower()
        while True:
            sample = self.latest(symbol)
            if sample is not None and self._is_fresh(sample, max_age_sec):
                return sample
            if time.time() >= deadline:
                return None
            time.sleep(0.05)

    def fetch_once(
        self,
        symbol: str,
        *,
        max_age_sec: float,
        timeout_sec: float,
    ) -> Optional[RtdsSample]:
        """Open a short-lived RTDS connection when the background cache is stale."""
        try:
            return asyncio.run(
                self._fetch_once(
                    symbol.lower(),
                    max_age_sec=max_age_sec,
                    timeout_sec=timeout_sec,
                )
            )
        except Exception as e:
            log.debug("RTDS one-shot fetch failed for %s: %s", symbol, e)
            return None

    async def _fetch_once(
        self,
        symbol: str,
        *,
        max_age_sec: float,
        timeout_sec: float,
    ) -> Optional[RtdsSample]:
        deadline = asyncio.get_running_loop().time() + max(float(timeout_sec), 0.5)
        async with websockets.connect(
            self.url,
            ping_interval=None,
            close_timeout=2,
        ) as ws:
            await self._send_subscribe(ws, symbol)
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return None
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    return None
                self._handle_message(str(message))
                sample = self.latest(symbol)
                if sample is not None and self._is_fresh(sample, max_age_sec):
                    return sample

    def sample_for_market_start(
        self,
        symbol: str,
        start_ts: float,
        *,
        max_start_lag_sec: float,
    ) -> Optional[RtdsSample]:
        symbol = symbol.lower()
        with self._lock:
            samples = list(self._samples.get(symbol) or [])
        if not samples:
            return None

        lower_bound = start_ts - 0.5
        for sample in samples:
            if sample.ts < lower_bound:
                continue
            lag = sample.ts - start_ts
            if lag < -0.5:
                continue
            if lag <= max_start_lag_sec:
                return sample
            return None
        return None

    def _is_fresh(self, sample: RtdsSample, max_age_sec: float) -> bool:
        now = time.time()
        max_age = max(float(max_age_sec), 0.5)
        received_age = now - sample.received_ts
        source_age = now - sample.ts
        return received_age <= max_age and source_age <= max_age + 2.0

    def _thread_main(self, symbol: str) -> None:
        try:
            asyncio.run(self._run_loop(symbol))
        except Exception as e:
            log.warning("RTDS thread stopped for %s: %s", symbol, e)

    async def _run_loop(self, symbol: str) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=None,
                    close_timeout=2,
                ) as ws:
                    await self._send_subscribe(ws, symbol)
                    heartbeat = asyncio.create_task(self._heartbeat_loop(ws))
                    try:
                        async for message in ws:
                            self._handle_message(str(message))
                    finally:
                        heartbeat.cancel()
                backoff = 1.0
            except Exception as e:
                log.debug("RTDS websocket reconnecting for %s after error: %s", symbol, e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)

    async def _send_subscribe(self, ws, symbol: str) -> None:
        subscriptions = [
            {
                "topic": self.topic,
                "type": "update",
                "filters": json.dumps({"symbol": symbol}, separators=(",", ":")),
            }
        ]
        await ws.send(json.dumps({"action": "subscribe", "subscriptions": subscriptions}, separators=(",", ":")))

    async def _heartbeat_loop(self, ws) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(5.0)
            try:
                await ws.send("PING")
            except Exception:
                return

    def _handle_message(self, message: str) -> None:
        if not message:
            return
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        if data.get("topic") != self.topic or data.get("type") != "update":
            return
        payload = data.get("payload") or {}
        symbol = str(payload.get("symbol") or "").lower()
        if symbol not in self.symbols:
            return
        try:
            value = float(payload["value"])
            ts_raw = float(payload["timestamp"])
        except (KeyError, TypeError, ValueError):
            return
        sample_ts = ts_raw / 1000.0 if ts_raw > 10_000_000_000 else ts_raw
        window_s = int(payload.get("window_s") or 30)
        sample = RtdsSample(
            symbol=symbol,
            value=value,
            ts=sample_ts,
            received_ts=time.time(),
            window_s=window_s,
        )
        with self._lock:
            q = self._samples[symbol]
            q.append(sample)
            cutoff = sample.received_ts - self.retention_sec
            while q and q[0].received_ts < cutoff:
                q.popleft()
            self._latest[symbol] = sample


_client_lock = threading.Lock()
_client: Optional[RtdsTwapClient] = None


def rtds_symbol_for_price_symbol(price_symbol: str) -> str:
    raw = price_symbol.strip().lower()
    if "/" in raw:
        base, _quote = raw.split("/", 1)
        return f"{base}/usd"
    upper = price_symbol.strip().upper()
    if upper.endswith("USDT"):
        base = upper[:-4]
    elif upper.endswith("USD"):
        base = upper[:-3]
    else:
        raise ValueError(f"unsupported RTDS price symbol: {price_symbol}")
    return f"{base.lower()}/usd"


def chainlink_feed_id_for_price_symbol(cfg: Config, price_symbol: str) -> str:
    symbol = price_symbol.strip().upper()
    if symbol.startswith("BTC"):
        return cfg.chainlink_btc_twap_30s_feed_id
    if symbol.startswith("ETH"):
        return cfg.chainlink_eth_twap_30s_feed_id
    return ""


def _chainlink_candles_symbol(price_symbol: str) -> str:
    upper = price_symbol.strip().upper()
    if upper.endswith("USDT"):
        return upper[:-4]
    if upper.endswith("USD"):
        return upper[:-3]
    return upper


def _fetch_chainlink_market_start_price(
    price_symbol: str,
    market_start_ts: float,
) -> tuple[float, str]:
    symbol = _chainlink_candles_symbol(price_symbol)
    start_ts = int(market_start_ts)
    r = requests.get(
        "https://polymarket.com/api/chainlink-candles",
        params={
            "symbol": symbol,
            "interval": "5m",
            "limit": 30,
            "twapEnabled": "true",
            "twapLookbackSeconds": 30,
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    candles = data.get("candles") if isinstance(data, dict) else data
    if not isinstance(candles, list):
        raise RuntimeError("unexpected chainlink-candles response")
    prev_close: Optional[float] = None
    prev_ts = start_ts - 300
    for candle in candles:
        try:
            candle_ts = int(candle.get("time"))
            if candle_ts == start_ts:
                return float(candle["open"]), "polymarket-chainlink-candles"
            if candle_ts == prev_ts:
                prev_close = float(candle["close"])
        except Exception:
            continue
    if prev_close is not None:
        return prev_close, "polymarket-chainlink-candles-prev-close"
    raise RuntimeError(f"no chainlink candle found for {symbol} market start {start_ts}")


def _sample_age_sec(sample: RtdsSample, now: Optional[float] = None) -> float:
    now = time.time() if now is None else now
    return max(now - sample.ts, now - sample.received_ts, 0.0)


def ensure_rtds_client(cfg: Config) -> RtdsTwapClient:
    global _client
    with _client_lock:
        if _client is None:
            symbols = [
                rtds_symbol_for_price_symbol(cfg.btc_price_symbol),
                rtds_symbol_for_price_symbol(cfg.eth_price_symbol),
            ]
            _client = RtdsTwapClient(
                url=cfg.rtds_ws_url,
                topic=cfg.rtds_topic,
                symbols=symbols,
                retention_sec=cfg.rtds_retention_sec,
            )
            _client.start()
        return _client


def get_rtds_twap_signal_data(
    cfg: Config,
    market: LiveMarket,
    *,
    price_symbol: str,
) -> RtdsSignalData:
    symbol = rtds_symbol_for_price_symbol(price_symbol)
    client = ensure_rtds_client(cfg)
    latest = client.wait_for_fresh_latest(
        symbol,
        max_age_sec=cfg.rtds_max_age_sec,
        timeout_sec=cfg.rtds_initial_wait_sec,
    )
    latest_is_stale = False
    if latest is None:
        stale = client.latest(symbol)
        stale_max_age = max(cfg.rtds_stale_max_age_sec, cfg.rtds_max_age_sec)
        if stale is not None and _sample_age_sec(stale) <= stale_max_age:
            latest = stale
            latest_is_stale = True
        else:
            latest = client.fetch_once(
                symbol,
                max_age_sec=cfg.rtds_max_age_sec,
                timeout_sec=cfg.rtds_initial_wait_sec,
            )
            if latest is None:
                raise RuntimeError(f"fresh RTDS TWAP unavailable for {symbol}")

    beat = client.sample_for_market_start(
        symbol,
        market.start_ts,
        max_start_lag_sec=cfg.rtds_beat_max_start_lag_sec,
    )
    beat_source = "polymarket-rtds-chainlink-twap-30s"
    if beat is None:
        beat_price, beat_source = _fetch_chainlink_market_start_price(price_symbol, market.start_ts)
        beat = RtdsSample(
            symbol=symbol,
            value=beat_price,
            ts=market.start_ts,
            received_ts=time.time(),
            window_s=30,
        )

    now = time.time()
    source = f"polymarket-rtds-chainlink-twap-{latest.window_s}s"
    if latest_is_stale:
        source = f"{source}|stale-latest"
    if beat_source != "polymarket-rtds-chainlink-twap-30s":
        source = f"{source}|beat={beat_source}"
    return RtdsSignalData(
        price_to_beat=beat.value,
        current_price=latest.value,
        delta_usd=latest.value - beat.value,
        source=source,
        source_ts=latest.ts,
        age_sec=_sample_age_sec(latest, now),
        feed_id=chainlink_feed_id_for_price_symbol(cfg, price_symbol),
    )
