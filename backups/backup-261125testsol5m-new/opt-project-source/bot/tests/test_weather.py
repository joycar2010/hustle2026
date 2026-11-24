from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json

from bot.config import Config
from bot.weather_data import EnsembleForecast
from bot.weather_markets import parse_weather_market
from bot.weather_strategy import build_signal


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


def _future_target_date() -> date:
    return datetime.now(timezone.utc).date() + timedelta(days=1)


def _weather_market(target_date: date, *, outcomes) -> dict:
    date_text = f"{target_date.strftime('%B')} {target_date.day}, {target_date.year}"
    return {
        "id": "1",
        "conditionId": "0xabc",
        "slug": f"nyc-high-{target_date.isoformat()}",
        "question": (
            "Will the high temperature in New York City be above "
            f"80°F on {date_text}?"
        ),
        "outcomes": json.dumps(outcomes),
        "clobTokenIds": json.dumps([f"{str(outcome).lower()}-token" for outcome in outcomes]),
        "outcomePrices": json.dumps(["0.30", "0.70"]),
        "endDate": f"{target_date.isoformat()}T23:59:00Z",
    }


def test_parse_yes_no_weather_market():
    market = _weather_market(_future_target_date(), outcomes=["Yes", "No"])
    parsed = parse_weather_market(make_cfg(), market)
    assert parsed is not None
    assert parsed.city_key == "nyc"
    assert parsed.kind == "above"
    assert parsed.yes_token == "yes-token"
    assert parsed.no_token == "no-token"


def test_signal_selects_yes_when_ensemble_edge_is_positive():
    target_date = _future_target_date()
    market_data = _weather_market(target_date, outcomes=["No", "Yes"])
    market_data["outcomePrices"] = ["0.80", "0.20"]
    market = parse_weather_market(
        make_cfg(),
        market_data,
    )
    assert market is not None
    forecast = EnsembleForecast(
        city_key="nyc",
        target_date=target_date,
        member_highs=tuple([82.0] * 20 + [79.0] * 11),
        member_lows=tuple([70.0] * 31),
        fetched_at=datetime.now(timezone.utc),
    )
    signal = build_signal(make_cfg(), market, forecast)
    assert signal.side == "UP"
    assert signal.token_id == "yes-token"
    assert signal.edge > 0.0
