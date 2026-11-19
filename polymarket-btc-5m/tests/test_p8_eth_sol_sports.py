"""P8: eth5m/sol5m late_edge + OddsAPI sports enablement — BTC 5m untouched."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from btc5m.odds_bus import (
    OddsApiProvider,
    OddsBus,
    build_odds_bus,
    deveig_two_way,
    sport_keys_for_product,
)
from btc5m.phase_stubs import assert_dota_soccer_live_ready, assert_nba_nfl_ready
from btc5m.products import (
    BTC_5M,
    ETH_5M,
    NBA,
    SOL_5M,
    apply_product,
    get_product,
    list_products,
)
from conftest import make_cfg


def test_btc5m_still_identity_after_p8():
    cfg = make_cfg()
    out, product = apply_product(cfg, "btc-up-or-down-5m")
    assert product.key == "btc5m"
    assert out.crypto_asset == "btc"
    assert out.late_edge_db_name == "paper.db"
    assert out.up_min_delta_usd == cfg.up_min_delta_usd
    assert BTC_5M.enabled


def test_eth5m_sol5m_overlays_and_ledgers():
    cfg = make_cfg()
    eth, p_eth = apply_product(cfg, "eth5m")
    assert p_eth is ETH_5M
    assert eth.series_slug == "eth-up-or-down-5m"
    assert eth.crypto_asset == "eth"
    assert eth.late_edge_db_name == "paper_eth5m.db"
    assert eth.mode == "late_edge"
    assert eth.up_min_delta_usd == pytest.approx(0.80)
    assert eth.lead_table_enabled is False
    assert eth.max_entry_price == pytest.approx(0.78)
    assert eth.market_slug_prefix == "eth-updown-5m"

    sol, p_sol = apply_product(cfg, "sol5m")
    assert p_sol is SOL_5M
    assert sol.crypto_asset == "sol"
    assert sol.late_edge_db_name == "paper_sol5m.db"
    assert sol.lead_min_bp == pytest.approx(3.0)
    assert sol.opening_gap_min_bp == pytest.approx(8.0)
    assert sol.up_min_delta_usd == pytest.approx(0.12)
    assert sol.lead_table_enabled is False


def test_nba_nfl_dota_soccer_enabled():
    assert_nba_nfl_ready()  # no longer raises
    assert_dota_soccer_live_ready()
    for key in ("nba", "nfl", "dota", "soccer_unl"):
        p = get_product(key)
        assert p.enabled
        cfg, product = apply_product(make_cfg(), key)
        assert product.key == key
        assert cfg.mode == "sports_mm"
        assert cfg.sports_quote_on_mock is False


def test_nba_odds_sport_keys():
    assert sport_keys_for_product("nba") == ["basketball_nba"]
    assert sport_keys_for_product("nfl") == ["americanfootball_nfl"]
    assert sport_keys_for_product("dota") == []
    assert "soccer_epl" in sport_keys_for_product("soccer_unl")
    assert sport_keys_for_product("nba", "basketball_nba,custom") == [
        "basketball_nba",
        "custom",
    ]


def test_build_odds_bus_skips_mock_when_key_present(monkeypatch):
    bus = build_odds_bus(api_key="test-key", product_key="nba")
    assert bus.primary_source == "odds_api"
    assert not bus.using_mock
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    mock_bus = build_odds_bus(api_key="", product_key="nba")
    assert mock_bus.using_mock


def test_odds_api_provider_matches_teams():
    provider = OddsApiProvider("fake-key", sport_keys=["basketball_nba"])
    sample = [
        {
            "home_team": "Boston Celtics",
            "away_team": "New York Knicks",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Boston Celtics", "price": 1.70},
                                {"name": "New York Knicks", "price": 2.20},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    with patch.object(provider, "_events_for_sport", return_value=sample):
        q = provider.fair_match("nba-nyk-bos", "Celtics", "Knicks")
    assert q is not None
    assert not q.is_mock
    assert abs(q.p_home + q.p_away - 1.0) < 1e-9
    assert q.p_home > q.p_away  # Celtics favored at 1.70
    # Swapped orientation (poly home = Knicks)
    with patch.object(provider, "_events_for_sport", return_value=sample):
        q2 = provider.fair_match("nba-nyk-bos-2", "Knicks", "Celtics")
    assert q2 is not None
    assert q2.p_home < q2.p_away


def test_deveig_and_list_products_include_new():
    p_h, p_a = deveig_two_way(2.0, 2.0)
    assert abs(p_h - 0.5) < 1e-9
    keys = [p.key for p in list_products()]
    assert keys[:4] == ["btc5m", "btc15m", "eth5m", "sol5m"]
    assert "nba" in keys and "nfl" in keys
    assert NBA.enabled


def test_engine_uses_eth_ledger(tmp_path: Path):
    from btc5m.engine import Engine

    cfg = make_cfg(data_dir=tmp_path)
    cfg, _ = apply_product(cfg, "eth5m")
    eng = Engine(cfg, live=False)
    assert eng.store.path.name == "paper_eth5m.db"
    assert eng._hb_mode == "late_edge_eth5m"
