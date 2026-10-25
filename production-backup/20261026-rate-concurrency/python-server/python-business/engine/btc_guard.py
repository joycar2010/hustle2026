"""BTC crash circuit breaker feed (C1 extension).

One process-wide task polls the BTC spot price every second (public
``/api/v3/ticker/price``, weight 2 on the api/v3 IP pool: ~120/min) and keeps
a six-minute ring. ``btc_crash_reason()`` returns a human-readable reason
while any rolling window exceeds its threshold (both directions), and stays
sticky for ``BTC_BREAKER_HOLD_SEC`` after the last breach so a falling market
cannot flap the breaker open/closed. Workers weave it into ``_breaker_gate``,
so the halt inherits the full C1 semantics: the trading cycle (borrow/open/
auto-close) stops while transfers, reconcile and the risk sentinel keep
running, and the dashboard banner shows the reason.

Thresholds were calibrated on the 2026-09-23 21:55-22:25 (Beijing) BTC slide:
worst rolling moves measured 1m -0.48% / 3m -0.73% / 5m -0.92%; the defaults
0.45/0.70/0.90 are set to catch exactly that class of event. Set an env var
to 0 to disable that window.
"""
import asyncio
import logging
import os
import time
from collections import deque

import httpx

logger = logging.getLogger(__name__)


def _pct(name: str, default: float) -> float:
    try:
        v = float(os.getenv(name, str(default)))
        return v if v > 0 else 0.0
    except (TypeError, ValueError):
        return default


BTC_BREAKER_1M_PCT = _pct("BTC_BREAKER_1M_PCT", 0.45)
BTC_BREAKER_3M_PCT = _pct("BTC_BREAKER_3M_PCT", 0.70)
BTC_BREAKER_5M_PCT = _pct("BTC_BREAKER_5M_PCT", 0.90)
try:
    BTC_BREAKER_HOLD_SEC = max(0, int(os.getenv("BTC_BREAKER_HOLD_SEC", "180")))
except (TypeError, ValueError):
    BTC_BREAKER_HOLD_SEC = 180

_PRICE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
_ring: deque = deque(maxlen=400)  # (monotonic_ts, price), ~6.5 min at 1s
_hold_until = 0.0
_hold_reason = ""
_task: asyncio.Task | None = None


def _window_move(now: float, px: float, span: float) -> float | None:
    """Return % move of ``px`` vs the OLDEST sample within [now-span, now]."""
    ref = None
    for ts, p in _ring:
        if ts >= now - span:
            ref = p
            break
    if ref is None or ref <= 0:
        return None
    return (px - ref) / ref * 100.0


def btc_crash_reason() -> str | None:
    """Sync accessor for worker breaker gates; None = calm.

    Fail-open by design: no BTC samples (poller down/unreachable) means no
    market-shock halt -- the independent feed-death breaker still guards the
    quote pipeline itself.
    """
    global _hold_until, _hold_reason
    now = time.monotonic()
    if not _ring:
        return _hold_reason if now < _hold_until else None
    px = _ring[-1][1]
    breach = None
    for span, thr, label in (
        (60.0, BTC_BREAKER_1M_PCT, "1分钟"),
        (180.0, BTC_BREAKER_3M_PCT, "3分钟"),
        (300.0, BTC_BREAKER_5M_PCT, "5分钟"),
    ):
        if thr <= 0:
            continue
        mv = _window_move(now, px, span)
        if mv is not None and abs(mv) >= thr:
            breach = (
                "BTC %s波动 %+.2f%%(阈值 %.2f%%),市场剧烈波动熔断"
                % (label, mv, thr)
            )
            break
    if breach:
        _hold_until = now + BTC_BREAKER_HOLD_SEC
        _hold_reason = breach
        return breach
    if now < _hold_until:
        return _hold_reason
    return None


async def _poll_loop() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                resp = await client.get(_PRICE_URL)
                data = resp.json()
                px = float(data.get("price") or 0)
                if px > 0:
                    _ring.append((time.monotonic(), px))
            except Exception as e:
                logger.debug("btc_guard poll failed: %s", e)
            await asyncio.sleep(1.0)


def start_btc_guard() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_poll_loop())
        logger.info(
            "BTC crash guard started: 1m %.2f%% / 3m %.2f%% / 5m %.2f%%, hold %ss",
            BTC_BREAKER_1M_PCT,
            BTC_BREAKER_3M_PCT,
            BTC_BREAKER_5M_PCT,
            BTC_BREAKER_HOLD_SEC,
        )
