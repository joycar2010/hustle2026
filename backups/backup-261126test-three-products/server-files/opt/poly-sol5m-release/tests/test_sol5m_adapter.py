from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from btc5m.book import TopOfBook
from sol5m import markets, signal, ws
from sol5m.profile import SOL5M, assert_paper_env, env_defaults
from sol5m.store import Sol5mStore


def test_profile_isolated_and_live_disabled():
    values = env_defaults(data_dir=Path("/tmp/sol5m-test"))
    assert values["PRODUCT_KEY"] == "sol5m"
    assert values["SERIES_SLUG"] == "sol-up-or-down-5m"
    assert values["CRYPTO_ASSET"] == "sol"
    assert values["LATE_EDGE_DB_NAME"] == "paper_sol5m.db"
    assert values["LIVE"] == values["LIVE_TRADING_ENABLED"] == "false"
    assert_paper_env(values)
    with pytest.raises(RuntimeError):
        assert_paper_env({"LIVE": "true"})


def test_market_discovery_cannot_drift_to_btc(monkeypatch):
    seen = {}

    def fake(host, series, **kwargs):
        seen.update(host=host, series=series, kwargs=kwargs)
        return None

    monkeypatch.setattr(markets, "_fetch_live_market", fake)
    assert markets.fetch_live_market("https://gamma.example") is None
    assert seen == {
        "host": "https://gamma.example",
        "series": SOL5M.series_slug,
        "kwargs": {"window_sec": 300, "slug_prefix": SOL5M.market_slug_prefix},
    }


def test_signal_forces_sol_asset(monkeypatch):
    captured = {}

    def fake(cfg, market):
        captured["asset"] = cfg.crypto_asset
        return "signal"

    monkeypatch.setattr(signal, "fetch_asset_signal", fake)
    from conftest import make_cfg

    cfg = make_cfg(crypto_asset="btc")
    assert signal.fetch_sol_signal(cfg, object()) == "signal"
    assert captured["asset"] == "sol"


def test_store_defaults_to_sol_database(tmp_path):
    store = Sol5mStore(tmp_path / "paper_sol5m.db")
    try:
        assert store.path.name == "paper_sol5m.db"
        assert store.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        store.conn.close()


def test_ws_namespace_and_cache(monkeypatch):
    ws.clear()
    calls = []
    book = TopOfBook(best_bid=0.45, best_ask=0.55, bid_size=10, ask_size=10)

    def fake(host, token):
        calls.append((host, token))
        return book

    monkeypatch.setattr(ws, "fetch_book", fake)
    assert ws.get_book("clob", "token") == book
    assert ws.get_book("clob", "token") == book
    assert calls == [("clob", "token")]
    assert ws.status()["namespace"] == "sol5m:"

