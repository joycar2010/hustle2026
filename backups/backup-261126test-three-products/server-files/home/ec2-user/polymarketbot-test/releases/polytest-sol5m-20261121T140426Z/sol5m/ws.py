"""SOL WebSocket/order-book namespace.

The upstream cache is token keyed; prefixing token IDs prevents accidental
cross-process cache reuse when this module is embedded in a long-running API.
"""
from __future__ import annotations

import threading
import time

from btc5m.book import TopOfBook, fetch_book

_PREFIX = "sol5m:"
_TTL = 0.15
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, TopOfBook]] = {}


def get_book(clob_host: str, token_id: str, *, force: bool = False) -> TopOfBook:
    key = f"{_PREFIX}{token_id}"
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if not force and hit and now - hit[0] <= _TTL:
            return hit[1]
    book = fetch_book(clob_host, token_id)
    with _LOCK:
        _CACHE[key] = (time.time(), book)
    return book


def put_book(token_id: str, book: TopOfBook) -> None:
    with _LOCK:
        _CACHE[f"{_PREFIX}{token_id}"] = (time.time(), book)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


def status() -> dict:
    try:
        import websocket  # noqa: F401
        ws_installed = True
    except Exception:  # noqa: BLE001
        ws_installed = False
    with _LOCK:
        n = len(_CACHE)
    return {
        "product": "sol5m",
        "namespace": _PREFIX,
        "cached_tokens": n,
        "ttl_sec": _TTL,
        "websocket_client_installed": ws_installed,
        "note": "isolated SOL cache; REST fallback is safe for Paper",
    }

