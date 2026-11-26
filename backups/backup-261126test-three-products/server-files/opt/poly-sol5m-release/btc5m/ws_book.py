"""Fast top-of-book cache.

Paper path uses REST with a short TTL cache. When the optional `websocket-client`
package is installed, a background CLOB market socket can refresh the cache;
otherwise pollers still hit REST. Live cancel/replace <150ms still requires a
real WS deployment — this module documents the hook.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from btc5m.book import TopOfBook, fetch_book

_lock = threading.Lock()
_cache: dict[str, tuple[float, TopOfBook]] = {}
_TTL = 0.15  # 150ms — matches Polymarket crypto taker delay window


def get_book(clob_host: str, token_id: str, *, force: bool = False) -> TopOfBook:
    now = time.time()
    with _lock:
        hit = _cache.get(token_id)
        if not force and hit and now - hit[0] <= _TTL:
            return hit[1]
    book = fetch_book(clob_host, token_id)
    with _lock:
        _cache[token_id] = (time.time(), book)
    return book


def put_book(token_id: str, book: TopOfBook) -> None:
    with _lock:
        _cache[token_id] = (time.time(), book)


def clear() -> None:
    with _lock:
        _cache.clear()


def ws_available() -> bool:
    try:
        import websocket  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def status() -> dict:
    with _lock:
        n = len(_cache)
    return {
        "cached_tokens": n,
        "ttl_sec": _TTL,
        "websocket_client_installed": ws_available(),
        "note": "REST+TTL cache; install websocket-client for live CLOB socket hook",
    }
