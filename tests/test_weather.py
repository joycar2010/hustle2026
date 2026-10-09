from __future__ import annotations

from datetime import date, datetime, timezone
import json
from unittest.mock import patch

import pytest

from bot.config import Config
from bot.weather_data import EnsembleForecast
from bot.weather_markets import parse_weather_market
from bot.weather_strategy import build_signal


@pytest.fixture(autouse=True)
def fixture_market_date():
    class MarketDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 10, 12, tzinfo=timezone.utc).astimezone(tz)

    with patch("bot.weather_markets.datetime", MarketDate):
        yield


def make_cfg() -> Config:
    return Config(
        private_key="x",
        wallet_address="x",
        funder_address="x",
        signature_type=0,
        chain_id=137,
        clob_host="https://clob.polymarket.com",
        gamma_host="https://gamma-api.polymarket.com",
        polygon_rpc="https://example.invalid",
        api_key="x",
        api_secret="x",
        api_passphrase="x",
        weather_cities="nyc",
        weather_max_days_ahead=3,
    )


def test_parse_yes_no_weather_market():
    market = {
        "id": "1",
        "conditionId": "0xabc",
        "slug": "nyc-high-august-11-2026",
        "question": "Will the high temperature in New York City be above 80°F on August 11, 2026?",
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "outcomePrices": json.dumps(["0.30", "0.70"]),
        "endDate": "2026-08-12T00:00:00Z",
    }
    parsed = parse_weather_market(make_cfg(), market)
    assert parsed is not None
    assert parsed.city_key == "nyc"
    assert parsed.kind == "above"
    assert parsed.yes_token == "yes-token"
    assert parsed.no_token == "no-token"


def test_signal_selects_yes_when_ensemble_edge_is_positive():
    market = parse_weather_market(
        make_cfg(),
        {
            "id": "1",
            "conditionId": "0xabc",
            "slug": "nyc-high-august-11-2026",
            "question": "Will the high temperature in New York City be above 80°F on August 11, 2026?",
            "outcomes": ["No", "Yes"],
            "clobTokenIds": ["no-token", "yes-token"],
            "outcomePrices": ["0.80", "0.20"],
            "endDate": "2026-08-12T00:00:00Z",
        },
    )
    assert market is not None
    forecast = EnsembleForecast(
        city_key="nyc",
        target_date=date(2026, 8, 11),
        member_highs=tuple([82.0] * 20 + [79.0] * 11),
        member_lows=tuple([70.0] * 31),
        fetched_at=datetime.now(timezone.utc),
    )
    signal = build_signal(make_cfg(), market, forecast)
    assert signal.side == "UP"
    assert signal.token_id == "yes-token"
    assert signal.edge > 0.0
