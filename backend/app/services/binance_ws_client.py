"""Binance Futures WebSocket client for real-time market data (multi-symbol)"""
import asyncio
import json
import time
import logging
from typing import Optional, Dict, List
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

BINANCE_WS_BASE = "wss://fstream.binance.com"


class BinanceWebSocketClient:
    """Subscribes to Binance Futures bookTicker streams for multiple symbols.

    Uses the combined stream endpoint:
      wss://fstream.binance.com/stream?streams=xauusdt@bookTicker/xagusdt@bookTicker/...

    Each symbol's latest bid/ask is stored in _quotes dict.
    """

    def __init__(self, symbols: Optional[List[str]] = None):
        self._symbols: List[str] = [s.lower() for s in (symbols or ["xauusdt"])]
        self._quotes: Dict[str, dict] = {}  # symbol -> {bid, ask, ts}
        self._connected: bool = False
        self._task: Optional[asyncio.Task] = None

    # ── Backward-compatible properties (return first symbol's data) ──
    @property
    def bid(self) -> float:
        q = self._quotes.get(self._symbols[0]) if self._symbols else None
        return q["bid"] if q else 0.0

    @property
    def ask(self) -> float:
        q = self._quotes.get(self._symbols[0]) if self._symbols else None
        return q["ask"] if q else 0.0

    @property
    def mid(self) -> float:
        b, a = self.bid, self.ask
        return (b + a) / 2 if b and a else 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def timestamp(self) -> int:
        q = self._quotes.get(self._symbols[0]) if self._symbols else None
        return q["ts"] if q else 0

    # ── Multi-symbol API ──
    def get_quote(self, symbol: str) -> Optional[dict]:
        """Get latest bid/ask for a specific symbol.

        Returns: {"bid": float, "ask": float, "ts": int} or None
        """
        return self._quotes.get(symbol.lower())

    def get_all_quotes(self) -> Dict[str, dict]:
        """Get all symbol quotes."""
        return dict(self._quotes)

    # ── Lifecycle ──
    def start(self):
        """Start the WebSocket listener as a background task."""
        # Load symbols from hedging pair service if available
        self._load_symbols()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        # 20260707 品种清单热重载(新建交易对免重启)
        _watch = getattr(self, "_symbol_watch_task", None)
        if _watch is None or _watch.done():
            self._symbol_watch_task = asyncio.create_task(self._symbol_watch())

    def _load_symbols(self):
        """Load active Binance symbols from hedging pair config."""
        try:
            from app.services.hedging_pair_service import hedging_pair_service
            pairs = hedging_pair_service.list_active_pairs()
            if pairs:
                syms = []
                for p in pairs:
                    if p.symbol_a.platform_type == "cex":
                        _s = p.symbol_a.symbol.lower()
                        # 20260716 NG止血(V1.1 §7.6): 只订阅合法币安venue symbol。
                        # okx/gate等platform_type也是cex, xau_usdt/xau-usdt-swap混进
                        # binance combined stream属非法订阅(NATGASUSDT行情反复不可用
                        # 元凶之一); 同时去重(同symbol多对重复订阅)。
                        if getattr(p.symbol_a, 'platform_id', 1) != 1:
                            continue
                        if not _s.isalnum():
                            logger.warning(f"[BinanceWS] 跳过非法binance symbol: {_s}")
                            continue
                        if _s not in syms:
                            syms.append(_s)
                if syms:
                    self._symbols = syms
                    logger.info(f"[BinanceWS] Loaded {len(syms)} symbols from DB: {syms}")
        except Exception as e:
            logger.warning(f"[BinanceWS] Failed to load symbols from DB, using defaults: {e}")

    async def _symbol_watch(self):
        """20260707 品种清单热重载: 每300s重载 hedging_pairs 的A腿品种集合, 变更即
        强制断开当前连接 → _run 重连时按新清单重建订阅URL(天然完成重订阅)。
        根治"新建交易对必须重启后端才有币安行情"(BTC/PAXG两次实证; 配合
        get_binance_quote 的防冒充闸, 变更生效前新对显示空白而非错价)。
        生效时延 ≤ hedging_pair_service 5min缓存 + 本监视300s ≈ 最长10分钟。"""
        while True:
            await asyncio.sleep(300)
            try:
                _before = set(self._symbols)
                self._load_symbols()
                if set(self._symbols) != _before:
                    logger.info(
                        f"[BinanceWS] 品种清单变更 {sorted(_before)} → {sorted(set(self._symbols))}, "
                        f"断开重连以重建订阅")
                    _w = getattr(self, "_ws", None)
                    if _w is not None:
                        try:
                            await _w.close()
                        except Exception:
                            pass
            except Exception as _e:
                logger.debug(f"[BinanceWS] symbol watch error: {_e}")

    async def stop(self):
        """Stop the WebSocket listener."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False

    async def _run(self):
        """Reconnect loop — keeps reconnecting on any error."""
        reconnect_count = 0
        while True:
            # Build combined stream URL
            streams = "/".join(f"{s}@bookTicker" for s in self._symbols)
            if len(self._symbols) == 1:
                url = f"{BINANCE_WS_BASE}/ws/{streams}"
            else:
                url = f"{BINANCE_WS_BASE}/stream?streams={streams}"

            try:
                logger.info(f"[BinanceWS] Connecting: {len(self._symbols)} symbols (attempt #{reconnect_count + 1})")
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws  # 供品种热重载强制断开触发重订阅
                    self._connected = True
                    reconnect_count = 0
                    logger.info(f"[BinanceWS] Connected successfully ({len(self._symbols)} symbols: {self._symbols})")
                    async for raw in ws:
                        data = json.loads(raw)
                        # Combined stream wraps payload in {"stream": "...", "data": {...}}
                        if "data" in data and "stream" in data:
                            payload = data["data"]
                        else:
                            payload = data

                        sym = payload.get("s", "").lower()  # symbol field in bookTicker
                        b = payload.get("b")
                        a = payload.get("a")
                        if sym and b and a:
                            self._quotes[sym] = {
                                "bid": float(b),
                                "ask": float(a),
                                "bid_qty": float(payload.get("B", 0)),
                                "ask_qty": float(payload.get("A", 0)),
                                "ts": int(time.time() * 1000),
                                # 20260716 M1续(V1.1 §10): 保留交易所源时间与序列,
                                # 不再只存本地now — E=事件时间/T=撮合时间/u=更新序号
                                "src_event_ms": int(payload.get("E") or 0) or None,
                                "src_txn_ms": int(payload.get("T") or 0) or None,
                                "update_id": payload.get("u"),
                            }
            except asyncio.CancelledError:
                logger.info("[BinanceWS] Task cancelled")
                break
            except (ConnectionClosed, OSError, Exception) as e:
                self._connected = False
                reconnect_count += 1
                logger.warning(f"[BinanceWS] Disconnected (attempt #{reconnect_count}): {e}, reconnecting in 5s")
                await asyncio.sleep(5)


# Global instance — symbols loaded dynamically on start()
binance_ws = BinanceWebSocketClient()
