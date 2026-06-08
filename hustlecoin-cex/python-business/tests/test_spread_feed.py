import time
from decimal import Decimal

from engine.spread_feed import SpreadSnapshot, SpreadFeed


def _now_ms():
    return int(time.time() * 1000)


class TestSpreadSnapshot:
    def test_creation(self):
        s = SpreadSnapshot(
            symbol="BTCUSDT",
            spot_bid=Decimal("50000"),
            spot_ask=Decimal("50010"),
            fut_bid=Decimal("50050"),
            fut_ask=Decimal("50060"),
            spread_long=Decimal("0.08"),
            spread_short=Decimal("0.10"),
            ts=_now_ms(),
        )
        assert s.symbol == "BTCUSDT"
        assert s.spread_short == Decimal("0.10")


class TestSpreadFeedCache:
    def test_get_symbol_returns_none_for_missing(self):
        feed = SpreadFeed()
        assert feed.get_symbol("NONEXIST") is None

    def test_get_symbol_case_insensitive(self):
        feed = SpreadFeed()
        snap = SpreadSnapshot(
            symbol="BTCUSDT",
            spot_bid=Decimal("50000"), spot_ask=Decimal("50010"),
            fut_bid=Decimal("50050"), fut_ask=Decimal("50060"),
            spread_long=Decimal("0.08"), spread_short=Decimal("0.10"),
            ts=_now_ms(),
        )
        feed._cache["BTCUSDT"] = snap
        assert feed.get_symbol("btcusdt") is not None
        assert feed.get_symbol("BTCUSDT").symbol == "BTCUSDT"

    def test_get_all_returns_cache(self):
        feed = SpreadFeed()
        snap = SpreadSnapshot(
            symbol="ETHUSDT",
            spot_bid=Decimal("3000"), spot_ask=Decimal("3001"),
            fut_bid=Decimal("3005"), fut_ask=Decimal("3006"),
            spread_long=Decimal("0.13"), spread_short=Decimal("0.17"),
            ts=_now_ms(),
        )
        feed._cache["ETHUSDT"] = snap
        all_data = feed.get_all()
        assert "ETHUSDT" in all_data
        assert len(all_data) == 1

    def test_count_property(self):
        feed = SpreadFeed()
        assert feed.count == 0
        feed._cache["A"] = "dummy"
        feed._cache["B"] = "dummy"
        assert feed.count == 2


class TestSpreadFeedStaleness:
    def _make_snap(self, symbol, ts):
        return SpreadSnapshot(
            symbol=symbol,
            spot_bid=Decimal("100"), spot_ask=Decimal("101"),
            fut_bid=Decimal("102"), fut_ask=Decimal("103"),
            spread_long=Decimal("0.5"), spread_short=Decimal("0.8"),
            ts=ts,
        )

    def test_get_symbol_returns_none_for_stale(self):
        feed = SpreadFeed()
        feed._cache["BTCUSDT"] = self._make_snap("BTCUSDT", _now_ms() - 15000)
        assert feed.get_symbol("BTCUSDT") is None

    def test_get_symbol_returns_fresh(self):
        feed = SpreadFeed()
        feed._cache["BTCUSDT"] = self._make_snap("BTCUSDT", _now_ms())
        assert feed.get_symbol("BTCUSDT") is not None

    def test_get_symbol_custom_max_age(self):
        feed = SpreadFeed()
        feed._cache["BTCUSDT"] = self._make_snap("BTCUSDT", _now_ms() - 15000)
        assert feed.get_symbol("BTCUSDT", max_age_ms=20000) is not None
        assert feed.get_symbol("BTCUSDT", max_age_ms=10000) is None

    def test_get_all_filters_stale(self):
        feed = SpreadFeed()
        feed._cache["FRESH"] = self._make_snap("FRESH", _now_ms())
        feed._cache["STALE"] = self._make_snap("STALE", _now_ms() - 15000)
        result = feed.get_all()
        assert "FRESH" in result
        assert "STALE" not in result

    def test_get_all_custom_max_age(self):
        feed = SpreadFeed()
        feed._cache["A"] = self._make_snap("A", _now_ms() - 15000)
        assert len(feed.get_all(max_age_ms=20000)) == 1
        assert len(feed.get_all(max_age_ms=10000)) == 0

    def test_health(self):
        feed = SpreadFeed()
        feed._cache["FRESH"] = self._make_snap("FRESH", _now_ms())
        feed._cache["STALE"] = self._make_snap("STALE", _now_ms() - 15000)
        h = feed.health()
        assert h["total"] == 2
        assert h["stale"] == 1
        assert h["all_stale"] is False

    def test_health_all_stale(self):
        feed = SpreadFeed()
        feed._cache["A"] = self._make_snap("A", _now_ms() - 15000)
        h = feed.health()
        assert h["all_stale"] is True

    def test_health_empty(self):
        feed = SpreadFeed()
        h = feed.health()
        assert h["total"] == 0
        assert h["stale"] == 0
        assert h["all_stale"] is False
