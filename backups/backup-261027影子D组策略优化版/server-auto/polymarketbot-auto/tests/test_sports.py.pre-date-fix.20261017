from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json

from bot.sports_data import StaticSportsDataSource, poisson_win_probability
from bot.sports_main import SportsPaperService, run_cycle
from bot.sports_markets import parse_sports_market
from bot.sports_strategy import build_signal, signal_is_allowed


def sample_market() -> dict:
    end = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {
        "id": "101",
        "conditionId": "0xsp",
        "slug": "nba-lakers-celtics",
        "question": "Will the Lakers beat the Celtics?",
        "tags": ["sports", "basketball", "NBA"],
        "league": "NBA",
        "eventTitle": "Lakers vs Celtics",
        "eventStartTime": datetime.now(timezone.utc).isoformat(),
        "outcomes": json.dumps(["Lakers", "Celtics"]),
        "clobTokenIds": json.dumps(["tok-a", "tok-b"]),
        "outcomePrices": json.dumps(["0.40", "0.60"]),
        "endDate": end,
        "description": "Resolves to the winner of the NBA game.",
        "resolutionSource": "Official NBA result",
        "negRisk": True,
        "liquidity": "1250",
    }


def test_parse_sports_market_normalizes_metadata_and_rules():
    market = parse_sports_market(sample_market())
    assert market is not None
    assert market.sport == "basketball"
    assert market.league == "NBA"
    assert market.outcomes == ("Lakers", "Celtics")
    assert market.neg_risk is True
    assert market.settlement.source == "Official NBA result"
    assert market.settlement.criteria.startswith("Resolves")

    class Cfg:
        sports_max_days_ahead = 30

    assert parse_sports_market(Cfg(), sample_market()) is not None


def test_signal_uses_pluggable_probability_source_and_risk_gate():
    market = parse_sports_market(sample_market())
    assert market is not None
    source = StaticSportsDataSource({market.market_key: {"Lakers": 0.65, "Celtics": 0.35}})
    signal = build_signal(market, source)
    assert signal.outcome == "Lakers"
    assert signal.edge > 0.20

    class Cfg:
        sports_min_entry_price = 0.05
        sports_max_entry_price = 0.95
        sports_min_edge = 0.10
        sports_max_exposure_usd = 5.0

    assert signal_is_allowed(Cfg(), signal)[0]
    assert not signal_is_allowed(Cfg(), signal, exposure_usd=5.0)[0]


def test_paper_service_records_orders_without_live_path():
    market = parse_sports_market(sample_market())
    assert market is not None

    class Cfg:
        sports_enabled = True
        sports_max_exposure_usd = 5.0
        sports_order_size = 1.0
        sports_min_entry_price = 0.05
        sports_max_entry_price = 0.95
        sports_min_edge = 0.10

    service = SportsPaperService(Cfg(), data_source=StaticSportsDataSource({market.market_key: {"Lakers": 0.65, "Celtics": 0.35}}), market_fetcher=lambda cfg: [market])
    snapshot = service.run_once()
    assert snapshot["paper_only"] is True
    assert snapshot["live_orders"] is False
    assert snapshot["orders"][0]["status"] == "paper_simulated"

    try:
        run_cycle(Cfg(), live=True)
    except ValueError as exc:
        assert "paper-only" in str(exc)
    else:
        raise AssertionError("sports live path must always be rejected")


def test_poisson_probability_is_bounded():
    probability = poisson_win_probability(2.0, 1.0)
    assert 0.0 < probability < 1.0
